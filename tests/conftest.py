"""Shared pytest fixtures for QP tests."""

from __future__ import annotations

import importlib
import os
import tempfile
import warnings
from pathlib import Path

import pytest

_PRODUCTION_MONITORING_DIR = Path(__file__).resolve().parent.parent / "data" / "monitoring"
_PRODUCTION_FACTOR_VALUES = (
    Path(__file__).resolve().parent.parent / "data" / "dataset" / "factor_values_daily.parquet"
)

# Modules that bind monitoring paths at import time.  They are patched to a
# per-test temp dir so no test can touch the live scheduler's files.
# ``qp.pipeline.factor_calc_pipeline`` is included because FactorCalcPipeline
# writes data/dataset/factor_values_daily.parquet — the one production artifact
# a test managed to write (2026-09-26, see docs/tracking/qt_backlog_tracker.md).
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
    "qp.pipeline.factor_calc_pipeline",
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
        # FactorCalcPipeline's default write dir (bound at import from DATASET_DIR).
        "_DEFAULT_OUTPUT_DIR": target,
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


def _stat_fingerprint(path: Path) -> tuple[int, int] | None:
    """(size, mtime_ns) of a single production file, or None if absent."""
    if not path.is_file():
        return None
    st = path.stat()
    return (st.st_size, st.st_mtime_ns)


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
    """Backstop: catch a test session that modified live production artifacts.

    Isolation above should make this impossible; the guard exists to catch
    paths that are not enumerated there (e.g. newly added writers).

    ``data/dataset/factor_values_daily.parquet`` fails hard: only the daily
    pipeline and manual ``qp factor compute`` write it, so a test writing it is
    always a bug (2026-09-26, see docs/tracking/qt_backlog_tracker.md).
    """
    before = _production_fingerprint()
    before_fv = _stat_fingerprint(_PRODUCTION_FACTOR_VALUES)
    yield
    after_fv = _stat_fingerprint(_PRODUCTION_FACTOR_VALUES)
    if before_fv != after_fv:
        pytest.fail(
            f"a test wrote the live factor dataset {_PRODUCTION_FACTOR_VALUES} "
            f"(size/mtime {before_fv} → {after_fv}). Isolate the writer (tmp output_dir "
            "or stub the pipeline) instead of writing data/ — see "
            "docs/tracking/qt_backlog_tracker.md. If the scheduled qp-daily run overlapped "
            "this session, re-run the suite when it is idle.",
            pytrace=False,
        )
    after = _production_fingerprint()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed:
        # Concurrent writers are legitimate: the scheduler (09:07 / 16:53 /
        # 18:00 / 18:32) and manual `qp` commands both touch this directory.
        # Report what changed and when so the reader can tell a real leak
        # (a test writing production state) from a concurrent run.
        detail = ", ".join(
            f"{name} (mtime={after.get(name, (0, 0))[1] / 1e9:.0f})" for name in changed
        )
        warnings.warn(
            "data/monitoring changed during the pytest session: "
            + detail
            + " — if no scheduler job or manual `qp` command ran concurrently, a test is "
            "writing production state (docs/tracking/rolling_ic_false_stale.md §4.1 / P1-5).",
            stacklevel=1,
        )
