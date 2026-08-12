"""Global seed utilities — Rule 24 (Same Input, Same Output) determinism.

The single entry point for seeding all random sources in the QP platform.
Call ``seed_everything()`` once at every process entry point (CLI main,
scheduler, pipeline runners) so research results are reproducible given the
same input versions, seed, and environment.

Rule 24 states: 在指定输入版本、随机种子与运行环境中，研究结果必须确定性复现。

Usage:
    from qp.shared.constants.seed import DEFAULT_SEED, seed_everything

    seed_everything()           # use DEFAULT_SEED (42)
    seed_everything(2026)       # custom seed for a specific experiment
"""

from __future__ import annotations

import random

import numpy as np

from qp.shared.constants import DEFAULT_SEED

__all__ = ["DEFAULT_SEED", "seed_everything"]


def seed_everything(seed: int = DEFAULT_SEED) -> None:
    """Seed all random sources for deterministic execution.

    Args:
        seed: Master random seed. Defaults to the platform-wide DEFAULT_SEED.
    """
    random.seed(seed)
    np.random.seed(seed)
    # numpy's legacy GlobalState is seeded above; libraries built on top
    # (LightGBM, polars sampling) take explicit seed params which should
    # reference DEFAULT_SEED — see lgb_rank.py / demo_adapter.py.
