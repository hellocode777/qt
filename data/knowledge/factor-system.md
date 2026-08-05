# QP 因子体系

> 整理时间：2026-08-05 | 源码：`qp/research/feature/`

---

## 1. 计算约定

| 约定 | 说明 |
|------|------|
| **PIT 防泄露** | 所有因子计算后执行 `shift(1)`，T 日因子值仅使用 ≤ T-1 的数据 |
| **最少交易日 = lookback + 1** | `pct_change(N)` 或 `rolling_*(N)` 需要 N 天，`shift(1)` 再加 1 天 |
| **方向校准** | A股 2024-2026 单因子 IC 校准；`+1` = 做多高值，`-1` = 做空高值 |
| **A股特征** | 均值回归主导 → 大部分因子方向为 `-1`（反转信号） |
| **波动率取反** | Volatility_20D/60D 计算时已取反，值越大 = 波动越低 = 越好 |
| **年化常数** | `TRADING_DAYS_PER_YEAR = 252` |
| **amount 缺省** | 无 `amount` 列时自动用 `close * volume` 近似 |

---

## 2. 因子总表

### 2.1 动量类（6 个）— `momentum.py`

A股动量 IC 为负，过去赢家未来表现差，除 Trend_MA120 外全部做空。

| 因子 | 公式 | 最少交易日 | 方向 | 输入 | 说明 |
|------|------|:---------:|:----:|:----:|------|
| Short_Term_Reversal_5D | `pct_change(5)` | 6 | -1 | C | 5日反转，做空短线赢家 |
| Momentum_1M | `pct_change(20)` | 21 | -1 | C | 20日动量 ≈ 1月 |
| Momentum_3M | `pct_change(60)` | 61 | -1 | C | 60日动量 ≈ 3月 |
| Momentum_6M 🔴 | `pct_change(120)` | **121** | -1 | C | 120日动量 ≈ 6月，长周期瓶颈 |
| Momentum_3M_vol_adj | `pct_change(60) / rolling_std(pct_change, 60)` | 61 | -1 | C | 单位风险超额收益，比原始动量更稳定 |
| Trend_MA120 🔴 | `(close - ma(120)) / ma(120)` | **121** | **+1** | C | 价格偏离120日均线，唯一正向动量因子，趋势跟踪 |

### 2.2 波动率类（3 个）— `volatility.py`

低波动异象，值越大越好（已取反或越接近0）。

| 因子 | 公式 | 最少交易日 | 方向 | 输入 | 说明 |
|------|------|:---------:|:----:|:----:|------|
| Volatility_20D | `-std(log_return, 20) * √252` | 21 | +1 | C | 20日年化波动率（已取反） |
| Volatility_60D | `-std(log_return, 60) * √252` | 61 | +1 | C | 60日年化波动率（已取反） |
| MaxDD_60D | `(close - rolling_max(60)) / rolling_max(60)` | 61 | +1 | C | 60日最大回撤，范围 [-1, 0]，0 = 新高 |

### 2.3 成交量类（6 个）— `volume.py`

A股量价因子 IC 为负，放量多为出货信号。

| 因子 | 公式 | 最少交易日 | 方向 | 输入 | 说明 |
|------|------|:---------:|:----:|:----:|------|
| Volume_Ratio_5D | `volume / ma(volume, 5)` | 6 | -1 | V | 放量比，>1 = 放量突破 |
| Volume_Trend_10D | `ma(volume, 5) / ma(volume, 20)` | 21 | -1 | V | 短期均量 / 中期均量 |
| Price_Volume_Corr | 20日 `corr(return, volume)` | 21 | -1 | C,V | 量价相关系数 |
| Volume_Price_Trend | `sign(price_slope) * sign(vol_slope)` | 11 | -1 | C,V | 量价趋势一致性，slope = `ma(5).diff(5)` |
| Volume_Expansion_20_120 🔴 | `ma(volume, 20) / ma(volume, 120)` | **121** | **+1** | V | 中期量能扩张，机构关注度 |
| Amount_Momentum_20_120 🔴 | `ma(amount, 20) / ma(amount, 120)` | **121** | **+1** | C,V | 中期资金流入趋势 |

### 2.4 资金流类（3 个）— `money_flow.py`

A股资金流 IC 为负。

| 因子 | 公式 | 最少交易日 | 方向 | 输入 | 说明 |
|------|------|:---------:|:----:|:----:|------|
| Amplitude_5D | `ma((high-low)/prev_close, 5)` | 6 | -1 | H,L,C | 5日平均日内振幅，高振幅 = 分歧大 |
| Volume_Concentration | `std(amount, 20) / mean(amount, 20)` | 21 | -1 | C,V | 成交额 CV，高值 = 机构脉冲式交易 |
| Implied_Net_Flow | `(Σ阳线额 - Σ阴线额) / Σ总额`（5日窗口） | 6 | -1 | O,C,V | 隐含净资金流，正 = 买入压力 |

---

## 3. 主汇总表（按最少交易日升序）

| # | 因子 | 类别 | 最少交易日 | 方向 | 输入 | 瓶颈 |
|:-:|------|------|:---------:|:----:|:----:|:----:|
| 1 | Short_Term_Reversal_5D | 动量 | 6 | -1 | C | |
| 2 | Volume_Ratio_5D | 成交量 | 6 | -1 | V | |
| 3 | Amplitude_5D | 资金流 | 6 | -1 | H,L,C | |
| 4 | Implied_Net_Flow | 资金流 | 6 | -1 | O,C,V | |
| 5 | Volume_Price_Trend | 成交量 | 11 | -1 | C,V | |
| 6 | Momentum_1M | 动量 | 21 | -1 | C | |
| 7 | Volatility_20D | 波动率 | 21 | +1 | C | |
| 8 | Volume_Trend_10D | 成交量 | 21 | -1 | V | |
| 9 | Price_Volume_Corr | 成交量 | 21 | -1 | C,V | |
| 10 | Volume_Concentration | 资金流 | 21 | -1 | C,V | |
| 11 | Momentum_3M | 动量 | 61 | -1 | C | |
| 12 | Momentum_3M_vol_adj | 动量 | 61 | -1 | C | |
| 13 | Volatility_60D | 波动率 | 61 | +1 | C | |
| 14 | MaxDD_60D | 波动率 | 61 | +1 | C | |
| 15 | Momentum_6M | 动量 | 121 | -1 | C | 🔴 |
| 16 | Trend_MA120 | 动量 | 121 | +1 | C | 🔴 |
| 17 | Volume_Expansion_20_120 | 成交量 | 121 | +1 | V | 🔴 |
| 18 | Amount_Momentum_20_120 | 成交量 | 121 | +1 | C,V | 🔴 |

| | 方向 | 数量 |
|:--|------|:--:|
| | **-1**（反转/做空） | 13 |
| | **+1**（趋势/做多） | 5 |

---

## 4. 已知问题：`compute_all_factors()` 长周期瓶颈

`compute_all_factors()` 计算全部 18 个因子后对所有列执行 `drop_nulls()`，**任一因子为 NaN 整行丢弃**：

```python
# qp/research/feature/compute.py:107
return result.drop_nulls()  # 4 个未使用的 121 天因子拖累全局
```

| 场景 | 实际需要 | warm-up | 首次建仓 |
|------|:--------:|:-------:|----------|
| 只用短周期因子 | ≤21 天 | ~1 月 | 训练起点 + 21 天 |
| 用到 Momentum_3M | ≤61 天 | ~3 月 | 训练起点 + 61 天 |
| **当前实现（无论用哪些）** | **121 天** | **~6 月** | 训练起点 + 121 天 |

**修复方向：** 按需 drop_nulls，只检查策略实际使用的列。

---

## 5. 未纳入的因子

估值类因子（依赖外部数据，不在 `compute_all_factors` 范围）：PE_TTM、PB、Dividend_Yield、PS_TTM、PCF_OCF。
