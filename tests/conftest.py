"""Shared pytest fixtures for QP tests."""

from __future__ import annotations

import importlib
import os
import tempfile
import warnings
from pathlib import Path

import pytest

_PRODUCTION_MONITORING_DIR = Path(__file__).resolve().parent.parent / "data" / "monitoring"

# Modules that bind monitoring paths at import time.  They are patched to a
# per-test temp dir so no test can touch the live scheduler's files.
_MONITORING_MODULES = (
    "qp.shared.paths",
    "qp.monitoring.system_state",
    "qp.monitoring.online_monitor",
    "qp.monitoring.health_logger",
    "qp.monitoring.factor_health_logger",
    "qp.monitoring.retrain_signal",
    "qp.monitoring.strategy_health_logger",
    "qp.monitoring.strategy_monitor",
    "qp.monitoring.kill_switch_pipeline",
)


def _monitoring_overrides(target: Path) -> dict[str, object]:
    """Attribute name → replacement value for a redirected monitoring dir."""
    return {
        "MONITORING_DIR": target,
        "ONLINE_SIGNAL_HISTORY": target / "online_signal_history.parquet",
        "SYSTEM_HEALTH_LOG": target / "system_health_log.parquet",
        "WATCHDOG_DIR": target / "watchdog",
        "DEFAULT_STATE_DIR": target,
        "DEFAULT_HEALTH_LOG_DIR": target,
        "DEFAULT_FACTOR_HEALTH_DIR": target,
        "DEFAULT_RETRAIN_DIR": target,
        "HEALTH_PARQUET": target / "strategy_health.parquet",
        "_ONLINE_SIGNAL_PARQUET": target / "online_signal_history.parquet",
        "_ONLINE_HEALTH_PARQUET": target / "online_health_history.parquet",
    }


def _production_fingerprint() -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) per file in the live monitoring dir."""
    if not _PRODUCTION_MONITORING_DIR.is_dir():
        return {}
    return {
        str(p.relative_to(_PRODUCTION_MONITORING_DIR)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(_PRODUCTION_MONITORING_DIR.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(autouse=True)
def _isolate_strategy_registry(monkeypatch: pytest.MonkeyPatch):  # type: ignore[reportInvalidTypeForm]
    """Redirect StrategyRegistry persistence to a temp file for test isolation.

    Without this, tests share ``data/strategy_registry.json`` and state
    leaks between test runs (e.g. momentum_vol_full from production
    pollutes unit-test assertions).
    """
    fd, tmp_name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    tmp_path = Path(tmp_name)
    monkeypatch.setattr("qp.strategy.registry._REGISTRY_FILE", tmp_path)
    yield
    tmp_path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _isolate_monitoring_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[reportInvalidTypeForm]
    """Redirect every monitoring writer/reader to a per-test temp directory.

    ``data/monitoring/*`` is owned by the live scheduler.  Without isolation a
    unit test that runs ``KillSwitchPipeline()`` wrote the real
    ``system_state.parquet`` — on 2026-09-11 a pytest run cleared the state
    from WARNING to NORMAL (docs/tracking/rolling_ic_false_stale.md §4.1).

    Only module-level path constants are patched: the logger/state classes
    resolve their default directory at call time, so modules that imported the
    class in advance are covered as well.
    """
    overrides = _monitoring_overrides(tmp_path)
    for mod_name in _MONITORING_MODULES:
        try:
            module = importlib.import_module(mod_name)
        except ImportError:  # pragma: no cover - optional module
            continue
        for attr, value in overrides.items():
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, value)
    yield


@pytest.fixture(scope="session", autouse=True)
def _guard_production_monitoring():
    """Backstop: warn if the test session modified the live monitoring dir.

    Isolation above should make this impossible; the guard exists to catch
    paths that are not enumerated there (e.g. newly added writers).
    """
    before = _production_fingerprint()
    yield
    after = _production_fingerprint()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed:
        warnings.warn(
            "pytest modified the live data/monitoring directory: " + ", ".join(changed),
            stacklevel=1,
        )
