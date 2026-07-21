"""Tests for qp.data.corporate_action.engine — CorporateActionEngine."""

from __future__ import annotations

import pandas as pd
import pytest

from qp.data.corporate_action.engine import (
    ActionType,
    CorporateActionEngine,
    CorporateActionLoader,
)


@pytest.fixture
def portfolio() -> pd.DataFrame:
    return pd.DataFrame([
        {"symbol": "600519", "shares": 1000, "avg_cost": 1500.0, "cash": 50000.0},
        {"symbol": "000858", "shares": 500, "avg_cost": 120.0, "cash": 50000.0},
    ])


@pytest.fixture
def engine() -> CorporateActionEngine:
    return CorporateActionEngine()


class TestActionType:
    def test_enum_values(self):
        assert ActionType.CASH_DIVIDEND == "cash_dividend"
        assert ActionType.STOCK_DIVIDEND == "stock_dividend"
        assert ActionType.SPLIT == "split"
        assert ActionType.RIGHTS_ISSUE == "rights_issue"
        assert ActionType.BONUS_ISSUE == "bonus_issue"


class TestEmptyInput:
    def test_empty_actions(self, engine, portfolio):
        actions = pd.DataFrame(columns=[
            "symbol", "ex_date", "action_type", "dividend_per_share",
            "split_ratio", "rights_ratio", "rights_price", "bonus_ratio",
        ])
        result = engine.adjust_portfolio(portfolio, actions)
        pd.testing.assert_frame_equal(result, portfolio)

    def test_empty_portfolio(self, engine):
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-01",
            "action_type": "cash_dividend", "dividend_per_share": 10.0,
        }])
        empty_pf = pd.DataFrame(columns=["symbol", "shares", "avg_cost", "cash"])
        result = engine.adjust_portfolio(empty_pf, actions)
        assert result.empty


class TestCashDividend:
    def test_cash_dividend_increases_cash(self, engine, portfolio):
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "cash_dividend", "dividend_per_share": 25.91,
        }])
        result = engine.adjust_portfolio(portfolio.copy(), actions)
        row = result[result["symbol"] == "600519"].iloc[0]
        expected_dividend = 1000 * 25.91  # 25910
        assert row["cash"] == pytest.approx(50000.0 + expected_dividend)
        assert row["shares"] == 1000  # unchanged
        assert row["avg_cost"] == 1500.0  # unchanged

    def test_cash_dividend_only_affects_target(self, engine, portfolio):
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "cash_dividend", "dividend_per_share": 25.91,
        }])
        result = engine.adjust_portfolio(portfolio.copy(), actions)
        other = result[result["symbol"] == "000858"].iloc[0]
        assert other["cash"] == 50000.0  # unchanged
        assert other["shares"] == 500  # unchanged


class TestSplit:
    def test_split_doubles_shares(self, engine, portfolio):
        """1拆2: shares ×2, cost /2."""
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "split", "split_ratio": 2.0,
        }])
        result = engine.adjust_portfolio(portfolio.copy(), actions)
        row = result[result["symbol"] == "600519"].iloc[0]
        assert row["shares"] == 2000
        assert row["avg_cost"] == pytest.approx(750.0)

    def test_split_zero_ratio_noop(self, engine, portfolio):
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "split", "split_ratio": 0.0,
        }])
        result = engine.adjust_portfolio(portfolio.copy(), actions)
        row = result[result["symbol"] == "600519"].iloc[0]
        assert row["shares"] == 1000


class TestStockDividend:
    def test_stock_dividend_10_送_3(self, engine, portfolio):
        """10送3: shares ×1.3, cost /1.3."""
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "stock_dividend", "split_ratio": 0.3,
        }])
        result = engine.adjust_portfolio(portfolio.copy(), actions)
        row = result[result["symbol"] == "600519"].iloc[0]
        assert row["shares"] == 1300
        assert row["avg_cost"] == pytest.approx(1500.0 * 1000 / 1300)


class TestRightsIssue:
    def test_rights_issue_with_sufficient_cash(self, engine, portfolio):
        """配股: subscribe at rights price."""
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "rights_issue",
            "rights_ratio": 0.1,  # 10%
            "rights_price": 1000.0,  # below market price
        }])
        pf = portfolio.copy()
        pf.loc[pf["symbol"] == "600519", "cash"] = 200000.0  # ample cash
        result = engine.adjust_portfolio(pf, actions)
        row = result[result["symbol"] == "600519"].iloc[0]
        # 100 rights shares at 1000 each = 100000 cost
        assert row["shares"] == 1100
        assert row["cash"] == pytest.approx(200000.0 - 100000.0)

    def test_rights_issue_insufficient_cash(self, engine, portfolio):
        """Partial subscription when cash is tight."""
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "rights_issue",
            "rights_ratio": 0.1,
            "rights_price": 1000.0,
        }])
        pf = portfolio.copy()
        pf.loc[pf["symbol"] == "600519", "cash"] = 500.0  # can only buy 0 shares
        result = engine.adjust_portfolio(pf, actions)
        row = result[result["symbol"] == "600519"].iloc[0]
        assert row["shares"] == 1000  # no change (can't afford 1 share)


class TestBonusIssue:
    def test_bonus_issue(self, engine, portfolio):
        actions = pd.DataFrame([{
            "symbol": "600519", "ex_date": "2024-06-19",
            "action_type": "bonus_issue", "bonus_ratio": 0.5,
        }])
        result = engine.adjust_portfolio(portfolio.copy(), actions)
        row = result[result["symbol"] == "600519"].iloc[0]
        assert row["shares"] == 1500
        assert row["avg_cost"] == pytest.approx(1000.0)  # 1500000 / 1500


class TestLoader:
    def test_create_portfolio_df(self):
        pf = CorporateActionLoader.create_portfolio_df(
            positions={"600519": (1000, 1500.0), "000858": (500, 120.0)},
            cash=100000.0,
        )
        assert len(pf) == 2
        assert pf[pf["symbol"] == "600519"].iloc[0]["shares"] == 1000
        assert pf[pf["symbol"] == "600519"].iloc[0]["cash"] == 100000.0

    def test_from_tencent_qfq(self):
        df = CorporateActionLoader.from_tencent_qfq()
        assert df.empty
        assert "symbol" in df.columns
        assert "action_type" in df.columns
