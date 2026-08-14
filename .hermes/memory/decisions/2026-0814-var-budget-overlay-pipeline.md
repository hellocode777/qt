Task ID:        QT-2026-0814-003
Type:           Implement
Goal:           把 bootstrap VaR 接入每日 pipeline 风险预算（portfolio_risk_engine）
Scope:          qp/portfolio/budget/var_budget.py, cvar_budget.py, portfolio_risk_engine.py
Status:         DONE

Files inspected:
  - qp/portfolio/portfolio_risk_engine.py — _apply_risk_budget 原为纯逆波动率
  - qp/portfolio/budget/var_budget.py / cvar_budget.py — 原组合 VaR 用 sqrt-sum-of-squares

Evidence:
  - FACT: 初版设计"单仓 VaR 贡献 ≤15% 约束"实测无效——position_limits 用等权假设，
         VaR limit 恒宽松于 vol budget（min 后从不生效），真实银行股组合 ON/OFF 结果相同
  - FACT: 现有相关性检查（两两 >0.85 剔除）管极端两两相关，但 8 只银行股两两 0.6-0.8
         都能通过、组合整体仍伪分散（比值 0.882）
  - FACT: 改用"组合VaR/平均单股VaR 比值"后，银行股组合平均权重上限 8.38%→7.62% 生效，
         随机低相关组合（比值 0.6-0.67）不触发，方向正确
  - FACT: 阈值 0.75（var_diversification_threshold）——A股随机组合 0.60-0.67，银行 0.88

Conclusion:
  1. VaR 对组合风险的增量价值在"相关性"维度，不在"单仓波动"维度（后者 vol budget 已覆盖）
  2. 伪分散检测：组合VaR/平均单股VaR > 阈值 → 等比压缩所有权重上限（scale=阈值/比值）
  3. 所有 VaR 计算必须 try/except 兜底，失败回退 vol-only，绝不阻断 pipeline
  4. 配置项：enable_var_budget=True(默认), var_confidence=0.95, var_n_boot=5000,
     var_diversification_threshold=0.75

Confidence:     HIGH（真实数据验证 + 单测锁定）
Changes:        var_budget.py（bootstrap 方法+默认切换）、cvar_budget.py（bootstrap+公式修复）、
                portfolio_risk_engine.py（VaR overlay 接入）
Tests:          tests/unit/test_portfolio.py +7 tests；全量 1511 passed；ruff/pyright clean
Follow-up:
  - 若未来单仓相关性极高（>0.95）场景增多，考虑调低 threshold
