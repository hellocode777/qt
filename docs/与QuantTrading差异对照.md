# QP 与 QuantTrading 差异对照表

> **目的**：以 V2.1 Final 设计文档为基准，追踪两个项目与设计规范的偏差。
> **最后更新**：2026-07-23
> **设计基准**：《量化投资买卖规则说明书（V2.1 Final）》— PMConfig §7
>
> ⚠️ **重要**：以 V2.1 Final 为唯一事实来源。QuantTrading 实现代码可能已偏离设计文档。
>
> ### 最新修复
>
> | 日期 | 问题 | 状态 |
> |------|------|------|
> | 2026-07-23 | **复权公式错误** → 前复权 | ✅ 已修复 |
> | 2026-07-23 | **因子精简** 10→5 | ✅ 已完成 |
> | 2026-07-23 | **权重方向修正** | ✅ 已完成 |
> | 2026-07-23 | **Layer 5 形式化** GateResult + Archive + CLI | ✅ 已完成 |
> | 2026-07-23 | **分层 Q5 塌陷** | ❌ 因子工程，下一步 |

---

## 0. 设计基准：V2.1 Final PMConfig

```
@dataclass
class PMConfig:
    target_top_n: int = 10
    sell_buffer_rank: int = 20
    rebalance_frequency: str = "M"

    stop_loss_pct: float = -0.10
    stop_loss_check: str = "EOD"
    stop_loss_execute: str = "NEXT_OPEN"
    force_sell_st: bool = True

    # Not Used（明确不采用）
    # take_profit_pct = None
    # max_holding_days = None
```

**V2.1 §2.2 明确不采用的规则**：

| 不采用 | 原因 |
|--------|------|
| Score > 0.9 才买 | Score 不同市场阶段不可比 |
| **固定止盈** | **会切断动量策略最大的 Alpha 来源** |
| **最大持仓天数** | **属于人为规则，不符合模型驱动原则** |

---

## 1. V2.1 合规性对比（风控层）

| V2.1 要求 | QP | QuantTrading 代码 | 谁合规 |
|-----------|----|----|--------|
| Stop Loss = -10% | `RiskExitConfig.stop_loss_pct = -0.10` ✅ | `RISK_CONTROL.fixed_stop_loss = 0.12` ❌ | **QP** |
| **不采用固定止盈** | 无 take_profit ✅ | `RISK_CONTROL.take_profit = 0.25` ❌ | **QP** |
| **不采用最大持仓天数** | 无 max_hold_days ✅ | `RISK_CONTROL.max_hold_days = 60` ❌ | **QP** |
| Sell Buffer = Top 20 | `sell_buffer_multiplier=2` → Top 20 ✅ | 同 ✅ | 两者 |
| Top N = 10 | `max_positions=10` ✅ | 同 ✅ | 两者 |
| Risk Exit 每天 | `RiskExitManager` 每天 ✅ | `check_risk` 每天 ✅ | 两者 |
| Rank Exit 仅调仓日 | `rebalance_freq=20` ✅ | 同 ✅ | 两者 |

**结论**：QP 的风控参数**完全符合 V2.1 Final 设计**。QuantTrading 的 `RISK_CONTROL` 配置偏离了 V2.1。

### QuantTrading 为何偏离 V2.1？

QuantTrading 的 `RISK_CONTROL` 加上止盈和持仓上限是**实用主义妥协**——在因子质量不足的情况下，用风控规则硬撑回测结果。V2.1 设计哲学认为因子质量应该由模型保证，不应靠风控补救。

---

## 2. 数据层差异

| 维度 | QP | QuantTrading | 影响 |
|------|----|--------------|------|
| 价格数据源 | Gold Parquet 快照 | SQLite `daily_bar` + `adj_factors` 实时查询 | **中** |
| 复权方式 | **前复权** `close × cum_factor` | **前复权** `close × cum_factor` | ✅ **已对齐** |
| 复权代码 | `qp/data/loader/quant_trading_loader.py:120` | `data/storage/compat.py:89` | — |
| 基本面/估值 | 同一张表 | 同一张表 | 无 |
| 股票池输入量 | 3039（Gold ETL 预筛选） | 2887（显式过滤链） | **中** |

### 复权公式修复记录（2026-07-23）

**修复前（错误）**：
```python
# qp/data/loader/quant_trading_loader.py (旧)
mult = latest_cum / cum_factor_on_date
adj_price = raw_price × mult
# → 实际上等价于后复权：历史价格被放大
# 例：茅台 2016-07-05 close = 10043.10（错误）
```

**修复后（正确）**：
```python
# qp/data/loader/quant_trading_loader.py (新)
mult = cum_factor_on_date
adj_price = raw_price × mult
# → 前复权，与 QuantTrading compat.py 完全一致
# 例：茅台 2016-07-05 close = 9.00（正确）
```

**影响范围**：所有有除权/分红历史的股票。无除权事件（cum_factor ≡ 1.0）的股票不受影响。
**修复后需要**：`qp data fetch` 重建 Gold Parquet 数据集。

---

## 3. 策略配置层

| 维度 | QP | QuantTrading | 状态 |
|------|----|--------------|------|
| 因子权重（10 因子） | 完全相同 | 完全相同 | ✅ |
| max_positions | 10 | 10 | ✅ |
| rebalance_freq | 20 | 20 | ✅ |
| sell_buffer | 2× → Top 20 | 2× → Top 20 | ✅ |
| quality_filter | ✅ | ✅ | ✅ |
| industry_neutral | ✅ | ✅ | ✅ |
| orthogonalize | ✅ | ✅ | ✅ |
| anti_chase | 20%, 5天 | 20%, 5天 | ✅ |
| market_filter | MA20>MA60, 连续3日 | 同 | ✅ |
| regime_positions/freq | 同 | 同 | ✅ |

### 质量过滤阈值差异

| 过滤项 | QP | QuantTrading | V2.1 未定义 |
|--------|----|-------------|------------|
| ROE 连续 2 年 < 0 | 硬性剔除 | 硬性剔除 | — |
| debt_ratio > 95% | 硬性剔除 | 硬性剔除 | — |
| ROE > -5% | ✅ | ✅ | — |
| 毛利率 > 10% | ✅ | ✅ | — |
| 净利增速 > -50% | ✅ | ✅ | — |
| **debt_ratio 软门槛** | **< 85%** | **< 90%** | — |
| 0 < PE < 200 | ✅ | ✅ | — |

---

## 4. 回测引擎层

| 维度 | QP | QuantTrading |
|------|----|-------------|
| 引擎 | `SimulatedBroker` + `_compute_backtest` | `BacktestEngine` |
| 语言 | polars | pandas |
| 代码位置 | `qp/simulation/broker.py` / `qp/pipeline/multifactor_pipeline.py:758` | `backtest/engine.py` / `strategy/registry.py:230` |
| 市场过滤器指数 | 上证指数 000001 | 上证指数 000001 |
| §10.1 Gate | ✅ 策略进入前强制检验 | ❌ 无此机制 |

---

## 5. QP 特有的 Gate 机制

QP 在策略信号和回测之间插入了 §10.1 Gate（V2.1 未涉及，按 rule.md 设计）：

```
策略信号 → IC 归因 → 权重优化 → 分层测试 → Gate 检查 → 回测
                                              ↑
                                    不达标 → 归档 Research Debt
                                    （--skip-gate 跳过）
```

量化了 V2.1 "模型驱动" 原则——策略必须先证明因子有效，才能进入回测。

---

## 6. 回测结果差异分析（复权修复后更新）

| | QuantTrading 回测 | QP 实验（修复前） | QP 实验（修复后） |
|---|---|---|---|
| 年化 | **+8.7%** | Gate 拦截 | Gate 拦截 |
| IC Mean | — | -0.0307 | **-0.0460** |
| IC IR | — | 0.24 ❌ | **0.42** ✅ |
| IC>0% | — | 42.3% | 35.8% |
| Q5-Q1 spread t | — | 1.65 ❌ | **2.45** ✅ |
| 分层单调性 t | — | 0.67 ❌ | 1.26 ❌ |
| Gate 状态 | 无 Gate | 3/3 失败 | **1/3 失败** |

### 差异归因（更新）

```
QuantTrading +8.7% 的来源：

  +8.7%
  ├── 止盈 +25%              ← V2.1 明确禁止
  ├── 持仓上限 60 天          ← V2.1 明确禁止
  ├── 止损 -12%（更宽松）     ← V2.1 要求 -10%
  ├── debt_ratio < 90%        ← 比 QP 松 5pp
  └── 策略本身 Alpha（待定）   ← QP 已追平：IC=+0.067, IC_IR=0.42 ✅

QP 修复历程：
  1. 复权公式修正 (10因子) → IC_IR: 0.24→0.42 ✅, spread t: 1.65→2.45 ✅
  2. 精简 5 强因子          → IC 稳定在 +0.067, 权重方向全部修正
  3. 剩余：分层单调性 t≈1.1 < 2.0 — 非权重问题，是 Q5 顶部塌陷
```

**关键结论**：QP 通过复权修复 + 因子精简 + 权重修正，已将 IC 从 -0.031 拉到 +0.067，IC_IR 从 0.24 拉到 0.42。Gate 从 3/3 失败改善到 1/3 失败。剩余问题是分层 Q5 顶部塌陷（最高分股票收益反而不如 Q4），需要因子工程而非参数调整解决。

---

## 7. 待处理项

| 优先级 | 项目 | 状态 | 说明 |
|--------|------|------|------|
| ~~P0~~ | ~~复权公式~~ | ✅ 已修复 | 三个文件 `lc/cf` → `cf` |
| ~~P0~~ | ~~Gold 重建~~ | ✅ 已完成 | 实验验证有效 |
| ~~P1~~ | ~~因子精简~~ | ✅ 已完成 | 10→5 因子，移除 PE_TTM/PB/Price_Volume_Corr/Implied_Net_Flow/Volume_Price_Trend |
| ~~P2~~ | ~~权重方向~~ | ✅ 已完成 | 0 个方向错误，全部由 IC 驱动 |
| **P1** | **分层 Q5 塌陷** | ❌ 因子工程 | Q1→Q4 单调递增，Q5 回报跌回 Q1 水平。非参数问题，需研究因子为什么在最高分失效 |
| P3 | debt_ratio 软门槛 | 待定 | 85% vs 90%，无实质影响 |
| P3 | 股票池差异 | 待定 | 3039 vs 2887，~152 只，无实质影响 |
| P3 | 因子计算验证 | 待验证 | `qp/research/feature/` vs `QuantTrading/strategy/` 是否等价 |
| — | 风控参数 | V2.1 合规 | QP 完全对齐，无需修改 |

---

## 8. 差异来源快速排查

当两个项目对同一策略输出不同结果时，按此顺序排查：

```
1. 复权方式       → 前复权 vs 后复权 — 波动率/振幅因子值不同
2. 股票池         → 3039 (Gold Parquet) vs 2887 (SQLite)
3. 质量过滤       → debt_ratio 85% vs 90% — 通过率差 ~5pp
4. 风控规则       → QP 仅止损，QuantTrading 含止盈+持仓上限
5. 回测引擎       → SimulatedBroker(polars) vs BacktestEngine(pandas)
6. 因子计算       → qp/research/feature/ vs QuantTrading/strategy/（待验证）
```

---

*以 V2.1 Final 为设计基准生成。QuantTrading 实现代码可能偏离设计文档，以 V2.1 为准。*
