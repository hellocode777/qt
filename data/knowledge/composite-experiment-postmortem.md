# Composite Factor 实验结论

| 属性 | 值 |
|------|-----|
| 状态 | Archived |
| 日期 | 2026-08-05 |
| 作者 | Wei + Claude |
| 关联 | [[factor-system]], [[factor-failure-analysis]] |

---

## 实验背景

基于 Factor Health Monitor 的相关性分析，发现 16 个因子实际只有 ~6 个独立 Alpha 源：

```
Amplitude_5D ↔ Volatility_20D       0.98
Momentum_3M ↔ Residual_Momentum_3M  0.96
PCF_OCF ↔ PE_TTM                     0.96
PB ↔ PE                              0.91
ROE ↔ net_profit_growth              0.96
ROE ↔ net_margin                     0.89
```

为消除冗余，构建 6 Composite Factors：
- LowVol_Composite (Volatility_20D + Amplitude_5D + Volatility_60D)
- Momentum_Composite (Residual_Momentum_3M + Momentum_3M)
- Value_Composite (PE_TTM + PB + PCF_OCF)
- Quality_Composite (ROE + gross_margin + net_margin + debt_ratio)
- Volume_Composite (Volume_Concentration + Volume_Trend_10D)
- Reversal_Composite (Short_Term_Reversal_5D)

Composite = rank(member_1) + rank(member_2) + ... 等权均值。

---

## 实验结果

| 策略 | IC | IC_IR | Sharpe | MaxDD | 总收益 | 超额 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| **传统 5 因子** | **0.070** | **0.46** | **0.96** | **15.3%** | **39.5%** | **-2.1%** |
| v3 原始方向 | 0.020 | 0.21 | 0.46 | 60.2% | 16.6% | -30.6% |
| v3 LowVol+1 | 0.012 | 0.19 | 0.50 | 67.3% | 15.5% | -31.7% |
| v3 全部 -1 | -0.030 | 0.28 | 0.44 | 57.4% | 12.6% | -34.6% |

**结论: Composite 路线在日频上不成立。**

---

## 根因分析

### 1. 核心问题: LowVol 是唯一有效 Alpha，Composite 稀释了它

传统 5 因子 = Volatility_20D (权重 +0.22) + 4 个反转因子 → IC=0.067
v3 Composite = LowVol_Composite (30%) + 5 个其他 Composite → IC=0.012~0.020

LowVol 信号被 Value/Quality/Growth 噪音淹没。

### 2. Value/Quality/Growth 在日频上无预测力

| Composite | 来源 | 日频 IC | 为什么失效 |
|-----------|------|:---:|------|
| Value | PE+PB+PCF | ~0 | A 股估值因子需要月度以上周期 |
| Quality | ROE+Margin | ~0 | 财报季度更新，日频 IC 是噪音 |
| Growth | Rev+Profit | ~0 | 同上 |

### 3. Factor Correlation 是把双刃剑

相关性高 ≠ 应该合并。Volatility_20D 和 Amplitude_5D 虽然相关 0.98，但 Volatility_20D 的 IC 远强于 Amplitude_5D。合并后 Amplitude 拖累了 Volatility。

### 4. A 股的核心 Alpha 就一个: Low Volatility + Short-term Reversal

这是之前所有实验反复验证的结论。Composite 实验再次确认。

---

## 后续建议

1. **生产策略**: `momentum_vol_full`（5 因子价量）— 保持
2. **Composite 路线**: 等基本面数据升级到周频/月频后重新测试
3. **Value/Quality/Growth**: 如果要做复合，必须先做行业中性化 + 周频以上
4. **Factor Health Monitor**: 继续保持日频监控，作为早期预警

---

## 资产归档

- Composite Engine 代码保留在 `qp/strategy/factor_composite.py`
- v3 策略配置保留在 `qp/strategy/strategies/ensemble_v3.py`
- Alpha Family 聚类功能保留在 FactorHealthService
- 以上作为研究资产，等待基本面数据升级后复用
