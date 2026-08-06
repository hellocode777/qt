"""DuckDB Feature Engine — SQL-based analytical queries for Feature Store.

Implements data_layer.md recommendation:
  "利用 DuckDB 的 QUALIFY 语法快速查询 PIT 数据"
  "DuckDB / ClickHouse 就够用了"

Provides:
  1. SQL querying of registered Polars DataFrames
  2. Direct Parquet file querying (zero-copy analytical scans)
  3. PIT-aware queries (QUALIFY + ROW_NUMBER pattern)
  4. Bridge to OfflineStore for SQL over partitioned Parquet
  5. SQL expression-based feature computation

Usage::

    from qp.data.feature_store import DuckDBEngine, OfflineStore

    # 1. Query registered DataFrames
    engine = DuckDBEngine()
    engine.register("ohlcv", df)
    result = engine.query("SELECT symbol, AVG(close) FROM ohlcv GROUP BY symbol")

    # 2. Query Parquet directly (no memory load)
    df = engine.query_parquet(
        "data/features/momentum/**/*.parquet",
        "SELECT * FROM data WHERE trade_date >= '2024-01-01'",
    )

    # 3. PIT query (Knowledge Time filtering)
    pit_df = engine.pit_query(
        "financials",
        period_col="report_date",
        knowledge_col="publish_date",
        as_of="2024-03-01",
    )

    # 4. Bridge to OfflineStore
    store = OfflineStore("data/features")
    df = engine.query_store(
        store, "SELECT symbol, trade_date, momentum_20, rsi_14 FROM features"
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import polars as pl
from loguru import logger


class DuckDBEngine:
    """DuckDB-powered analytical query engine for the Feature Store.

    Complements Polars-based FeatureEngine with SQL capabilities:
      - Complex multi-table joins and aggregations
      - Direct Parquet file scanning (columnar projection + predicate pushdown)
      - PIT-aware queries with QUALIFY window functions
      - SQL expression features (easier to write than Polars for some patterns)

    DuckDB runs in-process with zero configuration. It reads Parquet files
    directly with full predicate and projection pushdown, making it ideal
    for analytical queries over large offline feature stores.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize the DuckDB engine.

        Args:
            db_path: Optional path to a persistent DuckDB database file.
                     None = in-memory only (default).
        """
        if db_path:
            self._conn = duckdb.connect(str(db_path))
            logger.info("DuckDBEngine: connected to {}", db_path)
        else:
            self._conn = duckdb.connect(":memory:")
            logger.debug("DuckDBEngine: in-memory connection")

        self._registered: set[str] = set()

    # ── DataFrame registration ──

    def register(self, name: str, df: pl.DataFrame) -> None:
        """Register a Polars DataFrame as a DuckDB table/view.

        The DataFrame is converted to an Arrow table for zero-copy access.
        Registered tables can be queried by name in SQL.

        Args:
            name: Table name for SQL queries.
            df: Polars DataFrame to register.
        """
        arrow = df.to_arrow()
        self._conn.register(name, arrow)
        self._registered.add(name)
        logger.debug(
            "DuckDBEngine: registered '{}' ({} rows × {} cols)",
            name,
            df.height,
            df.width,
        )

    def register_many(self, tables: dict[str, pl.DataFrame]) -> None:
        """Register multiple DataFrames at once.

        Args:
            tables: {name: DataFrame} mapping.
        """
        for name, df in tables.items():
            self.register(name, df)

    def unregister(self, name: str) -> None:
        """Remove a registered table."""
        self._conn.unregister(name)
        self._registered.discard(name)

    @property
    def registered_tables(self) -> list[str]:
        """List of registered table names."""
        return sorted(self._registered)

    # ── SQL queries ──

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pl.DataFrame:
        """Execute a SQL query and return results as a Polars DataFrame.

        Args:
            sql: SQL query string. Can reference any registered tables.
            params: Optional query parameters (for parameterized queries).

        Returns:
            Polars DataFrame with query results.
        """
        try:
            result = (
                self._conn.execute(sql, params) if params else self._conn.execute(sql)
            )
            # DuckDB >= 1.0 supports direct Polars conversion
            return result.pl()
        except Exception as e:
            logger.error("DuckDBEngine query failed: {}", e)
            raise

    def query_arrow(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        """Execute SQL and return as PyArrow Table (zero-copy for advanced use).

        Args:
            sql: SQL query string.
            params: Optional query parameters.

        Returns:
            PyArrow Table.
        """
        result = self._conn.execute(sql, params if params else {})
        return result.fetch_arrow_table()

    # ── Direct Parquet querying ──

    def query_parquet(
        self,
        path: str | Path,
        sql: str | None = None,
    ) -> pl.DataFrame:
        """Query Parquet files directly with SQL.

        DuckDB scans Parquet files with full predicate/projection pushdown,
        so only relevant columns and row groups are read from disk.

        Args:
            path: Path or glob pattern to Parquet file(s).
                  E.g., 'data/features/momentum/**/*.parquet'.
            sql: SQL query. If None, returns SELECT * FROM <path>.
                 Use 'data' as the alias for the Parquet source.

        Returns:
            Polars DataFrame.
        """
        path_str = str(path)

        if sql is None:
            sql = f"SELECT * FROM '{path_str}'"

        try:
            return self._conn.execute(sql).pl()
        except Exception as e:
            logger.error("DuckDBEngine query_parquet({}) failed: {}", path_str, e)
            raise

    def scan_parquet(
        self,
        path: str | Path,
        filter_expr: str | None = None,
        columns: list[str] | None = None,
        limit: int | None = None,
    ) -> pl.DataFrame:
        """Scan Parquet files with optional filter/column projection.

        Convenience method that builds the SQL for you.

        Args:
            path: Path or glob to Parquet files.
            filter_expr: SQL WHERE clause expression (without 'WHERE').
            columns: Columns to select. None = all columns.
            limit: Row limit.

        Returns:
            Polars DataFrame.
        """
        path_str = str(path)
        select_clause = ", ".join(f'"{c}"' for c in columns) if columns else "*"
        sql = f"SELECT {select_clause} FROM '{path_str}'"

        if filter_expr:
            sql += f" WHERE {filter_expr}"
        if limit is not None:
            sql += f" LIMIT {limit}"

        return self.query(sql)

    # ── PIT query helpers ──

    def pit_query(
        self,
        table: str,
        period_col: str = "report_date",
        knowledge_col: str = "publish_date",
        symbol_col: str = "symbol",
        as_of: str | None = None,
        partition_expr: str | None = None,
        select_cols: str = "*",
    ) -> pl.DataFrame:
        """Execute a Point-in-Time query using ROW_NUMBER() window function.

        Implements the canonical PIT pattern from data_layer.md §1.4:
          "在回测 2023-11-01 时，提取 PIT 财报数据"

        For each (symbol, period_end), returns the latest version where
        knowledge_time <= as_of_date.

        Args:
            table: Registered table name or Parquet path.
            period_col: Column for the reporting period end date.
            knowledge_col: Column for the knowledge/publication date.
            symbol_col: Column for stock identifier.
            as_of: Reference date (ISO format). If None, no PIT filter.
            partition_expr: Additional PARTITION BY expression.
            select_cols: Columns to select (default: *).

        Returns:
            Polars DataFrame with the latest visible version per (symbol, period).
        """
        part_cols = f"{symbol_col}, {period_col}"
        if partition_expr:
            part_cols = f"{part_cols}, {partition_expr}"

        where = f"WHERE {knowledge_col} <= '{as_of}'" if as_of else ""

        sql = f"""
            SELECT {select_cols}
            FROM {table}
            {where}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY {part_cols}
                ORDER BY {knowledge_col} DESC
            ) = 1
            ORDER BY {symbol_col}, {period_col}
        """

        return self.query(sql)

    def pit_latest(
        self,
        table: str,
        symbol_col: str = "symbol",
        knowledge_col: str = "publish_date",
        as_of: str | None = None,
        select_cols: str = "*",
        order_cols: str | None = None,
    ) -> pl.DataFrame:
        """Get the single latest row per symbol as of a PIT date.

        Unlike pit_query (which gets latest per period), this gets the
        single most recent row per symbol regardless of period.

        Args:
            table: Registered table or Parquet path.
            symbol_col: Symbol column.
            knowledge_col: Knowledge time column.
            as_of: Reference date (ISO). None = no filter.
            select_cols: Columns to select.
            order_cols: Additional ORDER BY columns for tie-breaking.

        Returns:
            DataFrame with one row per symbol (the latest published).
        """
        where = f"WHERE {knowledge_col} <= '{as_of}'" if as_of else ""

        order = f"{knowledge_col} DESC"
        if order_cols:
            order = f"{order}, {order_cols}"

        sql = f"""
            SELECT {select_cols}
            FROM {table}
            {where}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY {symbol_col}
                ORDER BY {order}
            ) = 1
        """

        return self.query(sql)

    # ── OfflineStore bridge ──

    def query_store(
        self,
        store,
        sql: str | None = None,
        factor_groups: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        symbols: list[str] | None = None,
        columns: list[str] | None = None,
    ) -> pl.DataFrame:
        """Query an OfflineStore's Parquet files with DuckDB SQL.

        This is the bridge between OfflineStore (Parquet) and DuckDB queries,
        enabling fast analytical SQL over partitioned feature data without
        loading everything into memory first.

        Args:
            store: OfflineStore instance.
            sql: Custom SQL query. If provided, other filters are ignored.
                 Use 'features' as the table alias for the store data.
            factor_groups: Factor groups to include (None = all).
            start_date: Start date filter (ISO).
            end_date: End date filter (ISO).
            symbols: Symbol filter.
            columns: Column filter.

        Returns:
            Polars DataFrame.
        """
        if sql is not None:
            # Register all matching Parquet files as a 'features' view
            groups = factor_groups or store.list_groups()
            parquet_paths: list[str] = []
            for group in groups:
                group_dir = store._store_dir / group
                if not group_dir.exists():
                    continue
                # Collect all .parquet files in the group
                pq_files = list(group_dir.glob("**/*.parquet"))
                for pf in pq_files:
                    parquet_paths.append(str(pf))

            if parquet_paths:
                # Register as a DuckDB view for the custom SQL query
                path_list = ", ".join(f"'{p}'" for p in parquet_paths)
                view_sql = f"CREATE OR REPLACE VIEW features AS SELECT * FROM read_parquet([{path_list}], union_by_name=true)"
                self._conn.execute(view_sql)

            return self.query(sql)

        groups = factor_groups or store.list_groups()
        if not groups:
            logger.warning("DuckDBEngine.query_store: no factor groups found")
            return pl.DataFrame()

        # Collect all Parquet files with glob
        parquet_paths: list[str] = []
        for group in groups:
            group_dir = store._store_dir / group
            if not group_dir.exists():
                continue
            for pf in sorted(group_dir.glob("**/*.parquet")):
                parquet_paths.append(str(pf))

        if not parquet_paths:
            return pl.DataFrame()

        # Build the query
        path_list = ", ".join(f"'{p}'" for p in parquet_paths)
        select = ", ".join(f'"{c}"' for c in columns) if columns else "*"

        conditions: list[str] = []
        if start_date:
            conditions.append(f"trade_date >= '{start_date}'")
        if end_date:
            conditions.append(f"trade_date <= '{end_date}'")
        if symbols:
            sym_list = ", ".join(f"'{s}'" for s in symbols)
            conditions.append(f"symbol IN ({sym_list})")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        sql_stmt = f"""
            SELECT {select}
            FROM read_parquet([{path_list}], union_by_name=true)
            {where}
            ORDER BY symbol, trade_date
        """

        logger.debug(
            "DuckDBEngine.query_store: {} groups, {} conditions",
            len(groups),
            len(conditions),
        )

        return self.query(sql_stmt)

    # ── SQL expression feature computation ──

    def compute_sql(
        self,
        df: pl.DataFrame,
        expressions: dict[str, str],
        group_by: str = "symbol",
        order_by: str = "trade_date",
    ) -> pl.DataFrame:
        """Compute features via SQL expressions on a registered DataFrame.

        This is an alternative to Polars-based FeatureEngine. Some features
        are naturally expressed in SQL (e.g., window functions).

        Args:
            df: Input DataFrame.
            expressions: {feature_name: sql_expression} mapping.
                         E.g., {"ma_20": "AVG(close) OVER w"}.
            group_by: Column to PARTITION BY in window clauses.
            order_by: Column to ORDER BY in window clauses.

        Returns:
            DataFrame with original columns + feature columns.
        """
        self.register("_compute_src", df)

        feature_sql = ", ".join(
            f"{expr} AS {name}" for name, expr in expressions.items()
        )

        sql = f"""
            SELECT *,
                   {feature_sql}
            FROM _compute_src
            WINDOW w AS (PARTITION BY {group_by} ORDER BY {order_by})
        """

        result = self.query(sql)
        self.unregister("_compute_src")
        return result

    # ── Data profiling ──

    def profile(self, table: str) -> pl.DataFrame:
        """Run SUMMARIZE on a registered table for quick data profiling.

        Returns basic statistics: count, min, max, mean, std, etc.
        """
        return self.query(f"SUMMARIZE {table}")

    def table_schema(self, table: str) -> pl.DataFrame:
        """Get column names and types for a registered table."""
        return self.query(f"DESCRIBE {table}")

    def row_count(self, table: str) -> int:
        """Get the row count of a registered table."""
        result = self.query(f"SELECT COUNT(*) AS cnt FROM {table}")
        return result["cnt"].item()

    # ── Management ──

    def close(self) -> None:
        """Close the DuckDB connection."""
        self._conn.close()
        logger.debug("DuckDBEngine: connection closed")

    def execute_raw(self, sql: str) -> None:
        """Execute SQL that doesn't return results (DDL, INSERT, etc.)."""
        self._conn.execute(sql)

    @property
    def version(self) -> str:
        """DuckDB version string."""
        return self._conn.execute("SELECT version()").fetchone()[0]  # type: ignore[no-any-return]

    def __enter__(self) -> DuckDBEngine:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"DuckDBEngine(version={self.version}, "
            f"in_memory={self._conn.execute('SELECT current_database()').fetchone()[0] == 'memory'}, "  # type: ignore[no-any-return]
            f"registered={len(self._registered)} tables)"
        )
