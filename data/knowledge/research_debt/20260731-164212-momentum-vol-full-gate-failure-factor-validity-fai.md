---
id: 20260731-164212-momentum-vol-full-gate-failure-factor-validity-fai
category: research_debt
title: 'momentum_vol_full — Gate Failure: Factor Validity Failure'
created_at: '2026-07-31T16:42:12.981545+00:00'
tags:
- momentum_vol_full
- gate_failure
- factor_validity_failure
strategy_id: momentum_vol_full
gate_stage: backtest_passed
ic_mean: '-0.0086'
ic_ir: '0.06'
q5_q1_spread: '+0.0029'
monotonicity_t: '5.09'
n_days: '634'
---

# momentum_vol_full — Gate Failure: Factor Validity Failure

## Context
**Date**: 2026-08-01 00:42
**Period**: 2024-01-01 → 2026-07-31
**Strategy**: momentum_vol_full

## Failed Thresholds (§10.1)

- ❌ |IC|=0.0086 < 0.02 (阈值)
- ❌ IC_IR=0.06 < 0.3 (阈值)
- ❌ IC t-stat=1.52 < 2.0 (阈值)

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | -0.0086 | \|IC\| ≥ 0.02 |
| IC IR | 0.06 | ≥ 0.3 |
| IC t-stat | 1.52 | ≥ 2.0 |
| IC>0% | 51.7% | — |
| Q5-Q1 spread | +0.0029 | t ≥ 2.0 |
| Spread t | 3.15 | ≥ 2.0 |
| Monotonicity t | 5.09 | ≥ 2.0 |
| N days | 634 | — |

## Next Steps

- [ ] 检查因子计算是否有错误（前视偏差、数据对齐）
- [ ] 考虑替换弱因子 (|IC| < 0.02) 或调整因子定义

---
*Archived by MultiFactorPipeline §10.1 Gate*
