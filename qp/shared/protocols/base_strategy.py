"""BaseStrategy — the core Alpha-producing object.

A Strategy binds Feature + Model + Signal logic together.
It produces Decisions, not Orders (ADR-026).

See rule.md §7.4 for the complete specification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class BaseStrategy(ABC):
    """Abstract base for all investment strategies.

    Strategy = Feature + Label + Model + Portfolio Rule + Execution Rule + Exit Rule.

    Note: DataFrame types are left as Any to allow both pandas and polars
    implementations (TDR-010).
    """

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """Unique strategy identifier including version (e.g. 'lgb_rank_v3.1')."""
        ...

    @abstractmethod
    def generate_signals(self, as_of_date: date) -> Any:
        """Generate raw Alpha signals from a PIT perspective.

        Args:
            as_of_date: The reference date for signal generation.
                        No data after this date may be used.

        Returns:
            DataFrame with columns [symbol, raw_score, rank].
        """
        ...
