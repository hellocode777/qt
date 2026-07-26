"""Concrete strategy implementations.

Each strategy inherits from BaseStrategy and implements:
  - strategy_id: unique identifier string
  - generate_signals(as_of_date): produce ranked alpha signals

Per docs/6_Strategy_Engine.md, strategies are hot-pluggable via importlib.
"""

from qp.strategy.strategies.alpha_multi_factor import (
    ALPHA_MULTI_FACTOR_CONFIG,
    ALPHA_MULTI_FACTOR_WEIGHTS,
    ALPHA_V2_CONFIG,
    ALPHA_V2_WEIGHTS,
    run_alpha_multi_factor_v1,
    run_alpha_multi_factor_v2,
)
from qp.strategy.strategies.momentum import MomentumStrategy
from qp.strategy.strategies.momentum_vol_full import (
    MOMENTUM_VOL_FULL_CONFIG,
    MOMENTUM_VOL_FULL_WEIGHTS,
    run_momentum_vol_full,
)
from qp.strategy.strategies.quality import QualityStrategy
from qp.strategy.strategies.value import ValueStrategy

__all__ = [
    "ALPHA_MULTI_FACTOR_CONFIG",
    "ALPHA_MULTI_FACTOR_WEIGHTS",
    "ALPHA_V2_CONFIG",
    "ALPHA_V2_WEIGHTS",
    "MomentumStrategy",
    "MOMENTUM_VOL_FULL_CONFIG",
    "MOMENTUM_VOL_FULL_WEIGHTS",
    "QualityStrategy",
    "ValueStrategy",
    "run_alpha_multi_factor_v1",
    "run_alpha_multi_factor_v2",
    "run_momentum_vol_full",
]
