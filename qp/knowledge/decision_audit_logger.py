"""Decision Audit Logger — structured trade decision records.

Implements the trade_decision_audit table from docs/11_12.md:
  - Daily raw target portfolio snapshots (L12-4.2)
  - Trade recommendations with structured reason tags (L12-4.3)
  - Human-in-the-loop override records
  - Execution price vs signal price tracking

Storage: Parquet files under data/decisions/.

Usage:
    logger = DecisionAuditLogger()
    logger.record_signal(
        date="2026-07-25",
        symbol="000001.SZ",
        action="BUY",
        score=0.85,
        reason_tags=["RANK_TOP20", "MOMENTUM_SIGNAL"],
    )
    # Later:
    df = logger.load_history(days=90)
    overrides = logger.query_human_overrides()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl

DEFAULT_AUDIT_DIR = "data/decisions"
AUDIT_LOG_FILE = "trade_decision_audit.parquet"


class TradeAction(StrEnum):
    """Trade action types."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    REDUCE = "REDUCE"


class ReasonTag(StrEnum):
    """Structured trade reason tags per docs/11_12.md.

    Every trade recommendation MUST carry at least one reason tag.
    """

    RANK_TOP20 = "RANK_TOP20"  # Ranked in top 20 by composite score
    RANK_DROP = "RANK_DROP"  # Fell out of top-N ranking
    STOP_LOSS = "STOP_LOSS"  # Triggered stop-loss threshold
    RISK_EVENT = "RISK_EVENT"  # Risk management override
    REGIME_GATE = "REGIME_GATE"  # Market regime filter
    CHASE_GATE = "CHASE_GATE"  # Anti-chase filter
    SELL_BUFFER = "SELL_BUFFER"  # Sell buffer (rank > 2× top-N)
    REBALANCE = "REBALANCE"  # Scheduled rebalance
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"  # Human decision
    LIQUIDITY = "LIQUIDITY"  # Liquidity constraint


_AUDIT_LOG_SCHEMA: dict[str, type] = {
    "date": str,
    "timestamp": str,
    "symbol": str,
    "action": str,
    "score": float,
    "rank": int,
    "reason_tags": str,  # JSON array string
    "signal_price": float,
    "execution_price": float,
    "quantity": int,
    "human_override": bool,
    "override_reason": str,
    "strategy_name": str,
}


@dataclass
class DecisionRecord:
    """One trade decision record.

    Attributes:
        date: Trading date (YYYY-MM-DD).
        timestamp: ISO timestamp when recorded.
        symbol: Stock symbol.
        action: BUY / SELL / HOLD / REDUCE.
        score: Composite factor score that drove the decision.
        rank: Rank in the cross-section (1 = best).
        reason_tags: List of ReasonTag values.
        signal_price: Price at signal generation time.
        execution_price: Actual execution price (if executed).
        quantity: Number of shares (0 if not executed).
        human_override: Whether a human overrode the system.
        override_reason: Why the override happened.
        strategy_name: Which strategy generated the signal.
    """

    date: str = ""
    timestamp: str = ""
    symbol: str = ""
    action: str = "HOLD"
    score: float = 0.0
    rank: int = 0
    reason_tags: list[str] = field(default_factory=list)
    signal_price: float = 0.0
    execution_price: float = 0.0
    quantity: int = 0
    human_override: bool = False
    override_reason: str = ""
    strategy_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        import json

        return {
            "date": self.date,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "action": self.action,
            "score": self.score,
            "rank": self.rank,
            "reason_tags": json.dumps(self.reason_tags, ensure_ascii=False),
            "signal_price": self.signal_price,
            "execution_price": self.execution_price,
            "quantity": self.quantity,
            "human_override": self.human_override,
            "override_reason": self.override_reason,
            "strategy_name": self.strategy_name,
        }


class DecisionAuditLogger:
    """Structured logger for trade decisions (T2 per docs/11_12.md).

    Appends records to a Parquet file. Supports querying by date,
    strategy, override status, and reason tags.

    Usage:
        logger = DecisionAuditLogger()
        logger.record_signal(
            date="2026-07-25",
            symbol="000001.SZ",
            action="BUY",
            score=0.85,
            reason_tags=["RANK_TOP20"],
        )
        # Batch record daily portfolio
        logger.record_portfolio_snapshot(signals_df, date_str="2026-07-25")
    """

    def __init__(self, base_dir: str = DEFAULT_AUDIT_DIR) -> None:
        self._base = Path(base_dir)
        self._filepath = self._base / AUDIT_LOG_FILE

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def record_signal(
        self,
        date: str = "",
        symbol: str = "",
        action: str = "HOLD",
        score: float = 0.0,
        rank: int = 0,
        reason_tags: list[str] | None = None,
        signal_price: float = 0.0,
        execution_price: float = 0.0,
        quantity: int = 0,
        human_override: bool = False,
        override_reason: str = "",
        strategy_name: str = "",
    ) -> DecisionRecord:
        """Record a single trade decision.

        Args:
            date: Trading date (YYYY-MM-DD).
            symbol: Stock symbol.
            action: BUY / SELL / HOLD / REDUCE.
            score: Composite score.
            rank: Cross-sectional rank.
            reason_tags: List of ReasonTag values.
            signal_price: Signal generation price.
            execution_price: Actual fill price.
            quantity: Shares.
            human_override: Human override flag.
            override_reason: Override explanation.
            strategy_name: Strategy identifier.

        Returns:
            The created DecisionRecord.
        """
        record = DecisionRecord(
            date=date or datetime.now(UTC).strftime("%Y-%m-%d"),
            timestamp=datetime.now(UTC).isoformat(),
            symbol=symbol,
            action=action,
            score=score,
            rank=rank,
            reason_tags=reason_tags or [],
            signal_price=signal_price,
            execution_price=execution_price,
            quantity=quantity,
            human_override=human_override,
            override_reason=override_reason,
            strategy_name=strategy_name,
        )
        self._append(record)
        return record

    def record_portfolio_snapshot(
        self,
        signals: pl.DataFrame,
        date_str: str = "",
        strategy_name: str = "",
    ) -> int:
        """Batch record a daily portfolio snapshot from a signals DataFrame.

        Expects a Polars DataFrame with columns matching DecisionRecord fields.
        At minimum: [symbol, action, score]. Optional: [rank, reason_tags].

        Args:
            signals: DataFrame with one row per trade decision.
            date_str: Trading date.
            strategy_name: Strategy name for all records.

        Returns:
            Number of records written.
        """
        if signals.is_empty():
            return 0

        date_val = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
        records: list[DecisionRecord] = []

        for row in signals.iter_rows(named=True):
            tags_raw = row.get("reason_tags", [])
            if isinstance(tags_raw, str):
                import json

                try:
                    tags_raw = json.loads(tags_raw)
                except (json.JSONDecodeError, TypeError):
                    tags_raw = [tags_raw] if tags_raw else []

            records.append(
                DecisionRecord(
                    date=date_val,
                    timestamp=datetime.now(UTC).isoformat(),
                    symbol=str(row.get("symbol", "")),
                    action=str(row.get("action", "HOLD")),
                    score=float(row.get("score", 0.0)),
                    rank=int(row.get("rank", 0)),
                    reason_tags=list(tags_raw) if tags_raw else [],
                    signal_price=float(row.get("signal_price", 0.0)),
                    execution_price=float(row.get("execution_price", 0.0)),
                    quantity=int(row.get("quantity", 0)),
                    human_override=bool(row.get("human_override", False)),
                    override_reason=str(row.get("override_reason", "")),
                    strategy_name=strategy_name,
                )
            )

        if records:
            self._append_batch(records)
        return len(records)

    def record_human_override(
        self,
        date: str,
        symbol: str,
        original_action: str,
        override_action: str,
        reason: str,
        strategy_name: str = "",
    ) -> DecisionRecord:
        """Record a human override of a system decision.

        Args:
            date: Trading date.
            symbol: Stock symbol.
            original_action: What the system recommended.
            override_action: What the human decided.
            reason: Why the override (e.g., "post-market announcement").
            strategy_name: Strategy name.

        Returns:
            DecisionRecord with human_override=True.
        """
        return self.record_signal(
            date=date,
            symbol=symbol,
            action=override_action,
            reason_tags=[ReasonTag.MANUAL_OVERRIDE],
            human_override=True,
            override_reason=(f"Override {original_action} → {override_action}: {reason}"),
            strategy_name=strategy_name,
        )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def load_history(self, days: int = 90) -> pl.DataFrame:
        """Load recent decision audit history.

        Args:
            days: Lookback in calendar days.

        Returns:
            Polars DataFrame, newest first.
        """
        if not self._filepath.exists():
            return pl.DataFrame(schema=_AUDIT_LOG_SCHEMA)

        df = pl.read_parquet(self._filepath)
        if df.is_empty():
            return df

        if len(df) > days * 100:  # Approximate filter
            # Keep last N days roughly
            df = df.sort("date", descending=True).head(days * 50)

        return df.sort("date", descending=True)

    def query_by_date(self, date_str: str) -> pl.DataFrame:
        """Get all decisions for a specific trading date."""
        df = self.load_history(days=365)
        if df.is_empty():
            return df
        return df.filter(pl.col("date") == date_str)

    def query_human_overrides(self, days: int = 90) -> pl.DataFrame:
        """Get all human override records."""
        df = self.load_history(days=days)
        if df.is_empty():
            return df
        return df.filter(pl.col("human_override"))

    def query_by_strategy(self, strategy_name: str, days: int = 90) -> pl.DataFrame:
        """Get all decisions for a specific strategy."""
        df = self.load_history(days=days)
        if df.is_empty():
            return df
        return df.filter(pl.col("strategy_name") == strategy_name)

    def query_by_tag(self, tag: str, days: int = 90) -> pl.DataFrame:
        """Get decisions containing a specific reason tag.

        Args:
            tag: ReasonTag value to search for.
            days: Lookback days.

        Returns:
            Filtered DataFrame.
        """
        df = self.load_history(days=days)
        if df.is_empty():
            return df
        return df.filter(pl.col("reason_tags").str.contains(tag))

    def stats(self, days: int = 90) -> dict[str, Any]:
        """Summary statistics for the audit log."""
        df = self.load_history(days=days)
        if df.is_empty():
            return {"n_decisions": 0}

        n_overrides = df.filter(pl.col("human_override")).height

        return {
            "n_decisions": df.height,
            "n_dates": df["date"].n_unique(),
            "n_symbols": df["symbol"].n_unique(),
            "n_human_overrides": n_overrides,
            "action_distribution": dict(df.group_by("action").len().iter_rows()),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, record: DecisionRecord) -> None:
        """Append a single record."""
        self._base.mkdir(parents=True, exist_ok=True)
        new_row = pl.DataFrame([record.to_dict()], schema=_AUDIT_LOG_SCHEMA)

        if self._filepath.exists():
            existing = pl.read_parquet(self._filepath)
            combined = pl.concat([existing, new_row], how="vertical")
            combined.write_parquet(self._filepath)
        else:
            new_row.write_parquet(self._filepath)

    def _append_batch(self, records: list[DecisionRecord]) -> None:
        """Append multiple records efficiently."""
        self._base.mkdir(parents=True, exist_ok=True)
        rows = [r.to_dict() for r in records]
        new_df = pl.DataFrame(rows, schema=_AUDIT_LOG_SCHEMA)

        if self._filepath.exists():
            existing = pl.read_parquet(self._filepath)
            combined = pl.concat([existing, new_df], how="vertical")
            combined.write_parquet(self._filepath)
        else:
            new_df.write_parquet(self._filepath)
