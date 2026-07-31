"""Type definitions and enumerations shared across layers."""

from enum import Enum


class RuntimeState(Enum):
    """QP Runtime lifecycle states (see ADR-012)."""

    CREATED = 1
    INITIALIZING = 2
    READY = 3
    RUNNING = 4
    STOPPING = 5
    TERMINATED = 6
    FAILED = 7


class PipelineStatus(Enum):
    """Outcome of a Pipeline run."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class PositionState(Enum):
    """Position lifecycle state machine (see rule.md §5.2)."""

    IDEA = 1
    CANDIDATE = 2
    APPROVED = 3
    HOLDING = 4
    REDUCING = 5
    CLOSED = 6
    ARCHIVED = 7


class OrderSide(Enum):
    """Buy or sell side of an order."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order execution status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class StrategyLifecycle(Enum):
    """Strategy lifecycle states (see rule.md §5.1)."""

    RESEARCH = "research"
    BACKTEST_PASSED = "backtest_passed"
    PAPER_TRADING = "paper_trading"
    SHADOW_PRODUCTION = "shadow_production"
    PRODUCTION = "production"
    WARNING = "warning"
    KILL_SWITCH = "kill_switch"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class ExperimentStatus(Enum):
    """Experiment lifecycle states."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    REGISTERED = "registered"
    VALIDATED = "validated"
    ARCHIVED = "archived"
    FAILED = "failed"


class MarketRegime(Enum):
    """Market regime classification."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


class ValidationStatus(Enum):
    """Validation gate result."""

    PASS = "pass"
    FAIL = "fail"


class DataTier(Enum):
    """Data processing tiers (Bronze → Silver → Gold)."""

    RAW = "raw"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class RebalanceSchedule(Enum):
    """Strategy rebalance frequency.

    Used by StrategyRunner to determine which strategies should run
    on a given trading day. See docs/6_Strategy_Engine.md §模块二.
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class ProposalStatus(Enum):
    """Strategy proposal workflow states."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


__all__ = [
    "ProposalStatus",
    "RuntimeState",
    "PipelineStatus",
    "PositionState",
    "OrderSide",
    "OrderStatus",
    "StrategyLifecycle",
    "ExperimentStatus",
    "MarketRegime",
    "ValidationStatus",
    "DataTier",
    "RebalanceSchedule",
]
