"""Cleaning layer — deterministic, auditable, PIT-compliant data repair.

Components:
  - ETLPipeline: 4-stage cleaning pipeline (anomaly→volume→suspension→adjustment)
  - repair: OHLC boundary repair, amount validation, missing date filling,
            board-aware price limits, suspension classification
  - audit: Audit trail generation for regulatory traceability
  - delisted_handler: Survivorship bias mitigation for backtesting

Usage:
    from qp.data.cleaning import ETLPipeline, repair_all, build_full_audit
    from qp.data.cleaning import DelistedHandler
"""

from qp.data.cleaning.audit import (
    build_audit_from_amount,
    build_audit_from_inserts,
    build_audit_from_limits,
    build_audit_from_repair,
    build_full_audit,
    generate_run_id,
    print_audit_summary,
)
from qp.data.cleaning.delisted_handler import DelistedHandler
from qp.data.cleaning.engine import CleaningEngine
from qp.data.cleaning.etl_pipeline import ETLPipeline
from qp.data.cleaning.repair import (
    PRICE_LIMITS,
    classify_suspension_type,
    detect_price_limit_anomalies,
    fill_missing_trading_dates,
    get_board_type,
    get_price_limit,
    repair_all,
    repair_ohlc_boundaries,
    validate_and_fix_amount,
)

__all__ = [
    # ETL Pipeline
    "ETLPipeline",
    "CleaningEngine",
    # Repair functions
    "repair_all",
    "repair_ohlc_boundaries",
    "validate_and_fix_amount",
    "fill_missing_trading_dates",
    "classify_suspension_type",
    "detect_price_limit_anomalies",
    "PRICE_LIMITS",
    "get_price_limit",
    "get_board_type",
    # Audit trail
    "build_full_audit",
    "build_audit_from_repair",
    "build_audit_from_amount",
    "build_audit_from_inserts",
    "build_audit_from_limits",
    "generate_run_id",
    "print_audit_summary",
    # Survivorship bias
    "DelistedHandler",
]
