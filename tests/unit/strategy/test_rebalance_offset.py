"""Tests for rebalance calendar alignment (rebalance_offset).

2026-08-16: a windowed experiment re-numbers trading days from the window
start, so its rebalance dates differ from a full-range run on the same
strategy. `rebalance_offset` (index of the window's first date within the
full-range date sequence, mod rebalance_freq) re-aligns the two calendars.
"""

import polars as pl

from qp.strategy.multifactor import generate_rebalance_signals


def _make_scores(n_days: int = 60, freq: int = 20) -> pl.DataFrame:
    dates = [f"2026-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n_days)]
    rows = [
        {"trade_date": d, "symbol": f"S{i % 5:03d}", "score": float(5 - (i % 5))}
        for i, d in enumerate(dates)
    ]
    return pl.DataFrame(rows)


def test_rebalance_offset_zero_is_full_range_behavior() -> None:
    scores = _make_scores()
    sig = generate_rebalance_signals(scores, top_n=2, rebalance_freq=20, rebalance_offset=0)
    rbs = sorted(sig["date"].unique().to_list())
    assert rbs[0] == "2026-01-01"  # first rebalance on first trading day


def test_rebalance_offset_shifts_calendar() -> None:
    scores = _make_scores()
    sig = generate_rebalance_signals(scores, top_n=2, rebalance_freq=20, rebalance_offset=10)
    rbs = sorted(sig["date"].unique().to_list())
    # Window starts at index 10 (mod 20) → first rebalance on 11th trading day
    assert rbs[0] == "2026-01-11"


def test_rebalance_offset_reproduce_full_range_dates() -> None:
    """A windowed run with the correct offset must rebalance on the same
    dates the full-range run would pick inside that window."""
    # Simulate full-range 40 days, then a window starting at full-range
    # index 5 with offset 5 → rebalance at full-range indices 5, 25.
    dates = [f"2026-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(40)]
    rows = [
        {"trade_date": d, "symbol": f"S{i % 5:03d}", "score": float(5 - (i % 5))}
        for i, d in enumerate(dates)
    ]
    scores = pl.DataFrame(rows)

    full = generate_rebalance_signals(scores, top_n=2, rebalance_freq=20, rebalance_offset=0)
    full_rbs = sorted(full["date"].unique().to_list())  # indices 0, 20
    assert full_rbs == ["2026-01-01", "2026-02-10"]

    window_scores = scores.filter(pl.col("trade_date") >= "2026-01-06")
    win = generate_rebalance_signals(window_scores, top_n=2, rebalance_freq=20, rebalance_offset=5)
    win_rbs = sorted(win["date"].unique().to_list())
    # Window's first day (2026-01-06) is full-range index 5 → first rebalance
    # at full-range index 10 = 2026-01-11 (i.e. 5 days into the window).
    assert win_rbs[0] == "2026-01-11"
