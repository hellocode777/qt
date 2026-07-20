"""Tests for Shared modules — constants, types, exceptions."""


from qp.shared.constants import (
    DEFAULT_CURRENCY,
    DEFAULT_TIMEZONE,
    MIN_TRAINING_WINDOW_DAYS,
    TRADING_DAYS_PER_YEAR,
)
from qp.shared.exceptions import (
    ConfigError,
    DataValidationError,
    FrozenConfigError,
    LayerViolationError,
    PipelineError,
    QPError,
)
from qp.shared.types import (
    PipelineStatus,
    PositionState,
    RuntimeState,
    StrategyLifecycle,
)


class TestConstants:
    """Test shared constants."""

    def test_trading_days_per_year(self) -> None:
        assert TRADING_DAYS_PER_YEAR == 252

    def test_default_currency(self) -> None:
        assert DEFAULT_CURRENCY == "CNY"

    def test_default_timezone_is_utc(self) -> None:
        from datetime import UTC
        assert DEFAULT_TIMEZONE == UTC

    def test_min_training_window_days(self) -> None:
        assert MIN_TRAINING_WINDOW_DAYS == 500


class TestTypes:
    """Test shared type enums."""

    def test_runtime_states(self) -> None:
        assert RuntimeState.CREATED.value == 1
        assert RuntimeState.RUNNING.value == 4
        assert RuntimeState.TERMINATED.value == 6

    def test_pipeline_status(self) -> None:
        assert PipelineStatus.SUCCESS.value == "success"
        assert PipelineStatus.FAILED.value == "failed"

    def test_position_states(self) -> None:
        assert PositionState.IDEA.value == 1
        assert PositionState.HOLDING.value == 4
        assert PositionState.ARCHIVED.value == 7

    def test_strategy_lifecycle(self) -> None:
        assert StrategyLifecycle.RESEARCH.value == "research"
        assert StrategyLifecycle.PRODUCTION.value == "production"
        assert StrategyLifecycle.KILL_SWITCH.value == "kill_switch"


class TestExceptions:
    """Test exception hierarchy."""

    def test_qp_error_is_base(self) -> None:
        assert issubclass(ConfigError, QPError)
        assert issubclass(PipelineError, QPError)
        assert issubclass(LayerViolationError, QPError)

    def test_specific_exceptions(self) -> None:
        assert issubclass(FrozenConfigError, ConfigError)
        assert issubclass(DataValidationError, QPError)

    def test_exception_message(self) -> None:
        error = ConfigError("test message")
        assert str(error) == "test message"
