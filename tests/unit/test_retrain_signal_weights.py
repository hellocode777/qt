"""Tests for retrain-signal weight scaling (auto-deweighting).

Covers qp.monitoring.retrain_signal.load_weight_scales — the consumer
side of the REDUCE_WEIGHT feedback loop (L11-1.7): a strategy with a
recent decay/drift signal gets a reduced weight scale for the daily
ensemble and capital allocation.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from qp.monitoring.retrain_signal import (
    DEFAULT_RETRAIN_DIR,
    RetrainSignal,
    RetrainSignalLogger,
    load_weight_scales,
)


@pytest.fixture()
def signal_dir(tmp_path) -> str:
    """Isolated signal directory per test (no cross-test pollution)."""
    return str(tmp_path / "monitoring")


def _log_signals(signal_dir: str, signals: list[RetrainSignal]) -> None:
    logger = RetrainSignalLogger(base_dir=signal_dir)
    for sig in signals:
        logger.log(sig)


def _sig(
    strategy: str,
    action: str,
    severity: str = "INFO",
    date: str | None = None,
) -> RetrainSignal:
    return RetrainSignal(
        date=date or datetime.now().strftime("%Y-%m-%d"),
        timestamp=datetime.now().isoformat(),
        strategy_name=strategy,
        action=action,
        severity=severity,
        rolling_ic=0.03,
        training_ic=0.035,
    )


class TestLoadWeightScales:
    def test_empty_history_returns_one(self, signal_dir: str) -> None:
        assert load_weight_scales(strategy_ids=["mom"], base_dir=signal_dir) == {"mom": 1.0}

    def test_no_signal_strategy_defaults_one(self, signal_dir: str) -> None:
        _log_signals(signal_dir, [_sig("mom", "NONE")])
        scales = load_weight_scales(strategy_ids=["mom", "other"], base_dir=signal_dir)
        assert scales["other"] == 1.0

    def test_reduce_weight_info_scales_to_half(self, signal_dir: str) -> None:
        _log_signals(signal_dir, [_sig("mom", "REDUCE_WEIGHT", "INFO")])
        scales = load_weight_scales(strategy_ids=["mom"], base_dir=signal_dir)
        assert scales["mom"] == 0.5

    def test_reduce_weight_warning_scales_harder(self, signal_dir: str) -> None:
        _log_signals(signal_dir, [_sig("mom", "REDUCE_WEIGHT", "WARNING")])
        scales = load_weight_scales(strategy_ids=["mom"], base_dir=signal_dir)
        assert scales["mom"] == 0.3

    def test_retire_zeroes(self, signal_dir: str) -> None:
        _log_signals(signal_dir, [_sig("mom", "RETIRE", "CRITICAL")])
        scales = load_weight_scales(strategy_ids=["mom"], base_dir=signal_dir)
        assert scales["mom"] == 0.0

    def test_schedule_retrain_mild_trim(self, signal_dir: str) -> None:
        _log_signals(signal_dir, [_sig("mom", "SCHEDULE_RETRAIN", "WARNING")])
        scales = load_weight_scales(strategy_ids=["mom"], base_dir=signal_dir)
        assert scales["mom"] == 0.85

    def test_latest_signal_wins(self, signal_dir: str) -> None:
        # NONE first, then REDUCE_WEIGHT → latest (REDUCE_WEIGHT) wins
        _log_signals(signal_dir, [_sig("mom", "NONE"), _sig("mom", "REDUCE_WEIGHT", "INFO")])
        scales = load_weight_scales(strategy_ids=["mom"], base_dir=signal_dir)
        assert scales["mom"] == 0.5

    def test_stale_signal_ignored(self, signal_dir: str) -> None:
        from datetime import timedelta

        stale = _sig("mom", "REDUCE_WEIGHT", "WARNING")
        stale.date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
        _log_signals(signal_dir, [stale])
        scales = load_weight_scales(strategy_ids=["mom"], base_dir=signal_dir)
        assert scales["mom"] == 1.0

    def test_real_default_dir_writes_to_disk(self) -> None:
        # Guard: the production default dir must remain the one
        # KillSwitchPipeline writes to.
        assert DEFAULT_RETRAIN_DIR == "data/monitoring"
