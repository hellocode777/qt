"""AlphaSignal — the standardised output of the Strategy Engine.

Per docs/6_Strategy_Engine.md §"Alpha Signal 的数据结构":
  Layer 6 传递给 Layer 7 的 AlphaSignal，采用无状态且带有元数据的
  可序列化结构，不仅包含 Alpha Score，还保留追踪信息（Traceability）。

Every strategy in the engine ultimately produces one thing:
  "今天什么股票值得看好，程度是多少（0~1）"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AlphaSignal:
    """A single stock's alpha signal for one trading day.

    This is the canonical output of Layer 6. It carries the normalised
    alpha score, optional per-strategy breakdown for attribution, and
    a confidence estimate.

    Attributes:
        date: Trading day for which the signal was generated.
        symbol: Stock code (e.g. "600519.SH").
        alpha_score: Normalised composite score in [0.0, 1.0].
        raw_components: Per-strategy raw scores for attribution
            (e.g. {"momentum": 0.88, "quality": 0.98}).
        confidence: Confidence / validity of this signal in [0.0, 1.0].
        strategy_id: Strategy that produced this signal (for traceability).
        generated_at: ISO-8601 timestamp of signal generation.
    """

    date: str
    symbol: str
    alpha_score: float
    raw_components: dict[str, float] = field(default_factory=dict)
    confidence: float = 1.0
    strategy_id: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Clamp alpha_score and confidence to [0, 1]."""
        self.alpha_score = max(0.0, min(1.0, float(self.alpha_score)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-safe)."""
        return {
            "date": self.date,
            "symbol": self.symbol,
            "alpha_score": self.alpha_score,
            "raw_components": self.raw_components,
            "confidence": self.confidence,
            "strategy_id": self.strategy_id,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlphaSignal:
        """Deserialize from a plain dict."""
        return cls(
            date=str(data.get("date", "")),
            symbol=str(data.get("symbol", "")),
            alpha_score=float(data.get("alpha_score", 0.0)),
            raw_components=data.get("raw_components", {}),
            confidence=float(data.get("confidence", 1.0)),
            strategy_id=str(data.get("strategy_id", "")),
            generated_at=str(data.get("generated_at", "")),
        )


@dataclass
class AlphaSignalBatch:
    """A collection of AlphaSignals for a single trading day.

    Convenience wrapper for passing signals from Layer 6 to Layer 7.
    Provides ranking, filtering, and serialization.

    Usage:
        batch = AlphaSignalBatch(
            date="2026-08-01",
            signals=[AlphaSignal(...), ...],
        )
        top10 = batch.top_n(10)
        print(batch.summary())
    """

    date: str
    signals: list[AlphaSignal] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self.signals)

    @property
    def symbols(self) -> list[str]:
        return [s.symbol for s in self.signals]

    @property
    def is_empty(self) -> bool:
        return len(self.signals) == 0

    def top_n(self, n: int = 10) -> list[AlphaSignal]:
        """Return the top-N signals by alpha_score (descending)."""
        return sorted(self.signals, key=lambda s: s.alpha_score, reverse=True)[:n]

    def above_threshold(self, threshold: float = 0.5) -> list[AlphaSignal]:
        """Return signals with alpha_score >= threshold."""
        return [s for s in self.signals if s.alpha_score >= threshold]

    def filter_confidence(self, min_confidence: float = 0.5) -> list[AlphaSignal]:
        """Return signals with confidence >= min_confidence."""
        return [s for s in self.signals if s.confidence >= min_confidence]

    def get_by_symbol(self, symbol: str) -> AlphaSignal | None:
        """Look up a signal by stock code."""
        for s in self.signals:
            if s.symbol == symbol:
                return s
        return None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Compute summary statistics for the batch."""
        if not self.signals:
            return {
                "date": self.date,
                "count": 0,
                "mean": 0.0,
                "std": 0.0,
                "min": 0.0,
                "max": 0.0,
                "mean_confidence": 0.0,
            }

        scores = [s.alpha_score for s in self.signals]
        confs = [s.confidence for s in self.signals]
        n = len(scores)
        mean_score = sum(scores) / n
        variance = sum((x - mean_score) ** 2 for x in scores) / n
        std_score = variance**0.5

        return {
            "date": self.date,
            "count": n,
            "mean": round(mean_score, 4),
            "std": round(std_score, 4),
            "min": round(min(scores), 4),
            "max": round(max(scores), 4),
            "mean_confidence": round(sum(confs) / n, 4),
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-safe)."""
        return {
            "date": self.date,
            "signals": [s.to_dict() for s in self.signals],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlphaSignalBatch:
        """Deserialize from a plain dict."""
        return cls(
            date=str(data.get("date", "")),
            signals=[AlphaSignal.from_dict(s) for s in data.get("signals", [])],
        )

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def to_polars(self):
        """Convert to a Polars DataFrame.

        Returns:
            Polars DataFrame with columns matching AlphaSignal fields.
        """
        import polars as pl

        if not self.signals:
            return pl.DataFrame(
                schema={
                    "date": pl.Utf8,
                    "symbol": pl.Utf8,
                    "alpha_score": pl.Float64,
                    "confidence": pl.Float64,
                    "strategy_id": pl.Utf8,
                }
            )

        return pl.DataFrame(
            {
                "date": [s.date for s in self.signals],
                "symbol": [s.symbol for s in self.signals],
                "alpha_score": [s.alpha_score for s in self.signals],
                "confidence": [s.confidence for s in self.signals],
                "strategy_id": [s.strategy_id for s in self.signals],
            }
        )

    @classmethod
    def from_polars(cls, df, date_str: str = "") -> AlphaSignalBatch:
        """Create a batch from a Polars DataFrame.

        Expected columns: symbol, alpha_score (or raw_score), and
        optionally confidence, strategy_id.
        """
        if df.is_empty():
            return cls(date=date_str)

        signals: list[AlphaSignal] = []
        for row in df.iter_rows(named=True):
            signals.append(
                AlphaSignal(
                    date=date_str or str(row.get("date", "")),
                    symbol=str(row.get("symbol", "")),
                    alpha_score=float(row.get("alpha_score", row.get("raw_score", 0.0))),
                    confidence=float(row.get("confidence", 1.0)),
                    strategy_id=str(row.get("strategy_id", "")),
                )
            )
        return cls(date=date_str, signals=signals)
