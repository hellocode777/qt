"""Immutable constants used across all layers of the QP platform."""

from datetime import UTC

# ── Determinism (Rule 24: Same Input, Same Output) ────────
# Global default seed — all random sources (numpy / random / LightGBM)
# should reference this instead of hardcoding their own literals.
DEFAULT_SEED = 42

# ── Time ───────────────────────────────────────────
DEFAULT_TIMEZONE = UTC
TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_WEEK = 5

# ── Currency ───────────────────────────────────────
DEFAULT_CURRENCY = "CNY"

# ── A-share market microstructure ──────────────────
# 日线 ``volume`` 的单位是「手」(lot)，1 手 = 100 股。腾讯 kline（TDR-001
# 唯一行情源）返回手，所以 成交额 = close × volume × SHARES_PER_LOT。
# 漏掉这个系数会把成交额低估 100×（ADV → 冲击成本高估 10×，流动性评分被系统性压低）。
SHARES_PER_LOT = 100.0

# ── Data ───────────────────────────────────────────
MIN_TRAINING_WINDOW_DAYS = 500  # ~2 years of trading days
DEFAULT_PURGED_CV_FOLDS = 5

# ── Pipeline ──────────────────────────────────────
DEFAULT_PIPELINE_TIMEOUT_SECONDS = 3600  # 1 hour

# ── Storage ───────────────────────────────────────
DEFAULT_STORAGE_BACKEND = "duckdb"

__all__ = [
    "DEFAULT_CURRENCY",
    "DEFAULT_PIPELINE_TIMEOUT_SECONDS",
    "DEFAULT_PURGED_CV_FOLDS",
    "DEFAULT_STORAGE_BACKEND",
    "DEFAULT_TIMEZONE",
    "MIN_TRAINING_WINDOW_DAYS",
    "SHARES_PER_LOT",
    "TRADING_DAYS_PER_MONTH",
    "TRADING_DAYS_PER_WEEK",
    "TRADING_DAYS_PER_YEAR",
]
