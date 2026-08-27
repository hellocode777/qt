"""Pydantic configuration models for the QP platform.

All configuration is organized by capability, not by layer.
See dp.md §6.7 for the configuration tree specification.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from qp.shared.exceptions import FrozenConfigError
from qp.shared.paths import DATASET_DIR, PARQUET_DIR, QP_DUCKDB, QP_SQLITE, RAW_DIR

# ── Freezable Base ──────────────────────────────────


class FreezableBaseModel(BaseModel):
    """Base model that supports runtime freezing."""

    def model_post_init(self, __context: object) -> None:
        """Initialize freeze state after model construction."""
        object.__setattr__(self, "_frozen", False)

    def freeze(self) -> None:
        """Recursively freeze this model and all nested FreezableBaseModels."""
        object.__setattr__(self, "_frozen", True)
        for field_name in self.__class__.model_fields:
            value = getattr(self, field_name)
            if isinstance(value, FreezableBaseModel):
                value.freeze()

    @property
    def is_frozen(self) -> bool:
        """Whether this instance has been frozen."""
        try:
            return object.__getattribute__(self, "_frozen")
        except AttributeError:
            return False

    def __setattr__(self, name: str, value: object) -> None:
        try:
            frozen = object.__getattribute__(self, "_frozen")
        except AttributeError:
            frozen = False
        if frozen:
            raise FrozenConfigError(f"Cannot modify '{name}' — configuration is frozen.")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        try:
            frozen = object.__getattribute__(self, "_frozen")
        except AttributeError:
            frozen = False
        if frozen:
            raise FrozenConfigError(f"Cannot delete '{name}' — configuration is frozen.")
        super().__delattr__(name)


# ── Project ─────────────────────────────────────────


class ProjectConfig(FreezableBaseModel):
    """Project-level settings."""

    name: str = "qp"
    version: str = "0.0.1"
    description: str = "Quant Platform"


# ── Storage ────────────────────────────────────────


class StorageConfig(FreezableBaseModel):
    """Storage backend configuration."""

    backend: str = "duckdb"  # duckdb | sqlite
    duckdb_path: str = str(QP_DUCKDB)
    sqlite_path: str = str(QP_SQLITE)
    parquet_dir: str = str(PARQUET_DIR)
    raw_dir: str = str(RAW_DIR)
    dataset_dir: str = str(DATASET_DIR)


# ── Logging ────────────────────────────────────────


class LoggingConfig(FreezableBaseModel):
    """Logging configuration."""

    level: str = "INFO"
    format: str = "structured"  # structured | colored
    json_output: bool = False
    log_dir: str = "logs"
    rotation: str = "10 MB"
    retention: str = "30 days"


# ── Scheduler ──────────────────────────────────────


class SchedulerConfig(FreezableBaseModel):
    """Job scheduler configuration."""

    timezone: str = "Asia/Shanghai"
    max_jobs: int = 100
    default_retry_count: int = 3
    default_retry_delay_seconds: int = 60


# ── Data ────────────────────────────────────────────


class DataConfig(FreezableBaseModel):
    """Data Layer configuration."""

    default_start_date: str = "2015-01-01"
    default_source: str = "akshare"
    cache_enabled: bool = True
    cache_ttl_hours: int = 24


# ── Feature ────────────────────────────────────────


class FeatureConfig(FreezableBaseModel):
    """Feature engineering configuration."""

    max_features: int = 60
    correlation_threshold: float = 0.9


# ── Model ──────────────────────────────────────────


class ModelConfig(FreezableBaseModel):
    """Model training configuration.

    See rule.md §7.9.4 for default hyperparameter recommendations.
    """

    default_algorithm: str = "lightgbm"
    objective: str = "lambdarank"
    num_leaves: int = 31
    max_depth: int = 6
    learning_rate: float = 0.05
    n_estimators: int = 1000
    min_data_in_leaf: int = 100
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    lambda_l1: float = 0.5
    lambda_l2: float = 0.5
    early_stopping_rounds: int = 50
    purged_cv_folds: int = 5
    min_training_window_days: int = 500


# ── Backtest ───────────────────────────────────────


class BacktestConfig(FreezableBaseModel):
    """Backtest and simulation configuration."""

    default_slippage_pct: float = 0.001  # 0.1%
    commission_pct: float = 0.00025  # 0.025%
    stamp_tax_pct: float = 0.0005  # 0.05% (sell only)
    adv_limit_pct: float = 0.10  # max 10% of daily volume


# ── Broker ─────────────────────────────────────────


class BrokerConfig(FreezableBaseModel):
    """Broker connection configuration."""

    provider: str = "simulated"


# ── Monitoring ─────────────────────────────────────


class MonitoringConfig(FreezableBaseModel):
    """Monitoring and Kill Switch configuration."""

    psi_threshold: float = 0.25
    max_drawdown_strategy_ratio: float = 1.5
    monthly_drawdown_limit: float = 0.15
    rolling_60d_drawdown_limit: float = 0.20
    consecutive_loss_days: int = 15
    model_decay_ic_ratio: float = 0.30


# ── Runtime ────────────────────────────────────────


class RuntimeConfig(FreezableBaseModel):
    """Runtime-level settings."""

    env: str = "development"


# ── Root Config ────────────────────────────────────


class Config(FreezableBaseModel):
    """Root configuration object — all settings unified under one tree.

    Frozen after startup (ADR-011). Secrets come from env vars only.
    """

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    feature: FeatureConfig = Field(default_factory=FeatureConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
