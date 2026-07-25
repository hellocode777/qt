"""Failure Archive Logger — structured stop-loss & black-swan event records.

Implements the failure_archive table from docs/11_12.md:
  - Stop-loss events with feature snapshots at buy time (L12-1.3)
  - Kill Switch trigger events with market context
  - Black-swan events with full factor cross-section data
  - Long-term: clustering analysis → blacklist rules for Layer 2/3

Storage: Parquet under data/knowledge/, plus Markdown entries in
KnowledgeArchive for human review.

Usage:
    logger = FailureArchiveLogger()
    logger.record_stop_loss(
        date="2026-07-25",
        symbol="000001.SZ",
        buy_date="2026-06-15",
        buy_price=15.80,
        sell_price=14.22,
        loss_pct=-0.10,
        feature_snapshot={"Momentum_1M": -0.03, "PE_TTM": 25.0},
    )
    # Query for clustering
    failures = logger.load_history(days=365)
    clusters = logger.get_feature_patterns(tag="STOP_LOSS")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl

from qp.knowledge.archive import KnowledgeArchive, KnowledgeCategory

DEFAULT_FAILURE_DIR = "data/knowledge"
FAILURE_LOG_FILE = "failure_archive.parquet"


class FailureType(StrEnum):
    """Types of failure events."""

    STOP_LOSS = "STOP_LOSS"  # Individual stock stop-loss
    KILL_SWITCH = "KILL_SWITCH"  # Portfolio-level kill switch
    BLACK_SWAN = "BLACK_SWAN"  # Extreme market event
    GATE_FAILURE = "GATE_FAILURE"  # Strategy failed validation gate
    MODEL_DECAY = "MODEL_DECAY"  # Model performance decay


_FAILURE_LOG_SCHEMA: dict[str, type] = {
    "date": str,
    "timestamp": str,
    "symbol": str,
    "failure_type": str,
    "strategy_name": str,
    "buy_date": str,
    "buy_price": float,
    "sell_price": float,
    "loss_pct": float,
    "feature_snapshot": str,  # JSON dict
    "market_regime": str,
    "trigger_reason": str,
    "kill_switch_level": str,
    "tags": str,  # JSON array
}


@dataclass
class FailureRecord:
    """One failure event record.

    Attributes:
        date: Event date (YYYY-MM-DD).
        timestamp: ISO timestamp.
        symbol: Stock symbol (empty for portfolio-level events).
        failure_type: STOP_LOSS / KILL_SWITCH / BLACK_SWAN / etc.
        strategy_name: Which strategy.
        buy_date: When the position was entered.
        buy_price: Entry price.
        sell_price: Exit price (0 if not sold).
        loss_pct: Percentage loss.
        feature_snapshot: Dict of factor values at buy time.
        market_regime: Regime at event time.
        trigger_reason: What triggered the failure.
        kill_switch_level: NORMAL / WARNING / HALT_BUY / FULL_STOP.
        tags: Searchable tags.
        notes: Free-text notes.
    """

    date: str = ""
    timestamp: str = ""
    symbol: str = ""
    failure_type: str = "STOP_LOSS"
    strategy_name: str = ""
    buy_date: str = ""
    buy_price: float = 0.0
    sell_price: float = 0.0
    loss_pct: float = 0.0
    feature_snapshot: dict[str, float] = field(default_factory=dict)
    market_regime: str = "UNKNOWN"
    trigger_reason: str = ""
    kill_switch_level: str = "NORMAL"
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        import json

        return {
            "date": self.date,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "failure_type": self.failure_type,
            "strategy_name": self.strategy_name,
            "buy_date": self.buy_date,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "loss_pct": self.loss_pct,
            "feature_snapshot": json.dumps(self.feature_snapshot, ensure_ascii=False),
            "market_regime": self.market_regime,
            "trigger_reason": self.trigger_reason,
            "kill_switch_level": self.kill_switch_level,
            "tags": json.dumps(self.tags, ensure_ascii=False),
        }


class FailureArchiveLogger:
    """Structured logger for failure events (T3 per docs/11_12.md).

    Records stop-loss events with factor snapshots, kill switch triggers,
    and black-swan events. Enables later clustering analysis to find
    common failure patterns → blacklist rules.

    Dual storage:
      - Parquet for machine querying (clustering, pattern mining)
      - Markdown via KnowledgeArchive for human review

    Usage:
        logger = FailureArchiveLogger()
        logger.record_stop_loss(
            date="2026-07-25",
            symbol="000001.SZ",
            buy_date="2026-06-15",
            buy_price=15.80,
            sell_price=14.22,
            loss_pct=-0.10,
            feature_snapshot={"Momentum_1M": -0.03},
        )
    """

    def __init__(self, base_dir: str = DEFAULT_FAILURE_DIR) -> None:
        self._base = Path(base_dir)
        self._filepath = self._base / FAILURE_LOG_FILE
        self._archive = KnowledgeArchive(base_dir=str(self._base))

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def record_stop_loss(
        self,
        date: str = "",
        symbol: str = "",
        strategy_name: str = "",
        buy_date: str = "",
        buy_price: float = 0.0,
        sell_price: float = 0.0,
        loss_pct: float = 0.0,
        feature_snapshot: dict[str, float] | None = None,
        market_regime: str = "UNKNOWN",
        trigger_reason: str = "",
        notes: str = "",
        tags: list[str] | None = None,
    ) -> FailureRecord:
        """Record a stop-loss event with feature snapshot at buy time.

        Args:
            date: Event date.
            symbol: Stock symbol.
            strategy_name: Strategy name.
            buy_date: Date position was entered.
            buy_price: Entry price.
            sell_price: Exit price.
            loss_pct: Loss percentage (negative).
            feature_snapshot: Dict of factor → value at buy time.
            market_regime: Regime classification at event.
            trigger_reason: Why stop-loss fired.
            notes: Free-text.
            tags: Tags for search.

        Returns:
            FailureRecord.
        """
        record = FailureRecord(
            date=date or datetime.now(UTC).strftime("%Y-%m-%d"),
            timestamp=datetime.now(UTC).isoformat(),
            symbol=symbol,
            failure_type=FailureType.STOP_LOSS,
            strategy_name=strategy_name,
            buy_date=buy_date,
            buy_price=buy_price,
            sell_price=sell_price,
            loss_pct=loss_pct,
            feature_snapshot=feature_snapshot or {},
            market_regime=market_regime,
            trigger_reason=trigger_reason or f"Stop-loss: {loss_pct:.1%}",
            tags=tags or ["STOP_LOSS", symbol],
            notes=notes,
        )
        self._append(record)
        self._archive_to_knowledge(record)
        return record

    def record_kill_switch(
        self,
        date: str = "",
        strategy_name: str = "",
        kill_switch_level: str = "HALT_BUY",
        market_regime: str = "UNKNOWN",
        trigger_reason: str = "",
        notes: str = "",
        tags: list[str] | None = None,
    ) -> FailureRecord:
        """Record a kill switch trigger event.

        Args:
            date: Event date.
            strategy_name: Strategy name (empty = portfolio-level).
            kill_switch_level: NORMAL / WARNING / HALT_BUY / FULL_STOP.
            market_regime: Regime when KS fired.
            trigger_reason: What triggered it.
            notes: Additional context.
            tags: Search tags.

        Returns:
            FailureRecord.
        """
        record = FailureRecord(
            date=date or datetime.now(UTC).strftime("%Y-%m-%d"),
            timestamp=datetime.now(UTC).isoformat(),
            symbol="",  # Portfolio-level
            failure_type=FailureType.KILL_SWITCH,
            strategy_name=strategy_name,
            market_regime=market_regime,
            trigger_reason=trigger_reason,
            kill_switch_level=kill_switch_level,
            tags=tags or ["KILL_SWITCH", kill_switch_level.lower()],
            notes=notes,
        )
        self._append(record)
        self._archive_to_knowledge(record)
        return record

    def record_black_swan(
        self,
        date: str = "",
        symbol: str = "",
        strategy_name: str = "",
        loss_pct: float = 0.0,
        feature_snapshot: dict[str, float] | None = None,
        market_regime: str = "UNKNOWN",
        trigger_reason: str = "",
        notes: str = "",
        tags: list[str] | None = None,
    ) -> FailureRecord:
        """Record a black-swan event with factor cross-section.

        Args:
            date: Event date.
            symbol: Stock symbol (or empty for market-wide).
            strategy_name: Strategy name.
            loss_pct: Percentage loss.
            feature_snapshot: Full factor cross-section at event time.
            market_regime: Regime classification.
            trigger_reason: Description of the event.
            notes: Detailed analysis.
            tags: Search tags.

        Returns:
            FailureRecord.
        """
        record = FailureRecord(
            date=date or datetime.now(UTC).strftime("%Y-%m-%d"),
            timestamp=datetime.now(UTC).isoformat(),
            symbol=symbol,
            failure_type=FailureType.BLACK_SWAN,
            strategy_name=strategy_name,
            loss_pct=loss_pct,
            feature_snapshot=feature_snapshot or {},
            market_regime=market_regime,
            trigger_reason=trigger_reason,
            tags=tags or ["BLACK_SWAN"],
            notes=notes,
        )
        self._append(record)
        self._archive_to_knowledge(record)
        return record

    # ------------------------------------------------------------------
    # Read / Analysis API
    # ------------------------------------------------------------------

    def load_history(self, days: int = 365) -> pl.DataFrame:
        """Load failure archive history.

        Args:
            days: Lookback in calendar days.

        Returns:
            Polars DataFrame, newest first.
        """
        if not self._filepath.exists():
            return pl.DataFrame(schema=_FAILURE_LOG_SCHEMA)

        df = pl.read_parquet(self._filepath)
        if df.is_empty():
            return df

        if len(df) > days * 10:
            df = df.sort("date", descending=True).head(days * 5)

        return df.sort("date", descending=True)

    def query_by_type(self, failure_type: str, days: int = 365) -> pl.DataFrame:
        """Get all failures of a specific type."""
        df = self.load_history(days=days)
        if df.is_empty():
            return df
        return df.filter(pl.col("failure_type") == failure_type)

    def query_by_symbol(self, symbol: str, days: int = 365) -> pl.DataFrame:
        """Get all failure events for a specific stock."""
        df = self.load_history(days=days)
        if df.is_empty():
            return df
        return df.filter(pl.col("symbol") == symbol)

    def get_feature_patterns(
        self,
        failure_type: str = "STOP_LOSS",
        min_records: int = 10,
        days: int = 365,
    ) -> dict[str, dict[str, float]]:
        """Extract average feature values for clustering analysis.

        Groups failures by type and computes mean feature values.
        Use this to find common patterns → blacklist rules.

        Args:
            failure_type: Which failure type to analyze.
            min_records: Minimum records needed for meaningful stats.
            days: Lookback window.

        Returns:
            Dict: {feature_name: {mean, std, count}}.
        """
        import json

        df = self.query_by_type(failure_type, days=days)
        if df.is_empty() or df.height < min_records:
            return {}

        # Parse feature snapshots from JSON
        all_features: dict[str, list[float]] = {}
        for row in df.iter_rows(named=True):
            try:
                snapshot = json.loads(row["feature_snapshot"])
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
            for feat, val in snapshot.items():
                if feat not in all_features:
                    all_features[feat] = []
                all_features[feat].append(float(val))

        patterns: dict[str, dict[str, float]] = {}
        for feat, values in all_features.items():
            if len(values) >= min_records:
                import numpy as np

                arr = np.array(values)
                patterns[feat] = {
                    "mean": float(np.mean(arr)),
                    "std": float(np.std(arr)),
                    "count": float(len(values)),
                }

        return patterns

    def stats(self, days: int = 365) -> dict[str, Any]:
        """Summary statistics."""
        df = self.load_history(days=days)
        if df.is_empty():
            return {"n_failures": 0}

        avg_loss = 0.0
        loss_df = df.filter(pl.col("loss_pct") != 0.0)
        if not loss_df.is_empty():
            avg_loss = float(loss_df["loss_pct"].mean())  # type: ignore[arg-type]

        return {
            "n_failures": df.height,
            "n_symbols": df["symbol"].n_unique(),
            "avg_loss_pct": avg_loss,
            "type_distribution": dict(df.group_by("failure_type").len().iter_rows()),
            "regime_distribution": dict(df.group_by("market_regime").len().iter_rows()),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, record: FailureRecord) -> None:
        """Append to Parquet file."""
        self._base.mkdir(parents=True, exist_ok=True)
        new_row = pl.DataFrame([record.to_dict()], schema=_FAILURE_LOG_SCHEMA)

        if self._filepath.exists():
            existing = pl.read_parquet(self._filepath)
            combined = pl.concat([existing, new_row], how="vertical")
            combined.write_parquet(self._filepath)
        else:
            new_row.write_parquet(self._filepath)

    def _archive_to_knowledge(self, record: FailureRecord) -> None:
        """Also create a Markdown entry for human review."""
        try:
            content = (
                f"## Failure Event\n\n"
                f"- **Date**: {record.date}\n"
                f"- **Type**: {record.failure_type}\n"
                f"- **Symbol**: {record.symbol or 'PORTFOLIO'}\n"
                f"- **Strategy**: {record.strategy_name}\n"
                f"- **Loss**: {record.loss_pct:.1%}\n"
                f"- **Regime**: {record.market_regime}\n"
                f"- **Trigger**: {record.trigger_reason}\n"
                f"- **KS Level**: {record.kill_switch_level}\n"
                f"\n## Feature Snapshot\n\n"
                f"```json\n{record.feature_snapshot}\n```\n"
                f"\n## Notes\n\n{record.notes}\n"
            )
            self._archive.create_entry(
                category=KnowledgeCategory.FAILURE_ANALYSIS,
                title=f"[{record.failure_type}] {record.symbol or 'PORTFOLIO'} {record.date}",
                content=content,
                tags=record.tags,
                metadata={
                    "failure_type": record.failure_type,
                    "symbol": record.symbol,
                    "date": record.date,
                    "loss_pct": f"{record.loss_pct:.4f}",
                },
            )
        except Exception:
            pass  # Best-effort archival
