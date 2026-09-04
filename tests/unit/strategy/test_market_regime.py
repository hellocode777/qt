"""Unit tests for MarketRegimeDetector — 2026-09 A-share panic gauge.

Guards the 2026-09-04 finding: the detector's crisis branch only fired on
trend+vol+volume; a mass limit-down day (143-226 stocks) was classified as
bear/TREND_DOWN with no crisis signal. The limit-down dimension forces
crisis when whole-market limit-down count >= PANIC_LIMIT_DOWN_COUNT (100).
"""

from __future__ import annotations

import numpy as np
import polars as pl

from qp.strategy.market_regime import (
    PANIC_LIMIT_DOWN_COUNT,
    MarketRegimeDetector,
)


def _make_index(n_days: int = 250, drift: float = 0.001) -> pl.DataFrame:
    np.random.seed(42)
    closes = 100 + np.cumsum(np.random.normal(drift, 1.0, n_days))
    closes = np.maximum(closes, 10.0)
    # Monotonic business-day-ish dates (no 28-day wrap)
    import datetime as _dt

    dates = [_dt.date(2025, 1, 1) + _dt.timedelta(days=i) for i in range(n_days)]
    return pl.DataFrame({"date": dates, "close": closes})


def _make_price_data(
    n_symbols: int = 200,
    n_limit_down: int = 0,
    main_board: bool = True,
) -> dict[str, pl.DataFrame]:
    """Build {symbol: DataFrame[date, close]} with a configurable number of
    limit-down stocks on the last day.

    Symbols: main-board style (600000+) unless main_board=False (300xxx).
    Limit-down stocks drop ~10% (main) or ~20% (ChiNext) on the last day.
    """
    price_data: dict[str, pl.DataFrame] = {}
    n_days = 250
    import datetime as _dt

    dates = [_dt.date(2025, 1, 1) + _dt.timedelta(days=i) for i in range(n_days)]
    for i in range(n_symbols):
        np.random.seed(1000 + i)
        closes = 100 + np.cumsum(np.random.normal(0.0005, 1.0, n_days))
        closes = np.maximum(closes, 10.0)
        prefix = "600" if main_board else "300"
        code = f"{prefix}{i:03d}"
        if i < n_limit_down:
            drop = -0.10 if main_board else -0.20
            closes[-1] = closes[-2] * (1 + drop)
        price_data[code] = pl.DataFrame({"date": dates, "close": closes})
    return price_data


class TestDetectorLimitDownDimension:
    def test_panic_limit_down_forces_crisis(self) -> None:
        """>=100 limit-downs forces crisis even with flat/up trend."""
        detector = MarketRegimeDetector()
        index_df = _make_index(drift=0.002)  # slightly up-trending index
        # 150 of 200 symbols limit-down on the last day
        price_data = _make_price_data(n_symbols=200, n_limit_down=150)
        result = detector.detect(index_df, price_data)
        assert result.regime == "crisis"
        assert result.n_limit_down >= PANIC_LIMIT_DOWN_COUNT
        assert result.suggested_position_pct == 0.0
        assert result.allow_buy is False

    def test_normal_limit_down_not_crisis(self) -> None:
        """Few limit-downs (normal day) must NOT force crisis."""
        detector = MarketRegimeDetector()
        index_df = _make_index(drift=-0.001)  # bear-ish trend
        price_data = _make_price_data(n_symbols=200, n_limit_down=8)
        result = detector.detect(index_df, price_data)
        assert result.regime != "crisis"
        assert result.n_limit_down <= PANIC_LIMIT_DOWN_COUNT

    def test_crunch_without_price_data(self) -> None:
        """No price_data → n_limit_down=0, no crisis from panic gauge."""
        detector = MarketRegimeDetector()
        index_df = _make_index(drift=0.001)
        result = detector.detect(index_df, None)
        assert result.n_limit_down == 0
        assert result.regime != "crisis"

    def test_20cm_board_limit_down_counted(self) -> None:
        """ChiNext (300) -20% days count as limit-down for the panic gauge."""
        detector = MarketRegimeDetector()
        index_df = _make_index(drift=0.001)
        price_data = _make_price_data(n_symbols=200, n_limit_down=120, main_board=False)
        result = detector.detect(index_df, price_data)
        assert result.regime == "crisis"

    def test_stale_symbols_do_not_fabricate_limit_downs(self) -> None:
        """Delisted / long-suspended symbols (series ends years earlier)
        must NOT count: their last-two-rows span years and produce fake
        -60% moves. Regression for 2026-09: naive per-symbol last-two-row
        logic counted 1155 limit-downs on a real 11-limit-down day."""
        import datetime as _dt

        detector = MarketRegimeDetector()
        index_df = _make_index(drift=0.001)
        price_data = _make_price_data(n_symbols=190, n_limit_down=0)
        dates_all = [_dt.date(2025, 1, 1) + _dt.timedelta(days=i) for i in range(250)]
        for i in range(10):
            np.random.seed(9000 + i)
            closes = 100 + np.cumsum(np.random.normal(0.0005, 1.0, 150))
            closes = np.maximum(closes, 10.0)
            # Fake -50% gap on the last two rows of the stale series
            closes[-1] = closes[-2] * 0.5
            code = f"688{900 + i}"
            price_data[code] = pl.DataFrame({"date": dates_all[:150], "close": closes})
        result = detector.detect(index_df, price_data)
        # Stale -50% symbols excluded → no crisis from panic gauge
        assert result.n_limit_down == 0
        assert result.regime != "crisis"
