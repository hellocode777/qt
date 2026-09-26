"""Equivalence tests for the price-window optimisation in `rank_ic`.

`compute_daily_ic_series` used to sort and shift the **entire** price history on
every call (7.3M rows → 1.1s per call, 168 calls per factor-health run).  It now
first drops the price rows no score date can reach.  These tests pin that the
optimised path returns **exactly** the same IC series as the unoptimised
reference implementation, including the suspension edge case the buffer exists
for.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from qp.research.evaluation.rank_ic import (
    _restrict_price_to_score_windows,
    compute_daily_ic_series,
)


def _trading_days(count: int, start: date = date(2025, 1, 2)) -> list[date]:
    """Calendar days (weekends included as holidays would be) for test frames."""
    return [start + timedelta(days=i) for i in range(count)]


def _reference_daily_ic(
    score_df: pl.DataFrame,
    price_df: pl.DataFrame,
    forward_days: int,
    min_stocks_per_day: int = 10,
) -> list[dict[str, object]]:
    """The pre-optimisation implementation, verbatim — the equivalence oracle."""
    px = price_df.sort(["symbol", "trade_date"])
    px = px.with_columns(
        (pl.col("close").shift(-forward_days).over("symbol") / pl.col("close") - 1).alias(
            "forward_return"
        )
    )
    px = px.drop_nulls(subset=["forward_return"])

    score_df = score_df.with_columns(pl.col("trade_date").cast(pl.Utf8))
    px = px.with_columns(pl.col("trade_date").cast(pl.Utf8))

    merged = score_df.join(
        px.select(["trade_date", "symbol", "forward_return"]),
        on=["trade_date", "symbol"],
        how="inner",
    )
    if merged.is_empty():
        return []

    from qp.research.evaluation.rank_ic import compute_rank_ic

    results: list[dict[str, object]] = []
    for d in sorted(merged["trade_date"].unique().to_list()):
        day = merged.filter(pl.col("trade_date") == d)
        if day.height < min_stocks_per_day:
            continue
        results.append(
            {
                "date": d,
                "ic": compute_rank_ic(day["score"].to_numpy(), day["forward_return"].to_numpy()),
                "n_stocks": day.height,
            }
        )
    return results


SYMBOLS = [f"S{i:02d}" for i in range(12)]


def _price_frame(suspend_days: list[date] | None = None) -> pl.DataFrame:
    """40 trading days × 12 symbols; symbol S00 is missing `suspend_days` rows.

    12 symbols keeps every cross-section above the default `min_stocks_per_day`.
    """
    days = _trading_days(40)
    suspend_days = suspend_days or []
    rows: list[dict[str, object]] = []
    for sym_i, symbol in enumerate(SYMBOLS):
        for i, day in enumerate(days):
            if symbol == "S00" and day in suspend_days:
                continue
            rows.append(
                {
                    "trade_date": day,
                    "symbol": symbol,
                    "close": 10.0 + sym_i + i * 0.1 + (i % 3) * 0.05 + (sym_i % 4) * 0.02,
                }
            )
    return pl.DataFrame(rows)


def _score_frame(dates: list[date]) -> pl.DataFrame:
    """Scores for every symbol on each date — non-degenerate across symbols."""
    rows = [
        {"trade_date": day, "symbol": symbol, "score": (sym_i - 5.5) + 0.1 * (day_i % 3)}
        for day_i, day in enumerate(dates)
        for sym_i, symbol in enumerate(SYMBOLS)
    ]
    return pl.DataFrame(rows)


class TestWindowRestrictionEquivalence:
    @pytest.mark.parametrize("forward_days", [1, 3, 5, 10, 20])
    def test_matches_reference_for_mid_series_scores(self, forward_days: int) -> None:
        price_df = _price_frame()
        score_df = _score_frame([date(2025, 1, 5), date(2025, 1, 20)])

        optimised = compute_daily_ic_series(score_df, price_df, forward_days=forward_days)
        reference = _reference_daily_ic(score_df, price_df, forward_days)

        assert optimised == reference
        assert optimised, "fixture must produce a non-empty IC series"

    @pytest.mark.parametrize("forward_days", [1, 5, 20])
    def test_matches_reference_when_score_is_on_last_day(self, forward_days: int) -> None:
        """The last trading day has no forward return — both paths return []."""
        price_df = _price_frame()
        last_day = price_df["trade_date"].max()
        assert isinstance(last_day, date)
        score_df = _score_frame([last_day])

        assert compute_daily_ic_series(
            score_df, price_df, forward_days=forward_days
        ) == _reference_daily_ic(score_df, price_df, forward_days)

    @pytest.mark.parametrize("forward_days", [1, 3, 10])
    def test_matches_reference_across_a_short_suspension(self, forward_days: int) -> None:
        """A 3-day suspension hole must stay covered by the window buffer."""
        days = _trading_days(40)
        price_df = _price_frame(suspend_days=days[10:13])
        score_df = _score_frame([days[8], days[9]])

        optimised = compute_daily_ic_series(score_df, price_df, forward_days=forward_days)
        reference = _reference_daily_ic(score_df, price_df, forward_days)

        assert optimised == reference
        assert optimised, "suspension must not empty the IC series"

    def test_matches_reference_for_every_forward_index(self) -> None:
        """Score every trading day: the whole IC series must be identical."""
        days = _trading_days(40)
        price_df = _price_frame(suspend_days=days[5:7])
        score_df = _score_frame(days)

        for forward_days in (1, 3, 5, 10, 20):
            assert compute_daily_ic_series(
                score_df, price_df, forward_days=forward_days
            ) == _reference_daily_ic(score_df, price_df, forward_days)


class TestWindowRestrictionGuards:
    def test_drops_unreachable_rows_but_keeps_the_horizon(self) -> None:
        price_df = _price_frame()
        days = _trading_days(40)
        score_df = _score_frame([days[30]])

        restricted = _restrict_price_to_score_windows(score_df, price_df, forward_days=5)

        assert restricted.height < price_df.height
        assert restricted["trade_date"].min() == days[30]
        # 5 forward days + the 10-day suspension buffer must survive.
        assert restricted["trade_date"].max() == days[39]

    def test_returns_frame_unchanged_for_empty_scores(self) -> None:
        price_df = _price_frame()
        empty = pl.DataFrame(schema={"trade_date": pl.Date, "symbol": pl.Utf8, "score": pl.Float64})

        assert compute_daily_ic_series(empty, price_df) == []
        assert _restrict_price_to_score_windows(empty, price_df, 5).height == price_df.height

    def test_score_dates_absent_from_price_do_not_break(self) -> None:
        price_df = _price_frame()
        score_df = _score_frame([date(2030, 1, 1)])

        assert compute_daily_ic_series(score_df, price_df) == []
        assert _restrict_price_to_score_windows(score_df, price_df, 5).height == price_df.height

    def test_unparseable_score_dates_fall_back_to_full_frame(self) -> None:
        price_df = _price_frame()
        score_df = pl.DataFrame(
            {
                "trade_date": ["not-a-date"],
                "symbol": ["AAA"],
                "score": [0.5],
            }
        )

        assert _restrict_price_to_score_windows(score_df, price_df, 5).height == price_df.height
        assert compute_daily_ic_series(score_df, price_df) == []

    def test_string_score_dates_align_with_date_price_index(self) -> None:
        """Score frames may carry ISO strings — the window must still apply."""
        price_df = _price_frame()
        days = _trading_days(40)
        score_df = _score_frame([days[20]]).with_columns(
            pl.col("trade_date").cast(pl.Utf8).str.to_date("%Y-%m-%d")
        )

        restricted = _restrict_price_to_score_windows(score_df, price_df, forward_days=5)

        assert restricted["trade_date"].min() == days[20]
