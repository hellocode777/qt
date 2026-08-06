"""AllocationResult — records one capital allocation execution.

Per docs/8_Capital_Allocation_Layer.md §模块设计:
  Captures input parameters, allocator used, output target portfolio,
  and metadata for downstream audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

import pandas as pd

from qp.portfolio.models.target_portfolio import TargetPortfolio

_Number = float | int | str


@dataclass
class AllocationResult:
    """Result of one capital allocation call.

    Records what went in (candidates, risk_report, capital), what algorithm
    was used, and what came out (target portfolio). Designed for auditability
    and downstream consumption by Decision Layer.

    Attributes:
        allocator_used: Name of the allocator (e.g. "EqualWeightAllocator").
        target_portfolio: The output TargetPortfolio.
        n_candidates_in: Number of candidates passed in.
        n_positions_out: Number of equity positions allocated.
        cash_reserve: Final cash reserve ratio.
        total_capital: Total capital in CNY.
        elapsed_ms: Allocation computation time in milliseconds.
        warnings: Any warnings or notes from the allocation process.
        generated_at: ISO timestamp.
        metadata: Arbitrary extra context.
    """

    allocator_used: str = ""
    target_portfolio: TargetPortfolio | None = None
    n_candidates_in: int = 0
    n_positions_out: int = 0
    cash_reserve: float = 0.0
    total_capital: float = 0.0
    elapsed_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def has_warnings(self) -> bool:
        """True if the allocation produced warnings."""
        return len(self.warnings) > 0

    @property
    def total_equity_weight(self) -> float:
        """Total equity allocation weight (1 - cash_reserve)."""
        return 1.0 - self.cash_reserve

    @property
    def invested_capital(self) -> float:
        """Capital actually allocated to equities."""
        return self.total_capital * self.total_equity_weight

    @property
    def avg_position_weight(self) -> float:
        """Average equity position weight."""
        if self.n_positions_out == 0:
            return 0.0
        return self.total_equity_weight / self.n_positions_out

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Full serialization."""
        return {
            "allocator_used": self.allocator_used,
            "target_portfolio": self.target_portfolio.to_dict()
            if self.target_portfolio
            else None,
            "n_candidates_in": self.n_candidates_in,
            "n_positions_out": self.n_positions_out,
            "cash_reserve": self.cash_reserve,
            "total_capital": self.total_capital,
            "elapsed_ms": self.elapsed_ms,
            "warnings": self.warnings,
            "generated_at": self.generated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AllocationResult:
        """Deserialize from a dictionary."""
        tp_dict = data.get("target_portfolio")
        tp = (
            TargetPortfolio.from_dict(cast("dict[str, object]", tp_dict))
            if isinstance(tp_dict, dict)
            else None
        )
        return cls(
            allocator_used=str(data.get("allocator_used", "")),
            target_portfolio=tp,
            n_candidates_in=int(cast("_Number", data.get("n_candidates_in", 0))),
            n_positions_out=int(cast("_Number", data.get("n_positions_out", 0))),
            cash_reserve=float(cast("_Number", data.get("cash_reserve", 0))),
            total_capital=float(cast("_Number", data.get("total_capital", 0))),
            elapsed_ms=float(cast("_Number", data.get("elapsed_ms", 0))),
            warnings=list(cast("list[str]", data.get("warnings", []))),
            generated_at=str(data.get("generated_at", "")),
            metadata=dict(cast("dict[str, str]", data.get("metadata", {}))),
        )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """One-line summary of the allocation result."""
        parts = [
            f"allocator={self.allocator_used}",
            f"candidates {self.n_candidates_in}→{self.n_positions_out}",
            f"equity={self.total_equity_weight:.1%}",
            f"cash={self.cash_reserve:.1%}",
            f"capital=¥{self.total_capital:,.0f}",
        ]
        if self.elapsed_ms > 0:
            parts.append(f"t={self.elapsed_ms:.1f}ms")
        if self.warnings:
            parts.append(f"⚠ ×{len(self.warnings)}")
        return " | ".join(parts)

    def to_dataframe(self) -> pd.DataFrame:
        """Return target portfolio as a DataFrame (delegates to TargetPortfolio)."""
        if self.target_portfolio is None:
            return pd.DataFrame(
                columns=[
                    "date",
                    "symbol",
                    "target_weight",
                    "target_capital",
                    "allocator_used",
                    "cash_reserve",
                ]
            )
        return self.target_portfolio.to_dataframe()
