"""`qp validate` 的指标来源：必须来自真实实验记录。

背景（2026-09-25）：``cmd_validate()`` 曾把 ``ctx.backtest_metrics`` 写死成
`{"sharpe_ratio": 0.88, ...}`，于是门禁分数是在常量上算出来的。
现在指标一律来自 ``ExperimentTracker``；找不到可用实验就报错，不用占位值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from qp.platform.cli.commands.validate import _load_experiment_record

_NOW = datetime(2026, 9, 1, 2, 5, 20, tzinfo=UTC)


@dataclass
class _Config:
    experiment_id: str = "mf_x"
    strategy_name: str = "momentum_vol_full"
    created_at: datetime = _NOW
    train_start: str = "2025-09-05"
    train_end: str = "2026-08-31"


@dataclass
class _Metrics:
    n_days: int = 238
    sharpe_ratio: float = 1.6
    max_drawdown_pct: float = 16.93
    total_return_pct: float = 33.95
    in_sample_ic: float = 0.0
    out_of_sample_ic: float = 0.0


@dataclass
class _Record:
    config: _Config = field(default_factory=_Config)
    metrics: _Metrics = field(default_factory=_Metrics)


class _StubTracker:
    def __init__(self, records: list[_Record], by_id: dict[str, _Record] | None = None) -> None:
        self._records = records
        self._by_id = by_id or {}

    def list_experiments(self, status: Any = None, tag: Any = None) -> list[_Record]:
        return list(self._records)

    def get(self, experiment_id: str) -> _Record | None:
        return self._by_id.get(experiment_id)


def _patch_tracker(monkeypatch: Any, stub: _StubTracker) -> None:
    import qp.research.experiment.tracker as tracker_module

    monkeypatch.setattr(tracker_module, "ExperimentTracker", lambda *a, **k: stub)


def test_picks_newest_experiment_for_strategy(monkeypatch: Any) -> None:
    newest = _Record(_Config(experiment_id="mf_new", strategy_name="momentum_vol_full"))
    older = _Record(_Config(experiment_id="mf_old", strategy_name="momentum_vol_full"))
    other = _Record(_Config(experiment_id="mf_other", strategy_name="lvr_vol_only"))
    # list_experiments() 契约：newest first
    _patch_tracker(monkeypatch, _StubTracker([newest, older, other]))

    record, reason = _load_experiment_record("momentum_vol_full", "")

    assert reason == ""
    assert record is not None and record.config.experiment_id == "mf_new"


def test_errors_when_strategy_has_no_experiment(monkeypatch: Any) -> None:
    _patch_tracker(
        monkeypatch,
        _StubTracker([_Record(_Config(strategy_name="lvr_vol_only"))]),
    )

    record, reason = _load_experiment_record("momentum_vol_full", "")

    assert record is None
    assert "没有 'momentum_vol_full' 的实验记录" in reason
    assert "--experiment" in reason  # 提示出路


def test_explicit_experiment_id_is_used(monkeypatch: Any) -> None:
    wanted = _Record(_Config(experiment_id="mf_pickme", strategy_name="lvr_vol_only"))
    _patch_tracker(monkeypatch, _StubTracker([], by_id={"mf_pickme": wanted}))

    record, reason = _load_experiment_record("momentum_vol_full", "mf_pickme")

    assert reason == ""
    assert record is not None and record.config.experiment_id == "mf_pickme"


def test_errors_when_explicit_experiment_missing(monkeypatch: Any) -> None:
    _patch_tracker(monkeypatch, _StubTracker([], by_id={}))

    record, reason = _load_experiment_record("momentum_vol_full", "nope")

    assert record is None
    assert "实验不存在" in reason


def test_errors_when_experiment_has_no_backtest(monkeypatch: Any) -> None:
    """n_days=0 = 没跑过回测 → 不能拿全 0 的指标去跑门禁。"""
    no_bt = _Record(metrics=_Metrics(n_days=0, sharpe_ratio=0.0, max_drawdown_pct=0.0))
    _patch_tracker(monkeypatch, _StubTracker([no_bt]))

    record, reason = _load_experiment_record("momentum_vol_full", "")

    assert record is None
    assert "没有回测结果" in reason


def test_build_context_omits_unmeasured_metrics(monkeypatch: Any) -> None:
    """没被实测的键一律不塞占位值（net/turnover/total_cost 都不进 ctx）。"""
    from qp.platform.cli.commands.validate import _build_context

    record = _Record()
    ctx = _build_context(record, feature_df=None, price_df=None)

    assert ctx.backtest_metrics == {
        "sharpe_ratio": pytest.approx(1.6),
        "max_drawdown_pct": pytest.approx(16.93),
        "total_return_pct": pytest.approx(33.95),
    }
    assert "sharpe_ratio_net" not in ctx.backtest_metrics
    assert "total_cost_pct" not in ctx.backtest_metrics
    assert ctx.metadata["train_start"] == "2025-09-05"
    assert ctx.metadata["train_end"] == "2026-08-31"
    # in/out-of-sample IC 默认 0.0（未计算）→ 不塞进 metadata
    assert "in_sample_ic" not in ctx.metadata
