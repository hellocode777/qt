"""StrategyResult — wrapper for a single strategy execution.

Per docs/6_Strategy_Engine.md 目录结构:
  "models/strategy_result.py"

Stores the output of one strategy.run() invocation along with
execution metadata for traceability and debugging.

Usage:
    result = StrategyResult(
        strategy_id="momentum_v1",
        date="2026-08-01",
        signals=[AlphaSignal(...), ...],
        elapsed_ms=145.3,
    )
    print(result.summary())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qp.shared.time import utc_iso
from qp.strategy.models.alpha_signal import AlphaSignal


@dataclass
class StrategyResult:
    """Output of a single strategy execution on one trading day.

    Captures the signals, execution context, and performance metadata
    for downstream analysis and audit trails.

    Attributes:
        strategy_id: Which strategy produced this result.
        date: Trading day (YYYY-MM-DD).
        signals: List of AlphaSignal objects produced.
        elapsed_ms: Wall-clock execution time in milliseconds.
        n_stocks_evaluated: Number of stocks in the input universe.
        n_stocks_selected: Number of stocks with valid signals.
        metadata: Arbitrary execution metadata (config used, etc.).
        generated_at: ISO-8601 timestamp of generation.
        success: Whether execution completed without error.
        error_message: Error description if success is False.
    """

    strategy_id: str
    date: str
    signals: list[AlphaSignal] = field(default_factory=list)
    elapsed_ms: float = 0.0
    n_stocks_evaluated: int = 0
    n_stocks_selected: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: utc_iso())
    success: bool = True
    error_message: str = ""

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    @property
    def is_empty(self) -> bool:
        return len(self.signals) == 0

    def top_n(self, n: int = 10) -> list[AlphaSignal]:
        """Return top-N signals by alpha_score."""
        return sorted(self.signals, key=lambda s: s.alpha_score, reverse=True)[:n]

    @property
    def mean_score(self) -> float:
        if not self.signals:
            return 0.0
        return sum(s.alpha_score for s in self.signals) / len(self.signals)

    @property
    def mean_confidence(self) -> float:
        if not self.signals:
            return 0.0
        return sum(s.confidence for s in self.signals) / len(self.signals)

    @property
    def coverage_ratio(self) -> float:
        """Fraction of evaluated stocks that produced signals."""
        if self.n_stocks_evaluated == 0:
            return 0.0
        return self.n_stocks_selected / self.n_stocks_evaluated

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Produce a human-readable summary dict."""
        return {
            "strategy_id": self.strategy_id,
            "date": self.date,
            "success": self.success,
            "signal_count": self.signal_count,
            "mean_score": round(self.mean_score, 4),
            "mean_confidence": round(self.mean_confidence, 4),
            "coverage": f"{self.coverage_ratio:.1%}",
            "elapsed_ms": round(self.elapsed_ms, 1),
            "n_evaluated": self.n_stocks_evaluated,
            "n_selected": self.n_stocks_selected,
            "error": self.error_message or None,
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "date": self.date,
            "signals": [s.to_dict() for s in self.signals],
            "elapsed_ms": self.elapsed_ms,
            "n_stocks_evaluated": self.n_stocks_evaluated,
            "n_stocks_selected": self.n_stocks_selected,
            "metadata": self.metadata,
            "generated_at": self.generated_at,
            "success": self.success,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyResult:
        return cls(
            strategy_id=str(data.get("strategy_id", "")),
            date=str(data.get("date", "")),
            signals=[AlphaSignal.from_dict(s) for s in data.get("signals", [])],
            elapsed_ms=float(data.get("elapsed_ms", 0.0)),
            n_stocks_evaluated=int(data.get("n_stocks_evaluated", 0)),
            n_stocks_selected=int(data.get("n_stocks_selected", 0)),
            metadata=data.get("metadata", {}),
            generated_at=str(data.get("generated_at", "")),
            success=bool(data.get("success", True)),
            error_message=str(data.get("error_message", "")),
        )

    # ------------------------------------------------------------------
    # Failure factory
    # ------------------------------------------------------------------

    @classmethod
    def failed(
        cls,
        strategy_id: str,
        date: str,
        error: str,
        **kwargs: Any,
    ) -> StrategyResult:
        """Create a StrategyResult representing a failed execution."""
        return cls(
            strategy_id=strategy_id,
            date=date,
            success=False,
            error_message=error,
            **kwargs,
        )
