"""StrategyHealthReport — actionable strategy health assessment for Decision Layer.

Converts raw StrategyHealth metrics into a structured report with:
  - Health trend analysis (improving / stable / declining)
  - Signal quality assessment
  - Actionable recommendation: HEALTHY / NEEDS_RETRAIN / NOT_APPROVED

This bridges monitoring (Layer 9, observe-only) to strategy (Layer 5) and
decision (Layer 8) by telling the Decision Layer whether each strategy is
currently trustworthy.

Usage:
    from qp.monitoring.strategy_health_report import (
        StrategyHealthReport, HealthRecommendation,
    )
    report = StrategyHealthReport.from_health(health, history=[...])
    print(report.recommendation.value)  # "healthy"
    print(report.to_markdown())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth


class HealthRecommendation(StrEnum):
    """What the Decision Layer should do with this strategy."""

    HEALTHY = "healthy"  # 健康 — 正常使用
    NEEDS_RETRAIN = "needs_retrain"  # 需重训 — 降低权重或暂停使用
    NOT_APPROVED = "not_approved"  # 不可用 — 不应参与决策


def _compute_recommendation(
    health: StrategyHealth,
    trend: str,
) -> HealthRecommendation:
    """Determine the recommendation based on health score, level, and trend.

    Rules:
      - CRITICAL level → NOT_APPROVED
      - WARNING level + declining trend → NOT_APPROVED
      - WARNING level + stable/improving → NEEDS_RETRAIN
      - HEALTHY/WATCH but declining trend → NEEDS_RETRAIN
      - HEALTHY/WATCH + stable/improving → HEALTHY
      - Score < 20 → NOT_APPROVED regardless
    """
    if health.health_level == HealthLevel.CRITICAL:
        return HealthRecommendation.NOT_APPROVED
    if health.health_score < 20:
        return HealthRecommendation.NOT_APPROVED
    if health.health_level == HealthLevel.WARNING:
        if trend == "declining":
            return HealthRecommendation.NOT_APPROVED
        return HealthRecommendation.NEEDS_RETRAIN
    if trend == "declining" and health.health_score < 70:
        return HealthRecommendation.NEEDS_RETRAIN
    return HealthRecommendation.HEALTHY


def _compute_trend(history: list[StrategyHealth]) -> str:
    """Compute trend from historical health scores.

    Uses linear regression on recent scores. Returns:
      - "improving": slope > 1
      - "stable": -1 <= slope <= 1
      - "declining": slope < -1
      - "unknown": fewer than 2 data points
    """
    if len(history) < 2:
        return "unknown"

    scores = [h.health_score for h in history[-10:]]  # Last 10 observations
    n = len(scores)
    if n < 2:
        return "unknown"

    # Simple linear regression slope
    x_mean = (n - 1) / 2
    y_mean = sum(scores) / n
    numerator = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return "stable"

    slope = numerator / denominator

    if slope > 1:
        return "improving"
    if slope < -1:
        return "declining"
    return "stable"


@dataclass
class StrategyHealthReport:
    """Actionable strategy health report for the Decision Layer.

    Answers: "Is this strategy healthy enough to trust its signals today?"

    Attributes:
        strategy_id: Which strategy.
        recommendation: HEALTHY / NEEDS_RETRAIN / NOT_APPROVED.
        health_score: Current health score (0-100).
        health_level: Current health level.
        trend: Health score trend (improving / stable / declining / unknown).
        signal_summary: Summary of signal generation health.
        alerts: Active alerts from StrategyHealth.
        details: Additional analysis details.
    """

    strategy_id: str = ""
    recommendation: HealthRecommendation = HealthRecommendation.HEALTHY
    health_score: float = 100.0
    health_level: str = "healthy"
    trend: str = "unknown"
    signal_summary: str = ""
    alerts: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_health(
        cls,
        health: StrategyHealth,
        history: list[StrategyHealth] | None = None,
    ) -> StrategyHealthReport:
        """Build a report from a StrategyHealth snapshot.

        Args:
            health: Current health snapshot.
            history: Optional historical health records for trend analysis.

        Returns:
            StrategyHealthReport with recommendation.
        """
        history = history or []
        trend = _compute_trend(history)
        recommendation = _compute_recommendation(health, trend)

        # Build signal summary
        signal_parts = [f"日均信号: {health.avg_daily_signals:.1f}"]
        if health.days_since_last_signal > 0:
            signal_parts.append(f"距上次信号: {health.days_since_last_signal}天")
        if health.signal_consistency < 0.7:
            signal_parts.append(f"一致性低: {health.signal_consistency:.0%}")
        signal_summary = " | ".join(signal_parts)

        # Build details
        details: dict[str, Any] = {
            "avg_daily_signals": round(health.avg_daily_signals, 1),
            "signal_consistency": round(health.signal_consistency, 3),
            "weekly_turnover_pct": round(health.weekly_turnover_pct, 3),
            "current_drawdown_pct": round(health.current_drawdown_pct, 3),
            "days_since_last_signal": health.days_since_last_signal,
            "trend": trend,
            "history_points": len(history),
        }

        return cls(
            strategy_id=health.strategy_id,
            recommendation=recommendation,
            health_score=round(health.health_score, 1),
            health_level=health.health_level.value,
            trend=trend,
            signal_summary=signal_summary,
            alerts=list(health.alerts),
            details=details,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def can_use_in_decision(self) -> bool:
        """True if this strategy's signals should be used today."""
        return self.recommendation == HealthRecommendation.HEALTHY

    @property
    def needs_human_review(self) -> bool:
        """True if a human should review this strategy before using it."""
        return self.recommendation != HealthRecommendation.HEALTHY

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-safe dict for DecisionPackage."""
        return {
            "strategy_id": self.strategy_id,
            "recommendation": self.recommendation.value,
            "recommendation_label": _recommendation_label(self.recommendation),
            "health_score": self.health_score,
            "health_level": self.health_level,
            "trend": self.trend,
            "trend_icon": _trend_icon(self.trend),
            "signal_summary": self.signal_summary,
            "alerts": self.alerts,
            "details": self.details,
        }

    def to_markdown(self) -> str:
        """Render as Markdown for DecisionPackage report."""
        lines: list[str] = [
            f"### {self.strategy_id}",
            "",
            "| 指标 | 值 |",
            "|------|-----|",
            f"| 健康分 / Health Score | {self.health_score}/100 |",
            f"| 健康等级 / Level | {self.health_level} |",
            f"| 趋势 / Trend | {_trend_icon(self.trend)} {self.trend} |",
            f"| 建议 / Recommendation | **{_recommendation_label(self.recommendation)}** |",
            f"| 信号摘要 | {self.signal_summary} |",
        ]

        if self.alerts:
            lines.append("")
            lines.append("**告警 / Alerts:**")
            for a in self.alerts:
                lines.append(f"- ⚠️ {a}")

        return "\n".join(lines)


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------


def _recommendation_label(rec: HealthRecommendation) -> str:
    """Human-readable Chinese label for a recommendation."""
    labels = {
        HealthRecommendation.HEALTHY: "✅ 健康 — 可正常使用",
        HealthRecommendation.NEEDS_RETRAIN: "⚠️ 需重训 — 建议降低权重或暂停",
        HealthRecommendation.NOT_APPROVED: "❌ 不可用 — 不应参与本次决策",
    }
    return labels.get(rec, rec.value)


def _trend_icon(trend: str) -> str:
    """Emoji icon for trend direction."""
    icons = {
        "improving": "📈",
        "stable": "➡️",
        "declining": "📉",
        "unknown": "❓",
    }
    return icons.get(trend, "❓")
