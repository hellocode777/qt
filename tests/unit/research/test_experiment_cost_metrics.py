# pyright: reportArgumentType=false, reportReturnType=false
"""Tests for experiment cost metrics persistence (total_cost / final_equity)."""

import json

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
