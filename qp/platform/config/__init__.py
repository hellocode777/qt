"""Configuration system — 4-tier priority (CLI > Env > TOML > Defaults).

After startup, Config is frozen (read-only). Secrets come from env vars only.
"""

from qp.platform.config.loader import load_config
from qp.platform.config.models import Config

__all__ = [
    "Config",
    "load_config",
]
