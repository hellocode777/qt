"""Custom exception classes for the QP platform.

All exceptions inherit from QPError to allow unified error handling.
No bare `except:` is allowed — always catch specific exception types.
"""


class QPError(Exception):
    """Base exception for all QP platform errors."""


# ── Configuration ──────────────────────────────────


class ConfigError(QPError):
    """Configuration loading or validation error."""


class ConfigNotFoundError(ConfigError):
    """Configuration file not found."""


class ConfigValidationError(ConfigError):
    """Configuration value is invalid."""


class FrozenConfigError(ConfigError):
    """Attempted to modify a frozen configuration."""


# ── Data ───────────────────────────────────────────


class DataError(QPError):
    """Base exception for Data Layer errors."""


class DataValidationError(DataError):
    """Data failed schema or quality validation."""


class DataContractError(DataError):
    """Data does not satisfy its contract."""


class DatasetNotFoundError(DataError):
    """Requested dataset or version not found."""


class DataSourceError(DataError):
    """Error fetching data from an external source."""


# ── Pipeline ───────────────────────────────────────


class PipelineError(QPError):
    """Base exception for Pipeline execution errors."""


class PipelineConfigError(PipelineError):
    """Pipeline configuration is invalid."""


class PipelineTimeoutError(PipelineError):
    """Pipeline execution timed out."""


# ── Architecture ───────────────────────────────────


class LayerViolationError(QPError):
    """A cross-layer dependency or shortcut was detected."""


class RuntimeStateError(QPError):
    """Invalid Runtime state transition or operation."""


# ── Validation ─────────────────────────────────────


class ValidationError(QPError):
    """Base exception for Validation Layer errors."""


class ValidationGateError(ValidationError):
    """Strategy failed to pass the Validation Gate."""


# ── Portfolio / Decision ───────────────────────────


class PortfolioError(QPError):
    """Base exception for Portfolio Layer errors."""


class InsufficientCashError(PortfolioError):
    """Account cash is insufficient to open a position (ADR-032)."""

    def __init__(self, symbol: str = "", required: float = 0.0, available: float = 0.0) -> None:
        self.symbol = symbol
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient cash: need ¥{required:,.0f} for {symbol}, have ¥{available:,.0f}"
        )


# ── Research ───────────────────────────────────────


class ResearchError(QPError):
    """Base exception for Research Layer errors."""


class ExperimentError(ResearchError):
    """Experiment is misconfigured or failed."""


class ModelError(ResearchError):
    """Model training or inference error."""


class PurgedCVError(ResearchError):
    """Error in Purged Cross-Validation setup."""


__all__ = [
    "ConfigError",
    "ConfigNotFoundError",
    "ConfigValidationError",
    "DataContractError",
    "DataError",
    "DataSourceError",
    "DataValidationError",
    "DatasetNotFoundError",
    "ExperimentError",
    "FrozenConfigError",
    "InsufficientCashError",
    "LayerViolationError",
    "ModelError",
    "PipelineConfigError",
    "PipelineError",
    "PipelineTimeoutError",
    "PortfolioError",
    "PurgedCVError",
    "QPError",
    "ResearchError",
    "RuntimeStateError",
    "ValidationError",
    "ValidationGateError",
]
