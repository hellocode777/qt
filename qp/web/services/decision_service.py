"""DecisionService — DecisionPackage lifecycle management.

Bridges the QP Decision layer (Layer 8) to the Web layer.
Handles both query (read) and status transitions (write).
Returns plain dicts — never exposes domain objects to templates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

from qp.decision.decision_package import DecisionPackage
from qp.decision.state_machine import DecisionStateError
from qp.shared.paths import DECISIONS_DIR

# ── Risk audit detail parsing ──
# detail 是英文文本（如 "Position cap: equal weight 20.0% > 8% at 5 positions"），
# WebUI 展示前解析成结构化字段，避免用户从文本里自己数百分比。
_RISK_CATEGORY_PATTERNS: list[tuple[str, str, str]] = [
    # (匹配关键词, category, 中文标签)
    ("Position count", "position_count", "持仓数量"),
    ("Position cap", "position_cap", "单仓上限"),
    ("Sector cap", "sector_cap", "行业集中"),
    ("Correlation", "correlation", "相关性"),
]


def _parse_risk_entry(entry: Any) -> dict[str, Any]:
    """Parse a RiskAuditEntry into a template-ready dict with structured numbers.

    Extracts actual/threshold percentages from the free-text detail when the
    entry doesn't already carry them. Numbers that cannot be parsed stay None —
    templates render them as N/A rather than fake zeros.
    """
    detail = entry.detail or ""
    vtype = entry.violation_type or "risk_limit"

    # Structured violation_type wins; else sniff the free-text detail.
    if vtype == "correlation":
        category, label = "correlation", "相关性"
    else:
        category, label = vtype, vtype
        for keyword, cat, lab in _RISK_CATEGORY_PATTERNS:
            if keyword in detail:
                category, label = cat, lab
                break

    # Prefer structured fields (correlation entries carry them)
    actual_pct: float | None = None
    threshold_pct: float | None = None
    if entry.actual:
        try:
            actual_pct = (
                float(entry.actual) * 100
                if "%" not in str(entry.actual)
                else float(str(entry.actual).rstrip("%"))
            )
        except ValueError:
            actual_pct = None
    if entry.threshold:
        try:
            threshold_pct = (
                float(entry.threshold) * 100
                if "%" not in str(entry.threshold)
                else float(str(entry.threshold).rstrip("%"))
            )
        except ValueError:
            threshold_pct = None

    # Fallback: parse percentages from free-text detail.
    # "Correlation: N pair(s) > X%" — the % is the threshold; the pair count is
    # NOT a percentage, so leave actual as None (honest N/A, not a fake number).
    pcts = re.findall(r"(\d+(?:\.\d+)?)%", detail)
    if category == "correlation" and "pair(s)" in detail:
        if threshold_pct is None and pcts:
            threshold_pct = float(pcts[0])
    else:
        if actual_pct is None and pcts:
            actual_pct = float(pcts[0])
        if threshold_pct is None and len(pcts) > 1:
            threshold_pct = float(pcts[1])

    over_pct = (
        round(actual_pct - threshold_pct, 1)
        if actual_pct is not None and threshold_pct is not None
        else None
    )

    return {
        "symbol": entry.symbol,
        "violation_type": entry.violation_type,
        "category": category,
        "category_label": label,
        "detail": detail,
        "threshold": entry.threshold,
        "actual": entry.actual,
        "threshold_pct": threshold_pct,
        "actual_pct": actual_pct,
        "over_pct": over_pct,
        "action": entry.action,
        # display helpers
        "severity": "danger" if entry.action == "dropped" else "warning",
    }


def _build_candidate_stocks(risk_audit: Any) -> list[dict[str, Any]]:
    """Build per-stock rows for the risk audit panel.

    Uses the candidate→weight map saved at decision time plus the industry
    mapper so the UI can show WHICH stocks drive sector/position violations.
    Returns [] when the stored package predates candidate_weights (no data —
    UI renders "无数据" instead of fabricating rows).
    """
    weights = dict(getattr(risk_audit, "candidate_weights", {}) or {})
    if not weights:
        return []

    try:
        from qp.portfolio.industry import IndustryMapper

        mapper = IndustryMapper()
    except Exception:
        mapper = None

    rows: list[dict[str, Any]] = []
    for sym, w in sorted(weights.items(), key=lambda x: -x[1]):
        sector = mapper.get_sector(str(sym)) if mapper is not None else ""
        rows.append(
            {
                "symbol": str(sym),
                "weight_pct": round(float(w) * 100, 1),
                "sector": sector,
            }
        )
    return rows


class DecisionService:
    """Decision lifecycle service — query + status transitions.

    Usage:
        svc = DecisionService()
        latest = svc.latest()                          # Today's decision
        history = svc.history(limit=30)                # Recent decisions
        detail = svc.get_by_id("dp-2026-07-30-xxx")   # Specific package

        # State transitions (validated via state machine)
        svc.approve("dp-xxx", reviewer="张三")         # PENDING → APPROVED
        svc.reject("dp-xxx", reviewer="李四")          # PENDING → REJECTED
        svc.modify("dp-xxx", reviewer="王五")          # PENDING → MODIFIED
        svc.mark_executed("dp-xxx")                    # APPROVED → PARTIALLY_EXECUTED
        svc.mark_executed("dp-xxx")                    # PARTIALLY_EXECUTED → MONITORING
        svc.close("dp-xxx")                            # MONITORING → CLOSED
    """

    def __init__(self) -> None:
        self._index_cache: list[dict[str, Any]] = []
        self._index_loaded = False

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def latest(self) -> dict[str, Any] | None:
        """Load today's latest DecisionPackage as a template-ready dict.

        Returns None if no package exists for today.
        """
        pkg = DecisionPackage.load_latest()
        if pkg is None:
            pkg = self._load_most_recent()
        if pkg is None:
            return None

        return self._package_to_dict(pkg)

    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        """Load recent decision index entries.

        Returns lightweight metadata for the decision history list.
        """
        entries = DecisionPackage.load_index()
        return entries[:limit]

    def get_by_id(self, package_id: str) -> dict[str, Any] | None:
        """Load a specific decision package by ID."""
        path = _resolve_path(package_id)
        if not path.exists():
            logger.warning("DecisionPackage not found: {}", package_id)
            return None

        try:
            pkg = DecisionPackage.from_json(path)
            return self._package_to_dict(pkg)
        except Exception as e:
            logger.error("Failed to load DecisionPackage {}: {}", package_id, e)
            return None

    # ------------------------------------------------------------------
    # Status transitions (P0.3 — state-machine validated)
    # ------------------------------------------------------------------

    def approve(
        self,
        package_id: str,
        reviewer: str = "",
        notes: str = "",
        create_positions: bool = True,
    ) -> dict[str, Any] | None:
        """Approve a decision (PENDING/MODIFIED → APPROVED).

        Validates the transition via the state machine.
        Saves updated JSON and refreshes the index.

        If create_positions is True (default), auto-applies the package to
        PositionLedger: closes positions for each SELL recommendation and
        creates Position records for each BUY recommendation.
        """
        result = self._transition(
            package_id,
            method_name="approve",
            reviewer=reviewer,
            notes=notes,
        )
        if result is not None and create_positions:
            try:
                path = _resolve_path(package_id)
                pkg = DecisionPackage.from_json(path)
                from qp.decision.position_ledger import PositionLedger

                ledger = PositionLedger()
                # SELL first: cash flows back before BUY cash is debited
                closed = ledger.close_from_decision(pkg)
                positions = ledger.open_from_decision(pkg)
                logger.info(
                    "Auto-applied {} closes / {} positions from {}",
                    len(closed),
                    len(positions),
                    package_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to auto-apply positions for {}: {}",
                    package_id,
                    e,
                )
        return result

    def reject(
        self,
        package_id: str,
        reviewer: str = "",
        notes: str = "",
    ) -> dict[str, Any] | None:
        """Reject a decision (PENDING → REJECTED, terminal)."""
        return self._transition(
            package_id,
            method_name="reject",
            reviewer=reviewer,
            notes=notes,
        )

    def modify(
        self,
        package_id: str,
        reviewer: str = "",
        notes: str = "",
    ) -> dict[str, Any] | None:
        """Mark a decision as modified (PENDING → MODIFIED)."""
        return self._transition(
            package_id,
            method_name="modify",
            reviewer=reviewer,
            notes=notes,
        )

    def mark_executed(
        self,
        package_id: str,
        notes: str = "",
    ) -> dict[str, Any] | None:
        """Mark trades as executed (APPROVED → PARTIALLY_EXECUTED → MONITORING).

        First call moves APPROVED → PARTIALLY_EXECUTED.
        Second call moves PARTIALLY_EXECUTED → MONITORING.
        """
        return self._transition(
            package_id,
            method_name="mark_executed",
            actor="system",
            notes=notes,
        )

    def close(
        self,
        package_id: str,
        notes: str = "",
    ) -> dict[str, Any] | None:
        """Close a decision (MONITORING → CLOSED, terminal)."""
        return self._transition(
            package_id,
            method_name="close",
            actor="system",
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Legacy API (backward compat — delegates to state machine)
    # ------------------------------------------------------------------

    def mark_reviewed(self, package_id: str, notes: str = "") -> dict[str, Any] | None:
        """Legacy: mark a decision as reviewed (delegates to approve).

        Kept for backward compatibility with existing WebUI endpoints.
        """
        return self.approve(package_id, reviewer="webui", notes=notes)

    # ------------------------------------------------------------------
    # Internal: generic transition handler
    # ------------------------------------------------------------------

    def _transition(
        self,
        package_id: str,
        method_name: str,
        reviewer: str = "",
        actor: str = "",
        notes: str = "",
    ) -> dict[str, Any] | None:
        """Load DP → call state-machine method → save → update index.

        Args:
            package_id: Decision package ID.
            method_name: Name of the DecisionPackage transition method to call.
            reviewer: Who initiated (for human actions).
            actor: Who initiated (for system actions).
            notes: Optional reason or comment.

        Returns:
            Template-ready dict, or None on error.
        """
        path = _resolve_path(package_id)
        if not path.exists():
            logger.warning("DecisionPackage not found: {}", package_id)
            return None

        try:
            pkg = DecisionPackage.from_json(path)
            method = getattr(pkg, method_name)

            # Dispatch based on method signature
            if method_name in ("approve", "reject", "modify"):
                method(reviewer=reviewer or actor, notes=notes)
            elif method_name in ("mark_executed", "close"):
                method(actor=reviewer or actor or "system", notes=notes)
            else:
                method()

            pkg.to_json(path)
            pkg.update_index()
            logger.info(
                "Decision {} → {} by {}: {}",
                package_id,
                pkg.human_review.status,
                reviewer or actor or "system",
                notes,
            )
            return self._package_to_dict(pkg)
        except DecisionStateError as e:
            logger.warning(
                "Invalid transition for {}: {} → rejected: {}",
                package_id,
                e.from_status.value if hasattr(e, "from_status") else "?",
                e,
            )
            return None
        except Exception as e:
            logger.error("Failed to transition {} ({}): {}", package_id, method_name, e)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_most_recent(self) -> DecisionPackage | None:
        """Load the most recent decision package from the index."""
        entries = DecisionPackage.load_index()
        if not entries:
            return None

        latest_entry = entries[0]
        package_id = latest_entry.get("package_id", "")
        if not package_id:
            return None

        from pathlib import Path

        path = Path(DECISIONS_DIR) / f"{package_id}.json"
        if not path.exists():
            return None

        try:
            return DecisionPackage.from_json(path)
        except Exception as e:
            logger.error("Failed to load most recent DecisionPackage: {}", e)
            return None

    @staticmethod
    def _package_to_dict(pkg: DecisionPackage) -> dict[str, Any]:
        """Convert DecisionPackage to template-friendly dict.

        Flattens nested structures and adds computed display fields.
        """
        # Build buy/sell lists with display-friendly fields
        buys = []
        sells = []
        for rec in pkg.report.recommendations:
            item = {
                "symbol": rec.symbol,
                "action": rec.action,
                "target_weight_pct": rec.target_weight_pct,
                "current_weight_pct": rec.current_weight_pct,
                "quantity_shares": rec.quantity_shares,
                "estimated_price": rec.estimated_price,
                "estimated_cost": rec.estimated_cost,
                "reason": rec.reason,
                "risk_warnings": rec.risk_warnings,
                "confidence": rec.confidence,
                "strategy": rec.strategy,
                # Computed display fields
                "confidence_pct": int(rec.confidence * 100),
                "trade_value": rec.trade_value,
                "cost_pct": round(rec.cost_pct, 3),
            }
            if rec.action == "BUY":
                buys.append(item)
            elif rec.action == "SELL":
                sells.append(item)

        # Flatten risk audit entries
        risk_entries = [_parse_risk_entry(e) for e in pkg.risk_audit.entries]

        # Build strategy signals list for display
        strategy_signals = [
            {"strategy_id": sid, "count": count} for sid, count in pkg.strategy_signals.items()
        ]

        # Build validation summary
        validation_summary = []
        for sid, v in pkg.validation.items():
            validation_summary.append(
                {
                    "strategy_id": sid,
                    "stage": v.get("stage", "?"),
                    "score": v.get("score", 0),
                    "passed": v.get("passed", False),
                    "rules_total": v.get("rules_total", 0),
                    "rules_failed": v.get("rules_failed", 0),
                    "recommendation": v.get("recommendation", ""),
                }
            )

        return {
            # Identity
            "package_id": pkg.package_id,
            "date": pkg.date,
            "generated_at": pkg.generated_at,
            "generated_at_short": pkg.generated_at[:19] if pkg.generated_at else "",
            # Market regime
            "regime": {
                "regime": pkg.regime.regime,
                "confidence": pkg.regime.confidence,
                "confidence_pct": int(pkg.regime.confidence * 100),
                "suggested_exposure": pkg.regime.suggested_exposure,
                "suggested_exposure_pct": int(pkg.regime.suggested_exposure * 100),
                "trend_strength": pkg.regime.trend_strength,
                "annualized_vol": pkg.regime.annualized_vol,
                "annualized_vol_pct": round(pkg.regime.annualized_vol * 100, 1),
                "summary": pkg.regime.summary,
                "is_high_confidence": pkg.regime.is_high_confidence(),
                # Display label
                "label": _regime_label(pkg.regime.regime),
                "badge_class": _regime_badge_class(pkg.regime.regime),
            },
            # Strategy signals
            "strategy_signals": strategy_signals,
            "ensemble_method": pkg.ensemble_method,
            "effective_top_n": pkg.effective_top_n,
            # Report
            "report": {
                "report_id": pkg.report.report_id,
                "strategy_id": pkg.report.strategy_id,
                "total_capital": pkg.report.total_capital,
                "risk_summary": pkg.report.risk_summary,
                "market_regime": pkg.report.market_regime,
                "cost_summary": pkg.report.cost_summary,
                "n_buys": pkg.report.n_buys,
                "n_sells": pkg.report.n_sells,
                "n_holds": pkg.report.n_holds,
                "total_invested": pkg.report.total_invested,
                "total_invested_fmt": f"{pkg.report.total_invested:,.0f}",
                "remaining_cash": pkg.report.remaining_cash,
                "remaining_cash_fmt": f"{pkg.report.remaining_cash:,.0f}",
                "total_estimated_cost": pkg.report.total_estimated_cost,
                "has_warnings": pkg.report.has_warnings,
                "is_empty": pkg.report.is_empty,
            },
            # Recommendations
            "buys": buys,
            "sells": sells,
            # Risk audit
            "risk_audit": {
                "candidates_in": pkg.risk_audit.candidates_in,
                "candidates_out": pkg.risk_audit.candidates_out,
                "passed": pkg.risk_audit.passed,
                "entries": risk_entries,
                "dropped_symbols": pkg.risk_audit.dropped_symbols,
                "sector_exposure": [
                    {
                        "sector": k,
                        "weight_pct": round(v * 100, 1),
                        "over_pct": round(v * 100 - 25.0, 1),
                        "over_limit": v * 100 > 25.0,
                    }
                    for k, v in sorted(
                        pkg.risk_audit.sector_exposure.items(),
                        key=lambda x: -x[1],
                    )
                ],
                "candidate_stocks": _build_candidate_stocks(pkg.risk_audit),
                "summary": pkg.risk_audit.summary(),
            },
            # Cost
            "estimated_cost_pct": pkg.estimated_cost_pct,
            # Validation
            "validation": validation_summary,
            # Lineage
            "lineage": {
                "dataset_name": pkg.lineage.dataset_name,
                "dataset_version": pkg.lineage.dataset_version,
                "dataset_rows": pkg.lineage.dataset_rows,
                "dataset_symbols": pkg.lineage.dataset_symbols,
            },
            # Human review
            "human_review": {
                "reviewed": pkg.human_review.reviewed,
                "executed": pkg.human_review.executed,
                "notes": pkg.human_review.notes,
                "reviewer": pkg.human_review.reviewer,
                "execution_time": pkg.human_review.execution_time,
                # P0.2+ — state machine fields
                "status": pkg.human_review.status,
                "status_label": pkg.human_review.current_status.label,
                "is_pending": pkg.human_review.is_pending,
                "is_terminal": pkg.human_review.is_terminal,
                "status_history": pkg.human_review.status_history,
                # Allowed next transitions (for UI buttons)
                "_next": sorted(s.value for s in _allowed_next(pkg.human_review.current_status)),
            },
        }


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------


def _resolve_path(package_id: str) -> Path:
    """Resolve the JSON path for a decision package."""
    return DECISIONS_DIR / f"{package_id}.json"


def _allowed_next(current: Any) -> set[Any]:
    """Return valid next statuses (excluding self)."""
    from qp.decision.state_machine import allowed_transitions

    allowed = allowed_transitions(current)
    allowed.discard(current)
    return allowed


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------


def _regime_label(regime: str) -> str:
    """Human-readable Chinese label for market regime."""
    labels = {
        "bull": "🐂 牛市 / BULL",
        "bear": "🐻 熊市 / BEAR",
        "neutral": "⚪ 震荡 / NEUTRAL",
        "crisis": "🔴 危机 / CRISIS",
        "sideways_up": "🟡 横盘偏多 / SIDEWAYS UP",
        "sideways_down": "🟠 横盘偏空 / SIDEWAYS DOWN",
        "unknown": "❓ 未知 / UNKNOWN",
    }
    return labels.get(regime, regime)


def _regime_badge_class(regime: str) -> str:
    """CSS class for regime badge color."""
    classes = {
        "bull": "badge-green",
        "bear": "badge-red",
        "neutral": "badge-yellow",
        "crisis": "badge-red",
        "sideways_up": "badge-yellow",
        "sideways_down": "badge-orange",
        "unknown": "badge-gray",
    }
    return classes.get(regime, "badge-gray")
