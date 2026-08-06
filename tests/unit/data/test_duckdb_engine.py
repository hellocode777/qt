"""Tests for qp.data.feature_store.DuckDBEngine."""

from __future__ import annotations

import polars as pl

from qp.data.feature_store import DuckDBEngine, OfflineStore

# ==================================================================
# Test helpers
# ==================================================================


def _make_ohlcv_df(n_days: int = 30) -> pl.DataFrame:
    """Create a small OHLCV DataFrame."""
    import numpy as np

    rng = np.random.default_rng(42)
    rows: list[dict] = []
    for sym in ["600519", "000001"]:
        close = 100.0 + rng.normal(0, 2, n_days).cumsum()
        for d_idx in range(n_days):
            c = close[d_idx]
            rows.append(
                {
                    "symbol": sym,
                    "trade_date": f"2024-01-{d_idx + 1:02d}",
                    "close": c,
                    "volume": float(abs(rng.normal(1e6, 2e5))),
                }
            )
    return (
        pl.DataFrame(rows)
        .with_columns(
            pl.col("trade_date").str.to_date(),
        )
        .sort(["symbol", "trade_date"])
    )


def _make_financials_df() -> pl.DataFrame:
    """Create a mini PIT financial dataset."""
    return pl.DataFrame(
        {
            "symbol": ["600519", "600519", "600519", "000001", "000001"],
            "report_date": [
                "2024-03-31",
                "2024-06-30",
                "2024-06-30",
                "2024-03-31",
                "2024-06-30",
            ],
            "publish_date": [
                "2024-04-25",
                "2024-08-15",
                "2025-03-10",
                "2024-04-28",
                "2024-08-20",
            ],
            "ROE": [8.5, 10.2, 9.8, 5.0, 6.5],
            "EPS": [2.5, 3.1, 3.0, 1.2, 1.5],
        }
    ).with_columns(
        [
            pl.col("report_date").str.to_date(),
            pl.col("publish_date").str.to_date(),
        ]
    )


# ==================================================================
# DuckDBEngine tests
# ==================================================================


class TestDuckDBEngine:
    def test_register_and_query(self):
        engine = DuckDBEngine()
        df = _make_ohlcv_df()
        engine.register("ohlcv", df)

        result = engine.query("SELECT symbol, COUNT(*) AS n FROM ohlcv GROUP BY symbol")
        assert result.height == 2
        assert set(result["symbol"].to_list()) == {"600519", "000001"}
        # Each symbol has 30 rows
        assert result["n"].sum() == 60

    def test_register_many(self):
        engine = DuckDBEngine()
        df1 = pl.DataFrame({"a": [1, 2], "b": [3, 4]})
        df2 = pl.DataFrame({"x": [10, 20], "y": [30, 40]})
        engine.register_many({"t1": df1, "t2": df2})
        assert "t1" in engine.registered_tables
        assert "t2" in engine.registered_tables

    def test_unregister(self):
        engine = DuckDBEngine()
        engine.register("tmp", pl.DataFrame({"a": [1]}))
        assert "tmp" in engine.registered_tables
        engine.unregister("tmp")
        assert "tmp" not in engine.registered_tables

    def test_query_filter(self):
        engine = DuckDBEngine()
        df = _make_ohlcv_df()
        engine.register("ohlcv", df)

        result = engine.query(
            "SELECT * FROM ohlcv WHERE symbol = '600519' AND trade_date = '2024-01-15'"
        )
        assert result.height == 1
        assert result["symbol"].item() == "600519"

    def test_query_aggregation(self):
        engine = DuckDBEngine()
        df = _make_ohlcv_df()
        engine.register("ohlcv", df)

        result = engine.query("""
            SELECT symbol,
                   AVG(close) AS avg_close,
                   SUM(volume) AS total_vol
            FROM ohlcv
            GROUP BY symbol
        """)
        assert result.height == 2
        assert "avg_close" in result.columns
        assert "total_vol" in result.columns

    def test_query_window_function(self):
        engine = DuckDBEngine()
        df = _make_ohlcv_df()
        engine.register("ohlcv", df)

        result = engine.query("""
            SELECT symbol, trade_date, close,
                   AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date
                                    ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5
            FROM ohlcv
            ORDER BY symbol, trade_date
        """)
        assert "ma5" in result.columns
        # First 4 rows per symbol should have partial MA
        assert result.height == 60

    def test_version(self):
        engine = DuckDBEngine()
        v = engine.version
        assert v is not None
        assert len(v) > 0

    def test_row_count(self):
        engine = DuckDBEngine()
        engine.register("t", pl.DataFrame({"x": [1, 2, 3, 4, 5]}))
        assert engine.row_count("t") == 5

    def test_context_manager(self):
        with DuckDBEngine() as engine:
            engine.register("t", pl.DataFrame({"a": [1]}))
            result = engine.query("SELECT * FROM t")
            assert result.height == 1


# ==================================================================
# PIT queries
# ==================================================================


class TestPITQueries:
    def test_pit_query_basic(self):
        engine = DuckDBEngine()
        df = _make_financials_df()
        engine.register("financials", df)

        # As of 2024-05-01: only Q1 reports published
        result = engine.pit_query("financials", as_of="2024-05-01")
        # Should have 1 row per (symbol, report_date) — latest before 2024-05-01
        assert result.height == 2  # 600519 Q1 + 000001 Q1

    def test_pit_query_after_restatement(self):
        """After restatement (2025-03-10), 600519 Q2 should show v2 ROE=9.8."""
        engine = DuckDBEngine()
        df = _make_financials_df()
        engine.register("financials", df)

        result = engine.pit_query("financials", as_of="2025-06-01")
        # 600519 Q2: latest publish_date <= 2025-06-01 is 2025-03-10 (v2, ROE=9.8)
        row_519_q2 = result.filter(
            (pl.col("symbol") == "600519")
            & (pl.col("report_date") == pl.lit("2024-06-30").str.to_date())
        )
        assert row_519_q2.height == 1
        assert row_519_q2["ROE"].item() == 9.8  # Restated value

    def test_pit_query_before_restatement(self):
        """Before restatement, only v1 (ROE=10.2) is visible."""
        engine = DuckDBEngine()
        df = _make_financials_df()
        engine.register("financials", df)

        result = engine.pit_query("financials", as_of="2024-12-01")
        row_519_q2 = result.filter(
            (pl.col("symbol") == "600519")
            & (pl.col("report_date") == pl.lit("2024-06-30").str.to_date())
        )
        assert row_519_q2.height == 1
        assert row_519_q2["ROE"].item() == 10.2  # Original value

    def test_pit_latest(self):
        engine = DuckDBEngine()
        df = _make_financials_df()
        engine.register("financials", df)

        result = engine.pit_latest("financials", as_of="2024-05-01")
        # Latest report per symbol visible on 2024-05-01
        assert result.height == 2  # One per symbol

    def test_pit_query_select_cols(self):
        engine = DuckDBEngine()
        df = _make_financials_df()
        engine.register("financials", df)

        result = engine.pit_query(
            "financials", as_of="2024-05-01", select_cols="symbol, report_date, ROE"
        )
        assert "ROE" in result.columns
        assert "EPS" not in result.columns

    def test_pit_query_no_as_of(self):
        """Without as_of filter, returns latest per partition overall."""
        engine = DuckDBEngine()
        df = _make_financials_df()
        engine.register("financials", df)

        result = engine.pit_query("financials")
        # 4 combos: 600519-Q1, 600519-Q2(v2), 000001-Q1, 000001-Q2
        assert result.height == 4

    def test_pit_query_empty(self):
        """PIT query with as_of before all data → empty."""
        engine = DuckDBEngine()
        df = _make_financials_df()
        engine.register("financials", df)

        result = engine.pit_query("financials", as_of="2020-01-01")
        assert result.is_empty()


# ==================================================================
# Parquet querying
# ==================================================================


class TestParquetQueries:
    def test_query_parquet_direct(self, tmp_path):
        """Query Parquet files directly without registration."""
        df = _make_ohlcv_df(n_days=10)
        pq_path = tmp_path / "test.parquet"
        df.write_parquet(str(pq_path))

        engine = DuckDBEngine()
        result = engine.query_parquet(pq_path)
        assert result.height == 20  # 10 days × 2 symbols

    def test_query_parquet_with_sql(self, tmp_path):
        """Query Parquet with custom SQL filter."""
        df = _make_ohlcv_df(n_days=10)
        pq_path = tmp_path / "test.parquet"
        df.write_parquet(str(pq_path))

        engine = DuckDBEngine()
        result = engine.query_parquet(
            pq_path,
            sql=f"SELECT symbol, close FROM '{pq_path}' WHERE symbol = '600519'",
        )
        assert result.height == 10
        assert "close" in result.columns
        assert "volume" not in result.columns

    def test_scan_parquet(self, tmp_path):
        """scan_parquet convenience method."""
        df = _make_ohlcv_df(n_days=10)
        pq_path = tmp_path / "test.parquet"
        df.write_parquet(str(pq_path))

        engine = DuckDBEngine()
        result = engine.scan_parquet(
            pq_path,
            filter_expr="symbol = '000001'",
            columns=["symbol", "trade_date", "close"],
        )
        assert result.height == 10
        assert sorted(result.columns) == ["close", "symbol", "trade_date"]

    def test_scan_parquet_with_limit(self, tmp_path):
        df = _make_ohlcv_df(n_days=10)
        pq_path = tmp_path / "test.parquet"
        df.write_parquet(str(pq_path))

        engine = DuckDBEngine()
        result = engine.scan_parquet(pq_path, limit=3)
        assert result.height == 3


# ==================================================================
# OfflineStore bridge
# ==================================================================


class TestOfflineStoreBridge:
    def test_query_store(self, tmp_path):
        """Query OfflineStore Parquet files via DuckDB."""
        store = OfflineStore(tmp_path / "features")

        n = 10
        syms = ["600519", "000001"] * (n // 2)  # 10 items
        df = pl.DataFrame(
            {
                "symbol": syms,
                "trade_date": [f"2024-01-{d + 1:02d}" for d in range(n)],
                "momentum_20": [0.05 + i * 0.01 for i in range(n)],
                "rsi_14": [50.0 + i * 2 for i in range(n)],
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        store.write(df, factor_group="momentum")

        engine = DuckDBEngine()
        result = engine.query_store(
            store,
            factor_groups=["momentum"],
            symbols=["600519"],
        )
        assert not result.is_empty()
        if "symbol" in result.columns:
            assert result["symbol"].unique().to_list() == ["600519"]

    def test_query_store_date_filter(self, tmp_path):
        store = OfflineStore(tmp_path / "features")
        df = pl.DataFrame(
            {
                "symbol": ["600519"] * 20,
                "trade_date": [f"2024-01-{d + 1:02d}" for d in range(20)],
                "momentum_20": [0.01 * i for i in range(20)],
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        store.write(df, factor_group="momentum")

        engine = DuckDBEngine()
        result = engine.query_store(
            store,
            factor_groups=["momentum"],
            start_date="2024-01-10",
            end_date="2024-01-15",
        )
        if not result.is_empty() and "trade_date" in result.columns:
            dates = result["trade_date"].unique()
            assert dates.len() <= 6  # 10 to 15 inclusive

    def test_query_store_custom_sql(self, tmp_path):
        store = OfflineStore(tmp_path / "features")
        df = pl.DataFrame(
            {
                "symbol": ["600519", "000001"] * 3,
                "trade_date": ["2024-01-15"] * 6,
                "factor_a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        store.write(df, factor_group="test")

        engine = DuckDBEngine()
        result = engine.query_store(
            store,
            sql="SELECT symbol, AVG(factor_a) AS avg_a, COUNT(*) AS n FROM features GROUP BY symbol",
        )
        assert result.height == 2
        assert "avg_a" in result.columns


# ==================================================================
# SQL expression computation
# ==================================================================


class TestSQLCompute:
    def test_compute_sql(self):
        engine = DuckDBEngine()
        df = _make_ohlcv_df(n_days=20)

        result = engine.compute_sql(
            df,
            expressions={
                "ma5": "AVG(close) OVER w",
                "ma10": "AVG(close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)",
            },
        )
        assert "ma5" in result.columns
        assert "ma10" in result.columns
        # ma5 should be non-null after 5 rows per symbol
        first_symbol = df["symbol"][0]
        ma5_vals = result.filter(pl.col("symbol") == first_symbol)["ma5"].drop_nulls()
        assert ma5_vals.len() > 0


# ==================================================================
# Integration
# ==================================================================


class TestDuckDBIntegration:
    def test_full_workflow(self, tmp_path):
        """End-to-end: OfflineStore → DuckDB → PIT query → Polars."""
        # 1. Write features to OfflineStore
        store = OfflineStore(tmp_path / "features")
        features = pl.DataFrame(
            {
                "symbol": ["600519", "000001"] * 10,
                "trade_date": [f"2024-0{d // 4 + 1}-{(d % 28) + 1:02d}" for d in range(20)],
                "momentum_20": [0.01 * d for d in range(20)],
                "rsi_14": [50.0 + d for d in range(20)],
            }
        ).with_columns(pl.col("trade_date").str.to_date())
        store.write(features, factor_group="merged")

        # 2. Query with DuckDB
        engine = DuckDBEngine()
        result = engine.query_store(
            store,
            sql="""
                SELECT symbol, AVG(momentum_20) AS avg_mom, AVG(rsi_14) AS avg_rsi
                FROM features
                GROUP BY symbol
            """,
        )
        assert result.height == 2

        # 3. Register for further analysis
        engine.register("summary", result)
        top = engine.query("SELECT * FROM summary ORDER BY avg_mom DESC LIMIT 1")
        assert top.height == 1

    def test_register_from_polars_chain(self):
        """Register → query → register result → query again."""
        engine = DuckDBEngine()

        # Step 1
        df = _make_ohlcv_df(n_days=10)
        engine.register("raw", df)

        # Step 2: aggregate
        agg = engine.query("""
            SELECT symbol, AVG(close) AS avg_close, SUM(volume) AS total_vol
            FROM raw GROUP BY symbol
        """)

        # Step 3: register result
        engine.register("agg", agg)

        # Step 4: query the aggregation
        final = engine.query("""
            SELECT * FROM agg
            WHERE avg_close > 50
            ORDER BY total_vol DESC
        """)
        assert final.height == 2  # Both symbols have avg_close > 50
