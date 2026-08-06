"""CorporateActionEngine — adjusts portfolio for dividends, splits, etc.

Implements the CorporateActionEngine ABC from shared/protocols/.
Handles: cash dividends, stock dividends, splits, and rights issues.

Note: The Tencent adapter fetches qfq (前复权) data, so prices are already
adjusted. This engine is primarily for position-level cost basis tracking
in paper/live trading and for dividend income tracking.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import pandas as pd

from qp.shared.protocols.base_corporate_action import (
    CorporateActionEngine as CorpActionABC,
)


class ActionType(StrEnum):
    """Corporate action types."""

    CASH_DIVIDEND = "cash_dividend"  # 现金分红
    STOCK_DIVIDEND = "stock_dividend"  # 送股
    SPLIT = "split"  # 拆股
    RIGHTS_ISSUE = "rights_issue"  # 配股
    BONUS_ISSUE = "bonus_issue"  # 转增


class CorporateActionEngine(CorpActionABC):
    """Engine for adjusting portfolios through corporate actions.

    Usage:
        engine = CorporateActionEngine()
        actions = pd.DataFrame([{
            "symbol": "600519",
            "ex_date": "2024-06-19",
            "action_type": "cash_dividend",
            "dividend_per_share": 25.91,
        }])
        adjusted = engine.adjust_portfolio(portfolio_df, actions)
    """

    def adjust_portfolio(
        self,
        portfolio: pd.DataFrame,
        actions_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply corporate actions to portfolio holdings.

        Args:
            portfolio: Current holdings with columns:
                [symbol, shares, avg_cost, cash].
            actions_df: Corporate actions with columns:
                [symbol, ex_date, action_type, dividend_per_share (optional),
                 split_ratio (optional), rights_ratio (optional),
                 rights_price (optional), bonus_ratio (optional)].

        Returns:
            Adjusted portfolio DataFrame with same schema.
        """
        result = portfolio.copy()

        if actions_df.empty or portfolio.empty:
            return result

        for _, action in actions_df.iterrows():
            symbol = action["symbol"]
            action_type = ActionType(action["action_type"])
            mask = result["symbol"] == symbol

            if not mask.any():
                continue

            idx = result[mask].index[0]

            if action_type == ActionType.CASH_DIVIDEND:
                result = self._apply_cash_dividend(result, idx, action)
            elif action_type == ActionType.STOCK_DIVIDEND:
                result = self._apply_stock_dividend(result, idx, action)
            elif action_type == ActionType.SPLIT:
                result = self._apply_split(result, idx, action)
            elif action_type == ActionType.RIGHTS_ISSUE:
                result = self._apply_rights_issue(result, idx, action)
            elif action_type == ActionType.BONUS_ISSUE:
                result = self._apply_bonus_issue(result, idx, action)

        return result

    # ------------------------------------------------------------------
    # Individual action handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_cash_dividend(
        df: pd.DataFrame,
        idx: Any,
        action: pd.Series,
    ) -> pd.DataFrame:
        """现金分红: increase cash, cost basis unchanged (price already adjusted)."""
        dps = float(action.get("dividend_per_share", 0.0) or 0.0)
        shares = int(df.at[idx, "shares"])
        dividend_income = shares * dps
        df.at[idx, "cash"] = df.at[idx, "cash"] + dividend_income
        return df

    @staticmethod
    def _apply_stock_dividend(
        df: pd.DataFrame,
        idx: Any,
        action: pd.Series,
    ) -> pd.DataFrame:
        """送股: increase shares, adjust cost basis down proportionally."""
        ratio = float(action.get("split_ratio", 0.0) or 0.0)  # type: ignore[arg-type]  # e.g., 10送3
        if ratio <= 0:
            return df

        shares = int(df.at[idx, "shares"])
        avg_cost = float(df.at[idx, "avg_cost"])
        bonus_shares = int(shares * ratio)
        if bonus_shares <= 0:
            return df

        total_cost = shares * avg_cost
        new_shares = shares + bonus_shares
        new_avg_cost = total_cost / new_shares if new_shares > 0 else 0.0

        df.at[idx, "shares"] = new_shares
        df.at[idx, "avg_cost"] = new_avg_cost
        return df

    @staticmethod
    def _apply_split(
        df: pd.DataFrame,
        idx: Any,
        action: pd.Series,
    ) -> pd.DataFrame:
        """拆股: multiply shares, divide cost basis."""
        ratio = float(action.get("split_ratio", 1.0) or 1.0)  # type: ignore[arg-type]  # e.g., 2.0 = 1拆2
        if ratio <= 0:
            return df

        shares = int(df.at[idx, "shares"])
        avg_cost = float(df.at[idx, "avg_cost"])

        df.at[idx, "shares"] = int(shares * ratio)
        df.at[idx, "avg_cost"] = avg_cost / ratio
        return df

    @staticmethod
    def _apply_rights_issue(
        df: pd.DataFrame,
        idx: Any,
        action: pd.Series,
    ) -> pd.DataFrame:
        """配股: add shares at subscription price, adjust cost basis."""
        ratio = float(action.get("rights_ratio", 0.0) or 0.0)  # type: ignore[arg-type]
        price = float(action.get("rights_price", 0.0) or 0.0)  # type: ignore[arg-type]

        if ratio <= 0:
            return df

        shares = int(df.at[idx, "shares"])
        avg_cost = float(df.at[idx, "avg_cost"])
        cash = float(df.at[idx, "cash"])

        rights_shares = int(shares * ratio)
        subscription_cost = rights_shares * price

        if subscription_cost > cash:
            # Not enough cash — subscribe partially
            rights_shares = int(cash / price) if price > 0 else 0

        actual_cost = rights_shares * price
        new_shares = shares + rights_shares
        new_total_cost = shares * avg_cost + actual_cost
        new_avg_cost = new_total_cost / new_shares if new_shares > 0 else 0.0

        df.at[idx, "shares"] = new_shares
        df.at[idx, "avg_cost"] = new_avg_cost
        df.at[idx, "cash"] = cash - actual_cost
        return df

    @staticmethod
    def _apply_bonus_issue(
        df: pd.DataFrame,
        idx: Any,
        action: pd.Series,
    ) -> pd.DataFrame:
        """转增: increase shares from capital reserve, adjust cost basis.

        Similar to stock dividend but from capital reserve (资本公积转增股本).
        """
        ratio = float(action.get("bonus_ratio", 0.0) or 0.0)  # type: ignore[arg-type]
        if ratio <= 0:
            return df

        shares = int(df.at[idx, "shares"])
        avg_cost = float(df.at[idx, "avg_cost"])
        bonus_shares = int(shares * ratio)
        if bonus_shares <= 0:
            return df

        total_cost = shares * avg_cost
        new_shares = shares + bonus_shares
        new_avg_cost = total_cost / new_shares if new_shares > 0 else 0.0

        df.at[idx, "shares"] = new_shares
        df.at[idx, "avg_cost"] = new_avg_cost
        return df


class CorporateActionLoader:
    """Loads corporate action data for A-share stocks.

    Currently: uses the Tencent adapter's built-in qfq (前复权) data.
    Future: load from AkShare's `stock_dividend_detail` and similar APIs.
    """

    @staticmethod
    def from_tencent_qfq() -> pd.DataFrame:
        """Return an empty action DataFrame.

        When using qfq (前复权) prices from Tencent, all price adjustments
        are already baked into the price series. No additional adjustments
        are needed for backtesting.

        For paper/live trading with raw prices, load actions from the
        exchange or data provider.
        """
        return pd.DataFrame(
            columns=[
                "symbol",
                "ex_date",
                "action_type",
                "dividend_per_share",
                "split_ratio",
                "rights_ratio",
                "rights_price",
                "bonus_ratio",
            ]
        )

    @staticmethod
    def create_portfolio_df(
        positions: dict[str, tuple[int, float]],
        cash: float = 0.0,
    ) -> pd.DataFrame:
        """Create a standard portfolio DataFrame for the engine.

        Args:
            positions: symbol → (shares, avg_cost) mapping.
            cash: Available cash.

        Returns:
            Portfolio DataFrame with [symbol, shares, avg_cost, cash].
        """
        rows = []
        for sym, (shares, avg_cost) in positions.items():
            rows.append(
                {
                    "symbol": sym,
                    "shares": shares,
                    "avg_cost": avg_cost,
                    "cash": cash,
                }
            )
        return pd.DataFrame(rows)
