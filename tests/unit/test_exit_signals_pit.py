"""Tests for PIT (point-in-time) filtering in FundamentalExitDetector.

Covers the 2026-08-25 fix: financials whose publish_date is AFTER the
as_of_date must not be used for exit decisions (no look-ahead into
unpublished quarterly reports).

2026-09-03 (V2.3): data contract is percent-scaled (ROE=10.17 means 10.17%,
not 0.1017 — matches quality_filter.py). Detector normalizes ÷100 internally
and compares cumulative/point-in-time metrics YoY (same period a year earlier),
never latest-vs-previous-quarter.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from qp.portfolio.exit_signals import FundamentalExitDetector


@dataclass
class FakePosition:
    symbol: str
    is_active: bool = True


def _fund(
    symbol: str,
    report_dates: list[str],
    publish_dates: list[str],
    roes: list[float] | None = None,
    rev_growths: list[float] | None = None,
    np_growths: list[float] | None = None,
) -> pl.DataFrame:
    """Build a fundamental df with PERCENT-scaled values (10.17 = 10.17%)."""
    n = len(report_dates)
    roes = roes or [10.0] * n
    rev_growths = rev_growths or [5.0] * n
    np_growths = np_growths or [5.0] * n
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "report_date": report_dates,
            "publish_date": publish_dates,
            "ROE": roes,
            "revenue_growth": rev_growths,
            "net_profit_growth": np_growths,
            "debt_ratio": [40.0] * n,
        }
    ).with_columns(
        pl.col("report_date").str.to_date(),
        pl.col("publish_date").str.to_date(),
    )


class TestPitExitSignals:
    def test_unpublished_report_not_used(self) -> None:
        """Q2 report (report_date 2026-06-30, published 2026-08-30) must be
        invisible on 2026-08-15 — deterioration in it must NOT trigger."""
        # 2025Q2 healthy baseline, 2026Q2 collapsed but UNPUBLISHED by as_of.
        fund = _fund(
            "600000",
            report_dates=["2025-06-30", "2026-06-30"],
            publish_dates=["2025-08-25", "2026-08-30"],
            roes=[12.0, 2.0],
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
            report_dates=["2025-06-30", "2026-06-30"],
            publish_dates=["2025-08-25", "2026-08-30"],
            roes=[12.0, 2.0],
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
            report_dates=["2025-06-30", "2026-06-30"],
            publish_dates=["2025-08-25", "2026-08-30"],
            roes=[12.0, 2.0],
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("600000")],
            fundamental_data={"600000": fund},
        )
        assert len(exits) == 1


class TestFundamentalUnitAndPeriod:
    """2026-09-02 regressions: ×100 display bug + Q1-vs-annual false positive."""

    def test_display_is_percent_not_thousand(self) -> None:
        """ROE 12.0 → 2.0 (percent-scaled) must display as 12.0%→2.0%, not
        1200%→200%."""
        fund = _fund(
            "600001",
            report_dates=["2025-06-30", "2026-06-30"],
            publish_dates=["2025-08-25", "2026-08-30"],
            roes=[12.0, 2.0],
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("600001")],
            fundamental_data={"600001": fund},
            as_of_date="2026-08-31",
        )
        assert len(exits) == 1
        detail = exits[0].detail
        assert "12.0%" in detail and "2.0%" in detail
        assert "1200%" not in detail and "200.0%" not in detail

    def test_q1_vs_annual_not_false_positive(self) -> None:
        """2026Q1 ROE (2.17, cumulative 1 quarter) vs 2025FY (10.17, cumulative
        4 quarters) must NOT trigger — different period type.

        Real 2026-09-02 case: 002608 was flagged "ROE 1017%→217% 恶化79%"
        because Q1 was compared against the annual report.
        """
        fund = _fund(
            "002608",
            report_dates=["2025-12-31", "2026-03-31"],
            publish_dates=["2026-04-25", "2026-04-25"],
            roes=[10.17, 2.17],
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("002608")],
            fundamental_data={"002608": fund},
            as_of_date="2026-09-02",
        )
        assert exits == []

    def test_q1_vs_q1_yoy_triggers_on_real_decline(self) -> None:
        """Same period type (Q1→Q1) with real YoY decline still triggers."""
        fund = _fund(
            "002608",
            report_dates=["2025-03-31", "2026-03-31"],
            publish_dates=["2025-04-25", "2026-04-25"],
            roes=[8.0, 2.0],
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("002608")],
            fundamental_data={"002608": fund},
            as_of_date="2026-09-02",
        )
        assert len(exits) == 1

    def test_growth_threshold_percent_scale(self) -> None:
        """revenue_growth -42.87 (=-42.87%) vs -10% threshold triggers;
        -9.73 (=-9.73%) vs -20% net-profit threshold does NOT (was falsely
        triggering as '-973%')."""
        # Case A: revenue -42.87% < -10% → triggers
        fund_a = _fund(
            "600207",
            report_dates=["2025-12-31", "2026-03-31"],
            publish_dates=["2026-04-25", "2026-04-25"],
            rev_growths=[5.0, -42.87],
            np_growths=[5.0, 5.0],
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("600207")],
            fundamental_data={"600207": fund_a},
            as_of_date="2026-09-02",
        )
        assert len(exits) == 1
        assert "营收增速 -42.9%" in exits[0].detail

        # Case B: net profit -9.73% > -20% threshold → no trigger (real 002608)
        fund_b = _fund(
            "002608",
            report_dates=["2025-12-31", "2026-03-31"],
            publish_dates=["2026-04-25", "2026-04-25"],
            rev_growths=[5.0, 13.32],
            np_growths=[5.0, -9.73],
        )
        exits = detector.check(
            active_positions=[FakePosition("002608")],
            fundamental_data={"002608": fund_b},
            as_of_date="2026-09-02",
        )
        assert exits == []

    def test_dirty_value_skipped(self) -> None:
        """Sanity bounds: debt_ratio 1.07e8 is dirty — must not trigger."""
        fund = _fund(
            "600001",
            report_dates=["2025-12-31", "2026-03-31"],
            publish_dates=["2026-04-25", "2026-04-25"],
            roes=[10.0, 10.0],
        )
        fund = fund.with_columns(
            pl.when(
                (pl.col("report_date").dt.month() == 3) & (pl.col("report_date").dt.day() == 31)
            )
            .then(pl.lit(107_408_119.0))
            .otherwise(pl.col("debt_ratio"))
            .alias("debt_ratio")
        )
        detector = FundamentalExitDetector()
        exits = detector.check(
            active_positions=[FakePosition("600001")],
            fundamental_data={"600001": fund},
            as_of_date="2026-09-02",
        )
        assert exits == []
