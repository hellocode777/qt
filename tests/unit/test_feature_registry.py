"""Tests for persisted FeatureRegistry (save/load/scan)."""

from __future__ import annotations

import polars as pl
import pytest

from qp.research.feature.registry import FeatureRegistry
from qp.shared.json_io import json_load
from qp.shared.protocols.base_feature import BaseFeature


class _DummyFeature(BaseFeature):
    """Minimal BaseFeature for registry tests."""

    @property
    def feature_name(self) -> str:
        return "Dummy_Test"

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        raise NotImplementedError  # not used in registry tests

    version = "1.0.0"  # type: ignore[assignment]
    category = "Custom"  # type: ignore[assignment]
    direction = 1  # type: ignore[assignment]


def test_register_sets_version_map() -> None:
    registry = FeatureRegistry()
    registry.register(_DummyFeature())
    assert registry.list_features() == ["Dummy_Test"]
    assert registry._version_map["Dummy_Test"] == "1.0.0"


def test_duplicate_register_raises() -> None:
    registry = FeatureRegistry()
    registry.register(_DummyFeature())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_DummyFeature())


def test_save_load_roundtrip(tmp_path) -> None:
    registry = FeatureRegistry()
    registry.register(_DummyFeature())
    path = str(tmp_path / "factor_registry.json")
    registry.save(path, direction_overrides={"Dummy_Test": -1})

    loaded = FeatureRegistry.load_from_json(path)
    assert loaded.list_features() == ["Dummy_Test"]
    assert loaded._version_map["Dummy_Test"] == "1.0.0"
    # direction override persisted
    payload = json_load(path)
    assert payload["factors"]["Dummy_Test"]["direction"] == -1


def test_scan_finds_production_factors() -> None:
    registry = FeatureRegistry()
    classes = registry.scan_feature_classes()
    names = {cls().feature_name for cls in classes}
    # Spot-check a few production factors across modules
    assert "Momentum_3M" in names
    assert "Volatility_20D" in names
    assert "Volume_Trend_10D" in names
    assert "ROE_Level" in names
