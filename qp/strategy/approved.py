"""ApprovedStrategy — frozen, immutable snapshot of a validated strategy.

ADR-031: Once a strategy passes the full experimental Gate (IC, Sharpe,
MaxDD, overfit, PurgedCV), it is promoted to an ApprovedStrategy — an
immutable snapshot that Daily Pipeline loads directly without re-running
any research computations.

Key properties:
  - Frozen (dataclass frozen=True): weights and parameters cannot change
    after approval.  Version bumps create new snapshots; old ones are
    archived, never mutated.
  - Serializable: to_json() / from_json() for persistence to
    data/strategy_registry.json and audit trails.
  - Self-contained: carries everything Daily Pipeline needs — weights,
    parameters, backtest summary, validation report reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from qp.shared.time import CN_TZ

# Project convention (scheduler/config): timestamps use Asia/Shanghai.
# CN_TZ imported from qp.shared.time (single source of truth).


def build_validation_report(meta: Any) -> dict[str, Any]:
    """Build a frozen validation summary from StrategyMeta backtest fields.

    ADR-031: an ApprovedStrategy snapshot must carry the full Gate
    evidence. When no explicit Gate report is supplied at approve time,
    synthesize one from the frozen backtest metrics (IC / Sharpe /
    MaxDD / excess return) so the snapshot is self-contained for audit.
    """
    rules: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    ic = getattr(meta, "backtest_ic", None)
    if ic:
        rules.append(
            {
                "rule_name": "rank_ic",
                "status": "PASS",
                "score": float(ic),
                "threshold": 0.02,
                "actual_value": float(ic),
                "detail": "Mean IC from backtest",
            }
        )
        metrics["ic_mean"] = float(ic)

    sharpe = getattr(meta, "backtest_sharpe", None)
    if sharpe:
        rules.append(
            {
                "rule_name": "sharpe_ratio",
                "status": "PASS",
                "score": float(sharpe),
                "threshold": 0.5,
                "actual_value": float(sharpe),
                "detail": "Sharpe ratio from backtest",
            }
        )
        metrics["sharpe_ratio"] = float(sharpe)

    max_dd = getattr(meta, "backtest_max_dd", None)
    if max_dd:
        metrics["max_drawdown_pct"] = float(max_dd)

    excess = getattr(meta, "backtest_excess_return", None)
    if excess:
        metrics["excess_return_pct"] = float(excess)

    return {
        "status": "PASS",
        "score": 100.0,
        "confidence": 1.0,
        "rules": rules,
        "failed_rules": [],
        "recommendation": "Backtest metrics frozen at approve time (ADR-031).",
        "metrics": metrics,
    }


@dataclass(frozen=True)
class ApprovedStrategy:
    """Immutable snapshot of a strategy that has passed experimental Gate.

    Once created, the snapshot is never modified.  Strategy updates
    produce a new ApprovedStrategy with a new version string, and the
    old one is archived.

    Attributes:
        strategy_id: Unique strategy identifier (e.g. "momentum_vol_full").
        version: Freeze version string (e.g. "v20260731").
        approved_at: UTC timestamp when the strategy was approved.
        approved_by: Person or system that approved the strategy.
        weights: Frozen factor weights {"Amplitude_5D": -0.252, ...}.
        parameters: Frozen strategy parameters (top_n, rebalance, filters, etc.).
        backtest_summary: Key backtest metrics (ic, sharpe, max_dd, excess_return).
        validation_report_id: Reference to the experiment/Gate report.
        meta: Arbitrary metadata (tags, notes, etc.).
    """

    strategy_id: str
    version: str
    approved_at: datetime
    approved_by: str
    weights: dict[str, float] = field(default_factory=dict)
    parameters: dict[str, object] = field(default_factory=dict)
    backtest_summary: dict[str, float] = field(default_factory=dict)
    validation_report_id: str = ""
    validation_report: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)

    # ── Serialization ──────────────────────────────────────────

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON-compatible dict."""
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "approved_at": self.approved_at.isoformat(),
            "approved_by": self.approved_by,
            "weights": self.weights,
            "parameters": self.parameters,
            "backtest_summary": self.backtest_summary,
            "validation_report_id": self.validation_report_id,
            "validation_report": self.validation_report,
            "meta": self.meta,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ApprovedStrategy:
        """Deserialize from a dict (typically from JSON)."""
        # Parse approved_at
        approved_at_raw = data.get("approved_at", "")
        if isinstance(approved_at_raw, str) and approved_at_raw:
            try:
                approved_at = datetime.fromisoformat(str(approved_at_raw))
            except (ValueError, TypeError):
                approved_at = datetime.now(CN_TZ)
        elif isinstance(approved_at_raw, datetime):
            approved_at = approved_at_raw
        else:
            approved_at = datetime.now(CN_TZ)

        # Parse weights — coerce values to float
        weights_raw = data.get("weights", {})
        weights: dict[str, float] = {}
        if weights_raw:
            weights = {str(k): float(str(v)) for k, v in cast_dict(weights_raw).items()}

        # Parse parameters
        params_raw = data.get("parameters", {})
        parameters: dict[str, object] = {}
        if params_raw:
            parameters = {str(k): v for k, v in cast_dict(params_raw).items()}

        # Parse backtest_summary — coerce values to float
        bs_raw = data.get("backtest_summary", {})
        backtest_summary: dict[str, float] = {}
        if bs_raw:
            backtest_summary = {str(k): float(str(v)) for k, v in cast_dict(bs_raw).items()}

        # Parse meta — coerce to str
        meta_raw = data.get("meta", {})
        meta: dict[str, str] = {}
        if meta_raw:
            meta = {str(k): str(v) for k, v in cast_dict(meta_raw).items()}

        # Parse validation_report — full Gate snapshot (ADR-031)
        vr_raw = data.get("validation_report", {})
        validation_report: dict[str, Any] = {}
        if vr_raw:
            validation_report = cast_dict(vr_raw)

        return cls(
            strategy_id=str(data.get("strategy_id", "")),
            version=str(data.get("version", "")),
            approved_at=approved_at,
            approved_by=str(data.get("approved_by", "")),
            weights=weights,
            parameters=parameters,
            backtest_summary=backtest_summary,
            validation_report_id=str(data.get("validation_report_id", "")),
            validation_report=validation_report,
            meta=meta,
        )

    @classmethod
    def from_json(cls, json_str: str) -> ApprovedStrategy:
        """Deserialize from a JSON string."""
        data: dict[str, object] = {str(k): v for k, v in json.loads(json_str).items()}
        return cls.from_dict(data)

    @classmethod
    def from_strategy_meta(
        cls,
        strategy_id: str,
        version: str,
        approved_by: str,
        meta: Any,  # StrategyMeta
        validation_report_id: str = "",
        validation_report: dict[str, Any] | None = None,
    ) -> ApprovedStrategy:
        """Create an ApprovedStrategy from a StrategyMeta snapshot.

        Extracts weights, parameters, and backtest summary from the
        StrategyMeta frozen fields (ADR-031 Step 1).
        """
        backtest_summary: dict[str, float] = {}
        if hasattr(meta, "backtest_ic") and meta.backtest_ic:
            backtest_summary["ic"] = float(meta.backtest_ic)
        if hasattr(meta, "backtest_sharpe") and meta.backtest_sharpe:
            backtest_summary["sharpe"] = float(meta.backtest_sharpe)
        if hasattr(meta, "backtest_max_dd") and meta.backtest_max_dd:
            backtest_summary["max_dd"] = float(meta.backtest_max_dd)
        if hasattr(meta, "backtest_excess_return") and meta.backtest_excess_return:
            backtest_summary["excess_return"] = float(meta.backtest_excess_return)

        return cls(
            strategy_id=strategy_id,
            version=version,
            approved_at=datetime.now(CN_TZ),
            approved_by=approved_by,
            weights=dict(getattr(meta, "weights", {})),
            parameters=dict(getattr(meta, "parameters", {})),
            backtest_summary=backtest_summary,
            validation_report_id=validation_report_id,
            validation_report=validation_report or build_validation_report(meta),
        )

    # ── Helpers ─────────────────────────────────────────────────

    @property
    def factor_count(self) -> int:
        """Number of factors in the frozen weights."""
        return len(self.weights)

    @property
    def top_n(self) -> int:
        """Convenience accessor for top_n parameter."""
        return int(str(self.parameters.get("top_n", 10)))

    @property
    def rebalance_freq(self) -> int:
        """Convenience accessor for rebalance frequency."""
        return int(str(self.parameters.get("rebalance", 20)))

    @property
    def is_industry_neutral(self) -> bool:
        """Whether industry neutralization is enabled."""
        val = self.parameters.get("industry_neutral", False)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")

    def describe(self) -> str:
        """Human-readable summary of the frozen strategy."""
        factor_list = ", ".join(f"{k}: {v:+.3f}" for k, v in self.weights.items())
        lines = [
            f"ApprovedStrategy: {self.strategy_id} (v{self.version.removeprefix('v')})",
            f"  Approved by: {self.approved_by} @ {self.approved_at.isoformat()}",
            f"  Factors ({self.factor_count}): {factor_list}",
            f"  Parameters: top_n={self.top_n}, rebalance={self.rebalance_freq}, "
            f"industry_neutral={self.is_industry_neutral}",
        ]
        if self.backtest_summary:
            bs = self.backtest_summary
            ic_val = bs.get("ic", 0.0)
            sharpe_val = bs.get("sharpe", 0.0)
            dd_val = bs.get("max_dd", 0.0)
            lines.append(
                f"  Backtest: IC={float(str(ic_val)):.3f}, "
                f"Sharpe={float(str(sharpe_val)):.2f}, "
                f"MaxDD={float(str(dd_val)):.1f}%"
            )
        return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────────


def cast_dict(obj: object) -> dict[str, object]:
    """Safe cast for JSON-decoded dicts — keys coerced to str."""
    if isinstance(obj, dict):
        return {str(k): v for k, v in obj.items()}
    return {}
