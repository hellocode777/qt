"""Tests for FactorCalculator — the Factor Execution Plane core engine.

NOTE: compute_all_factors calls category-specific batch functions
(compute_momentum_factors, etc.) that internally drop_nulls() on ALL
their own columns.  The longest lookback factor is Trend_MA120 (121
rows), so any stock with fewer than ~130 trading days will produce
zero rows for ALL factors — even short-lookback ones.
"""

from __future__ import annotations

from datetime import date as DateType

import polars as pl

from qp.research.factor_calculator import FactorCalculator

# Minimum trading days for any factor to be non-null (Trend_MA120 = 121)
MIN_DAYS = 140


# ------------------------------------------------------------------
# Helpers: build synthetic price data
# ------------------------------------------------------------------


def _make_price_df(
    symbols: list[str],
    dates: list[DateType],
    seed: int = 42,
) -> pl.DataFrame:
    """Build synthetic OHLCV price data for testing."""
    import numpy as np

    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    base_prices: dict[str, float] = {s: 10.0 + i * 5.0 for i, s in enumerate(symbols)}

    for sym in symbols:
        px = base_prices[sym]
        for d in dates:
            ret = rng.normal(0.001, 0.02)
            px = px * (1.0 + ret)
            high = px * (1.0 + abs(rng.normal(0, 0.01)))
            low = px * (1.0 - abs(rng.normal(0, 0.01)))
            vol = rng.integers(100_000, 1_000_000)
            rows.append(
                {
                    "trade_date": d,
                    "symbol": sym,
                    "open": float(px),
                    "high": float(high),
                    "low": float(low),
                    "close": float(px),
                    "volume": float(vol),
                }
            )

    schema = {
        "trade_date": pl.Date,
        "symbol": pl.Utf8,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


def _make_date_range(n_days: int, start: str = "2026-01-05") -> list[DateType]:
    """Generate consecutive weekday dates as datetime.date objects."""
    from datetime import date, timedelta

    result: list[DateType] = []
    current = date.fromisoformat(start)
    while len(result) < n_days:
        if current.weekday() < 5:  # Mon-Fri only
            result.append(current)
        current = current + timedelta(days=1)
    return result


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestFactorCalculator:
    def test_latest_date(self) -> None:
        """_latest_date returns the max trade_date."""
        df = pl.DataFrame(
            {
                "trade_date": [DateType(2026, 1, 5), DateType(2026, 1, 6), DateType(2026, 1, 5)],
                "symbol": ["A", "A", "B"],
            },
            schema={"trade_date": pl.Date, "symbol": pl.Utf8},
        )
        result = FactorCalculator._latest_date(df)
        assert result == DateType(2026, 1, 6)

    def test_compute_with_synthetic_data(self) -> None:
        """End-to-end: compute factor values from synthetic price data."""
        dates = _make_date_range(MIN_DAYS)
        symbols = ["000001", "000002", "000003"]
        price_df = _make_price_df(symbols, dates)

        calc = FactorCalculator(progress_interval=1)
        result = calc.compute(price_df, factors=["Momentum_3M", "Volatility_20D"])

        assert not result.is_empty()
        assert "trade_date" in result.columns
        assert "symbol" in result.columns
        assert "Momentum_3M" in result.columns
        assert "Volatility_20D" in result.columns
        assert result.height == len(symbols)

    def test_compute_subset_factors(self) -> None:
        """Only requested factors appear in output."""
        dates = _make_date_range(MIN_DAYS)
        symbols = ["000001", "000002"]
        price_df = _make_price_df(symbols, dates)

        calc = FactorCalculator()
        result = calc.compute(price_df, factors=["Momentum_1M", "Amplitude_5D"])

        expected_cols = {"trade_date", "symbol", "Momentum_1M", "Amplitude_5D"}
        assert set(result.columns) == expected_cols
        assert "Volatility_20D" not in result.columns

    def test_compute_specific_date(self) -> None:
        """Target date parameter works."""
        dates = _make_date_range(MIN_DAYS)
        symbols = ["000001", "000002"]
        price_df = _make_price_df(symbols, dates)

        target = dates[-5]
        calc = FactorCalculator()
        result = calc.compute(price_df, date=target, factors=["Momentum_3M"])

        assert not result.is_empty()
        unique_dates = result["trade_date"].unique().to_list()
        assert len(unique_dates) == 1
        assert unique_dates[0] == target

    def test_insufficient_history_skipped(self) -> None:
        """Stocks with < 60 rows are skipped by FactorCalculator's own guard."""
        short_dates = _make_date_range(30)
        long_dates = _make_date_range(MIN_DAYS)

        short_df = _make_price_df(["000001"], short_dates)  # 30 days — skip
        long_df = _make_price_df(["000002"], long_dates)  # 140 days — ok
        price_df = pl.concat([short_df, long_df])

        calc = FactorCalculator()
        result = calc.compute(price_df, factors=["Momentum_1M"])

        symbols = result["symbol"].to_list()
        assert "000001" not in symbols
        assert "000002" in symbols

    def test_empty_result_when_no_stocks_qualify(self) -> None:
        """Returns empty DataFrame when no stock has enough history."""
        dates = _make_date_range(30)
        price_df = _make_price_df(["000001"], dates)

        calc = FactorCalculator()
        result = calc.compute(price_df, factors=["Momentum_3M"])

        assert result.is_empty()

    def test_compute_all_dates(self) -> None:
        """Full-history mode produces multiple dates."""
        dates = _make_date_range(MIN_DAYS)
        symbols = ["000001"]
        price_df = _make_price_df(symbols, dates)

        calc = FactorCalculator()
        result = calc.compute_all_dates(price_df, factors=["Momentum_1M"])

        assert not result.is_empty()
        n_dates = result["trade_date"].n_unique()
        assert n_dates > 1  # multiple dates produced
