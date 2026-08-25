"""Tests for PIT (point-in-time) filtering in FundamentalExitDetector.

Covers the 2026-08-25 fix: financials whose publish_date is AFTER the
as_of_date must not be used for exit decisions (no look-ahead into
unpublished quarterly reports).
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from qp.portfolio.exit_signals import FundamentalExitDetector


@dataclass
class FakePosition:
    symbol: str
    is_active: bool = True


def _fund(symbol: str, report_dates: list[str], publish_dates: list[str]) -> pl.DataFrame:
    n = len(report_dates)
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "report_date": report_dates,
            "publish_date": publish_dates,
            "ROE": [0.25] * n,
            "revenue_growth": [0.1] * n,
            "net_profit_growth": [0.1] * n,
            "debt_ratio": [0.4] * n,
        }
    ).with_columns(pl.col("publish_date").str.to_datetime())


class TestPitExitSignals:
    def test_unpublished_report_not_used(self) -> None:
        """Q2 report (report_date 2026-06-30, published 2026-08-30) must be
        invisible on 2026-08-15 — deterioration in it must NOT trigger."""
        # Q1 report: healthy. Q2 report (unpublished by as_of): collapsed ROE.
        fund = _fund(
            "600000",
            report_dates=["2026-03-31", "2026-06-30"],
            publish_dates=["2026-04-25", "2026-08-30"],
        )
        # Make the Q2 (latest) row look terrible
        fund = fund.with_columns(
            pl.when(pl.col("report_date") == "2026-06-30")
            .then(pl.lit(0.01))  # ROE collapse
            .otherwise(pl.col("ROE"))
            .alias("ROE")
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("600000")],
            fundamental_data={"600000": fund},
            as_of_date="2026-08-15",
        )
        assert exits == []

    def test_published_report_used(self) -> None:
        """Same Q2 deterioration, but as_of_date AFTER publish_date → triggers."""
        fund = _fund(
            "600000",
            report_dates=["2026-03-31", "2026-06-30"],
            publish_dates=["2026-04-25", "2026-08-30"],
        )
        fund = fund.with_columns(
            pl.when(pl.col("report_date") == "2026-06-30")
            .then(pl.lit(0.01))
            .otherwise(pl.col("ROE"))
            .alias("ROE")
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("600000")],
            fundamental_data={"600000": fund},
            as_of_date="2026-08-31",
        )
        assert len(exits) == 1
        assert any("ROE" in e.detail for e in exits)

    def test_no_as_of_date_uses_all(self) -> None:
        """Backward compatibility: as_of_date=None keeps old behaviour."""
        fund = _fund(
            "600000",
            report_dates=["2026-03-31", "2026-06-30"],
            publish_dates=["2026-04-25", "2026-08-30"],
        )
        fund = fund.with_columns(
            pl.when(pl.col("report_date") == "2026-06-30")
            .then(pl.lit(0.01))
            .otherwise(pl.col("ROE"))
            .alias("ROE")
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("600000")],
            fundamental_data={"600000": fund},
        )
        assert len(exits) == 1
