"""Factor Report Generator — auto-generate markdown factor research reports.

Produces single-factor and overview reports with:
  - IC statistics (mean, IR, t-stat, decay curve)
  - Lifecycle state and recommended action
  - Multi-horizon IC decay (1d/3d/5d/10d/20d)
  - Factor correlation matrix
  - Alpha Family assignment
  - Regime dependency (if available)

Usage:
    gen = FactorReportGenerator()
    report = gen.generate_single("Momentum_3M")
    gen.save_report(report, "Momentum_3M")
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from qp.shared.paths import KNOWLEDGE_DIR


class FactorReportGenerator:
    """Auto-generate factor research reports in markdown format."""

    def __init__(self, output_dir: str | Path = KNOWLEDGE_DIR) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Single-factor report
    # ------------------------------------------------------------------

    def generate_single(self, factor_name: str) -> str | None:
        """Generate a single-factor research report.

        Args:
            factor_name: Factor identifier.

        Returns:
            Markdown report string, or None if no data available.
        """
        from qp.web.services.factor_health_service import FactorHealthService

        svc = FactorHealthService()
        detail = svc.factor_detail(factor_name, days=252)

        if detail.get("is_empty"):
            return None

        overview = svc.overview()
        family_name = svc.FAMILY_MAP.get(factor_name, "其他 Other")

        lines: list[str] = []
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        # Header
        lines.append(f"# Factor Research Report: {factor_name}")
        lines.append(f"**Generated**: {now}")
        lines.append(f"**Category**: {family_name}")
        lines.append("")

        # ── Lifecycle Status ──
        stage = detail["stage"]
        icon = detail["icon"]
        label = detail["stage_label"]
        lines.append("## 1. Lifecycle Status")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Stage | {icon} {label} (`{stage}`) |")
        lines.append(f"| IC Mean (full) | {detail['ic_mean']:+.4f} |")
        lines.append(f"| IC 30d | {detail['ic_30d']:+.4f} |")
        lines.append(f"| IC 90d | {detail['ic_90d']:+.4f} |")
        lines.append(f"| IC 252d | {detail['ic_252d']:+.4f} |")
        lines.append(f"| IC IR | {detail['ic_ir']:.2f} |")
        lines.append(f"| IC Decay Rate | {detail['ic_decay_rate']:+.6f}/day |")
        lines.append(f"| IC>0% | {detail['ic_positive_pct']:.1f}% |")
        lines.append(f"| N Days | {detail['n_days']} |")

        action = detail.get("recommended_action", "")
        if action:
            lines.append(f"| Recommended Action | {action} |")
        lines.append("")

        # ── Multi-horizon IC decay ──
        lines.append("## 2. IC Decay Curve (Multi-Horizon)")
        lines.append("")
        # Try to load from health logger
        try:
            from qp.monitoring.factor_health_logger import FactorHealthLogger

            logger = FactorHealthLogger()
            latest_record = logger.load_latest(factor_name)
            if latest_record:
                lines.append("| Horizon | IC Mean |")
                lines.append("|---------|---------|")
                for h in [1, 3, 5, 10, 20]:
                    ic_val = latest_record.get(f"ic_{h}d", 0.0)
                    lines.append(f"| {h}d | {ic_val:+.4f} |")
                lines.append("")
                lines.append("> **解读**: IC 随 horizon 延长而衰减是健康的（信息逐渐被市场消化）。")
                lines.append("> 如果 IC 在长 horizon 反而上升，可能存在数据泄漏或反向预测问题。")
                lines.append("")
        except Exception:
            lines.append(
                "> Multi-horizon IC data not yet available. Run an experiment to populate."
            )
            lines.append("")

        # ── Assessment ──
        lines.append("## 3. Assessment")
        lines.append("")

        ic_30d = detail["ic_30d"]
        ic_ir = detail["ic_ir"]

        # IC strength
        if abs(ic_30d) >= 0.05:
            lines.append("- **IC Strength**: ✅ Strong (|IC| ≥ 0.05)")
        elif abs(ic_30d) >= 0.02:
            lines.append("- **IC Strength**: ⚠️ Moderate (0.02 ≤ |IC| < 0.05)")
        else:
            lines.append("- **IC Strength**: ❌ Weak (|IC| < 0.02)")

        # IC stability
        if ic_ir >= 0.50:
            lines.append("- **IC Stability**: ✅ Excellent (IR ≥ 0.50)")
        elif ic_ir >= 0.30:
            lines.append("- **IC Stability**: ⚠️ Adequate (0.30 ≤ IR < 0.50)")
        else:
            lines.append("- **IC Stability**: ❌ Unstable (IR < 0.30)")

        # Direction
        if ic_30d > 0:
            lines.append("- **Direction**: Factor value POSITIVELY correlated with future returns")
        else:
            lines.append("- **Direction**: Factor value NEGATIVELY correlated with future returns")

        # Summary
        summary = detail.get("summary", "")
        if summary:
            lines.append("")
            lines.append(f"> {summary}")

        lines.append("")

        # ── Correlation ──
        lines.append("## 4. Factor Correlation")
        lines.append("")
        corr = overview.get("correlation", {})
        related_pairs = [
            p
            for p in corr.get("pairs", [])
            if p["factor_a"] == factor_name or p["factor_b"] == factor_name
        ][:10]
        if related_pairs:
            lines.append("| Factor A | Factor B | IC Similarity |")
            lines.append("|----------|----------|:-------------:|")
            for p in related_pairs:
                lines.append(f"| {p['factor_a']} | {p['factor_b']} | {p['similarity']:.3f} |")
        else:
            lines.append("> No correlation data available.")
        lines.append("")

        # ── Family Context ──
        lines.append("## 5. Alpha Family Context")
        lines.append("")
        families = overview.get("families", {})
        for fam in families.get("families", []):
            if factor_name in fam.get("member_names", []):
                lines.append(f"- **Family**: {fam['name']}")
                lines.append(f"- **Weighted IC**: {fam.get('ic_30d_weighted', 0):+.4f}")
                lines.append(f"- **Dominant Stage**: {fam.get('dominant_stage', 'unknown')}")
                lines.append(f"- **Members**: {', '.join(fam.get('member_names', []))}")
                if fam.get("suggest_composite"):
                    lines.append("- **Suggestion**: Consider merging into composite factor")
                break
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Overview report
    # ------------------------------------------------------------------

    def generate_overview(self) -> str | None:
        """Generate a factor health overview report for all factors.

        Returns:
            Markdown report string, or None if no data.
        """
        from qp.web.services.factor_health_service import FactorHealthService

        svc = FactorHealthService()
        overview = svc.overview()

        if overview.get("is_empty"):
            return None

        lines: list[str] = []
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        lines.append("# Factor Health Overview Report")
        lines.append(f"**Generated**: {now}")
        lines.append(f"**Total Factors**: {overview['n_factors']}")
        lines.append("")

        # ── Lifecycle Summary ──
        lines.append("## 1. Lifecycle Distribution")
        lines.append("")
        lines.append("| Stage | Count |")
        lines.append("|-------|:-----:|")
        counts = overview["counts"]
        stage_labels = [
            ("production", "🚀 Production"),
            ("weakening", "🟠 Weakening"),
            ("validated", "✅ Validated"),
            ("research", "🔬 Research"),
            ("degraded", "🔴 Degraded"),
            ("retired", "💀 Retired"),
            ("archived", "📦 Archived"),
        ]
        for stage, label in stage_labels:
            n = counts.get(stage, 0)
            if n:
                lines.append(f"| {label} | {n} |")
        lines.append("")

        # ── Factor List ──
        lines.append("## 2. Factor Details")
        lines.append("")
        lines.append("| Factor | Stage | IC_30d | IC_IR | N Days | Contribution |")
        lines.append("|--------|-------|:------:|:-----:|:------:|:------------:|")
        for f in overview["factors"]:
            lines.append(
                f"| {f['icon']} {f['name']} | {f['stage_label']} "
                f"| {f['ic_30d']:+.4f} | {f['ic_ir']:.2f} "
                f"| {f['n_days']} | {f.get('contribution_pct', 0):.1f}% |"
            )
        lines.append("")

        # ── Alpha Families ──
        families = overview.get("families", {})
        if families.get("has_data"):
            lines.append("## 3. Alpha Family Clusters")
            lines.append("")
            lines.append("| Family | Members | Weighted IC | Dominant Stage |")
            lines.append("|--------|:-------:|:-----------:|:--------------:|")
            for fam in families.get("families", []):
                lines.append(
                    f"| {fam['name']} | {len(fam.get('member_names', []))} "
                    f"| {fam.get('ic_30d_weighted', 0):+.4f} "
                    f"| {fam.get('dominant_stage', 'unknown')} |"
                )
            lines.append("")

        # ── Recommendations ──
        recs = overview.get("recommendations", [])
        if recs:
            lines.append("## 4. Recommendations")
            lines.append("")
            for r in recs:
                sev_icon = {"danger": "🔴", "warning": "⚠️", "info": "📊", "success": "✅"}.get(
                    r.get("severity", ""), "•"
                )
                lines.append(f"- {sev_icon} **{r.get('factor', '')}**: {r.get('message', '')}")
                action = r.get("action", "")
                if action:
                    lines.append(f"  → Action: {action}")
            lines.append("")

        # ── Redundant Pairs ──
        corr = overview.get("correlation", {})
        redundant = corr.get("redundant", [])
        if redundant:
            lines.append("## 5. Redundant Factor Pairs (Similarity > 0.70)")
            lines.append("")
            for pair in redundant[:10]:
                lines.append(
                    f"- {pair['factor_a']} ↔ {pair['factor_b']} "
                    f"(similarity: {pair['similarity']:.3f})"
                )
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_report(self, report: str, name: str) -> Path:
        """Save a report to disk.

        Args:
            report: Markdown report content.
            name: Factor name or 'overview' for overview report.

        Returns:
            Path to saved report file.
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"factor_report_{name}_{timestamp}.md"
        path = self._output_dir / filename
        path.write_text(report)
        return path
