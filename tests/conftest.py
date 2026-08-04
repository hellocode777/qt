"""Shared pytest fixtures for QP tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_strategy_registry(monkeypatch: pytest.MonkeyPatch) -> None:
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
