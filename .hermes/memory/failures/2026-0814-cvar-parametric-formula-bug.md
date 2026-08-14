Task ID:        QT-2026-0814-002
Type:           Failure record
Goal:           CVaR parametric 公式 bug 修复记录（避免再次踩坑）
Scope:          qp/portfolio/budget/cvar_budget.py
Status:         DONE（已修复 + 测试锁定）

Files inspected:
  - qp/portfolio/budget/cvar_budget.py — _parametric_cvar / _cvar_from_vol

Evidence:
  - FACT: 修复前 parametric CVaR 在真实数据上算出 -3.44%（负数），CVaR/VaR ratio = -0.12（荒谬值）
  - FACT: 正态 CVaR（亏损为正约定）= -μ + σ·φ(z_α)/α，其中 α = 1-confidence（尾部概率）
  - FACT: 原代码两个错误：(1) 分母写成 (1-confidence)=0.95 而非 α=0.05 → 低估 19 倍；
         (2) 整体 -(μ + σφ/α) 把 μ 符号搞反 → 强正漂移下翻负数
  - FACT: 修复后 parametric CVaR=3.50%，CVaR/VaR=1.94（合理）；historical=4.29%，bootstrap=4.47%
  - FACT: A股肥尾 → historical/bootstrap CVaR 比 parametric 高 20%+（正态低估尾部）

Conclusion:
  1. CVaR 公式错误不会在简单数据上暴露（测试数据 μ≈0 时两个错误互相抵消），
     真实数据（μ>0）才暴露。测试必须用真实统计量的性质断言（CVaR>0、CVaR≥VaR）
  2. 修复后 CVaR/VaR ratio：parametric≈1.9（正态理论值），historical/bootstrap 2.7-1.7
     （肥尾越高 ratio 越大）

Confidence:     HIGH
Changes:        qp/portfolio/budget/cvar_budget.py（两处分母 α + μ 符号）
Tests:          tests/unit/test_portfolio.py::test_parametric_cvar_positive_and_ge_var
                （断言 CVaR>0 且 ≥VaR）；全量 1511 passed
Follow-up:
  - 同类风险：任何"理论上应>0 的指标"的公式 bug，测试要锁性质而非数值
