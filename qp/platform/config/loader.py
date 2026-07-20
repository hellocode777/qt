"""Configuration loader — 4-tier priority system.

Priority (highest to lowest):
  1. CLI Arguments
  2. Environment Variables
  3. config.toml
  4. Defaults

After loading, the config is frozen (read-only) per ADR-011.
Secrets (API keys, etc.) must come from environment variables only.

See dp.md §6.7 for the complete configuration specification.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from qp.platform.config.defaults import build_default_config
from qp.platform.config.models import Config
from qp.platform.config.validator import validate_config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_toml(path: Path) -> dict[str, Any]:
    """Load and parse a TOML configuration file."""
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _apply_env_overrides(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides.

    Environment variables use the format QP__SECTION__KEY, e.g.:
      QP__LOGGING__LEVEL=DEBUG
      QP__STORAGE__BACKEND=duckdb
      QP__MODEL__LEARNING_RATE=0.03

    Secrets (API keys, tokens) are loaded from QP_SECRET_* variables
    and are never sourced from config files.
    """
    result = config_dict.copy()
    for env_key, env_value in os.environ.items():
        if env_key.startswith("QP__"):
            # QP__SECTION__KEY → section.key
            parts = env_key.removeprefix("QP__").lower().split("__")
            if len(parts) == 2:
                section, key = parts
                if section not in result:
                    result[section] = {}
                # Cast to appropriate type
                result[section][key] = _cast_env_value(env_value)
    return result


def _cast_env_value(value: str) -> Any:
    """Cast an environment variable string to the most appropriate Python type."""
    # Bool
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    # Int
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    return value


def load_config(
    config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> Config:
    """Load configuration using the 4-tier priority system.

    Args:
        config_path: Path to config.toml (defaults to ./config.toml).
        cli_overrides: CLI-provided overrides (highest priority).

    Returns:
        A frozen (read-only) Config instance.

    Raises:
        ConfigValidationError: If the configuration fails validation.
    """
    # Tier 4: Defaults
    default_config = build_default_config()
    config_dict = default_config.model_dump()

    # Tier 3: config.toml
    if config_path is None:
        config_path = Path("config.toml")
    elif isinstance(config_path, str):
        config_path = Path(config_path)
    toml_data = _load_toml(config_path)
    if toml_data:
        config_dict = _deep_merge(config_dict, toml_data)

    # Tier 2: Environment Variables
    config_dict = _apply_env_overrides(config_dict)

    # Tier 1: CLI Arguments
    if cli_overrides:
        config_dict = _deep_merge(config_dict, cli_overrides)

    # Build and validate
    config = Config(**config_dict)
    validate_config(config)

    # Freeze — no further modifications allowed (ADR-011)
    config.freeze()

    return config
