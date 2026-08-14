"""Regression tests for index column normalization in market_filter / market_regime.

``data/dataset/index_csi300.parquet`` uses ``trade_date`` (Gold dataset
convention, same as daily_price_latest), but strategy-layer consumers
(market_filter, market_regime) historically expected a ``date`` column.
After the CSI300 index restore the mismatch crashed
``qp experiment run multifactor --strategy momentum_vol_full`` with
``ColumnNotFoundError: unable to find column "date"``.

Both callers must accept ``trade_date`` (data-layer) and ``date`` (legacy).
"""

import polars as pl

from qp.strategy.market_filter import check_market_environment, filter_signals
from qp.strategy.market_regime import MarketRegimeDetector


def _index_df(
    rising: bool = True,
    col: str = "trade_date",
    n: int = 60,
) -> pl.DataFrame:
    base = 300.0
    step = 3.0 if rising else -3.0
    dates = pl.date_range(
        pl.date(2025, 1, 1),
        pl.date(2025, 3, 1),
        interval="1d",
        eager=True,
    )[:n]
    return pl.DataFrame(
        {
            col: dates,
            "close": [base + i * step for i in range(n)],
            "volume": [1_000_000.0] * n,
        }
    )


def _signals_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": ["2025-02-20", "2025-02-25", "2025-02-28"],
            "symbol": ["000001", "000002", "000003"],
            "signal": ["buy", "buy", "sell"],
            "score": [1.0, 0.9, 0.8],
        }
    )


def test_filter_signals_trade_date_bull_keeps_buys() -> None:
    """Index with trade_date (Gold convention) — regression for ColumnNotFoundError."""
    out = filter_signals(_signals_df(), _index_df(rising=True))
    assert out.height == 3
    assert {r["signal"] for r in out.to_dicts()} == {"buy", "sell"}


def test_filter_signals_trade_date_bear_removes_buys() -> None:
    out = filter_signals(_signals_df(), _index_df(rising=False))
    assert [r["signal"] for r in out.to_dicts()] == ["sell"]


def test_filter_signals_legacy_date_column_still_works() -> None:
    out = filter_signals(_signals_df(), _index_df(rising=False, col="date"))
    assert [r["signal"] for r in out.to_dicts()] == ["sell"]


def test_check_market_environment_trade_date() -> None:
    env = check_market_environment(_index_df(rising=True))
    assert env["status"] == "bull"
    assert env["allow_trading"] is True


def test_check_market_environment_legacy_date() -> None:
    env = check_market_environment(_index_df(rising=False, col="date"))
    assert env["status"] == "bear"
    assert env["allow_trading"] is False


def test_detect_history_trade_date_no_crash() -> None:
    # min_history=200, so feed a long enough index
    n = 240
    dates = pl.date_range(
        pl.date(2025, 1, 1),
        pl.date(2025, 8, 28),
        interval="1d",
        eager=True,
    )[:n]
    index_df = pl.DataFrame(
        {
            "trade_date": dates,
            "close": [300.0 - i * 1.0 for i in range(n)],
            "volume": [1_000_000.0] * n,
        }
    )
    hist = MarketRegimeDetector().detect_history(index_df)
    assert not hist.is_empty()
    assert "regime" in hist.columns
