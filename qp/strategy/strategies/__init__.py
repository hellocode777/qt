"""Concrete strategy implementations.

Each strategy inherits from BaseStrategy and implements:
  - strategy_id: unique identifier string
  - generate_signals(as_of_date): produce ranked alpha signals

Per docs/6_Strategy_Engine.md, strategies are hot-pluggable via importlib.
"""

from qp.strategy.strategies.momentum import MomentumStrategy
from qp.strategy.strategies.momentum_vol_full import (
    MOMENTUM_VOL_FULL_CONFIG,
    MOMENTUM_VOL_FULL_WEIGHTS,
    run_momentum_vol_full,
)
from qp.strategy.strategies.quality import QualityStrategy
from qp.strategy.strategies.value import ValueStrategy

__all__ = [
    "MomentumStrategy",
    "QualityStrategy",
    "ValueStrategy",
    "MOMENTUM_VOL_FULL_CONFIG",
    "MOMENTUM_VOL_FULL_WEIGHTS",
    "run_momentum_vol_full",
]
