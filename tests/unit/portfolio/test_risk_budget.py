# pyright: reportArgumentType=false
"""Tests for risk budget implementations (RiskBudget base / MaxDiversificationBudget).

2026-08-14: RiskBudget.allocate() was a NotImplementedError stub — the
backlog item "RiskBudget 抽象基类未实现" (runtime-module-and-backlog.md #8).
Now the base class has a default inverse-vol allocation and
MaxDiversificationBudget provides the MDP-lite variant.
"""

from qp.portfolio.budget import (
    MaxDiversificationBudget,
    RiskBudget,
    RiskBudgetResult,
    VolatilityBudget,
)

VOLS = {"A": 0.10, "B": 0.20, "C": 0.30, "D": 0.40}


def test_base_risk_budget_inverse_vol() -> None:
    budget = RiskBudget(target_vol=0.15)
    result = budget.allocate(VOLS)
    assert isinstance(result, RiskBudgetResult)
    # 低波动股票获得更大权重（逆波动率）
    assert (
        result.weight_caps["A"]
        > result.weight_caps["B"]
        > result.weight_caps["C"]
        > result.weight_caps["D"]
    )
    # 权重总和 ≈ 1
    assert abs(sum(result.weight_caps.values()) - 1.0) < 1e-4
    # 风险贡献 = w * σ / target_vol
    rc_a = result.risk_contributions["A"]
    assert abs(rc_a - (result.weight_caps["A"] * 0.10 / 0.15)) < 1e-3


def test_base_risk_budget_empty() -> None:
    budget = RiskBudget(target_vol=0.20)
    result = budget.allocate({})
    assert result.weight_caps == {}
    assert result.total_vol_target == 0.20


def test_base_risk_budget_missing_vol_uses_default() -> None:
    budget = RiskBudget(target_vol=0.15)
    result = budget.allocate({"A": 0.10, "B": 0.30}, symbols=["A", "B", "UNKNOWN"])
    assert "UNKNOWN" in result.weight_caps
    # 未知股票用默认 0.30 波动率参与分配
    assert result.weight_caps["UNKNOWN"] > 0


def test_base_risk_budget_symbols_order() -> None:
    budget = RiskBudget(target_vol=0.15)
    result = budget.allocate(VOLS, symbols=["D", "A", "B", "C"])
    # 显式符号顺序决定结果顺序
    assert list(result.weight_caps.keys()) == ["D", "A", "B", "C"]


def test_volatility_budget_inverse_vol() -> None:
    budget = VolatilityBudget(target_vol=0.15)
    result = budget.allocate(VOLS)
    assert isinstance(result, RiskBudgetResult)
    # 波动率倒数加权
    assert result.weight_caps["A"] > result.weight_caps["D"]
    # 单仓上限 15%（max_single_weight）
    assert max(result.weight_caps.values()) <= 0.15 + 1e-6


def test_max_diversification_budget_caps_extreme() -> None:
    budget = MaxDiversificationBudget(target_vol=0.15, max_single_weight=0.25)
    result = budget.allocate(VOLS)
    assert isinstance(result, RiskBudgetResult)
    # 低波动权重更大
    assert result.weight_caps["A"] > result.weight_caps["D"]
    # 单仓上限 25%
    assert max(result.weight_caps.values()) <= 0.25 + 1e-6
    # cap 后总和 ≤ 1（残差 = 保留现金）
    assert sum(result.weight_caps.values()) <= 1.0 + 1e-4


def test_max_diversification_empty() -> None:
    budget = MaxDiversificationBudget(target_vol=0.15)
    result = budget.allocate({})
    assert result.weight_caps == {}


def test_max_diversification_result_fields() -> None:
    budget = MaxDiversificationBudget(target_vol=0.15)
    result = budget.allocate(VOLS)
    d = result.to_dict()
    assert set(d.keys()) == {
        "weight_caps",
        "risk_contributions",
        "cluster_budgets",
        "total_vol_target",
        "estimated_portfolio_vol",
    }
    assert d["total_vol_target"] == 0.15
