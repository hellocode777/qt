---
id: 20260723-123846-low-vol-reversal-gate-failure-portfolio-conversion
category: research_debt
title: 'low_vol_reversal — Gate Failure: Portfolio Conversion Failure'
created_at: '2026-07-23T12:38:46.976578+00:00'
tags:
- low_vol_reversal
- gate_failure
- portfolio_conversion_failure
strategy_id: low_vol_reversal
gate_stage: backtest_passed
ic_mean: '+0.0666'
ic_ir: '0.42'
q5_q1_spread: '-0.0030'
monotonicity_t: '1.15'
n_days: '492'
---

# low_vol_reversal — Gate Failure: Portfolio Conversion Failure

## Context
**Date**: 2026-07-23 20:38
**Period**: 2024-01-01 → 2026-07-23
**Strategy**: low_vol_reversal

## Failed Thresholds (§10.1)

- ❌ 分层收益不单调

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0666 | \|IC\| ≥ 0.02 |
| IC IR | 0.42 | ≥ 0.3 |
| IC t-stat | 9.22 | ≥ 2.0 |
| IC>0% | 61.2% | — |
| Q5-Q1 spread | -0.0030 | t ≥ 2.0 |
| Spread t | 2.57 | ≥ 2.0 |
| Monotonicity t | 1.15 | ≥ 2.0 |
| N days | 492 | — |

## Next Steps

- [ ] 研究 Q5 顶部塌陷原因（价值陷阱 / 极端反转）
- [ ] 尝试非线性得分变换或叠加质量过滤

---
*Archived by MultiFactorPipeline §10.1 Gate*
