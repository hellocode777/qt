# 流动性退出单位错配 / Liquidity Exit Unit Mismatch

> 创建: 2026-10-09 | 触发: 「今天的决策怎么把昨天买的给卖了?」
> 状态: 根因已修（工作区，**未提交** —— risk 路径属 production-sensitive，待批准）
> 结论一句话: **决策没有改主意**。是「每日流动性退出」把日线 volume 的「手」当成「股」去比阈值，门槛被放大 100×，40.5% 主板股票被误判「流动性不足」并在次日强制卖出。

---

## 1. 现象

`data/decisions/dp-2026-10-09-e22fbbe9.json`（is_rebalance_day=False）：

* `n_buys=0`, `n_sells=2`
* 601158 SELL 100 股、603167 SELL 100 股 —— `reason=RISK_LIQUIDITY`，`risk_warnings=["流动性不足"]`
* 两只都是 **2026-10-08 刚买入**的（`positions.parquet` P-00016 / P-00017，entry_date=2026-10-08）
* while `risk_audit.candidate_weights` 里 601158 / 603167 **仍在策略 top3**（策略并不想卖）

运行期日志 `logs/scheduler.log:3964`：

```
2026-10-09 18:21:51 | 🛡️ Risk Exit (2026-10-09/2): MEDIUM=2 — ['601158(RISK_LIQUIDITY)', '603167(RISK_LIQUIDITY)']
```

非调仓日 → RANK_DROP / 行业超配 / 基本面恶化 / 停牌 四路退出全部被 `is_rebalance_day` 挡住，
当天唯一可能触发的退出通道就是**每日必检的流动性检查**。

---

## 2. 根因（证据链）

| 环节 | 证据 |
|---|---|
| 喂进去的是原始值 | `qp/pipeline/daily_pipeline.py:1081-1089` → `volume_data[sym] = prices["volume"].to_list()`（无换算） |
| 比较处 | `qp/portfolio/risk_exit.py:208-213` → `avg_vol = mean(vols)` 直接 `< config.liquidity_min_avg_volume` |
| 阈值语义 | `risk_exit.py:110` 旧值 `liquidity_min_avg_volume: int = 100_000  # (股)` |
| data 单位是「手」 | `qp/shared/constants/__init__.py:20-23` `SHARES_PER_LOT=100.0`（注释：腾讯 kline 返回手）；`cost_model.py:286` / `portfolio_risk_engine.py:576` / `liquidity_exposure.py:177` 均乘了 100，**只有风险退出这条路径没乘** |
| 外部复核 | 实测腾讯 `kline/kline` sh601158 2026-10-09 `day[-1][5] = 73997.0`，与 `daily_price_latest.parquet` 存的值完全相同 → 落库未换算 |

→ 比较双方单位不同（手 vs 股），等效门槛 = 100,000 手 = **1,000 万股/日**。

---

## 3. 量化影响（`daily_price_latest.parquet`，3051 只主板，20 日均量）

| 阈值口径 | 通过 | 通过率 |
|---|---|---|
| 旧逻辑（手 vs 100,000） | 1815/3051 | **59.5%** |
| ×100 后 vs 5,000,000 股 | 2400/3051 | 78.7% |
| ×100 后 vs 500,000 股（本次采用） | 3048/3051 | **99.9%** |

事故中两只的绝对流动性：601158 日均 6,324,640 股（≈5,705 万元/日，p27.3）、
603167 日均 2,306,670 股（≈2,611 万元/日，p6.8）—— 对 100k 资金量的组合毫无流动性问题。

---

## 4. 修复（本次改动）

* `qp/portfolio/risk_exit.py`
  * 比较前统一单位：`avg_vol_shares = mean(vols) * SHARES_PER_LOT`
  * 阈值 `100_000` → `500_000` 股/日 —— 与 `qp/data/universe/liquidity.py` 注释的流动性下限
    口径一致（"500k shares/day minimum"），使**买入侧闸门与卖出侧闸门同一标准**
* `qp/pipeline/daily_pipeline.py`
  * 回看天数不再硬编码：`head(20)` → `head(exit_config.liquidity_lookback_days)`
  * `RiskExitManager()` → `RiskExitManager(exit_config)`（配置真正生效）
* `tests/unit/test_monitoring.py`
  * 新增 `test_exit_check_liquidity_volume_unit_is_lots`：1,000 手 → 触发；
    63,246 手（事故真实值）→ 不触发。此前 `volume_data` 分支**零测试覆盖**（`grep volume_data tests/` = 0）

验证：`ruff format --check .` 通过 / `ruff check` 通过 / `pyright` 0 error / `pytest` 全量 1900 收集、1 skipped、其余全过。

---

## 5. 遗留待办

- [ ] 提交 + push（risk 路径 production-sensitive，需用户批准）
- [ ] 兄弟路径同源缺陷：`qp/data/universe/liquidity.py` `_DEFAULT_MIN_VOLUME = 500_000` 注释写
      「shares」，`filter_by_liquidity()` 同样直接与「手」比较（`liquidity.py:138`）。
      核实：`UniverseBuilder` 在 `qp/` 内**无生产调用点**（仅 docstring 示例 + `tests/unit/data/test_universe.py`），
      影响面 = 潜在，**未改**（改动会改变 universe 语义，需单独决策）
- [ ] 设计层（本次未动）：流动性退出是「绝对阈值 + 每日必检 + 买入侧无对应闸门」，
      结构上仍可复现「今天买、明天被卖」。若要根治需决定闸门口径（绝对 vs 分位）与
      买卖两侧一致性，属策略/风控设计变更
- [ ] 已知次要缺口：`RiskExitConfig.liquidity_lookback_days` 过去是死配置（仅定义处出现），
      本次已在 pipeline 侧接上，但 `multifactor_pipeline` 的回测调用未传 `volume_data`，
      其流动性分支实际不生效（回测只跑止损/ST/退市），如需回测同口径需另评估
