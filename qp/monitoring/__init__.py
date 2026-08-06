"""Monitoring Layer — observe only, never decide (ADR-030).

Exports:
  - KillSwitch + triggers (drawdown, portfolio, PSI, model decay)
  - DriftMonitor (feature + prediction distribution drift)
  - ModelDecayDetector (rolling IC degradation)
  - ModelDecayLifecycle (decay → strategy lifecycle bridge)
  - FactorHealthMonitor (per-factor IC + decay + crowding tracking)
  - MarketRegimeEngine (trend/ranging/volatility regime)
  - StrategyMonitor (signal frequency, turnover, drawdown tracking)
  - AlertManager + alert channels (Terminal, Log, Telegram)
"""

from qp.monitoring.alerts import (
    Alert,
    AlertManager,
    AlertSeverity,
    DingTalkAlert,
    EmailAlert,
    FileAlert,
    LogAlert,
    TelegramAlert,
    TerminalAlert,
    WeComAlert,
)
from qp.monitoring.drift import (
    DriftMonitor,
    DriftReport,
    DriftResult,
    DriftSeverity,
)
from qp.monitoring.factor_health import (
    FactorHealthMonitor,
    FactorHealthStage,
    FactorHealthStatus,
)
from qp.monitoring.factor_health_logger import FactorHealthLogger
from qp.monitoring.factor_health_pipeline import (
    FactorHealthPipeline,
    FactorHealthReport,
)
from qp.monitoring.health_logger import (
    HealthRecord,
    SystemHealthLogger,
)
from qp.monitoring.kill_switch import (
    AbnormalTurnoverTrigger,
    ConsecutiveLossTrigger,
    DrawdownTrigger,
    KillSwitch,
    KillSwitchLevel,
    KillSwitchResult,
    ModelDecayTrigger,
    PortfolioDrawdownTrigger,
    PSITrigger,
    WeeklyDrawdownTrigger,
)
from qp.monitoring.kill_switch_pipeline import (
    KillSwitchPipeline,
    MonitorAction,
    MonitorReport,
)
from qp.monitoring.model_decay import (
    DecayStage,
    DecayStatus,
    ModelDecayDetector,
)
from qp.monitoring.model_decay_lifecycle import (
    LifecycleAction,
    ModelDecayLifecycle,
)
from qp.monitoring.regime import (
    MarketRegimeEngine,
    Regime,
    RegimeResult,
)
from qp.monitoring.retrain_signal import (
    RetrainAction,
    RetrainSignal,
    RetrainSignalLogger,
    RetrainTrigger,
    evaluate_retrain_need,
)
from qp.monitoring.strategy_monitor import (
    HealthLevel,
    SignalRecord,
    StrategyHealth,
    StrategyMonitor,
)
from qp.monitoring.system_state import (
    StateTransition,
    SystemState,
    SystemStateManager,
)

__all__ = [
    # Kill switch
    "AbnormalTurnoverTrigger",
    # Alerts
    "Alert",
    "AlertManager",
    "AlertSeverity",
    "ConsecutiveLossTrigger",
    # Model decay
    "DecayStage",
    "DecayStatus",
    "DingTalkAlert",
    "DrawdownTrigger",
    # Drift
    "DriftMonitor",
    "DriftReport",
    "DriftResult",
    "DriftSeverity",
    "EmailAlert",
    "FactorHealthLogger",
    # Factor health
    "FactorHealthMonitor",
    "FactorHealthPipeline",
    "FactorHealthReport",
    "FactorHealthStage",
    "FactorHealthStatus",
    "FileAlert",
    # Strategy monitor
    "HealthLevel",
    # Health logger
    "HealthRecord",
    "KillSwitch",
    "KillSwitchLevel",
    "KillSwitchPipeline",
    "KillSwitchResult",
    "LifecycleAction",
    "LogAlert",
    # Market regime
    "MarketRegimeEngine",
    "ModelDecayDetector",
    "ModelDecayLifecycle",
    "ModelDecayTrigger",
    "MonitorAction",
    "MonitorReport",
    "PSITrigger",
    "PortfolioDrawdownTrigger",
    "Regime",
    "RegimeResult",
    # Retrain signal
    "RetrainAction",
    "RetrainSignal",
    "RetrainSignalLogger",
    "RetrainTrigger",
    "SignalRecord",
    # System state
    "StateTransition",
    "StrategyHealth",
    "StrategyMonitor",
    "SystemHealthLogger",
    "SystemState",
    "SystemStateManager",
    "TelegramAlert",
    "TerminalAlert",
    "WeComAlert",
    "WeeklyDrawdownTrigger",
    "evaluate_retrain_need",
]
