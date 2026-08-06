---
id: 20260805-125931-alpha-ensemble-v3-gate-failure-factor-validity-fai
category: research_debt
title: 'alpha_ensemble_v3 — Gate Failure: Factor Validity Failure'
created_at: '2026-08-05T12:59:31.262177+00:00'
tags:
- alpha_ensemble_v3
- gate_failure
- factor_validity_failure
strategy_id: alpha_ensemble_v3
gate_stage: backtest_passed
ic_mean: '+0.0167'
ic_ir: '0.21'
q5_q1_spread: '-0.0408'
monotonicity_t: '-0.40'
n_days: '403'
---

# alpha_ensemble_v3 — Gate Failure: Factor Validity Failure

## Context
**Date**: 2026-08-05 20:59
**Period**: 2024-06-01 → 2026-08-05
**Strategy**: alpha_ensemble_v3

## Failed Thresholds (§10.1)

- ❌ |IC|=0.0167 < 0.02 (阈值)
- ❌ IC_IR=0.21 < 0.3 (阈值)
- ❌ 因子方向反转: 高分→低收益 (Q5-Q1=-0.0408)，无法用于做多策略
- ❌ Q5-Q1 spread t=1.67 < 2.0 (阈值)

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0167 | \|IC\| ≥ 0.02 |
| IC IR | 0.21 | ≥ 0.3 |
| IC t-stat | 4.25 | ≥ 2.0 |
| IC>0% | 56.8% | — |
| Q5-Q1 spread | -0.0408 | t ≥ 2.0 |
| Spread t | 1.67 | ≥ 2.0 |
| Monotonicity t | -0.40 | ≥ 2.0 |
| N days | 403 | — |

## Next Steps

- [ ] 检查因子计算是否有错误（前视偏差、数据对齐）
- [ ] 考虑替换弱因子 (|IC| < 0.02) 或调整因子定义
- [ ] 扩大持仓数量 (Top10 → Top30) 或缩短调仓周期
- [ ] 测试不同 forward period 下的 spread 稳定性

---
*Archived by MultiFactorPipeline §10.1 Gate*
