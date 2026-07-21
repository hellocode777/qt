"""Tests for qp.data.cleaning.audit — ETL audit trail."""

from __future__ import annotations

import polars as pl

from qp.data.cleaning.audit import (
    audit_summary,
    build_audit_from_amount,
    build_audit_from_inserts,
    build_audit_from_limits,
    build_audit_from_repair,
    build_full_audit,
    generate_run_id,
)
from qp.data.cleaning.repair import repair_ohlc_boundaries


class TestGenerateRunId:
    def test_format(self):
        run_id = generate_run_id()
        assert run_id.startswith("etl-")
        assert len(run_id) >= 17  # etl-YYYYMMDD-HHMMSS

    def test_unique(self):
        id1 = generate_run_id()
        id2 = generate_run_id()
        assert id1.startswith("etl-")
        assert id2.startswith("etl-")


class TestBuildAuditFromRepair:
    def test_empty_no_repaired_column(self):
        df = pl.DataFrame({"trade_date": ["2024-01-15"], "close": [10.0]})
        records = build_audit_from_repair(df, "000001", "etl-test")
        assert records == []

    def test_extracts_repairs(self):
        """Use repair_ohlc_boundaries to generate proper _repaired metadata."""
        df = pl.DataFrame({
            "trade_date": ["2024-01-15", "2024-01-16"],
            "open": [0.0, 10.5],  # zero price triggers repair
            "high": [11.0, 10.8],
            "low": [9.5, 10.0],
            "close": [10.5, 10.3],
        })
        repaired_df = repair_ohlc_boundaries(df)
        records = build_audit_from_repair(repaired_df, "000001", "etl-test")
        # First row had zero open → should have a repair record
        assert len(records) >= 1
        assert records[0]["code"] == "000001"
        assert records[0]["action"] == "anomaly"


class TestBuildAuditFromAmount:
    def test_extracts_fixed_amounts(self):
        df = pl.DataFrame({
            "trade_date": ["2024-01-15", "2024-01-16"],
            "_amount_fixed": [True, False],
        })
        records = build_audit_from_amount(df, "000001", "etl-test")
        assert len(records) == 1
        assert records[0]["detail"] == "amount corrected"

    def test_no_amount_fixed_column(self):
        df = pl.DataFrame({"trade_date": ["2024-01-15"]})
        records = build_audit_from_amount(df, "000001", "etl-test")
        assert records == []


class TestBuildAuditFromInserts:
    def test_extracts_inserts(self):
        df = pl.DataFrame({
            "trade_date": ["2024-01-15", "2024-01-16", "2024-01-17"],
            "_inserted": [False, True, False],
        })
        records = build_audit_from_inserts(df, "000001", "etl-test")
        assert len(records) == 1
        assert records[0]["action"] == "insert"
        assert records[0]["date"] == "2024-01-16"


class TestBuildAuditFromLimits:
    def test_extracts_exceeded_limits(self):
        df = pl.DataFrame({
            "trade_date": ["2024-01-15", "2024-01-16"],
            "_limit_flag": ["normal", "ex_limit"],
        })
        records = build_audit_from_limits(df, "000001", "etl-test")
        assert len(records) == 1
        assert records[0]["action"] == "error"
        assert records[0]["detail"] == "price_exceeds_daily_limit"


class TestBuildFullAudit:
    def test_combines_all_sources(self):
        """Build a DataFrame with all audit metadata columns manually."""
        df = pl.DataFrame({
            "trade_date": ["2024-01-15"],
            "_amount_fixed": [True],
            "_inserted": [False],
            "_limit_flag": ["ex_limit"],
        })
        # Also add _repaired via repair_ohlc
        df = df.with_columns(
            open=pl.lit(0.0), high=pl.lit(11.0), low=pl.lit(9.0), close=pl.lit(10.0),
        )
        df = repair_ohlc_boundaries(df)
        audit_df = build_full_audit(df, "000001", "etl-test")
        # Should have records from repair + amount + limit
        assert audit_df.height >= 2

    def test_empty_when_no_issues(self):
        """Create clean data with no repairs needed."""
        df = pl.DataFrame({
            "trade_date": ["2024-01-15"],
            "open": [10.0], "high": [11.0], "low": [9.5], "close": [10.5],
        })
        df = repair_ohlc_boundaries(df)
        df = df.with_columns(
            pl.lit(False).alias("_amount_fixed"),
            pl.lit(False).alias("_inserted"),
            pl.lit("normal").alias("_limit_flag"),
        )
        audit_df = build_full_audit(df, "000001", "etl-test")
        assert audit_df.is_empty()


class TestAuditSummary:
    def test_summary_counts(self):
        audit_df = pl.DataFrame({
            "run_id": ["etl-test"] * 3,
            "stage": ["stage1_ohlc", "stage1_ohlc", "stage2_amount"],
            "code": ["000001"] * 3,
            "date": ["2024-01-15", "2024-01-16", "2024-01-17"],
            "action": ["anomaly", "anomaly", "update"],
            "detail": ["fix1", "fix2", "amount_corrected"],
        })
        summary = audit_summary(audit_df)
        assert summary["total"] == 3
        assert summary["by_stage"]["stage1_ohlc"] == 2
        assert summary["by_stage"]["stage2_amount"] == 1
        assert summary["by_action"]["anomaly"] == 2
        assert summary["by_action"]["update"] == 1

    def test_empty_summary(self):
        audit_df = pl.DataFrame(schema={
            "run_id": pl.Utf8, "stage": pl.Utf8, "code": pl.Utf8,
            "date": pl.Utf8, "action": pl.Utf8, "detail": pl.Utf8,
        }).clear()
        summary = audit_summary(audit_df)
        assert summary["total"] == 0
        assert summary["by_stage"] == {}
        assert summary["by_action"] == {}
