---
id: 20260725-014840-alpha-multi-factor-v2-gate-failure-factor-validity
category: research_debt
title: 'alpha_multi_factor_v2 — Gate Failure: Factor Validity Failure'
created_at: '2026-07-25T01:48:40.002428+00:00'
tags:
- alpha_multi_factor_v2
- gate_failure
- factor_validity_failure
strategy_id: alpha_multi_factor_v2
gate_stage: backtest_passed
ic_mean: '+0.0252'
ic_ir: '0.18'
q5_q1_spread: '+0.0010'
monotonicity_t: '4.25'
n_days: '613'
---

# alpha_multi_factor_v2 — Gate Failure: Factor Validity Failure

## Context
**Date**: 2026-07-25 09:48
**Period**: 2024-01-01 → 2026-07-25
**Strategy**: alpha_multi_factor_v2

## Failed Thresholds (§10.1)

- ❌ IC_IR=0.18 < 0.3 (阈值)

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0252 | \|IC\| ≥ 0.02 |
| IC IR | 0.18 | ≥ 0.3 |
| IC t-stat | 4.47 | ≥ 2.0 |
| IC>0% | 55.1% | — |
| Q5-Q1 spread | +0.0010 | t ≥ 2.0 |
| Spread t | 2.51 | ≥ 2.0 |
| Monotonicity t | 4.25 | ≥ 2.0 |
| N days | 613 | — |

## Next Steps

- [ ] 检查因子计算是否有错误（前视偏差、数据对齐）
- [ ] 考虑替换弱因子 (|IC| < 0.02) 或调整因子定义

---
*Archived by MultiFactorPipeline §10.1 Gate*
