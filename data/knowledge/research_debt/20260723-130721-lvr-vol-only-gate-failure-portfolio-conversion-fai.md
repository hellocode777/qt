---
id: 20260723-130721-lvr-vol-only-gate-failure-portfolio-conversion-fai
category: research_debt
title: 'lvr_vol_only — Gate Failure: Portfolio Conversion Failure'
created_at: '2026-07-23T13:07:21.734236+00:00'
tags:
- lvr_vol_only
- gate_failure
- portfolio_conversion_failure
strategy_id: lvr_vol_only
gate_stage: backtest_passed
ic_mean: '+0.0666'
ic_ir: '0.42'
q5_q1_spread: '-0.0005'
monotonicity_t: '0.09'
n_days: '492'
---

# lvr_vol_only — Gate Failure: Portfolio Conversion Failure

## Context
**Date**: 2026-07-23 21:07
**Period**: 2024-01-01 → 2026-07-23
**Strategy**: lvr_vol_only

## Failed Thresholds (§10.1)

- ❌ 分层收益不单调
- ❌ Q5-Q1 spread t=0.34 < 2.0 (阈值)

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | +0.0666 | \|IC\| ≥ 0.02 |
| IC IR | 0.42 | ≥ 0.3 |
| IC t-stat | 9.22 | ≥ 2.0 |
| IC>0% | 61.2% | — |
| Q5-Q1 spread | -0.0005 | t ≥ 2.0 |
| Spread t | 0.34 | ≥ 2.0 |
| Monotonicity t | 0.09 | ≥ 2.0 |
| N days | 492 | — |

## Next Steps

- [ ] 研究 Q5 顶部塌陷原因（价值陷阱 / 极端反转）
- [ ] 尝试非线性得分变换或叠加质量过滤
- [ ] 扩大持仓数量 (Top10 → Top30) 或缩短调仓周期
- [ ] 测试不同 forward period 下的 spread 稳定性

---
*Archived by MultiFactorPipeline §10.1 Gate*
