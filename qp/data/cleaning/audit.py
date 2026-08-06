"""ETL Audit Trail — records every data repair for traceability.

Each repair operation (OHLC fix, amount correction, missing date insertion,
suspension classification) generates an audit record with:
  - run_id: unique ETL run identifier
  - stage: which pipeline stage performed the repair
  - code: stock code
  - date: affected trading date
  - action: what was done (anomaly, update, insert)
  - detail: human-readable description of the repair

Regulatory requirement (rule.md §2 Rule 5):
  "所有数据修复操作必须可追溯、可审计、可回滚"
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import polars as pl
from loguru import logger

# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


def generate_run_id() -> str:
    """Generate a unique ETL run identifier.

    Format: etl-YYYYMMDD-HHMMSS
    """
    return f"etl-{datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')}"


# ------------------------------------------------------------------
# Audit record builders
# ------------------------------------------------------------------


def build_audit_from_repair(
    df: pl.DataFrame,
    code: str,
    run_id: str,
) -> list[dict[str, Any]]:
    """Extract audit records from OHLC repair metadata.

    Reads ``_repaired`` column (list of dicts) and generates one record
    per repaired row.

    Args:
        df: DataFrame with ``_repaired`` column.
        code: Stock code.
        run_id: ETL run identifier.

    Returns:
        List of audit record dicts.
    """
    if "_repaired" not in df.columns:
        return []

    records: list[dict[str, Any]] = []
    dates = df["trade_date"].cast(pl.Utf8).to_list()
    repaired = df["_repaired"].to_list()

    for i in range(df.height):
        repairs = repaired[i]
        if repairs and len(repairs) > 0:
            records.append(
                {
                    "run_id": run_id,
                    "stage": "stage1_ohlc",
                    "code": code,
                    "date": dates[i],
                    "action": "anomaly",
                    "detail": str(repairs),
                }
            )

    return records


def build_audit_from_amount(
    df: pl.DataFrame,
    code: str,
    run_id: str,
) -> list[dict[str, Any]]:
    """Extract audit records from amount fixes.

    Reads ``_amount_fixed`` boolean column.

    Args:
        df: DataFrame with ``_amount_fixed`` column.
        code: Stock code.
        run_id: ETL run identifier.

    Returns:
        List of audit record dicts.
    """
    if "_amount_fixed" not in df.columns:
        return []

    records: list[dict[str, Any]] = []
    dates = df["trade_date"].cast(pl.Utf8).to_list()
    fixed = df["_amount_fixed"].to_list()

    for i in range(df.height):
        if fixed[i]:
            records.append(
                {
                    "run_id": run_id,
                    "stage": "stage2_amount",
                    "code": code,
                    "date": dates[i],
                    "action": "update",
                    "detail": "amount corrected",
                }
            )

    return records


def build_audit_from_inserts(
    df: pl.DataFrame,
    code: str,
    run_id: str,
) -> list[dict[str, Any]]:
    """Extract audit records from inserted (missing) trading dates.

    Reads ``_inserted`` boolean column.

    Args:
        df: DataFrame with ``_inserted`` column.
        code: Stock code.
        run_id: ETL run identifier.

    Returns:
        List of audit record dicts.
    """
    if "_inserted" not in df.columns:
        return []

    records: list[dict[str, Any]] = []
    dates = df["trade_date"].cast(pl.Utf8).to_list()
    inserted = df["_inserted"].to_list()

    for i in range(df.height):
        if inserted[i]:
            records.append(
                {
                    "run_id": run_id,
                    "stage": "stage3_suspension",
                    "code": code,
                    "date": dates[i],
                    "action": "insert",
                    "detail": "missing_trading_day",
                }
            )

    return records


def build_audit_from_limits(
    df: pl.DataFrame,
    code: str,
    run_id: str,
) -> list[dict[str, Any]]:
    """Extract audit records from price limit anomalies.

    Reads ``_limit_flag`` column.

    Args:
        df: DataFrame with ``_limit_flag`` column.
        code: Stock code.
        run_id: ETL run identifier.

    Returns:
        List of audit record dicts.
    """
    if "_limit_flag" not in df.columns:
        return []

    records: list[dict[str, Any]] = []
    dates = df["trade_date"].cast(pl.Utf8).to_list()
    flags = df["_limit_flag"].to_list()

    for i in range(df.height):
        if flags[i] == "ex_limit":
            records.append(
                {
                    "run_id": run_id,
                    "stage": "stage1_anomaly",
                    "code": code,
                    "date": dates[i],
                    "action": "error",
                    "detail": "price_exceeds_daily_limit",
                }
            )

    return records


# ------------------------------------------------------------------
# Unified audit builder
# ------------------------------------------------------------------


def build_full_audit(
    df: pl.DataFrame,
    code: str,
    run_id: str,
) -> pl.DataFrame:
    """Extract all audit records from a repaired DataFrame.

    Combines records from all repair metadata columns:
      _repaired, _amount_fixed, _inserted, _limit_flag

    Args:
        df: DataFrame after running ``repair_all()``.
        code: Stock code.
        run_id: ETL run identifier.

    Returns:
        Polars DataFrame of audit records with columns:
        [run_id, stage, code, date, action, detail].
    """
    all_records = []
    all_records.extend(build_audit_from_repair(df, code, run_id))
    all_records.extend(build_audit_from_amount(df, code, run_id))
    all_records.extend(build_audit_from_inserts(df, code, run_id))
    all_records.extend(build_audit_from_limits(df, code, run_id))

    if not all_records:
        return pl.DataFrame(
            schema={
                "run_id": pl.Utf8,
                "stage": pl.Utf8,
                "code": pl.Utf8,
                "date": pl.Utf8,
                "action": pl.Utf8,
                "detail": pl.Utf8,
            }
        )

    return pl.DataFrame(all_records)


# ------------------------------------------------------------------
# Audit summary
# ------------------------------------------------------------------


def audit_summary(
    audit_df: pl.DataFrame,
) -> dict[str, Any]:
    """Generate a summary of audit records for a run.

    Args:
        audit_df: Output of ``build_full_audit()``.

    Returns:
        Dict with per-stage counts and total.
    """
    if audit_df.is_empty():
        return {"total": 0, "by_stage": {}, "by_action": {}}

    by_stage = audit_df.group_by("stage").len().to_dict(as_series=False)
    by_action = audit_df.group_by("action").len().to_dict(as_series=False)

    stage_counts = dict(
        zip(by_stage.get("stage", []), by_stage.get("len", []), strict=False)
    )
    action_counts = dict(
        zip(by_action.get("action", []), by_action.get("len", []), strict=False)
    )

    return {
        "total": audit_df.height,
        "by_stage": stage_counts,
        "by_action": action_counts,
    }


def print_audit_summary(audit_df: pl.DataFrame) -> None:
    """Log a human-readable audit summary."""
    summary = audit_summary(audit_df)
    logger.info("─" * 50)
    logger.info("ETL 审计日志: 共 {} 条记录", summary["total"])
    for stage, count in sorted(summary["by_stage"].items()):
        logger.info("  {}: {} 条", stage, count)
    logger.info("─" * 50)
