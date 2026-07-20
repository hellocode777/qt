"""BaseBroker — unified broker interface for simulation (backtest + paper trading).

See rule.md §7.7 for the complete specification.

DESIGN NOTE: QP is a decision-support system, NOT an automated trading system.
The system generates buy/sell RECOMMENDATIONS. The user executes trades manually.
This interface exists ONLY for backtesting and paper-trading simulation — there is
no live broker adapter and there never will be.
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
