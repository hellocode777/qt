"""Immutable constants used across all layers of the QP platform."""

from datetime import UTC

# ── Time ───────────────────────────────────────────
DEFAULT_TIMEZONE = UTC
TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_WEEK = 5

# ── Currency ───────────────────────────────────────
DEFAULT_CURRENCY = "CNY"

# ── Data ───────────────────────────────────────────
MIN_TRAINING_WINDOW_DAYS = 500  # ~2 years of trading days
DEFAULT_PURGED_CV_FOLDS = 5

# ── Pipeline ──────────────────────────────────────
DEFAULT_PIPELINE_TIMEOUT_SECONDS = 3600  # 1 hour

# ── Storage ───────────────────────────────────────
DEFAULT_STORAGE_BACKEND = "duckdb"

__all__ = [
    "DEFAULT_TIMEZONE",
    "TRADING_DAYS_PER_YEAR",
    "TRADING_DAYS_PER_MONTH",
    "TRADING_DAYS_PER_WEEK",
    "DEFAULT_CURRENCY",
    "MIN_TRAINING_WINDOW_DAYS",
    "DEFAULT_PURGED_CV_FOLDS",
    "DEFAULT_PIPELINE_TIMEOUT_SECONDS",
    "DEFAULT_STORAGE_BACKEND",
]
