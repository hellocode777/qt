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
    ic_mean: float = 0.0
    # ── 2026-09-25 新增的门禁指标（默认 0/空 = 未测）──
    sharpe_ratio_net: float = 0.0
    max_drawdown_pct_net: float = 0.0
    total_cost_pct: float = 0.0
    daily_turnover_pct: float = 0.0
    pre_neutralization_ic: float = 0.0
    post_neutralization_ic: float = 0.0
    feature_importance: dict[str, float] = field(default_factory=dict)
    custom: dict[str, Any] = field(default_factory=dict)


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
    assert "feature_importance" not in ctx.metadata


def test_build_context_feeds_measured_cost_metrics() -> None:
    """实测过的 net/成本/换手才进 ctx：门禁据此不再走"缺数据"分支。"""
    from qp.platform.cli.commands.validate import _build_context

    record = _Record(
        metrics=_Metrics(
            sharpe_ratio_net=1.81,
            max_drawdown_pct_net=8.77,
            total_cost_pct=3.33,
            daily_turnover_pct=3.73,
        )
    )
    ctx = _build_context(record, feature_df=None, price_df=None)

    assert ctx.backtest_metrics["sharpe_ratio_net"] == pytest.approx(1.81)
    assert ctx.backtest_metrics["max_drawdown_pct_net"] == pytest.approx(8.77)
    assert ctx.backtest_metrics["total_cost_pct"] == pytest.approx(3.33)
    assert ctx.backtest_metrics["daily_turnover_pct"] == pytest.approx(3.73)


def test_build_context_feature_importance_sorted_desc() -> None:
    """feature_importance dict → [feature, gain] 表且按 gain 降序（检查项取 gains[0] 为 top1）。"""
    from qp.platform.cli.commands.validate import _build_context

    record = _Record(
        metrics=_Metrics(feature_importance={"Volatility_20D": 0.22, "Amplitude_5D": 0.25})
    )
    ctx = _build_context(record, feature_df=None, price_df=None)

    fi = ctx.metadata["feature_importance"]
    assert fi.columns == ["feature", "gain"]
    assert fi["feature"].to_list() == ["Amplitude_5D", "Volatility_20D"]
    assert fi["gain"].to_list() == [pytest.approx(0.25), pytest.approx(0.22)]


def test_build_context_overfit_maps_ic_mean_and_cv_oos() -> None:
    """过拟合项：全期 IC(in-sample) vs Purged-CV OOS IC，并标注来源口径。"""
    from qp.platform.cli.commands.validate import _build_context

    record = _Record(metrics=_Metrics(ic_mean=0.077, custom={"cv_oos_ic_mean": 0.069}))
    ctx = _build_context(record, feature_df=None, price_df=None)

    assert ctx.metadata["in_sample_ic"] == pytest.approx(0.077)
    assert ctx.metadata["out_of_sample_ic"] == pytest.approx(0.069)
    assert "cv_oos_ic_mean" in ctx.metadata["ic_source"]


def test_build_context_omits_overfit_when_cv_missing() -> None:
    """没有 CV OOS 就照旧不评估 —— 不拿"全期 IC vs 0"编造过拟合结论。"""
    from qp.platform.cli.commands.validate import _build_context

    record = _Record(metrics=_Metrics(ic_mean=0.077))
    ctx = _build_context(record, feature_df=None, price_df=None)

    assert "in_sample_ic" not in ctx.metadata
    assert "out_of_sample_ic" not in ctx.metadata


def test_build_context_neutralization_needs_both_ends() -> None:
    """只有一个端点不能算"中性化前后"，宁可不评估。"""
    from qp.platform.cli.commands.validate import _build_context

    only_post = _Record(metrics=_Metrics(post_neutralization_ic=0.077))
    ctx = _build_context(only_post, feature_df=None, price_df=None)
    assert "post_neutralization_ic" not in ctx.metadata

    both = _Record(metrics=_Metrics(pre_neutralization_ic=0.10, post_neutralization_ic=0.077))
    ctx2 = _build_context(both, feature_df=None, price_df=None)
    assert ctx2.metadata["pre_neutralization_ic"] == pytest.approx(0.10)
    assert ctx2.metadata["post_neutralization_ic"] == pytest.approx(0.077)
