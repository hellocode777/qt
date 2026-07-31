---
id: 20260731-011742-killswitch-pause-buy-on
category: failure_analysis
title: 'KillSwitch: pause_buy on '
created_at: '2026-07-31T01:17:42.714872+00:00'
tags:
- auto-archived
- kill-switch
- pause_buy
- liquidity_crunch
---

# KillSwitch: pause_buy on 

## Event Summary
<!-- What failed? When? How was it detected? -->

N/A

## Root Cause Analysis
<!-- Why did it happen? Use 5-Whys or similar method. -->

Monitoring pipeline detected escalation to pause_buy. Market regime was LIQUIDITY_CRUNCH. Triggers: Weekly DD 7% > 5%.

## Impact Assessment
<!-- Financial impact, model performance, data quality, trust. -->

Action taken: pause_buy. See system_health_log for full context.

## Detection
<!-- How quickly was this caught? Could it have been caught sooner? -->

(待补充 / TBD)

## Mitigation
<!-- What was done to stop the damage? What safeguards are now in place? -->

(待补充 / TBD)

## Prevention
<!-- What process or code changes prevent recurrence? -->

(待补充 / TBD)

## Classification
<!-- Category: Overfitting | Data Leakage | Market Regime | Implementation Bug | External -->

**Category**: Market Regime
**Severity**: 2 (1-5, 5=worst)
