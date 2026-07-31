---
id: 20260731-061538-momentum-vol-full-gate-failure-portfolio-conversio
category: research_debt
title: 'momentum_vol_full — Gate Failure: Portfolio Conversion Failure'
created_at: '2026-07-31T06:15:38.232660+00:00'
tags:
- momentum_vol_full
- gate_failure
- portfolio_conversion_failure
strategy_id: momentum_vol_full
gate_stage: backtest_passed
ic_mean: '+0.0206'
ic_ir: '0.16'
q5_q1_spread: '+0.0021'
monotonicity_t: '1.68'
n_days: '1467'
---

# momentum_vol_full — Gate Failure: Portfolio Conversion Failure

## Context
**Date**: 2026-07-31 14:15
**Period**: 2020-01-01 → 2026-07-31
**Strategy**: momentum_vol_full

## Failed Thresholds (§10.1)

- ❌ IC_IR=0.16 < 0.3 (阈值)
- ❌ 分层收益不单调

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0206 | \|IC\| ≥ 0.02 |
| IC IR | 0.16 | ≥ 0.3 |
| IC t-stat | 5.98 | ≥ 2.0 |
| IC>0% | 55.5% | — |
| Q5-Q1 spread | +0.0021 | t ≥ 2.0 |
| Spread t | 5.15 | ≥ 2.0 |
| Monotonicity t | 1.68 | ≥ 2.0 |
| N days | 1467 | — |

## Next Steps

- [ ] 检查因子计算是否有错误（前视偏差、数据对齐）
- [ ] 考虑替换弱因子 (|IC| < 0.02) 或调整因子定义
- [ ] 研究 Q5 顶部塌陷原因（价值陷阱 / 极端反转）
- [ ] 尝试非线性得分变换或叠加质量过滤

---
*Archived by MultiFactorPipeline §10.1 Gate*
