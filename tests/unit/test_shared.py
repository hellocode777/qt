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


class TestResolveDailyPricePath:
    """`resolve_daily_price_path` — 读哪个日线文件只能有一个入口。

    回归背景（2026-09-25）：monitor regime / validate / decision 等 6 处各自写
    `sorted(glob("daily_price_*.parquet"))[-1]`，按文件名排序会把
    `daily_price_main_2026-08-14` 排在 `daily_price_latest` 之后，于是静默读到
    过期快照（实测 8/14 vs latest 9/24），且输出里不显示数据日期。
    """

    def test_prefers_daily_price_latest(self, tmp_path, monkeypatch) -> None:
        """latest 存在时优先它 —— 即使别的文件名排序更靠后。"""
        import qp.shared.paths as paths

        dataset = tmp_path / "dataset"
        dataset.mkdir()
        latest = dataset / "daily_price_latest.parquet"
        latest.write_bytes(b"")
        stale = dataset / "daily_price_main_2026-08-14.parquet"
        stale.write_bytes(b"")
        # 旧实现的排序结果：main_ 在 latest 之后 → [-1] 选到 stale
        assert sorted(dataset.glob("daily_price_*.parquet"))[-1] == stale

        monkeypatch.setattr(paths, "DATASET_DIR", dataset)
        monkeypatch.setattr(paths, "DAILY_PRICE_LATEST", latest)

        assert paths.resolve_daily_price_path() == latest

    def test_falls_back_to_freshest_by_mtime(self, tmp_path, monkeypatch) -> None:
        """latest 缺失时按 mtime 取最新，而不是按文件名排序。"""
        import os

        import qp.shared.paths as paths

        dataset = tmp_path / "dataset"
        dataset.mkdir()
        older = dataset / "daily_price_main_2026-08-14.parquet"
        older.write_bytes(b"")
        newer = dataset / "daily_price_main_2026-09-24.parquet"
        newer.write_bytes(b"")
        os.utime(older, (1_000_000, 1_000_000))

        monkeypatch.setattr(paths, "DATASET_DIR", dataset)
        monkeypatch.setattr(paths, "DAILY_PRICE_LATEST", tmp_path / "missing.parquet")

        assert paths.resolve_daily_price_path() == newer

    def test_raises_when_no_price_file_exists(self, tmp_path, monkeypatch) -> None:
        """两个位置都没有 → FileNotFoundError（调用方据此提示跑 daily）。"""
        import pytest

        import qp.shared.paths as paths

        dataset = tmp_path / "dataset"
        dataset.mkdir()
        monkeypatch.setattr(paths, "DATASET_DIR", dataset)
        monkeypatch.setattr(paths, "DAILY_PRICE_LATEST", tmp_path / "missing.parquet")

        with pytest.raises(FileNotFoundError):
            paths.resolve_daily_price_path()

    def test_is_exported(self) -> None:
        """公开入口（__all__）——改动路径解析时别漏导出。"""
        import qp.shared.paths as paths

        assert "resolve_daily_price_path" in paths.__all__
