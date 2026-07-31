---
id: 20260731-051053-momentum-v1-0-gate-failure-portfolio-conversion-fa
category: research_debt
title: 'momentum_v1.0 — Gate Failure: Portfolio Conversion Failure'
created_at: '2026-07-31T05:10:53.828615+00:00'
tags:
- momentum_v1.0
- gate_failure
- portfolio_conversion_failure
strategy_id: momentum_v1.0
gate_stage: backtest_passed
ic_mean: '+0.0732'
ic_ir: '0.48'
q5_q1_spread: '-0.0031'
monotonicity_t: '1.11'
n_days: '497'
---

# momentum_v1.0 — Gate Failure: Portfolio Conversion Failure

## Context
**Date**: 2026-07-31 13:10
**Period**: 2024-01-01 → 2026-07-31
**Strategy**: momentum_v1.0

## Failed Thresholds (§10.1)

- ❌ 分层收益不单调

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0732 | \|IC\| ≥ 0.02 |
| IC IR | 0.48 | ≥ 0.3 |
| IC t-stat | 10.80 | ≥ 2.0 |
| IC>0% | 66.8% | — |
| Q5-Q1 spread | -0.0031 | t ≥ 2.0 |
| Spread t | 2.72 | ≥ 2.0 |
| Monotonicity t | 1.11 | ≥ 2.0 |
| N days | 497 | — |

## Next Steps

- [ ] 研究 Q5 顶部塌陷原因（价值陷阱 / 极端反转）
- [ ] 尝试非线性得分变换或叠加质量过滤

---
*Archived by MultiFactorPipeline §10.1 Gate*
