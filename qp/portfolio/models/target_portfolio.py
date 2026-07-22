"""TargetPortfolio — Layer 8 final output to Layer 9 (Decision Layer).

Per docs/8_Capital_Allocation_Layer.md §"Layer 8 最终输出":
  "Layer 8 输出的应该是真正的目标组合"

Fields:
  date            — rebalance date
  symbol          — stock code or "CASH"
  target_weight   — target portfolio weight (e.g. 0.12 = 12%)
  target_capital  — target capital in CNY
  allocator_used  — algorithm name (e.g. "RiskParityAllocator")
  cash_reserve    — overall cash reserve ratio (e.g. 0.30 = 30%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import UTC, datetime

import pandas as pd
import polars as pl


@dataclass
class TargetPortfolio:
    """Final target portfolio output from Capital Allocation Layer.

    This is the input to the downstream Decision Layer. Each row represents
    one position (stock or cash) with its target weight and capital amount.

    Attributes:
        date: Rebalance date as ISO string ("2026-08-01").
        positions: List of (symbol, target_weight, target_capital) tuples.
        allocator_used: Name of the allocator algorithm.
        cash_reserve: Overall cash reserve ratio (0.0–1.0).
        total_capital: Total portfolio capital in CNY.
        generated_at: ISO timestamp of generation.
        metadata: Arbitrary extra context.
    """

    date: str = ""
    positions: list[dict[str, object]] = field(default_factory=list)
    allocator_used: str = ""
    cash_reserve: float = 0.0
    total_capital: float = 0.0
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience access
    # ------------------------------------------------------------------

    @property
    def symbols(self) -> list[str]:
        """All position symbols (including CASH if present)."""
        return [str(p["symbol"]) for p in self.positions]

    @property
    def equity_symbols(self) -> list[str]:
        """Stock symbols only (excluding CASH)."""
        return [str(p["symbol"]) for p in self.positions if str(p["symbol"]) != "CASH"]

    @property
    def n_positions(self) -> int:
        """Number of positions (including cash)."""
        return len(self.positions)

    @property
    def n_equities(self) -> int:
        """Number of equity positions (excluding cash)."""
        return len(self.equity_symbols)

    @property
    def total_equity_weight(self) -> float:
        """Sum of equity target weights."""
        return sum(float(p.get("target_weight", 0)) for p in self.positions if str(p["symbol"]) != "CASH")

    @property
    def cash_weight(self) -> float:
        """Cash position weight (from either cash row or cash_reserve field)."""
        for p in self.positions:
            if str(p["symbol"]) == "CASH":
                return float(p.get("target_weight", 0))
        return self.cash_reserve

    @property
    def weight_sum(self) -> float:
        """Sum of all target weights (should ≈ 1.0)."""
        return sum(float(p.get("target_weight", 0)) for p in self.positions)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dataframe(self) -> pd.DataFrame:
        """Convert positions to a pandas DataFrame."""
        if not self.positions:
            return pd.DataFrame(
                columns=["date", "symbol", "target_weight", "target_capital", "allocator_used", "cash_reserve"]
            )
        rows = []
        for p in self.positions:
            rows.append(
                {
                    "date": self.date,
                    "symbol": str(p["symbol"]),
                    "target_weight": float(p.get("target_weight", 0)),
                    "target_capital": float(p.get("target_capital", 0)),
                    "allocator_used": self.allocator_used,
                    "cash_reserve": self.cash_reserve,
                }
            )
        return pd.DataFrame(rows)

    def to_polars(self) -> pl.DataFrame:
        """Convert positions to a Polars DataFrame."""
        return pl.from_pandas(self.to_dataframe())

    def to_dict(self) -> dict[str, object]:
        """Full serialization including metadata."""
        return {
            "date": self.date,
            "positions": self.positions,
            "allocator_used": self.allocator_used,
            "cash_reserve": self.cash_reserve,
            "total_capital": self.total_capital,
            "generated_at": self.generated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TargetPortfolio:
        """Deserialize from a dictionary."""
        return cls(
            date=str(data.get("date", "")),
            positions=list(data.get("positions", [])),
            allocator_used=str(data.get("allocator_used", "")),
            cash_reserve=float(data.get("cash_reserve", 0)),
            total_capital=float(data.get("total_capital", 0)),
            generated_at=str(data.get("generated_at", "")),
            metadata=dict(data.get("metadata", {})),
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_allocator_output(
        cls,
        date: str,
        positions_df: pd.DataFrame,
        allocator_used: str,
        cash_reserve: float,
        total_capital: float,
    ) -> TargetPortfolio:
        """Build TargetPortfolio from an allocator's output DataFrame.

        Args:
            date: Rebalance date string.
            positions_df: Allocator output with [symbol, target_weight, target_capital].
            allocator_used: Name of the allocator.
            cash_reserve: Cash reserve ratio.
            total_capital: Total portfolio capital.

        Returns:
            TargetPortfolio instance.
        """
        positions: list[dict[str, object]] = []
        for _, row in positions_df.iterrows():
            positions.append(
                {
                    "symbol": str(row["symbol"]),
                    "target_weight": float(row.get("target_weight", 0)),
                    "target_capital": float(row.get("target_capital", 0)),
                }
            )

        # Add explicit CASH row if cash_reserve > 0
        if cash_reserve > 0:
            positions.append(
                {
                    "symbol": "CASH",
                    "target_weight": cash_reserve,
                    "target_capital": total_capital * cash_reserve,
                }
            )

        return cls(
            date=date,
            positions=positions,
            allocator_used=allocator_used,
            cash_reserve=cash_reserve,
            total_capital=total_capital,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Validate the target portfolio. Returns list of issues (empty = valid)."""
        issues: list[str] = []

        # Check weight sum
        w_sum = self.weight_sum
        if abs(w_sum - 1.0) > 0.02:
            issues.append(f"Weight sum is {w_sum:.4f}, expected ~1.0")

        # Check no negative weights
        for p in self.positions:
            wt = float(p.get("target_weight", 0))
            if wt < 0:
                issues.append(f"Negative weight for {p['symbol']}: {wt}")

        # Check cash_reserve consistency
        if self.cash_reserve < 0 or self.cash_reserve > 1.0:
            issues.append(f"cash_reserve out of range: {self.cash_reserve}")

        return issues

    @property
    def is_valid(self) -> bool:
        """True if the portfolio passes validation."""
        return len(self.validate()) == 0

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """One-line summary of the target portfolio."""
        return (
            f"TargetPortfolio({self.date}) — "
            f"{self.n_equities} stocks, "
            f"cash={self.cash_weight:.1%}, "
            f"allocator={self.allocator_used}, "
            f"total=¥{self.total_capital:,.0f}"
        )

    def format_table(self) -> str:
        """Formatted ASCII table for terminal display."""
        lines: list[str] = []
        sep = "─" * 64
        lines.append(sep)
        lines.append(f"  Target Portfolio — {self.date}  |  {self.allocator_used}")
        lines.append(sep)
        lines.append(f"  {'Symbol':<12s} {'Weight':>8s}  {'Capital':>14s}")
        lines.append(f"  {'-' * 12} {'-' * 8}  {'-' * 14}")

        for p in self.positions:
            symbol = str(p["symbol"])
            wt = float(p.get("target_weight", 0))
            cap = float(p.get("target_capital", 0))
            lines.append(f"  {symbol:<12s} {wt:7.2%}  ¥{cap:>13,.0f}")

        lines.append(f"  {'-' * 12} {'-' * 8}  {'-' * 14}")
        lines.append(f"  {'Total':<12s} {self.weight_sum:7.2%}  ¥{self.total_capital:>13,.0f}")
        lines.append(sep)
        return "\n".join(lines)
