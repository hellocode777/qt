---
id: 20260801-014930-momentum-vol-full-gate-failure-gate-failure
category: research_debt
title: 'momentum_vol_full — Gate Failure: Gate Failure'
created_at: '2026-08-01T01:49:30.245450+00:00'
tags:
- momentum_vol_full
- gate_failure
- gate_failure
strategy_id: momentum_vol_full
gate_stage: backtest_passed
ic_mean: '+0.0672'
ic_ir: '0.48'
q5_q1_spread: '+0.0035'
monotonicity_t: '0.00'
n_days: '498'
---

# momentum_vol_full — Gate Failure: Gate Failure

## Context
**Date**: 2026-08-01 09:49
**Period**: 2024-01-01 → 2026-08-01
**Strategy**: momentum_vol_full

## Failed Thresholds (§10.1)

- ❌ 因子方向反转: 高分→低收益 (Q5-Q1=+0.0035)，无法用于做多策略

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0672 | \|IC\| ≥ 0.02 |
| IC IR | 0.48 | ≥ 0.3 |
| IC t-stat | 10.80 | ≥ 2.0 |
| IC>0% | 65.7% | — |
| Q5-Q1 spread | +0.0035 | t ≥ 2.0 |
| Spread t | 3.62 | ≥ 2.0 |
| Monotonicity t | 0.00 | ≥ 2.0 |
| N days | 498 | — |

## Next Steps

- [ ] 扩大持仓数量 (Top10 → Top30) 或缩短调仓周期
- [ ] 测试不同 forward period 下的 spread 稳定性

---
*Archived by MultiFactorPipeline §10.1 Gate*
