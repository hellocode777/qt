---
id: 20260731-082611-momentum-vol-full-gate-failure-factor-validity-fai
category: research_debt
title: 'momentum_vol_full — Gate Failure: Factor Validity Failure'
created_at: '2026-07-31T08:26:11.995643+00:00'
tags:
- momentum_vol_full
- gate_failure
- factor_validity_failure
strategy_id: momentum_vol_full
gate_stage: backtest_passed
ic_mean: '+0.0205'
ic_ir: '0.17'
q5_q1_spread: '-0.0034'
monotonicity_t: '7.36'
n_days: '1467'
---

# momentum_vol_full — Gate Failure: Factor Validity Failure

## Context
**Date**: 2026-07-31 16:26
**Period**: 2020-01-01 → 2026-07-31
**Strategy**: momentum_vol_full

## Failed Thresholds (§10.1)

- ❌ IC_IR=0.17 < 0.3 (阈值)

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0205 | \|IC\| ≥ 0.02 |
| IC IR | 0.17 | ≥ 0.3 |
| IC t-stat | 6.54 | ≥ 2.0 |
| IC>0% | 56.9% | — |
| Q5-Q1 spread | -0.0034 | t ≥ 2.0 |
| Spread t | 7.15 | ≥ 2.0 |
| Monotonicity t | 7.36 | ≥ 2.0 |
| N days | 1467 | — |

## Next Steps

- [ ] 检查因子计算是否有错误（前视偏差、数据对齐）
- [ ] 考虑替换弱因子 (|IC| < 0.02) 或调整因子定义

---
*Archived by MultiFactorPipeline §10.1 Gate*
