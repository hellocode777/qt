# 策略研究

> 最后更新：2026-07-31
> 数据集：daily_price_latest（3051只，2015-2026）

---

## 策略清单

### 动量+成交量系列

| # | 策略名 | 显示名 | 因子 | 说明 |
|---|--------|--------|------|------|
| 1 | `momentum_vol_full` | 动量+成交量(完整版) | Momentum_1M, Momentum_3M, Volatility_20D, Volume_Ratio_5D, Amount_20D | 主线策略，全过滤器 |
| 2 | `lvr_vol_mom` | 低波+动量 | Volatility_20D, Momentum_3M | 精简版 |
| 3 | `lvr_vol_only` | 低波(仅波动率) | Volatility_20D | 单因子基线 |
| 4 | `low_vol_reversal` | 低波+反转 | Momentum_1M, Momentum_3M, Volatility_20D, Volume_Ratio_5D, Amount_20D | 5因子反转版 |
| 5 | `lvr_vol_all_rev` | 低波+全部反转 | Momentum_1M, Momentum_3M, Volatility_20D, Volume_Ratio_5D, Amount_20D | 全反转版 |

### Alpha多因子系列

| # | 策略名 | 显示名 | 因子 | 说明 |
|---|--------|--------|------|------|
| 6 | `alpha_multi_factor_v1` | Alpha多因子 v1.0 | Momentum_1M, Momentum_3M, Volatility_20D, Volume_Ratio_5D, Amount_20D, Turnover_5D, RSI_14D, MACD_DIF, BIAS_20D, PE_TTM, PB, ROE | 12因子 |
| 7 | `alpha_multi_factor_v2` | Alpha多因子 v2.0 (反转版) | 同上 + EPS | 13因子，修复v1符号错误 |

---

## 实验命令

```bash
# 基本实验
uv run qp experiment run multifactor --strategy <策略名> --start 2024-01-01

# 跳过门禁（看回测收益）
uv run qp experiment run multifactor --strategy <策略名> --start 2024-01-01 --skip-gate

# 指定股票池
uv run qp experiment run multifactor --strategy <策略名> --start 2024-01-01 --symbols 000001,600519,000858

# Score Band 自动搜索
uv run qp experiment run multifactor --strategy <策略名> --start 2024-01-01 --score-band auto

# 批量对比
uv run qp experiment run multifactor --strategy momentum_vol_full,alpha_multi_factor_v2 --start 2024-01-01

# 查看结果
uv run qp experiment list
uv run qp experiment show <experiment_id>
uv run qp experiment compare
```

---

## 实验记录

### 模板

```markdown
## [策略名] — YYYY-MM-DD

**命令**：`uv run qp experiment run multifactor --strategy xxx --start 2024-01-01`

| 指标 | 值 | 阈值 | 判定 |
|------|-----|------|------|
| IC Mean | | ≥0.02 | |
| IC IR | | ≥0.3 | |
| IC t-stat | | ≥2.0 | |
| 单调性 t | | ≥2.0 | |
| Q5-Q1 spread t | | ≥2.0 | |
| Sharpe | | ≥0.5 | |
| MaxDD | | ≤30% | |
| 总收益 | | — | |
| 超额收益 | | — | |

**Gate 判定**：PASSED / BLOCKED / RESEARCH_ONLY

**发现**：
-
```

---

## 实验历史

### 2026-07-31 — Gate 方向检查修复 + momentum_vol_full 验证

**改动**：`qp/research/evaluation/layered_test.py` — Q 编号翻转（Q1=最低分, Q5=最高分，行业标准），`is_monotonic` 增加方向检查（slope > 0），新增 `direction_correct` 字段。

**验证实验**：`uv run qp experiment run multifactor --strategy momentum_vol_full --start 2024-01-01`

| 指标 | 值 | 判定 |
|------|-----|------|
| IC Mean | +0.080 | ✅ |
| IC IR | 0.70 | ✅ |
| IC t-stat | 15.70 | ✅ |
| 单调性 t | 3.17 | ✅ |
| Q5-Q1 spread | +0.0067 | ✅ 正向 |
| direction_correct | ✅ | ↑ |
| Sharpe | 0.23 | ❌ |
| 总收益 | +2.49% | ❌ |
| 超额收益 | -16.43% | ❌ |

**Gate 判定**：✅ PASSED（因子有效，方向正确）

**新发现**：
- 因子方向正确（高分 → 高收益），Gate 通过。但策略仍跑输基准。
- 问题不在因子层，在**组合构建层**：Q5 日收益 +0.81%（5日持有），但策略仅捕获 +2.49%（2.5年）
- 根因推测：① 20天调仓 vs 5天信号周期的错配 ② Top-10 集中度太高 ③ 成本侵蚀

**下一步**：
- 测试 `--top-n 30` 分散风险
- 测试 `--score-band 60-80` 避开极端区域
- 缩短调仓周期或对齐信号周期

---

## 已知问题

1. **因子≠策略** — momentum_vol_full 因子有效（IC=0.08, 方向正确）但策略跑输，组合构建层需优化
2. **估值数据** — PE_TTM/PB 覆盖率 99.9%（3039/3043），4只无基本面数据
3. **IC 优化权重可能与策略内置方向冲突** — 需验证 `ALL_FACTOR_DIRECTIONS`

---

## 待研究问题

- [ ] 为什么 Q5 因子收益 +0.81%/5d 但策略仅 +2.49%/2.5年？信号衰减惩罚多大？
- [ ] 加入基本面质量过滤后，Q5 分层是否改善？
- [ ] Alpha多因子 v2 的 13 因子 vs momentum_vol_full 的 5 因子对比
- [ ] 不同市场状态（牛/熊/震荡）下的因子表现差异
- [ ] Top-N 持仓数量对收益/风险的影响（10/20/30/50）
- [x] Gate 方向检查 — 已实现 `direction_correct`
