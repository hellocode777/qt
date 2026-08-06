"""NAVLedger — daily portfolio NAV (Net Asset Value) time-series tracking.

Records a snapshot of total portfolio equity after every daily pipeline run
so that portfolio-level performance metrics (Sharpe, MaxDD, Calmar, etc.)
can be computed from historical data rather than placeholders.

Storage: ``data/portfolio/nav_history.parquet``

Usage:
    ledger = NAVLedger()
    ledger.record_daily(
        date="2026-07-31",
        total_value=1_050_000.0,
        cash=50_000.0,
    )
    history = ledger.load_history()
    latest = ledger.get_latest()
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from loguru import logger

NAV_DIR = Path("data/portfolio")
NAV_PARQUET = NAV_DIR / "nav_history.parquet"


class NAVLedger:
    """Tracks daily portfolio NAV with Parquet persistence.

    Usage:
        ledger = NAVLedger()
        ledger.record_daily(date="2026-07-31", total_value=1_050_000.0, cash=50_000.0)
        df = ledger.load_history()
        latest = ledger.get_latest()
    """

    def __init__(self) -> None:
        NAV_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_daily(
        self,
        date: str,
        total_value: float,
        cash: float = 0.0,
        benchmark_value: float | None = None,
        n_positions: int = 0,
        decision_id: str = "",
    ) -> None:
        """Record or update a daily NAV snapshot.

        If a record for ``date`` already exists it is replaced (idempotent).
        """
        row = {
            "date": date,
            "total_nav": round(total_value, 2),
            "cash": round(cash, 2),
            "positions_value": round(total_value - cash, 2),
            "benchmark_value": round(benchmark_value, 2) if benchmark_value is not None else None,
            "n_positions": n_positions,
            "decision_id": decision_id,
        }
        new_df = pl.DataFrame([row])

        if NAV_PARQUET.exists():
            existing = pl.read_parquet(str(NAV_PARQUET))
            existing = existing.filter(pl.col("date") != date)
            combined = pl.concat([existing, new_df], how="diagonal_relaxed")
        else:
            combined = new_df

        combined.write_parquet(str(NAV_PARQUET))
        logger.debug("NAV {}: ¥{:,.0f} ({} positions)", date, total_value, n_positions)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_history(self) -> pl.DataFrame:
        """Load full NAV time series sorted by date.

        Returns empty DataFrame if no history exists.
        """
        if not NAV_PARQUET.exists():
            return pl.DataFrame()
        df = pl.read_parquet(str(NAV_PARQUET))
        if df.is_empty():
            return df
        return df.sort("date")

    def get_latest(self) -> dict | None:
        """Return the most recent NAV snapshot as a dict, or None."""
        df = self.load_history()
        if df.is_empty():
            return None
        latest = df.tail(1)
        return latest.to_dicts()[0]

    def get_history_dicts(self, days: int = 252) -> list[dict]:
        """Return recent NAV history as list of dicts (for web display)."""
        df = self.load_history()
        if df.is_empty():
            return []
        return df.tail(days).to_dicts()

    def row_count(self) -> int:
        """Number of daily NAV records."""
        if not NAV_PARQUET.exists():
            return 0
        return pl.read_parquet(str(NAV_PARQUET)).height
