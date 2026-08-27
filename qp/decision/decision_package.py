"""DecisionPackage — structured daily decision record with full audit trail.

Each run of the daily pipeline produces one DecisionPackage, saved to
data/decisions/. It contains:
  - Data lineage: which dataset/feature versions were used
  - Market regime context
  - Per-strategy validation gate results
  - Risk audit trail (every violation with threshold vs actual)
  - Trade recommendations (DecisionReport)
  - Human review section (to be filled by the user)

This is the core of Layer 10 (Decision Layer) — bridging algorithmic output
to human-executable, auditable decisions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from qp.decision.models import DecisionReport
from qp.decision.state_machine import DecisionStatus, StatusTransition
from qp.shared.paths import DECISIONS_DIR

INDEX_PATH = DECISIONS_DIR / "index.json"


# ==================================================================
# Supporting types
# ==================================================================


@dataclass
class LineageSnapshot:
    """Immutable record of what data/features produced this decision.

    Answers: "If this decision turns out wrong, what was it based on?"
    """

    dataset_name: str = ""  # e.g. "daily_price_main"
    dataset_version: str = ""  # e.g. "2026-07-23"
    dataset_rows: int = 0
    dataset_symbols: int = 0
    feature_versions: dict[str, str] = field(default_factory=dict)
    strategy_versions: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"Dataset: {self.dataset_name} v{self.dataset_version} "
            f"({self.dataset_symbols} stocks, {self.dataset_rows} rows) | "
            f"Strategies: {len(self.strategy_versions)}"
        )


@dataclass
class RegimeContext:
    """Market state snapshot at decision time."""

    regime: str = "unknown"  # bull / bear / neutral / crisis / sideways_up / sideways_down
    confidence: float = 0.0
    suggested_exposure: float = 1.0
    trend_strength: float = 0.0
    annualized_vol: float = 0.0
    summary: str = ""

    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.6


@dataclass
class RiskAuditEntry:
    """One risk decision with full reasoning — for audit trail."""

    symbol: str = ""
    violation_type: str = ""  # "industry_concentration" | "max_position" | "correlation"
    detail: str = ""
    threshold: str = ""
    actual: str = ""
    action: str = ""  # "dropped" | "warning"


@dataclass
class RiskAudit:
    """Complete risk audit trail for a decision run."""

    candidates_in: int = 0
    candidates_out: int = 0
    entries: list[RiskAuditEntry] = field(default_factory=list)
    dropped_symbols: list[str] = field(default_factory=list)
    sector_exposure: dict[str, float] = field(default_factory=dict)
    passed: bool = True
    # Candidate → weight map (post-risk, final allocation weights).
    # Lets the WebUI show WHICH stocks drive sector/position violations.
    candidate_weights: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        if not self.entries:
            return f"风控通过 / Risk OK ({self.candidates_out}/{self.candidates_in})"
        return (
            f"风控告警 / Risk Warning: {len(self.entries)} violations, "
            f"{len(self.dropped_symbols)} dropped"
        )


@dataclass
class HumanReview:
    """User-filled review after reading the decision package.

    Attributes:
        reviewed: Legacy — True if human has reviewed (kept for backward compat).
        reviewer: Name of the person who reviewed.
        notes: Review notes or modification details.
        executed: Legacy — True if trades have been executed.
        execution_time: ISO timestamp of execution.
        status: DecisionStatus value (source of truth for state machine).
        status_history: Audit trail of all status transitions.
    """

    reviewed: bool = False
    reviewer: str = ""
    notes: str = ""
    executed: bool = False
    execution_time: str = ""
    status: str = "pending"
    status_history: list[dict[str, str]] = field(default_factory=list)

    @property
    def current_status(self) -> DecisionStatus:
        """Current DecisionStatus enum value."""
        try:
            return DecisionStatus(self.status)
        except ValueError:
            return DecisionStatus.PENDING

    @property
    def is_pending(self) -> bool:
        """True if awaiting human review."""
        return self.status == "pending"

    @property
    def is_terminal(self) -> bool:
        """True if in a terminal state."""
        return self.current_status.is_terminal

    def record_transition(
        self,
        to_status: DecisionStatus,
        actor: str = "",
        notes: str = "",
    ) -> None:
        """Record a status transition and update legacy compat fields.

        Args:
            to_status: The new DecisionStatus.
            actor: Who initiated the transition.
            notes: Optional reason or comment.
        """
        old_status = self.current_status

        record = StatusTransition(
            from_status=old_status,
            to_status=to_status,
            actor=actor,
            notes=notes,
        )

        self.status = to_status.value
        self.status_history.append(
            {
                "from_status": record.from_status.value,
                "to_status": record.to_status.value,
                "timestamp": record.timestamp,
                "actor": record.actor,
                "notes": record.notes,
            }
        )

        # Update legacy compat fields
        if to_status in (DecisionStatus.APPROVED, DecisionStatus.MODIFIED):
            self.reviewed = True
            if actor:
                self.reviewer = actor
            if notes:
                self.notes = notes
        elif to_status == DecisionStatus.REJECTED:
            self.reviewed = True
            if actor:
                self.reviewer = actor
        elif to_status in (
            DecisionStatus.PARTIALLY_EXECUTED,
            DecisionStatus.MONITORING,
        ):
            self.executed = True
            self.execution_time = record.timestamp


# ==================================================================
# Main DecisionPackage
# ==================================================================


@dataclass
class DecisionPackage:
    """Complete daily decision record — the unit of audit.

    Saved to data/decisions/dp-{date}-{run_id}.json each time the daily
    pipeline runs. Contains everything needed to reconstruct, audit, or
    challenge a single day's investment decision.
    """

    # Identity
    package_id: str = ""
    date: str = ""  # "2026-07-23"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Lineage — what produced this
    lineage: LineageSnapshot = field(default_factory=LineageSnapshot)

    # Market context
    regime: RegimeContext = field(default_factory=RegimeContext)

    # Strategy execution
    strategy_signals: dict[str, int] = field(default_factory=dict)
    ensemble_method: str = "equal_weight"
    effective_top_n: int = 10

    # Risk audit trail
    risk_audit: RiskAudit = field(default_factory=RiskAudit)

    # Cost
    estimated_cost_pct: float = 0.0

    # Validation gate results per strategy
    # {strategy_id: {stage, score, passed, rules_total, rules_failed, recommendation}}
    validation: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Core trade recommendations
    report: DecisionReport = field(default_factory=DecisionReport)

    # Human review (filled after generation)
    human_review: HumanReview = field(default_factory=HumanReview)

    # Arbitrary extra context
    metadata: dict[str, str] = field(default_factory=dict)

    # ==================================================================
    # Serialization
    # ==================================================================

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        # Convert RiskAuditEntry list
        risk_entries = [
            {
                "symbol": e.symbol,
                "violation_type": e.violation_type,
                "detail": e.detail,
                "threshold": e.threshold,
                "actual": e.actual,
                "action": e.action,
            }
            for e in self.risk_audit.entries
        ]

        # Convert TradeRecommendation list
        recs = [
            {
                "symbol": r.symbol,
                "action": r.action,
                "target_weight_pct": r.target_weight_pct,
                "current_weight_pct": r.current_weight_pct,
                "quantity_shares": r.quantity_shares,
                "estimated_price": r.estimated_price,
                "estimated_cost": r.estimated_cost,
                "reason": r.reason,
                "risk_warnings": r.risk_warnings,
                "confidence": r.confidence,
                "strategy": r.strategy,
            }
            for r in self.report.recommendations
        ]

        return {
            "package_id": self.package_id,
            "date": self.date,
            "generated_at": self.generated_at,
            "lineage": {
                "dataset_name": self.lineage.dataset_name,
                "dataset_version": self.lineage.dataset_version,
                "dataset_rows": self.lineage.dataset_rows,
                "dataset_symbols": self.lineage.dataset_symbols,
                "feature_versions": self.lineage.feature_versions,
                "strategy_versions": self.lineage.strategy_versions,
            },
            "regime": {
                "regime": self.regime.regime,
                "confidence": self.regime.confidence,
                "suggested_exposure": self.regime.suggested_exposure,
                "trend_strength": self.regime.trend_strength,
                "annualized_vol": self.regime.annualized_vol,
                "summary": self.regime.summary,
            },
            "strategy": {
                "signals": self.strategy_signals,
                "ensemble_method": self.ensemble_method,
                "effective_top_n": self.effective_top_n,
            },
            "risk_audit": {
                "candidates_in": self.risk_audit.candidates_in,
                "candidates_out": self.risk_audit.candidates_out,
                "entries": risk_entries,
                "dropped_symbols": self.risk_audit.dropped_symbols,
                "sector_exposure": self.risk_audit.sector_exposure,
                "passed": self.risk_audit.passed,
                "candidate_weights": self.risk_audit.candidate_weights,
            },
            "estimated_cost_pct": self.estimated_cost_pct,
            "validation": self.validation,
            "report": {
                "report_id": self.report.report_id,
                "strategy_id": self.report.strategy_id,
                "total_capital": self.report.total_capital,
                "risk_summary": self.report.risk_summary,
                "market_regime": self.report.market_regime,
                "cost_summary": self.report.cost_summary,
                "n_buys": self.report.n_buys,
                "n_sells": self.report.n_sells,
                "total_invested": self.report.total_invested,
                "remaining_cash": self.report.remaining_cash,
                "total_estimated_cost": self.report.total_estimated_cost,
                "recommendations": recs,
            },
            "human_review": {
                "reviewed": self.human_review.reviewed,
                "reviewer": self.human_review.reviewer,
                "notes": self.human_review.notes,
                "executed": self.human_review.executed,
                "execution_time": self.human_review.execution_time,
                "status": self.human_review.status,
                "status_history": self.human_review.status_history,
            },
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionPackage:
        """Restore from a JSON dict."""
        from qp.decision.models import DecisionReport, TradeRecommendation

        # Rebuild TradeRecommendations
        recs = []
        for r in data.get("report", {}).get("recommendations", []):
            recs.append(
                TradeRecommendation(
                    symbol=r.get("symbol", ""),
                    action=r.get("action", "BUY"),
                    target_weight_pct=r.get("target_weight_pct", 0.0),
                    current_weight_pct=r.get("current_weight_pct", 0.0),
                    quantity_shares=r.get("quantity_shares", 0),
                    estimated_price=r.get("estimated_price", 0.0),
                    estimated_cost=r.get("estimated_cost", 0.0),
                    reason=r.get("reason", ""),
                    risk_warnings=r.get("risk_warnings", []),
                    confidence=r.get("confidence", 0.0),
                    strategy=r.get("strategy", ""),
                )
            )

        report_data = data.get("report", {})
        report = DecisionReport(
            report_id=report_data.get("report_id", ""),
            strategy_id=report_data.get("strategy_id", ""),
            total_capital=report_data.get("total_capital", 0.0),
            recommendations=recs,
            risk_summary=report_data.get("risk_summary", ""),
            market_regime=report_data.get("market_regime", ""),
            cost_summary=report_data.get("cost_summary", ""),
        )

        lineage_data = data.get("lineage", {})
        lineage = LineageSnapshot(
            dataset_name=lineage_data.get("dataset_name", ""),
            dataset_version=lineage_data.get("dataset_version", ""),
            dataset_rows=lineage_data.get("dataset_rows", 0),
            dataset_symbols=lineage_data.get("dataset_symbols", 0),
            feature_versions=lineage_data.get("feature_versions", {}),
            strategy_versions=lineage_data.get("strategy_versions", {}),
        )

        regime_data = data.get("regime", {})
        regime = RegimeContext(
            regime=regime_data.get("regime", "unknown"),
            confidence=regime_data.get("confidence", 0.0),
            suggested_exposure=regime_data.get("suggested_exposure", 1.0),
            trend_strength=regime_data.get("trend_strength", 0.0),
            annualized_vol=regime_data.get("annualized_vol", 0.0),
            summary=regime_data.get("summary", ""),
        )

        risk_data = data.get("risk_audit", {})
        risk_entries = [
            RiskAuditEntry(
                symbol=e.get("symbol", ""),
                violation_type=e.get("violation_type", ""),
                detail=e.get("detail", ""),
                threshold=e.get("threshold", ""),
                actual=e.get("actual", ""),
                action=e.get("action", ""),
            )
            for e in risk_data.get("entries", [])
        ]
        risk_audit = RiskAudit(
            candidates_in=risk_data.get("candidates_in", 0),
            candidates_out=risk_data.get("candidates_out", 0),
            entries=risk_entries,
            dropped_symbols=risk_data.get("dropped_symbols", []),
            sector_exposure={
                str(k): float(v) for k, v in risk_data.get("sector_exposure", {}).items()
            },
            passed=risk_data.get("passed", True),
            candidate_weights={
                str(k): float(v)
                for k, v in risk_data.get("candidate_weights", {}).items()
            },
        )

        hr_data = data.get("human_review", {})
        # Backward compat: infer status from legacy booleans if status field missing
        hr_status = hr_data.get("status", "")
        hr_history = hr_data.get("status_history", [])
        if not hr_status:
            # Old format — infer from reviewed/executed booleans
            if hr_data.get("executed", False):
                hr_status = "monitoring"
            elif hr_data.get("reviewed", False):
                hr_status = "approved"
            else:
                hr_status = "pending"
            # Create a synthetic initial entry for the audit trail
            if hr_status != "pending":
                hr_history = [
                    {
                        "from_status": "pending",
                        "to_status": hr_status,
                        "timestamp": hr_data.get("execution_time", hr_data.get("generated_at", "")),
                        "actor": hr_data.get("reviewer", ""),
                        "notes": "Migrated from legacy format",
                    }
                ]
        human_review = HumanReview(
            reviewed=hr_data.get("reviewed", False),
            reviewer=hr_data.get("reviewer", ""),
            notes=hr_data.get("notes", ""),
            executed=hr_data.get("executed", False),
            execution_time=hr_data.get("execution_time", ""),
            status=hr_status,
            status_history=hr_history,
        )

        strategy_data = data.get("strategy", {})

        return cls(
            package_id=data.get("package_id", ""),
            date=data.get("date", ""),
            generated_at=data.get("generated_at", ""),
            lineage=lineage,
            regime=regime,
            strategy_signals=strategy_data.get("signals", {}),
            ensemble_method=strategy_data.get("ensemble_method", "equal_weight"),
            effective_top_n=strategy_data.get("effective_top_n", 10),
            risk_audit=risk_audit,
            estimated_cost_pct=data.get("estimated_cost_pct", 0.0),
            validation=data.get("validation", {}),
            report=report,
            human_review=human_review,
            metadata=data.get("metadata", {}),
        )

    # ==================================================================
    # File I/O
    # ==================================================================

    def to_json(self, path: str | Path | None = None) -> Path:
        """Save DecisionPackage as JSON.

        Args:
            path: File path. Defaults to data/decisions/{package_id}.json.

        Returns:
            The resolved Path where the file was saved.
        """
        if path is None:
            path = DECISIONS_DIR / f"{self.package_id}.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()
        path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("DecisionPackage saved → {}", path)
        return path

    @classmethod
    def from_json(cls, path: str | Path) -> DecisionPackage:
        """Load a DecisionPackage from JSON.

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"DecisionPackage not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def to_markdown(self, path: str | Path | None = None) -> Path:
        """Save a human-readable Markdown report.

        Args:
            path: File path. Defaults to data/decisions/{date}.md.

        Returns:
            The resolved Path where the file was saved.
        """
        if path is None:
            path = DECISIONS_DIR / f"{self.date}.md"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = self._build_markdown()
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("DecisionPackage Markdown → {}", path)
        return path

    @classmethod
    def load_latest(cls) -> DecisionPackage | None:
        """Load today's DecisionPackage if it exists."""
        today = datetime.now(UTC).date().isoformat()
        # Find matching files
        DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
        candidates = sorted(
            DECISIONS_DIR.glob(f"dp-{today}-*.json"),
            reverse=True,
        )
        if not candidates:
            return None
        return cls.from_json(candidates[0])

    # ==================================================================
    # Status transitions (delegates to state machine)
    # ==================================================================

    def transition_status(
        self,
        to_status: DecisionStatus | str,
        actor: str = "",
        notes: str = "",
    ) -> StatusTransition:
        """Transition this decision to a new status, with validation.

        Args:
            to_status: Target DecisionStatus.
            actor: Who initiated the transition.
            notes: Optional reason or comment.

        Returns:
            StatusTransition audit record.

        Raises:
            DecisionStateError: If the transition is not allowed.
        """
        from qp.decision.state_machine import transition

        if isinstance(to_status, str):
            to_status = DecisionStatus(to_status)

        new_status, record = transition(
            self.human_review.current_status,
            to_status,
            actor=actor,
            notes=notes,
        )
        self.human_review.record_transition(new_status, actor=actor, notes=notes)
        return record

    def approve(self, reviewer: str = "", notes: str = "") -> StatusTransition:
        """Approve this decision (PENDING/MODIFIED → APPROVED)."""
        from qp.decision.state_machine import approve

        new_status, record = approve(
            self.human_review.current_status,
            reviewer=reviewer,
            notes=notes,
        )
        self.human_review.record_transition(new_status, actor=reviewer, notes=notes)
        return record

    def reject(self, reviewer: str = "", notes: str = "") -> StatusTransition:
        """Reject this decision (PENDING → REJECTED)."""
        from qp.decision.state_machine import reject

        new_status, record = reject(
            self.human_review.current_status,
            reviewer=reviewer,
            notes=notes,
        )
        self.human_review.record_transition(new_status, actor=reviewer, notes=notes)
        return record

    def modify(self, reviewer: str = "", notes: str = "") -> StatusTransition:
        """Mark as modified (PENDING → MODIFIED)."""
        from qp.decision.state_machine import modify

        new_status, record = modify(
            self.human_review.current_status,
            reviewer=reviewer,
            notes=notes,
        )
        self.human_review.record_transition(new_status, actor=reviewer, notes=notes)
        return record

    def mark_executed(self, actor: str = "system", notes: str = "") -> StatusTransition:
        """Mark trades executed (APPROVED → PARTIALLY_EXECUTED → MONITORING)."""
        from qp.decision.state_machine import mark_executed

        new_status, record = mark_executed(
            self.human_review.current_status,
            actor=actor,
            notes=notes,
        )
        self.human_review.record_transition(new_status, actor=actor, notes=notes)
        return record

    def close(self, actor: str = "system", notes: str = "") -> StatusTransition:
        """Close this decision (MONITORING → CLOSED)."""
        from qp.decision.state_machine import close

        new_status, record = close(
            self.human_review.current_status,
            actor=actor,
            notes=notes,
        )
        self.human_review.record_transition(new_status, actor=actor, notes=notes)
        return record

    @property
    def status(self) -> DecisionStatus:
        """Current DecisionStatus of this package."""
        return self.human_review.current_status

    # ==================================================================
    # Index management
    # ==================================================================

    @staticmethod
    def load_index() -> list[dict[str, Any]]:
        """Load the decision index (lightweight metadata for all packages)."""
        DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
        if not INDEX_PATH.exists():
            return []
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def save_index(entries: list[dict[str, Any]]) -> None:
        """Save the decision index."""
        DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(
            json.dumps(entries, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    def update_index(self) -> None:
        """Add this package to the index (idempotent — updates if exists)."""
        entries = self.load_index()

        # Remove existing entry with same package_id
        entries = [e for e in entries if e.get("package_id") != self.package_id]

        entries.append(
            {
                "package_id": self.package_id,
                "date": self.date,
                "generated_at": self.generated_at,
                "regime": self.regime.regime,
                "n_recommendations": self.report.n_buys,
                "estimated_cost_pct": self.estimated_cost_pct,
                "risk_passed": self.risk_audit.passed,
                "human_reviewed": self.human_review.reviewed,
                "human_executed": self.human_review.executed,
                "status": self.human_review.status,
            }
        )

        # Keep most recent 365 entries
        entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)[:365]

        self.save_index(entries)
        logger.info("Index updated → {} ({} entries)", INDEX_PATH, len(entries))

    # ==================================================================
    # Markdown builder
    # ==================================================================

    def _build_markdown(self) -> list[str]:
        """Build the complete Markdown report."""
        from qp.decision.engine import DecisionEngine

        lines: list[str] = [
            f"# QP Decision Package — {self.package_id}",
            "",
            f"**Date**: {self.date} | **Generated**: {self.generated_at[:19]}",
            "",
            "---",
            "",
            "## 1. 数据血缘 / Data Lineage",
            "",
            f"- **Dataset**: {self.lineage.dataset_name} v{self.lineage.dataset_version}",
            f"- **Coverage**: {self.lineage.dataset_symbols} stocks, {self.lineage.dataset_rows:,} rows",
        ]
        if self.lineage.feature_versions:
            lines.append("- **Features**:")
            for fname, fver in self.lineage.feature_versions.items():
                lines.append(f"  - {fname}: v{fver}")
        if self.lineage.strategy_versions:
            lines.append("- **Strategies**:")
            for sid, lifecycle in self.lineage.strategy_versions.items():
                lines.append(f"  - {sid}: {lifecycle}")
        lines.append("")

        lines.extend(
            [
                "## 2. 市场状态 / Market Regime",
                "",
                f"- **Regime**: {self.regime.regime} (confidence: {self.regime.confidence:.0%})",
                f"- **Suggested Exposure**: {self.regime.suggested_exposure:.0%}",
                f"- **Trend Strength (ADX)**: {self.regime.trend_strength:.1f}",
                f"- **Annualized Vol**: {self.regime.annualized_vol:.1%}",
                f"- **Summary**: {self.regime.summary}",
                "",
            ]
        )

        lines.extend(
            [
                "## 3. 策略执行 / Strategy Execution",
                "",
                f"**Ensemble Method**: {self.ensemble_method}",
                f"**Effective Top-N**: {self.effective_top_n}",
                "",
                "| Strategy | Signals |",
                "|----------|---------|",
            ]
        )
        for sid, count in self.strategy_signals.items():
            lines.append(f"| {sid} | {count} |")
        lines.append("")

        # Validation + Health (P1.1/P1.2)
        if self.validation:
            lines.extend(
                [
                    "## 4. 验证门禁 / Validation Gate",
                    "",
                    "| Strategy | Stage | Score | Passed | Health | Trend | Rec |",
                    "|----------|-------|-------|--------|--------|-------|-----|",
                ]
            )
            for sid, v in self.validation.items():
                passed_icon = "✅" if v.get("passed", False) else "❌"
                health = v.get("health", {})
                report = v.get("health_report", {})
                if health:
                    health_score = health.get("health_score", "?")
                    health_level = health.get("health_level", "?")
                    n_alerts = len(health.get("alerts", []))
                    alert_str = f"⚠️ {n_alerts}" if n_alerts else "—"
                    health_str = f"{health_score} ({health_level}){alert_str}"
                else:
                    health_str = "—"
                if report:
                    trend = report.get("trend", "?")
                    trend_icon = {
                        "improving": "📈",
                        "stable": "➡️",
                        "declining": "📉",
                        "unknown": "❓",
                    }.get(trend, "?")
                    rec = report.get("recommendation", "?")
                    rec_icon = {
                        "healthy": "✅",
                        "needs_retrain": "⚠️",
                        "not_approved": "❌",
                    }.get(rec, "?")
                else:
                    trend_icon = "—"
                    rec_icon = "—"
                lines.append(
                    f"| {sid} | {v.get('stage', '?')} | "
                    f"{v.get('score', 0)}/100 | {passed_icon} | "
                    f"{health_str} | {trend_icon} | {rec_icon} |"
                )
            lines.append("")

            # Per-strategy validation rule details (P1.3)
            for sid, v in self.validation.items():
                rules = v.get("rules", [])
                if rules:
                    failed = [r for r in rules if r.get("status") == "fail"]
                    if failed:
                        lines.append(f"**{sid}** — {len(failed)}/{len(rules)} rules failed:")
                        for r in failed:
                            threshold_str = (
                                f" (threshold: {r.get('threshold')})"
                                if r.get("threshold") is not None
                                else ""
                            )
                            actual_str = (
                                f" actual: {r.get('actual_value')}"
                                if r.get("actual_value") is not None
                                else ""
                            )
                            detail_str = f" — {r.get('detail')}" if r.get("detail") else ""
                            lines.append(
                                f"  - ❌ {r.get('rule_name', '?')}: "
                                f"score={r.get('score', 0)}{threshold_str}{actual_str}{detail_str}"
                            )
                        lines.append("")

            # Per-strategy health report details (P1.2)
            for sid, v in self.validation.items():
                report = v.get("health_report", {})
                if report:
                    rec_label = report.get("recommendation_label", "")
                    signal_summary = report.get("signal_summary", "")
                    lines.extend(
                        [
                            f"**{sid}**: {rec_label}",
                            f"  - 信号: {signal_summary}",
                        ]
                    )
                    alerts = report.get("alerts", [])
                    if alerts:
                        for a in alerts:
                            lines.append(f"  - ⚠️ {a}")
                    lines.append("")
            if not any(v.get("health_report") for v in self.validation.values()):
                lines.append("")

        # Risk Audit
        lines.extend(
            [
                "## 5. 风控审计 / Risk Audit",
                "",
                f"- **Candidates**: {self.risk_audit.candidates_in} → {self.risk_audit.candidates_out}",
                f"- **Passed**: {'✅' if self.risk_audit.passed else '⚠️'}",
            ]
        )
        if self.risk_audit.dropped_symbols:
            lines.append(f"- **Dropped**: {', '.join(self.risk_audit.dropped_symbols)}")
        if self.risk_audit.entries:
            lines.append("")
            lines.append("| Symbol | Violation | Detail | Threshold | Actual | Action |")
            lines.append("|--------|-----------|--------|-----------|--------|--------|")
            for e in self.risk_audit.entries:
                lines.append(
                    f"| {e.symbol} | {e.violation_type} | {e.detail} | "
                    f"{e.threshold} | {e.actual} | {e.action} |"
                )
        if self.risk_audit.sector_exposure:
            lines.append("")
            lines.append("**Sector Exposure**:")
            for sector, wt in sorted(self.risk_audit.sector_exposure.items(), key=lambda x: -x[1]):
                lines.append(f"- {sector}: {wt:.1%}")
        lines.append("")

        # Cost
        lines.extend(
            [
                "## 6. 成本估算 / Cost Estimate",
                "",
                f"Estimated total cost: **{self.estimated_cost_pct:.2f}%** of capital",
                "",
            ]
        )

        # Trade Recommendations — reuse DecisionEngine Markdown
        lines.extend(
            [
                "## 7. 交易建议 / Trade Recommendations",
                "",
            ]
        )
        if self.report.is_empty:
            lines.append("*No recommendations generated.*")
        else:
            engine = DecisionEngine()
            report_md = engine.to_markdown(self.report)
            # Skip the top-level header since we already have one
            report_lines = report_md.split("\n")
            # Skip first 4 lines (title + blank + metadata)
            body_start = 0
            for i, line in enumerate(report_lines):
                if line.startswith("## "):
                    body_start = i
                    break
            lines.extend(report_lines[body_start:])
        lines.append("")

        # Human Review
        hr = self.human_review
        lines.extend(
            [
                "## 8. 人工审核 / Human Review",
                "",
                f"- **Reviewed**: {'✅' if hr.reviewed else '❌ (pending)'}",
                f"- **Reviewer**: {hr.reviewer or '(待审核)'}",
                f"- **Executed**: {'✅' if hr.executed else '❌ (not yet)'}",
            ]
        )
        if hr.notes:
            lines.append(f"- **Notes**: {hr.notes}")
        if hr.execution_time:
            lines.append(f"- **Execution Time**: {hr.execution_time}")
        lines.append("")

        # Disclaimer
        lines.extend(
            [
                "---",
                "",
                self.report.disclaimer.replace("\n", "\n\n"),
            ]
        )

        return lines
