"""SimulatedBroker — backtesting broker with realistic execution simulation.

Implements BaseBroker for BACKTESTING ONLY with:
  - Market order execution at next bar's price
  - Transaction cost tracking (stamp tax, commission, slippage, impact)
  - ADV-based liquidity limits (single order ≤ 10% ADV)
  - Cash and position tracking
  - Full trade log

DESIGN NOTE: QP is a decision-support system, not an automated trading system.
The SimulatedBroker exists purely for backtesting — to estimate what would happen
if the user followed the system's recommendations. In production, the system
outputs buy/sell RECOMMENDATIONS (see decision/ layer), and the user executes
trades manually through their own brokerage account.

See plan_v1.md §8.4 (M4.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import polars as pl

from qp.portfolio.cost_model import CostModel
from qp.shared.protocols.base_broker import BaseBroker
from qp.simulation.slippage import BaseSlippageModel, create_slippage_model

DEFAULT_ADV_LIMIT = 0.10  # Single order ≤ 10% of ADV


@dataclass
class Position:
    """Tracked position with cost basis."""

    symbol: str
    shares: int = 0
    avg_cost: float = 0.0
    market_value: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        if self.shares == 0:
            return 0.0
        return self.market_value - self.shares * self.avg_cost


@dataclass
class Trade:
    """A single executed trade."""

    timestamp: str = ""
    symbol: str = ""
    side: str = ""
    shares: int = 0
    price: float = 0.0
    commission: float = 0.0
    stamp_tax: float = 0.0
    slippage: float = 0.0
    market_impact: float = 0.0
    total_cost: float = 0.0
    net_amount: float = 0.0


class SimulatedBroker(BaseBroker):
    """Paper-trading broker with realistic execution and cost tracking.

    Usage:
        broker = SimulatedBroker(initial_cash=100_000)
        broker.set_prices(today_prices_df, adv_map)   # Called each day
        order_id = broker.submit_order({"symbol": "600519", "side": "BUY", "quantity": 1000})
        broker.execute_pending(execution_price_map)   # Execute at fill prices
        positions = broker.get_positions()
        cash = broker.get_cash()
    """

    def __init__(
        self,
        initial_cash: float = 100_000,
        slippage_model: str = "fixed",
        adv_limit: float = DEFAULT_ADV_LIMIT,
    ) -> None:
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._positions: dict[str, Position] = {}
        self._pending_orders: list[dict] = []
        self._trade_log: list[Trade] = []
        self._order_counter: int = 0

        self._cost_model = CostModel()
        self._slippage_model: BaseSlippageModel = create_slippage_model(slippage_model)
        self._adv_limit = adv_limit

        # Per-day state (set via set_prices())
        self._current_prices: dict[str, float] = {}
        self._adv_map: dict[str, float] = {}
        self._current_date: str = ""

    # ------------------------------------------------------------------
    # BaseBroker interface
    # ------------------------------------------------------------------

    def submit_order(self, order: dict[str, Any]) -> str:
        """Submit an order for execution.

        Args:
            order: {
                "symbol": str,
                "side": "BUY" | "SELL",
                "quantity": int,
                "order_type": "market" | "limit",
                "limit_price": float | None,
            }

        Returns:
            Order ID string.
        """
        self._order_counter += 1
        order_id = f"ord_{self._order_counter:06d}"
        order["order_id"] = order_id
        order["submitted_at"] = self._current_date

        # Validate
        symbol = order.get("symbol", "")
        side = order.get("side", "BUY").upper()
        quantity = int(order.get("quantity", 0))

        if quantity <= 0:
            order["status"] = "REJECTED"
            order["reject_reason"] = "Quantity must be positive"
            self._pending_orders.append(order)
            return order_id

        if side not in ("BUY", "SELL"):
            order["status"] = "REJECTED"
            order["reject_reason"] = f"Invalid side: {side}"
            self._pending_orders.append(order)
            return order_id

        # Liquidity check
        adv = self._adv_map.get(symbol, 0.0)
        if adv > 0:
            price = self._current_prices.get(symbol, 0.0)
            trade_value = price * quantity
            if trade_value > adv * self._adv_limit:
                trimmed_qty = int(adv * self._adv_limit / price)
                if trimmed_qty < 100:
                    order["status"] = "REJECTED"
                    order["reject_reason"] = (
                        f"Trade value {trade_value:.0f} exceeds ADV limit "
                        f"({self._adv_limit:.0%} of {adv:.0f})"
                    )
                    self._pending_orders.append(order)
                    return order_id
                order["quantity"] = trimmed_qty
                order["adv_trimmed"] = True

        # Cash check for buys
        if side == "BUY":
            price = self._current_prices.get(symbol, 0.0)
            est_cost = price * order["quantity"] * 1.003  # ~0.3% buffer for costs
            if est_cost > self._cash:
                order["status"] = "REJECTED"
                order["reject_reason"] = (
                    f"Insufficient cash: need {est_cost:.0f}, have {self._cash:.0f}"
                )
                self._pending_orders.append(order)
                return order_id

        # Position check for sells
        if side == "SELL":
            pos = self._positions.get(symbol)
            if pos is None or pos.shares < order["quantity"]:
                order["status"] = "REJECTED"
                order["reject_reason"] = (
                    f"Insufficient shares: need {order['quantity']}, "
                    f"have {pos.shares if pos else 0}"
                )
                self._pending_orders.append(order)
                return order_id

        order["status"] = "PENDING"
        self._pending_orders.append(order)
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        for i, order in enumerate(self._pending_orders):
            if order.get("order_id") == order_id and order.get("status") == "PENDING":
                order["status"] = "CANCELLED"
                self._pending_orders[i] = order
                return True
        return False

    def get_positions(self) -> pd.DataFrame:
        """Get current positions as DataFrame."""
        rows = []
        for sym, pos in self._positions.items():
            price = self._current_prices.get(sym, pos.avg_cost)
            rows.append(
                {
                    "symbol": sym,
                    "shares": pos.shares,
                    "avg_cost": pos.avg_cost,
                    "current_price": price,
                    "market_value": pos.shares * price,
                    "unrealized_pnl": pos.shares * (price - pos.avg_cost),
                }
            )
        return pd.DataFrame(rows)

    def get_cash(self) -> float:
        """Available cash."""
        return self._cash

    def restore_positions(
        self, positions: dict[str, int], avg_costs: dict[str, float] | None = None
    ) -> None:
        """Restore a persisted position map (symbol → shares) into the broker.

        Used by paper trading to continue holding positions across days
        instead of starting fresh each day. Position cost basis is
        restored from avg_costs when provided, otherwise market price.

        Args:
            positions: Mapping of symbol → share count.
            avg_costs: Optional mapping of symbol → average cost basis.
        """
        for sym, shares in positions.items():
            if shares <= 0:
                continue
            if sym not in self._positions:
                self._positions[sym] = Position(symbol=sym)
            pos = self._positions[sym]
            pos.shares = shares
            price = self._current_prices.get(sym, avg_costs.get(sym, 0.0) if avg_costs else 0.0)
            if avg_costs and sym in avg_costs:
                pos.avg_cost = avg_costs[sym]
            if price > 0:
                pos.market_value = shares * price

    # ------------------------------------------------------------------
    # Simulation API
    # ------------------------------------------------------------------

    def set_prices(
        self,
        prices: dict[str, float],
        adv_map: dict[str, float] | None = None,
        current_date: str = "",
    ) -> None:
        """Update current market prices for the day.

        Called once per simulation day before order submission.

        Args:
            prices: symbol → current price mapping.
            adv_map: symbol → ADV mapping (for liquidity checks).
            current_date: Current simulation date (YYYY-MM-DD).
        """
        self._current_prices = prices
        self._adv_map = adv_map or {}
        self._current_date = current_date

        # Mark positions to market
        for sym, pos in self._positions.items():
            if sym in prices:
                pos.market_value = pos.shares * prices[sym]

    def execute_pending(self) -> list[Trade]:
        """Execute all pending market orders at current prices.

        Call after set_prices() and submit_order() for the day.

        Returns:
            List of executed Trades.
        """
        executed: list[Trade] = []

        for order in list(self._pending_orders):
            if order.get("status") not in ("PENDING", "SUBMITTED"):
                continue

            symbol = order["symbol"]
            side = order["side"]
            quantity = order["quantity"]
            price = self._current_prices.get(symbol, 0.0)

            if price <= 0:
                order["status"] = "REJECTED"
                order["reject_reason"] = "No price available"
                continue

            # Compute slippage
            slippage_per_share = self._slippage_model.compute(
                price=price,
                volume=quantity,
                side=side,
                daily_volume=self._adv_map.get(symbol),
            )
            fill_price = price + (slippage_per_share if side == "BUY" else -slippage_per_share)
            fill_price = max(fill_price, 0.01)

            trade_value = fill_price * quantity

            # Cost
            cost = self._cost_model.estimate_trade(
                symbol=symbol,
                trade_value=trade_value,
                side=side,
                daily_volume=self._adv_map.get(symbol),
            )

            net_amount = trade_value + (cost.total_cost if side == "BUY" else -cost.total_cost)
            net_amount = net_amount if side == "BUY" else -net_amount

            # Cash check
            total_cash_needed = net_amount if side == "BUY" else 0
            if total_cash_needed > self._cash:
                # Trim
                max_qty = int(self._cash / fill_price / 1.003)
                if max_qty < 100:
                    order["status"] = "REJECTED"
                    order["reject_reason"] = "Insufficient cash after price update"
                    continue
                quantity = max_qty // 100 * 100
                trade_value = fill_price * quantity
                net_amount = trade_value + cost.total_cost  # re-estimate

            # Execute
            trade = Trade(
                timestamp=self._current_date,
                symbol=symbol,
                side=side,
                shares=quantity,
                price=fill_price,
                commission=cost.commission,
                stamp_tax=cost.stamp_tax,
                slippage=cost.slippage,
                market_impact=cost.market_impact,
                total_cost=cost.total_cost,
                net_amount=net_amount,
            )
            executed.append(trade)
            self._trade_log.append(trade)

            # Update cash
            if side == "BUY":
                self._cash -= net_amount
            else:
                self._cash += -net_amount

            # Update position
            if symbol not in self._positions:
                self._positions[symbol] = Position(symbol=symbol)
            pos = self._positions[symbol]

            if side == "BUY":
                total_shares = pos.shares + quantity
                total_cost_basis = pos.shares * pos.avg_cost + fill_price * quantity
                pos.shares = total_shares
                pos.avg_cost = total_cost_basis / total_shares if total_shares > 0 else 0.0
                # Mark-to-market immediately so get_equity() is correct
                # right after execution (not only after the next set_prices)
                pos.market_value = total_shares * fill_price
            else:
                pos.shares -= quantity
                if pos.shares == 0:
                    pos.avg_cost = 0.0
                    pos.market_value = 0.0

            order["status"] = "FILLED"

        # Clear processed orders
        self._pending_orders = [
            o
            for o in self._pending_orders
            if o.get("status") not in ("FILLED", "REJECTED", "CANCELLED")
        ]

        return executed

    def get_equity(self) -> float:
        """Total portfolio equity (cash + positions market value)."""
        positions_mv = sum(p.market_value for p in self._positions.values())
        return self._cash + positions_mv

    def get_trade_log(self) -> pl.DataFrame:
        """Full trade log as a Polars DataFrame."""
        if not self._trade_log:
            return pl.DataFrame()
        return pl.DataFrame(
            [
                {
                    "timestamp": t.timestamp,
                    "symbol": t.symbol,
                    "side": t.side,
                    "shares": t.shares,
                    "price": t.price,
                    "commission": t.commission,
                    "stamp_tax": t.stamp_tax,
                    "slippage": t.slippage,
                    "market_impact": t.market_impact,
                    "total_cost": t.total_cost,
                    "net_amount": t.net_amount,
                }
                for t in self._trade_log
            ]
        )

    def get_order_log(self) -> list[dict]:
        """Return all order records (including rejected/cancelled)."""
        return list(self._pending_orders)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def trade_count(self) -> int:
        return len(self._trade_log)

    @property
    def total_commission(self) -> float:
        return sum(t.commission for t in self._trade_log)

    @property
    def total_stamp_tax(self) -> float:
        return sum(t.stamp_tax for t in self._trade_log)

    @property
    def total_slippage(self) -> float:
        return sum(t.slippage for t in self._trade_log)

    @property
    def total_market_impact(self) -> float:
        return sum(t.market_impact for t in self._trade_log)

    @property
    def total_trading_cost(self) -> float:
        return sum(t.total_cost for t in self._trade_log)

    @property
    def initial_capital(self) -> float:
        return self._initial_cash
