"""Tests for the paper-trading auto-promotion guard (2026-10-16 incident).

Context: on 2026-10-14 the 18:32 ``paper_trading`` job evaluated
``lvr_vol_only``'s completed 30-day run as PASS and unconditionally rewrote
its lifecycle from APPROVED to SHADOW_PRODUCTION.  ``daily_pipeline`` trades
ONLY APPROVED strategies, so the next two sessions early-returned with
"无 APPROVED 策略" and produced no DecisionPackage.  The guard keeps the
automatic promotion/demotion from rewriting lifecycles that already sit at
or above SHADOW_PRODUCTION.
"""

from __future__ import annotations

import pytest

from qp.platform.cli.commands.scheduler import _paper_auto_lifecycle_change_allowed
from qp.shared.types import StrategyLifecycle


class TestPaperAutoLifecycleChangeGuard:
    @pytest.mark.parametrize(
        "lifecycle",
        [
            StrategyLifecycle.APPROVED,
            StrategyLifecycle.SHADOW_PRODUCTION,
            StrategyLifecycle.PRODUCTION,
            StrategyLifecycle.WARNING,
            StrategyLifecycle.KILL_SWITCH,
        ],
    )
    def test_protected_states_are_never_rewritten(self, lifecycle: StrategyLifecycle) -> None:
        """APPROVED must survive a PASS — the 2026-10-14 regression."""
        assert _paper_auto_lifecycle_change_allowed(lifecycle) is False

    @pytest.mark.parametrize(
        "lifecycle",
        [
            StrategyLifecycle.RESEARCH,
            StrategyLifecycle.BACKTEST_PASSED,
            StrategyLifecycle.PAPER_TRADING,
        ],
    )
    def test_lower_states_may_be_promoted(self, lifecycle: StrategyLifecycle) -> None:
        assert _paper_auto_lifecycle_change_allowed(lifecycle) is True

    def test_unregistered_strategy_is_allowed(self) -> None:
        """No lifecycle at all → keep the normal promote/demote path."""
        assert _paper_auto_lifecycle_change_allowed(None) is True
