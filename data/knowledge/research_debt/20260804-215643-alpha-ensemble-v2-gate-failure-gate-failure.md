---
id: 20260804-215643-alpha-ensemble-v2-gate-failure-gate-failure
category: research_debt
title: 'alpha_ensemble_v2 — Gate Failure: Gate Failure'
created_at: '2026-08-04T21:56:43.556859+00:00'
tags:
- alpha_ensemble_v2
- gate_failure
- gate_failure
strategy_id: alpha_ensemble_v2
gate_stage: backtest_passed
ic_mean: '+0.0746'
ic_ir: '0.49'
q5_q1_spread: '+0.0277'
monotonicity_t: '0.40'
n_days: '401'
---

# alpha_ensemble_v2 — Gate Failure: Gate Failure

## Context
**Date**: 2026-08-05 05:56
**Period**: 2024-06-01 → 2026-08-03
**Strategy**: alpha_ensemble_v2

## Failed Thresholds (§10.1)

- ❌ Q5-Q1 spread t=1.44 < 2.0 (阈值)

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0746 | \|IC\| ≥ 0.02 |
| IC IR | 0.49 | ≥ 0.3 |
| IC t-stat | 9.86 | ≥ 2.0 |
| IC>0% | 67.1% | — |
| Q5-Q1 spread | +0.0277 | t ≥ 2.0 |
| Spread t | 1.44 | ≥ 2.0 |
| Monotonicity t | 0.40 | ≥ 2.0 |
| N days | 401 | — |

## Next Steps

- [ ] 扩大持仓数量 (Top10 → Top30) 或缩短调仓周期
- [ ] 测试不同 forward period 下的 spread 稳定性

---
*Archived by MultiFactorPipeline §10.1 Gate*
