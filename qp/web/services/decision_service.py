"""DecisionService — read-only access to DecisionPackage data.

Bridges the QP Decision layer (Layer 8) to the Web layer.
Returns plain dicts — never exposes domain objects to templates.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from qp.decision.decision_package import DecisionPackage


class DecisionService:
    """Read-only service for decision data.

    Usage:
        svc = DecisionService()
        latest = svc.latest()  # Today's decision package
        history = svc.history(limit=30)  # Recent decisions
        detail = svc.get_by_id("dp-2026-07-26-xxx")  # Specific package
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
            # Fall back to most recent from index
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
        from pathlib import Path

        path = Path("data/decisions") / f"{package_id}.json"
        if not path.exists():
            logger.warning("DecisionPackage not found: {}", package_id)
            return None

        try:
            pkg = DecisionPackage.from_json(path)
            return self._package_to_dict(pkg)
        except Exception as e:
            logger.error("Failed to load DecisionPackage {}: {}", package_id, e)
            return None

    def mark_reviewed(self, package_id: str, notes: str = "") -> dict[str, Any] | None:
        """Mark a decision package as human-reviewed.

        Updates the JSON file on disk and the index.
        """
        from pathlib import Path

        path = Path("data/decisions") / f"{package_id}.json"
        if not path.exists():
            logger.warning("DecisionPackage not found for review: {}", package_id)
            return None

        try:
            pkg = DecisionPackage.from_json(path)
            pkg.human_review.reviewed = True
            pkg.human_review.reviewer = "webui"
            pkg.human_review.notes = notes or pkg.human_review.notes
            pkg.to_json(path)
            pkg.update_index()
            logger.info("DecisionPackage reviewed: {}", package_id)
            return self._package_to_dict(pkg)
        except Exception as e:
            logger.error("Failed to mark reviewed {}: {}", package_id, e)
            return None

    def mark_executed(self, package_id: str) -> dict[str, Any] | None:
        """Mark a decision package as executed (trades placed).

        Updates the JSON file on disk and the index.
        """
        from datetime import UTC, datetime
        from pathlib import Path

        path = Path("data/decisions") / f"{package_id}.json"
        if not path.exists():
            logger.warning("DecisionPackage not found for execution: {}", package_id)
            return None

        try:
            pkg = DecisionPackage.from_json(path)
            pkg.human_review.executed = True
            pkg.human_review.execution_time = datetime.now(UTC).isoformat()
            pkg.to_json(path)
            pkg.update_index()
            logger.info("DecisionPackage executed: {}", package_id)
            return self._package_to_dict(pkg)
        except Exception as e:
            logger.error("Failed to mark executed {}: {}", package_id, e)
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

        path = Path("data/decisions") / f"{package_id}.json"
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
        risk_entries = [
            {
                "symbol": e.symbol,
                "violation_type": e.violation_type,
                "detail": e.detail,
                "threshold": e.threshold,
                "actual": e.actual,
                "action": e.action,
            }
            for e in pkg.risk_audit.entries
        ]

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
                    {"sector": k, "weight_pct": round(v * 100, 1)}
                    for k, v in sorted(
                        pkg.risk_audit.sector_exposure.items(),
                        key=lambda x: -x[1],
                    )
                ],
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
            },
        }


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
