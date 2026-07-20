"""Default values for all configuration sections.

These are the lowest-priority tier in the 4-tier config hierarchy:
  1. CLI Arguments (highest)
  2. Environment Variables
  3. config.toml
  4. Defaults (lowest — this file)

See dp.md §6.7 for the full config specification.
"""

from qp.platform.config.models import (
    BacktestConfig,
    BrokerConfig,
    Config,
    DataConfig,
    FeatureConfig,
    LoggingConfig,
    ModelConfig,
    MonitoringConfig,
    ProjectConfig,
    RuntimeConfig,
    SchedulerConfig,
    StorageConfig,
)


def build_default_config() -> Config:
    """Build a Config populated entirely with default values.

    Returns:
        A Config instance with all defaults applied.
    """
    return Config(
        project=ProjectConfig(),
        storage=StorageConfig(),
        logging=LoggingConfig(),
        scheduler=SchedulerConfig(),
        data=DataConfig(),
        feature=FeatureConfig(),
        model=ModelConfig(),
        backtest=BacktestConfig(),
        broker=BrokerConfig(),
        monitoring=MonitoringConfig(),
        runtime=RuntimeConfig(),
    )
