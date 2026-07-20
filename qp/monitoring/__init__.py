"""Monitoring Layer — observe only, never decide (ADR-030).

Exports:
  - KillSwitch + triggers (drawdown, portfolio, PSI)
  - DriftMonitor (feature + prediction distribution drift)
  - ModelDecayDetector (rolling IC degradation)
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
from qp.monitoring.kill_switch import (
    DrawdownTrigger,
    KillSwitch,
    KillSwitchResult,
    PortfolioDrawdownTrigger,
    PSITrigger,
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
from qp.monitoring.regime import (
    MarketRegimeEngine,
    Regime,
    RegimeResult,
)
from qp.monitoring.strategy_monitor import (
    HealthLevel,
    SignalRecord,
    StrategyHealth,
    StrategyMonitor,
)

__all__ = [
    # Alerts
    "Alert",
    "AlertManager",
    "AlertSeverity",
    "DingTalkAlert",
    "EmailAlert",
    "FileAlert",
    "LogAlert",
    "TelegramAlert",
    "TerminalAlert",
    "WeComAlert",
    # Kill switch
    "KillSwitch",
    "KillSwitchPipeline",
    "KillSwitchResult",
    "DrawdownTrigger",
    "MonitorAction",
    "MonitorReport",
    "PortfolioDrawdownTrigger",
    "PSITrigger",
    # Drift
    "DriftMonitor",
    "DriftReport",
    "DriftResult",
    "DriftSeverity",
    # Model decay
    "DecayStage",
    "DecayStatus",
    "ModelDecayDetector",
    # Market regime
    "MarketRegimeEngine",
    "Regime",
    "RegimeResult",
    # Strategy monitor
    "HealthLevel",
    "SignalRecord",
    "StrategyHealth",
    "StrategyMonitor",
]
