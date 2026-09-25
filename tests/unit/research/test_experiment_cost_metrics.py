# pyright: reportArgumentType=false, reportReturnType=false
"""Tests for experiment cost metrics persistence (total_cost / final_equity)."""

import json

import pytest

from qp.research.experiment.models import ExperimentMetrics
from qp.research.experiment.tracker import ExperimentTracker


def test_experiment_metrics_roundtrip_total_cost() -> None:
    """ExperimentMetrics 序列化往返保留 total_cost / final_equity。"""
    m = ExperimentMetrics(
        experiment_id="test_roundtrip",
        ic_mean=0.0845,
        sharpe_ratio=1.99,
        total_return_pct=118.4,
        turnover_pct=1717.24,
        total_cost=11009.0,
        final_equity=218400.0,
    )
    d = m.to_dict()
    assert d["total_cost"] == 11009.0
    assert d["final_equity"] == 218400.0
    # JSON 可序列化
    json.dumps(d)


def test_tracker_persists_total_cost(tmp_path) -> None:
    """tracker.log_experiment 落盘后 JSON 含 total_cost / final_equity。"""
    from pathlib import Path

    tracker = ExperimentTracker(base_dir=str(tmp_path))
    tracker.log_experiment(
        experiment_id="test_cost_persist",
        config={
            "strategy_name": "momentum_vol_full",
            "model_mode": False,
            "description": "cost persistence test",
            "dataset_version": "daily_price_latest@2024-01-01_2026-08-05",
            "features": ["Amplitude_5D"],
            "model_params": {"Amplitude_5D": -0.25},
            "train_start": "2024-01-01",
            "train_end": "2026-08-05",
            "tags": ["test"],
        },
        metrics={
            "ic_mean": 0.0845,
            "ic_ir": 0.59,
            "sharpe_ratio": 1.99,
            "max_drawdown_pct": 9.21,
            "total_return_pct": 118.4,
            "excess_return_pct": 56.33,
            "annual_return_pct": 52.7,
            "annual_volatility_pct": 26.48,
            "turnover_pct": 1717.24,
            "total_cost": 11009.0,
            "final_equity": 218400.0,
            "n_days": 465,
        },
        lineage_graph={
            "dataset": "daily_price_latest@2024-09-01",
            "model_algo": "weighted_linear",
            "strategy_id": "multifactor_top10",
        },
    )
    # 读取落盘 JSON
    files = list(Path(tmp_path).glob("*.json"))
    assert files, "实验 JSON 未落盘"
    data = json.loads(files[0].read_text())
    met = data["metrics"]
    assert met["total_cost"] == 11009.0
    assert met["final_equity"] == 218400.0


def test_tracker_load_roundtrip_total_cost(tmp_path) -> None:
    """tracker 加载路径保留 total_cost（283 行反序列化分支）。"""

    tracker = ExperimentTracker(base_dir=str(tmp_path))
    tracker.log_experiment(
        experiment_id="test_cost_load",
        config={
            "strategy_name": "momentum_vol_full",
            "dataset_version": "daily_price_latest@2024-01-01_2026-08-05",
            "features": ["Amplitude_5D"],
            "model_params": {"Amplitude_5D": -0.25},
        },
        metrics={
            "total_cost": 2450.0,
            "final_equity": 148346.0,
            "turnover_pct": 492.31,
        },
        lineage_graph={"dataset": "daily_price_latest@2024-01-01", "strategy_id": "x"},
    )
    loaded = tracker.get("test_cost_load")
    assert loaded is not None
    assert loaded.metrics.total_cost == 2450.0
    assert loaded.metrics.final_equity == 148346.0


# ── 门禁指标生产者（2026-09-25）：net / 成本占比 / 日均换手 / 中性化前后 IC ──
_GATE_METRICS: dict[str, object] = {
    "ic_mean": 0.0845,
    "sharpe_ratio": 1.81,
    "max_drawdown_pct": 8.77,
    "sharpe_ratio_net": 1.81,
    "max_drawdown_pct_net": 8.77,
    "total_cost_pct": 3.33,
    "daily_turnover_pct": 3.73,
    "pre_neutralization_ic": 0.0912,
    "post_neutralization_ic": 0.0845,
}


def _log_gate_metrics(tracker: object, experiment_id: str) -> None:
    tracker.log_experiment(  # type: ignore[attr-defined]
        experiment_id=experiment_id,
        config={
            "strategy_name": "momentum_vol_full",
            "dataset_version": "daily_price_latest@2025-09-05_2026-08-31",
            "features": ["Amplitude_5D", "Volatility_20D"],
            "model_params": {"Amplitude_5D": -0.25, "Volatility_20D": 0.22},
        },
        metrics=dict(_GATE_METRICS)
        | {"feature_importance": {"Amplitude_5D": 0.531915, "Volatility_20D": 0.468085}},
        lineage_graph={"dataset": "daily_price_latest@2025-09-05", "strategy_id": "x"},
    )


def test_gate_metrics_persist_and_reload(tmp_path) -> None:
    """门禁指标落盘 + 回读保留（含 feature_importance dict）。"""
    from pathlib import Path

    tracker = ExperimentTracker(base_dir=str(tmp_path))
    _log_gate_metrics(tracker, "test_gate_metrics")

    data = json.loads(next(Path(tmp_path).glob("*.json")).read_text())
    met = data["metrics"]
    for key, value in _GATE_METRICS.items():
        assert met[key] == value, f"{key} 未落盘"
    assert met["feature_importance"] == {"Amplitude_5D": 0.531915, "Volatility_20D": 0.468085}

    loaded = tracker.get("test_gate_metrics")
    assert loaded is not None
    assert loaded.metrics.sharpe_ratio_net == 1.81
    assert loaded.metrics.total_cost_pct == 3.33
    assert loaded.metrics.daily_turnover_pct == 3.73
    assert loaded.metrics.pre_neutralization_ic == 0.0912
    assert loaded.metrics.post_neutralization_ic == 0.0845
    assert loaded.metrics.feature_importance["Amplitude_5D"] == 0.531915


def test_legacy_record_without_gate_metrics_still_loads(tmp_path) -> None:
    """历史实验 JSON（无新字段）仍能加载，新字段取默认 0/空 —— 不因加字段而读不了旧记录。"""
    import json as _json
    from pathlib import Path

    tracker = ExperimentTracker(base_dir=str(tmp_path))
    _log_gate_metrics(tracker, "test_legacy_trim")
    path = next(Path(tmp_path).glob("*.json"))
    raw = _json.loads(path.read_text())
    for key in (
        "sharpe_ratio_net",
        "max_drawdown_pct_net",
        "total_cost_pct",
        "daily_turnover_pct",
        "pre_neutralization_ic",
        "post_neutralization_ic",
        "feature_importance",
    ):
        raw["metrics"].pop(key, None)
    path.write_text(_json.dumps(raw, ensure_ascii=False))

    reloaded = ExperimentTracker(base_dir=str(tmp_path))
    old = reloaded.get("test_legacy_trim")
    assert old is not None
    assert old.metrics.sharpe_ratio == 1.81  # 老字段照旧
    assert old.metrics.sharpe_ratio_net == 0.0
    assert old.metrics.total_cost_pct == 0.0
    assert old.metrics.pre_neutralization_ic == 0.0
    assert old.metrics.feature_importance == {}


def test_normalized_importance_sums_to_one_and_sorted() -> None:
    """线性权重 → 归一化重要性：|权重| 占比、降序、和为 1。"""
    from qp.pipeline.multifactor_pipeline import _normalized_importance

    result = _normalized_importance({"A": -0.25, "B": 0.15, "C": 0.10})
    assert list(result) == ["A", "B", "C"]
    assert sum(result.values()) == pytest.approx(1.0)
    assert result["A"] == pytest.approx(0.5)

    assert _normalized_importance({}) == {}
    assert _normalized_importance({"A": 0.0}) == {}


def test_max_score_diff_detects_identical_vs_changed() -> None:
    """实证闸：两版分数完全相同 → 0.0（中性化没生效，不该落盘 pre/post）。"""
    import polars as pl

    from qp.pipeline.multifactor_pipeline import _max_score_diff

    base = pl.DataFrame(
        {
            "trade_date": ["2026-08-03", "2026-08-03", "2026-08-04"],
            "symbol": ["600000", "600001", "600000"],
            "score": [0.5, -0.2, 0.1],
        }
    )
    same = base.clone()
    changed = base.with_columns(
        pl.when(pl.col("symbol") == "600001")
        .then(pl.col("score") + 2.0)
        .otherwise(pl.col("score"))
        .alias("score")
    )

    assert _max_score_diff(base, same) == 0.0
    assert _max_score_diff(base, changed) == pytest.approx(2.0)
    # 空表 / 无交集 → 视为"没差异"（不落盘，而不是报错）
    assert _max_score_diff(base, base.head(0)) == 0.0
