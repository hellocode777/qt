"""Configuration validation.

Validates that the loaded configuration is internally consistent and
contains valid values before the runtime starts.

Fail Fast principle: any invalid configuration causes immediate exit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qp.platform.config.models import Config


class ConfigValidationError(ValueError):
    """Raised when the configuration fails validation."""


def validate_config(config: Config) -> None:
    """Validate a Config object for internal consistency.

    Args:
        config: The loaded configuration.

    Raises:
        ConfigValidationError: If any validation rule fails.
    """
    errors: list[str] = []

    # Storage
    if config.storage.backend not in ("duckdb", "sqlite"):
        errors.append(
            f"storage.backend must be 'duckdb' or 'sqlite', got '{config.storage.backend}'"
        )

    # Logging
    if config.logging.level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        errors.append(f"logging.level '{config.logging.level}' is not a valid log level")

    # Model
    if config.model.num_leaves < 2:
        errors.append("model.num_leaves must be >= 2")
    if config.model.max_depth < 1:
        errors.append("model.max_depth must be >= 1")
    if config.model.learning_rate <= 0:
        errors.append("model.learning_rate must be > 0")
    if config.model.purged_cv_folds < 2:
        errors.append("model.purged_cv_folds must be >= 2")
    if config.model.min_training_window_days < 100:
        errors.append("model.min_training_window_days must be >= 100")
    if not 0 < config.model.feature_fraction <= 1.0:
        errors.append("model.feature_fraction must be in (0, 1]")
    if not 0 < config.model.bagging_fraction <= 1.0:
        errors.append("model.bagging_fraction must be in (0, 1]")

    # Monitoring
    if not 0 < config.monitoring.psi_threshold <= 1.0:
        errors.append("monitoring.psi_threshold must be in (0, 1]")

    # Backtest
    if config.backtest.adv_limit_pct <= 0 or config.backtest.adv_limit_pct > 1:
        errors.append("backtest.adv_limit_pct must be in (0, 1]")

    if errors:
        raise ConfigValidationError(
            "Configuration validation failed:\n  - " + "\n  - ".join(errors)
        )
