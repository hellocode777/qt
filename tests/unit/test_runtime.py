"""Tests for the Runtime & Lifecycle system."""

import pytest

from qp.platform.runtime import build_runtime
from qp.shared.exceptions import RuntimeStateError
from qp.shared.types import RuntimeState


class TestLifecycle:
    """Test runtime state machine."""

    def test_initial_state_is_created(self) -> None:
        app = build_runtime()
        assert app.state == RuntimeState.CREATED

    def test_normal_lifecycle(self) -> None:
        app = build_runtime()
        app.start()
        assert app.state == RuntimeState.RUNNING
        app.stop()
        assert app.state == RuntimeState.TERMINATED

    def test_cannot_skip_states(self) -> None:
        app = build_runtime()
        # Cannot go directly from CREATED to RUNNING
        with pytest.raises(RuntimeStateError):
            app.lifecycle.transition_to(RuntimeState.RUNNING)

    def test_cannot_transition_from_terminated(self) -> None:
        app = build_runtime()
        app.start()
        app.stop()
        with pytest.raises(RuntimeStateError):
            app.lifecycle.transition_to(RuntimeState.RUNNING)

    def test_fail_transition(self) -> None:
        app = build_runtime()
        app.fail("test failure")
        assert app.state == RuntimeState.FAILED

    def test_config_is_accessible(self) -> None:
        app = build_runtime()
        assert app.context.config.project.name == "qp"

    def test_logger_is_accessible(self) -> None:
        app = build_runtime()
        app.context.logger.info("test", module="test_runtime")
