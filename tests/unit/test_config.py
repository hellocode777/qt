"""Tests for the Configuration System."""

import pytest

from qp.platform.config.defaults import build_default_config
from qp.platform.config.loader import load_config
from qp.platform.config.validator import ConfigValidationError, validate_config
from qp.shared.exceptions import FrozenConfigError


class TestConfigDefaults:
    """Test default configuration values."""

    def test_build_default_config(self) -> None:
        config = build_default_config()
        assert config.project.name == "qp"
        assert config.storage.backend == "duckdb"
        assert config.logging.level == "INFO"
        assert config.model.learning_rate == 0.05
        assert config.monitoring.psi_threshold == 0.25

    def test_load_config_with_defaults(self) -> None:
        config = load_config()
        assert config.project.name == "qp"
        assert config.runtime.env == "development"


class TestConfigFreeze:
    """Test configuration freezing."""

    def test_config_is_frozen_after_load(self) -> None:
        config = load_config()
        assert config.is_frozen is True
        # Sub-models are also frozen
        assert config.project.is_frozen is True

    def test_cannot_modify_frozen_config(self) -> None:
        config = load_config()
        with pytest.raises(FrozenConfigError):
            config.project.name = "hacked"

    def test_cannot_modify_nested_frozen_config(self) -> None:
        config = load_config()
        with pytest.raises(FrozenConfigError):
            config.model.num_leaves = 999

    def test_cannot_delete_frozen_attribute(self) -> None:
        config = load_config()
        with pytest.raises(FrozenConfigError):
            del config.project.name


class TestConfigValidation:
    """Test configuration validation."""

    def test_invalid_storage_backend(self) -> None:
        config = build_default_config()
        config.storage.backend = "invalid"
        with pytest.raises(ConfigValidationError, match="storage.backend"):
            validate_config(config)

    def test_invalid_log_level(self) -> None:
        config = build_default_config()
        config.logging.level = "TRACE"
        with pytest.raises(ConfigValidationError, match="logging.level"):
            validate_config(config)

    def test_invalid_num_leaves(self) -> None:
        config = build_default_config()
        config.model.num_leaves = 1
        with pytest.raises(ConfigValidationError, match="num_leaves"):
            validate_config(config)

    def test_invalid_feature_fraction(self) -> None:
        config = build_default_config()
        config.model.feature_fraction = 1.5
        with pytest.raises(ConfigValidationError, match="feature_fraction"):
            validate_config(config)
