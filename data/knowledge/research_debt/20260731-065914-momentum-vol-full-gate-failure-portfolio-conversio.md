---
id: 20260731-065914-momentum-vol-full-gate-failure-portfolio-conversio
category: research_debt
title: 'momentum_vol_full — Gate Failure: Portfolio Conversion Failure'
created_at: '2026-07-31T06:59:14.771951+00:00'
tags:
- momentum_vol_full
- gate_failure
- portfolio_conversion_failure
strategy_id: momentum_vol_full
gate_stage: backtest_passed
ic_mean: '+0.0673'
ic_ir: '0.42'
q5_q1_spread: '-0.0029'
monotonicity_t: '1.19'
n_days: '497'
---

# momentum_vol_full — Gate Failure: Portfolio Conversion Failure

## Context
**Date**: 2026-07-31 14:59
**Period**: 2024-01-01 → 2026-07-31
**Strategy**: momentum_vol_full

## Failed Thresholds (§10.1)

- ❌ 分层收益不单调

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0673 | \|IC\| ≥ 0.02 |
| IC IR | 0.42 | ≥ 0.3 |
| IC t-stat | 9.31 | ≥ 2.0 |
| IC>0% | 61.2% | — |
| Q5-Q1 spread | -0.0029 | t ≥ 2.0 |
| Spread t | 2.39 | ≥ 2.0 |
| Monotonicity t | 1.19 | ≥ 2.0 |
| N days | 497 | — |

## Next Steps

- [ ] 研究 Q5 顶部塌陷原因（价值陷阱 / 极端反转）
- [ ] 尝试非线性得分变换或叠加质量过滤

---
*Archived by MultiFactorPipeline §10.1 Gate*
