"""BaseBroker — unified broker API for paper and live trading.

See rule.md §7.7 for the complete specification.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseBroker(ABC):
    """Abstract base for broker APIs.

    Enables seamless switching between Paper Trading and Live Trading
    without changing strategy or portfolio code.
    """

    @abstractmethod
    def submit_order(self, order: dict) -> str:
        """Submit an order to the broker.

        Args:
            order: Order details (symbol, side, quantity, price, type).

        Returns:
            Broker-assigned order ID.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order.

        Args:
            order_id: Broker-assigned order ID.

        Returns:
            True if the order was successfully cancelled.
        """
        ...

    @abstractmethod
    def get_positions(self) -> pd.DataFrame:
        """Get current positions.

        Returns:
            DataFrame of current holdings.
        """
        ...

    @abstractmethod
    def get_cash(self) -> float:
        """Get available cash balance.

        Returns:
            Current cash balance.
        """
        ...
