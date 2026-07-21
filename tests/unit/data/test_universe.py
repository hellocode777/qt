"""Tests for qp.data.universe — PIT & Dynamic Universe module."""

from __future__ import annotations

from datetime import date

import polars as pl

from qp.data.universe import (
    ListingDateRegistry,
    RestatementTracker,
    UniverseBuilder,
    UniverseConfig,
    compute_median_volume,
    filter_by_liquidity,
    filter_by_percentile,
    get_liquidity_stats,
    get_listing_date,
    is_listed_before,
)

# ==================================================================
# ListingDateRegistry
# ==================================================================


class TestListingDateRegistry:
    def test_get_known_stock(self):
        reg = ListingDateRegistry()
        d = reg.get("600519")
        assert d == date(2001, 8, 27)

    def test_get_unknown_stock(self):
        reg = ListingDateRegistry()
        d = reg.get("999999")
        assert d is None

    def test_is_seasoned_old_stock(self):
        reg = ListingDateRegistry()
        assert reg.is_seasoned("600519", "2024-01-01") is True

    def test_is_seasoned_recent_ipo_false(self):
        """Stock listed Jul 2020, asked for Aug 2020 → not seasoned (<200 days)."""
        reg = ListingDateRegistry()
        assert reg.is_seasoned("688981", "2020-08-01") is False

    def test_is_seasoned_unknown_is_true(self):
        """Unknown listing date → assume tradeable (avoid false exclusion)."""
        reg = ListingDateRegistry()
        assert reg.is_seasoned("999999", "2024-01-01") is True

    def test_filter_seasoned(self):
        reg = ListingDateRegistry()
        symbols = ["600519", "688981", "999999"]
        result = reg.filter_seasoned(symbols, "2024-01-01")
        assert "600519" in result
        assert "999999" in result  # Unknown → kept
        # 688981 listed 2020-07-16, 2024-01-01 is well past 200 days → kept
        assert "688981" in result

    def test_get_all_known(self):
        reg = ListingDateRegistry()
        all_dates = reg.get_all_known()
        assert len(all_dates) >= 80
        assert "600519" in all_dates

    def test_string_date(self):
        reg = ListingDateRegistry()
        assert reg.is_seasoned("600519", "2024-01-01") is True

    def test_module_level_convenience(self):
        d = get_listing_date("600519")
        assert d == date(2001, 8, 27)
        assert is_listed_before("600519", "2024-01-01") is True


# ==================================================================
# Liquidity
# ==================================================================


class TestLiquidity:
    def test_compute_median_volume(self):
        df = pl.DataFrame({
            "symbol": ["000001", "000001", "000002", "000002"],
            "trade_date": ["2024-01-15", "2024-01-16", "2024-01-15", "2024-01-16"],
            "volume": [1000000.0, 1200000.0, 500000.0, 300000.0],
        }).with_columns(pl.col("trade_date").str.to_date())
        result = compute_median_volume(df)
        assert result.height == 2
        syms = result["symbol"].to_list()
        assert "000001" in syms
        assert "000002" in syms

    def test_filter_by_liquidity_absolute(self):
        df = pl.DataFrame({
            "symbol": ["A", "B", "C"],
            "trade_date": ["2024-01-15"] * 3,
            "volume": [1000000.0, 500000.0, 100000.0],
        }).with_columns(pl.col("trade_date").str.to_date())
        result = filter_by_liquidity(df, min_volume=200000.0)
        assert "A" in result
        assert "B" in result
        assert "C" not in result

    def test_filter_by_percentile(self):
        df = pl.DataFrame({
            "symbol": [f"S{i:03d}" for i in range(20)],
            "trade_date": ["2024-01-15"] * 20,
            "volume": [float(i * 100000 + 100000) for i in range(20)],
        }).with_columns(pl.col("trade_date").str.to_date())
        result = filter_by_percentile(df, min_percentile=50.0)
        # Bottom 50% excluded → keeps ~10
        assert 8 <= len(result) <= 12

    def test_get_liquidity_stats(self):
        df = pl.DataFrame({
            "symbol": ["A", "B", "C"],
            "trade_date": ["2024-01-15"] * 3,
            "volume": [1e6, 5e5, 1e5],
        }).with_columns(pl.col("trade_date").str.to_date())
        stats = get_liquidity_stats(df)
        assert stats["count"] == 3
        assert stats["median"] > 0
        assert "p10" in stats
        assert "p90" in stats

    def test_empty_dataframe(self):
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "volume": pl.Float64})
        assert compute_median_volume(df).is_empty()
        assert filter_by_liquidity(df) == []
        assert filter_by_percentile(df) == []
        assert get_liquidity_stats(df) == {}


# ==================================================================
# RestatementTracker
# ==================================================================


class TestRestatementTracker:
    def test_single_version(self):
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001"],
            "report_date": ["2024-09-30"],
            "publish_date": ["2024-10-25"],
            "ROE": [15.5],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        n = tracker.ingest(df)
        assert n == 1
        assert tracker.count == 1
        assert tracker.restatement_count == 0

    def test_restatement_detection(self):
        """Two versions of same report → second is a restatement."""
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001", "000001"],
            "report_date": ["2024-09-30", "2024-09-30"],
            "publish_date": ["2024-10-25", "2025-03-15"],
            "ROE": [15.5, 14.2],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        n = tracker.ingest(df)
        assert n == 2
        assert tracker.restatement_count == 1

    def test_pit_visibility(self):
        """Version visible depends on as_of_date."""
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001", "000001"],
            "report_date": ["2024-09-30", "2024-09-30"],
            "publish_date": ["2024-10-25", "2025-03-15"],
            "ROE": [15.5, 14.2],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        tracker.ingest(df)

        # Before second publish → only v1 visible
        v1 = tracker.get_visible("000001", "2024-09-30", "2024-12-31")
        assert v1 is not None
        assert v1["version"].item() == 1
        assert v1["ROE"].item() == 15.5

        # After second publish → v2 visible
        v2 = tracker.get_visible("000001", "2024-09-30", "2025-06-01")
        assert v2 is not None
        assert v2["version"].item() == 2
        assert v2["ROE"].item() == 14.2

    def test_no_visible_before_first_publish(self):
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001"],
            "report_date": ["2024-09-30"],
            "publish_date": ["2024-10-25"],
            "ROE": [15.5],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        tracker.ingest(df)
        v = tracker.get_visible("000001", "2024-09-30", "2024-09-30")
        assert v is None  # Not yet published

    def test_version_history(self):
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001", "000001", "000001"],
            "report_date": ["2024-09-30", "2024-09-30", "2024-09-30"],
            "publish_date": ["2024-10-25", "2025-03-15", "2025-05-01"],
            "ROE": [15.5, 14.2, 13.8],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        tracker.ingest(df)
        history = tracker.get_version_history("000001", "2024-09-30")
        assert history.height == 3
        assert history["version"].to_list() == [1, 2, 3]

    def test_get_restated_reports(self):
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001", "000001", "000002"],
            "report_date": ["2024-09-30", "2024-09-30", "2024-06-30"],
            "publish_date": ["2024-10-25", "2025-03-15", "2024-08-15"],
            "ROE": [15.5, 14.2, 10.0],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        tracker.ingest(df)
        restated = tracker.get_restated_reports()
        assert restated.height == 1  # Only 000001's second version

    def test_idempotent_ingest(self):
        """Ingesting the same data twice shouldn't create duplicates."""
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001"],
            "report_date": ["2024-09-30"],
            "publish_date": ["2024-10-25"],
            "ROE": [15.5],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        n1 = tracker.ingest(df)
        n2 = tracker.ingest(df)
        assert n1 == 1
        assert n2 == 0  # No new versions
        assert tracker.count == 1

    def test_multiple_symbols(self):
        tracker = RestatementTracker()
        df = pl.DataFrame({
            "symbol": ["000001", "000002"],
            "report_date": ["2024-09-30", "2024-09-30"],
            "publish_date": ["2024-10-25", "2024-10-28"],
            "ROE": [15.5, 10.0],
        }).with_columns(
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        )
        tracker.ingest(df)
        assert tracker.count == 2
        assert tracker.symbol_count == 2

    def test_empty_ingest(self):
        tracker = RestatementTracker()
        n = tracker.ingest(pl.DataFrame())
        assert n == 0
        assert tracker.count == 0


# ==================================================================
# UniverseBuilder
# ==================================================================


class TestUniverseBuilder:
    @staticmethod
    def _make_df(symbols=None, **overrides):
        if symbols is None:
            symbols = ["600519", "000001"]
        data = {"symbol": symbols, "trade_date": ["2024-06-15"] * len(symbols)}
        for col in ["open", "high", "low", "close"]:
            data[col] = [100.0] * len(symbols)
        data["volume"] = [1e6] * len(symbols)
        data.update(overrides)
        return pl.DataFrame(data).with_columns(pl.col("trade_date").str.to_date())

    def test_build_keeps_all_when_no_filters(self):
        config = UniverseConfig(
            enable_ipo_filter=False,
            enable_st_filter=False,
            enable_suspension_filter=False,
            enable_delisting_filter=False,
            enable_liquidity_filter=False,
        )
        builder = UniverseBuilder(config)
        df = self._make_df(["600519", "000001", "000002"])
        result = builder.build(df)
        assert len(result.symbols) == 3
        assert result.stats["input"] == 3
        assert result.stats["output"] == 3

    def test_ipo_filter_excludes_new_stock(self):
        config = UniverseConfig(
            enable_ipo_filter=True,
            enable_st_filter=False,
            enable_suspension_filter=False,
            enable_delisting_filter=False,
            enable_liquidity_filter=False,
            min_listing_days=200,
        )
        builder = UniverseBuilder(config)
        # 688981 listed 2020-07-16, so as_of 2020-08-01 is <200 days
        df = self._make_df(["600519", "688981"])
        result = builder.build(df, as_of_date="2020-08-01")
        assert "600519" in result.symbols
        assert "688981" not in result.symbols  # Too new
        assert result.stats["ipo_excluded"] == 1

    def test_st_filter(self):
        config = UniverseConfig(
            enable_ipo_filter=False,
            enable_st_filter=True,
            enable_suspension_filter=False,
            enable_delisting_filter=False,
            enable_liquidity_filter=False,
        )
        builder = UniverseBuilder(config)
        df = self._make_df(
            ["600519", "000001"],
            name=["贵州茅台", "*ST华泽"],
        )
        result = builder.build(df)
        assert "600519" in result.symbols
        assert "000001" not in result.symbols  # ST excluded

    def test_suspension_filter(self):
        config = UniverseConfig(
            enable_ipo_filter=False,
            enable_st_filter=False,
            enable_suspension_filter=True,
            enable_delisting_filter=False,
            enable_liquidity_filter=False,
        )
        builder = UniverseBuilder(config)
        df = self._make_df(
            ["600519", "000001"],
            is_suspended=[False, True],
        )
        result = builder.build(df)
        assert "600519" in result.symbols
        assert "000001" not in result.symbols

    def test_liquidity_filter(self):
        config = UniverseConfig(
            enable_ipo_filter=False,
            enable_st_filter=False,
            enable_suspension_filter=False,
            enable_delisting_filter=False,
            enable_liquidity_filter=True,
            min_volume=500_000,
        )
        builder = UniverseBuilder(config)
        df = self._make_df(
            ["A", "B", "C"],
            volume=[2e6, 5e5, 1e5],
        )
        result = builder.build(df)
        assert "A" in result.symbols
        assert "B" in result.symbols
        assert "C" not in result.symbols

    def test_combined_filters(self):
        """All filters together on realistic data — all pass with high volume."""
        config = UniverseConfig()
        builder = UniverseBuilder(config)
        df = pl.DataFrame({
            "symbol": ["600519", "000001", "688981"],
            "trade_date": ["2024-06-15"] * 3,
            "open": [100.0, 10.0, 50.0],
            "high": [101.0, 11.0, 51.0],
            "low": [99.0, 9.8, 49.8],
            "close": [100.5, 10.2, 50.2],
            "volume": [2e6, 1e6, 8e5],
        }).with_columns(pl.col("trade_date").str.to_date())
        result = builder.build(df, as_of_date="2024-06-15")
        assert len(result.symbols) == 3
        assert result.stats["input"] == 3
        assert result.stats["output"] == 3

    def test_get_universe(self):
        builder = UniverseBuilder(UniverseConfig(
            enable_ipo_filter=False, enable_st_filter=False,
            enable_suspension_filter=False, enable_delisting_filter=False,
            enable_liquidity_filter=False,
        ))
        df = self._make_df(["A", "B", "C"])
        syms = builder.get_universe(df)
        assert sorted(syms) == ["A", "B", "C"]

    def test_empty_dataframe(self):
        builder = UniverseBuilder()
        df = pl.DataFrame(schema={"symbol": pl.Utf8, "volume": pl.Float64})
        result = builder.build(df)
        assert result.symbols == []

    def test_extra_exclude(self):
        builder = UniverseBuilder(UniverseConfig(
            enable_ipo_filter=False, enable_st_filter=False,
            enable_suspension_filter=False, enable_delisting_filter=False,
            enable_liquidity_filter=False,
        ))
        df = self._make_df(["A", "B", "C"])
        result = builder.build(df, extra_exclude=["B"])
        assert sorted(result.symbols) == ["A", "C"]
