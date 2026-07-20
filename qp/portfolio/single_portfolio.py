"""SinglePortfolio — equal-weight portfolio for Walking Skeleton."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass
class Order:
    """A trade order."""

    symbol: str
    side: str  # BUY / SELL
    quantity: int
    price: float | None = None
    order_type: str = "market"


class SinglePortfolio:
    """Equal-weight portfolio that generates orders from signals."""

    def __init__(self, total_capital: float = 1_000_000) -> None:
        self._total_capital = total_capital

    def generate_orders(
        self,
        signals: pl.DataFrame,
        current_positions: pl.DataFrame | None = None,
    ) -> list[Order]:
        """Generate orders to equal-weight the target stocks.

        Args:
            signals: Strategy signals with [symbol, action].
            current_positions: Currently held positions (empty for Walking Skeleton).

        Returns:
            List of Order objects.
        """
        if signals.is_empty():
            return []

        n_stocks = len(signals)
        weight = 1.0 / n_stocks
        target_amount = self._total_capital * weight

        orders: list[Order] = []
        for row in signals.iter_rows(named=True):
            symbol = row["symbol"]
            action = row.get("action", "BUY")
            # Assume price 10 for Walking Skeleton (real implementation uses market data)
            estimated_price = 10.0
            quantity = int(target_amount / estimated_price // 100 * 100)  # Round to lots
            if quantity > 0:
                orders.append(
                    Order(symbol=symbol, side=action, quantity=quantity)
                )

        return orders
