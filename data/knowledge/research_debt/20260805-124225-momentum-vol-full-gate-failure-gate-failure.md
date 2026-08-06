---
id: 20260805-124225-momentum-vol-full-gate-failure-gate-failure
category: research_debt
title: 'momentum_vol_full — Gate Failure: Gate Failure'
created_at: '2026-08-05T12:42:25.737442+00:00'
tags:
- momentum_vol_full
- gate_failure
- gate_failure
strategy_id: momentum_vol_full
gate_stage: backtest_passed
ic_mean: '+0.0673'
ic_ir: '0.42'
q5_q1_spread: '-0.0086'
monotonicity_t: '-0.90'
n_days: '645'
---

# momentum_vol_full — Gate Failure: Gate Failure

## Context
**Date**: 2026-08-05 20:42
**Period**: 2023-06-01 → 2026-08-05
**Strategy**: momentum_vol_full

## Failed Thresholds (§10.1)

- ❌ 因子方向反转: 高分→低收益 (Q5-Q1=-0.0086)，无法用于做多策略
- ❌ Q5-Q1 spread t=1.29 < 2.0 (阈值)

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0673 | \|IC\| ≥ 0.02 |
| IC IR | 0.42 | ≥ 0.3 |
| IC t-stat | 10.77 | ≥ 2.0 |
| IC>0% | 63.7% | — |
| Q5-Q1 spread | -0.0086 | t ≥ 2.0 |
| Spread t | 1.29 | ≥ 2.0 |
| Monotonicity t | -0.90 | ≥ 2.0 |
| N days | 645 | — |

## Next Steps

- [ ] 扩大持仓数量 (Top10 → Top30) 或缩短调仓周期
- [ ] 测试不同 forward period 下的 spread 稳定性

---
*Archived by MultiFactorPipeline §10.1 Gate*
