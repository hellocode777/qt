"""统一数据路径常量（Path 对象）。

替代散落的 ``'data/...'`` 字符串字面量（153 处 / 87 文件，2026-08-27 扫描，
见 docs/tracking/qt_backlog_tracker.md C-1）。常量是 ``pathlib.Path`` 对象，
支持直接 ``/`` 拼接（``DECISIONS_DIR / "file.json"``）和 ``Path(...)`` 包裹。

路径相对 repo 根（运行时 cwd），与现有行为一致；改数据目录位置/命名时只动本文件。

Usage:
    from qp.shared.paths import DATASET_DIR, DAILY_PRICE_LATEST

    path = DATASET_DIR / "my.parquet"
"""

from __future__ import annotations

from pathlib import Path

# ── 顶层目录 ─────────────────────────────────────────────
DATA_DIR = Path("data")
DATASET_DIR = Path("data/dataset")
EXPERIMENTS_DIR = Path("data/experiments")
MONITORING_DIR = Path("data/monitoring")
KNOWLEDGE_DIR = Path("data/knowledge")
DECISIONS_DIR = Path("data/decisions")
METADATA_DIR = Path("data/metadata")
FEATURES_DIR = Path("data/features")
PAPER_TRADING_DIR = Path("data/paper_trading")
FACTOR_LIBRARY_DIR = Path("data/factor_library")
RAW_DIR = Path("data/raw")
PARQUET_DIR = Path("data/parquet")
REPORTS_DIR = Path("data/reports")
SIMULATION_DIR = Path("data/simulation")
MODELS_DIR = Path("data/models")
CACHE_DIR = Path("data/cache")
ARTIFACTS_DIR = Path("data/artifacts")
POSITIONS_DIR = Path("data/positions")
PORTFOLIO_DIR = Path("data/portfolio")
OPTUNA_DIR = Path("data/optuna")
INDUSTRY_HEAT_DIR = Path("data/industry_heat")
CAPITAL_FLOW_CACHE_DIR = Path("data/capital_flow_cache")
BRONZE_DIR = Path("data/bronze")
SILVER_DIR = Path("data/silver")
FACTOR_STORE_DIR = Path("data/factor_store")
FEATURE_STORE_DIR = Path("data/feature_store_data")
FUNDAMENTAL_CACHE_DIR = Path("data/fundamental_cache")
VALUATION_CACHE_DIR = Path("data/valuation_cache")
REGIME_NOTES_DIR = Path("data/knowledge/market_regime_notes")
PROPOSALS_DIR = Path("data/proposals")
RESEARCH_CACHE_DIR = Path("data/cache/research")

# ── 常用文件 ─────────────────────────────────────────────
DAILY_PRICE_LATEST = Path("data/dataset/daily_price_latest.parquet")
DAILY_PRICE_MAIN = Path("data/dataset/daily_price_main.parquet")
DAILY_PRICE_PREFIX = Path("data/dataset/daily_price_")  # 模板前缀：daily_price_{name}.parquet
MOMENTUM_20D = Path("data/dataset/momentum_20d.parquet")
VOLATILITY_20D = Path("data/dataset/volatility_20d.parquet")
FUNDAMENTALS_LATEST = Path("data/dataset/fundamentals_latest.parquet")
FACTOR_VALUES_DAILY = Path("data/dataset/factor_values_daily.parquet")
FACTOR_REGISTRY = Path("data/factor_registry.json")
STRATEGY_REGISTRY = Path("data/strategy_registry.json")
BLACKLIST = Path("data/blacklist.json")
STOCK_NAMES = Path("data/stock_names.json")
STOCK_INDUSTRY = Path("data/stock_industry.json")
STOCK_INDUSTRY_CSRC = Path("data/stock_industry_csrc.json")
QP_DUCKDB = Path("data/qp.duckdb")
QP_SQLITE = Path("data/qp.sqlite")
SOURCES_JSON = Path("data/metadata/sources.json")
ONLINE_SIGNAL_HISTORY = Path("data/monitoring/online_signal_history.parquet")
SYSTEM_HEALTH_LOG = Path("data/monitoring/system_health_log.parquet")
WATCHDOG_DIR = Path("data/monitoring/watchdog")
FACTOR_RAW_FULL = Path("data/experiments/_factor_raw_full_5factors_2015_2026.parquet")
FACTOR_RAW_CACHE = Path("data/experiments/_factor_raw_cache.parquet")
MAIN_BOARD_CODES = Path("data/main_board_codes.json")
DELISTED_CACHE = Path("data/delisted_cache.json")
ADJ_FACTOR = Path("data/dataset/adj_factor.parquet")
INDUSTRY_CACHE = Path("data/industry_cache.json")
LISTING_DATES_CACHE = Path("data/listing_dates_cache.json")
LINEAGE_JSON = Path("data/metadata/lineage.json")
SCHEMAS_JSON = Path("data/metadata/schemas.json")
LINEAGE_GRAPH_JSON = Path("data/metadata/lineage_graph.json")
BLACKLIST_RULES = Path("data/knowledge/blacklist_rules.json")
VERSION_TREE_JSON = Path("data/knowledge/version_tree.json")
ONLINE_HEALTH_HISTORY = Path("data/monitoring/online_health_history.parquet")
CAPITAL_FLOW_LATEST = Path("data/dataset/capital_flow_latest.parquet")

__all__ = [
    "ADJ_FACTOR",
    "ARTIFACTS_DIR",
    "BLACKLIST",
    "BLACKLIST_RULES",
    "BRONZE_DIR",
    "CACHE_DIR",
    "CAPITAL_FLOW_LATEST",
    "DAILY_PRICE_LATEST",
    "DAILY_PRICE_MAIN",
    "DAILY_PRICE_PREFIX",
    "DATASET_DIR",
    "DATA_DIR",
    "DECISIONS_DIR",
    "DELISTED_CACHE",
    "EXPERIMENTS_DIR",
    "FACTOR_LIBRARY_DIR",
    "FACTOR_RAW_CACHE",
    "FACTOR_RAW_FULL",
    "FACTOR_REGISTRY",
    "FACTOR_STORE_DIR",
    "FACTOR_VALUES_DAILY",
    "FEATURES_DIR",
    "FEATURE_STORE_DIR",
    "FUNDAMENTALS_LATEST",
    "FUNDAMENTAL_CACHE_DIR",
    "INDUSTRY_CACHE",
    "KNOWLEDGE_DIR",
    "LINEAGE_GRAPH_JSON",
    "LINEAGE_JSON",
    "LISTING_DATES_CACHE",
    "MAIN_BOARD_CODES",
    "METADATA_DIR",
    "MODELS_DIR",
    "MOMENTUM_20D",
    "MONITORING_DIR",
    "ONLINE_HEALTH_HISTORY",
    "ONLINE_SIGNAL_HISTORY",
    "OPTUNA_DIR",
    "PAPER_TRADING_DIR",
    "PARQUET_DIR",
    "PORTFOLIO_DIR",
    "POSITIONS_DIR",
    "QP_DUCKDB",
    "QP_SQLITE",
    "RAW_DIR",
    "REGIME_NOTES_DIR",
    "REPORTS_DIR",
    "SCHEMAS_JSON",
    "SILVER_DIR",
    "SIMULATION_DIR",
    "SOURCES_JSON",
    "STOCK_INDUSTRY",
    "STOCK_INDUSTRY_CSRC",
    "STOCK_NAMES",
    "STRATEGY_REGISTRY",
    "SYSTEM_HEALTH_LOG",
    "VALUATION_CACHE_DIR",
    "VERSION_TREE_JSON",
    "VOLATILITY_20D",
    "WATCHDOG_DIR",
]
