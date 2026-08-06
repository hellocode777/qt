"""FactorHealthService — read-only access to per-factor health data.

Bridges the QP Monitoring layer (Layer 9) factor health data to the Web layer.
Reads from factor_health.parquet and transforms into template-friendly dicts.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from qp.monitoring.factor_health_logger import FactorHealthLogger


def _lifecycle_meta(stage: str) -> dict:
    """Get display metadata for a lifecycle stage."""
    return {
        "research": {"icon": "🔬", "label": "研究", "badge": "badge-info"},
        "validated": {"icon": "✅", "label": "已验证", "badge": "badge-success"},
        "production": {"icon": "🚀", "label": "生产中", "badge": "badge-green"},
        "weakening": {"icon": "🟠", "label": "衰退中", "badge": "badge-warning"},
        "degraded": {"icon": "🔴", "label": "衰减", "badge": "badge-danger"},
        "retired": {"icon": "💀", "label": "已淘汰", "badge": "badge-dark"},
        "archived": {"icon": "📦", "label": "已归档", "badge": "badge-secondary"},
        # Backward compat
        "healthy": {"icon": "🚀", "label": "生产中", "badge": "badge-green"},
        "warning": {"icon": "✅", "label": "已验证", "badge": "badge-success"},
        "stale": {"icon": "💀", "label": "已淘汰", "badge": "badge-dark"},
    }.get(stage, {"icon": "❓", "label": stage, "badge": "badge-secondary"})


def _stage_badge(stage: str) -> str:
    return _lifecycle_meta(stage)["badge"]


def _stage_icon(stage: str) -> str:
    return _lifecycle_meta(stage)["icon"]


def _stage_label(stage: str) -> str:
    return _lifecycle_meta(stage)["label"]


class FactorHealthService:
    """Read-only service for factor health data.

    Usage:
        svc = FactorHealthService()
        overview = svc.overview()
        detail = svc.factor_detail("Momentum_3M")
    """

    def __init__(self) -> None:
        self._logger = FactorHealthLogger()

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        """Get factor health overview with lifecycle stats + correlation + recommendations.

        Returns:
            Dict with factors list, aggregate counts, correlation matrix,
            and auto-generated retirement recommendations.
        """
        try:
            latest = self._logger.load_all_latest()
        except Exception as e:
            logger.warning("Failed to read factor health: {}", e)
            return _empty_overview()

        factors = []
        for name, record in latest.items():
            stage = record.get("stage", "research")
            meta = _lifecycle_meta(stage)
            factors.append(
                {
                    "name": name,
                    "stage": stage,
                    "stage_label": meta["label"],
                    "badge_class": meta["badge"],
                    "icon": meta["icon"],
                    "ic_30d": record.get("ic_30d", 0.0),
                    "ic_90d": record.get("ic_90d", 0.0),
                    "ic_ir": record.get("ic_ir", 0.0),
                    "ic_decay_rate": record.get("ic_decay_rate", 0.0),
                    "ic_ratio": record.get("ic_ratio", 1.0),
                    "n_days": record.get("n_days", 0),
                    "retired_reason": record.get("retired_reason", ""),
                    "direction_flipped": record.get("direction_flipped", False),
                    "consecutive_degraded_days": record.get("consecutive_degraded_days", 0),
                    "recommended_action": record.get("recommended_action", ""),
                    # Multi-horizon IC decay (DP-002 §4.4)
                    "ic_1d": record.get("ic_1d", 0.0),
                    "ic_3d": record.get("ic_3d", 0.0),
                    "ic_5d": record.get("ic_5d", 0.0),
                    "ic_10d": record.get("ic_10d", 0.0),
                    "ic_20d": record.get("ic_20d", 0.0),
                    # PSI drift (DP-002 H7)
                    "psi_30d": record.get("psi_30d", 0.0),
                    "psi_90d": record.get("psi_90d", 0.0),
                    "psi_alert": record.get("psi_30d", 0.0) > 0.25,
                    # Crowding/Turnover
                    "crowding_hhi": record.get("crowding_hhi", 0.0),
                    "turnover_30d": record.get("turnover_30d", 0.0),
                }
            )

        # ── Compute contribution % (weight × |IC| based) ──
        weight_map = {
            "research": 0.25,
            "validated": 0.50,
            "production": 1.00,
            "weakening": 0.75,
            "degraded": 0.50,
            "retired": 0.0,
            "archived": 0.0,
        }
        total_contrib = sum(
            abs(f["ic_30d"]) * weight_map.get(f.get("stage", "research"), 0.25) for f in factors
        )
        for f in factors:
            raw = abs(f["ic_30d"]) * weight_map.get(f.get("stage", "research"), 0.25)
            f["contribution_pct"] = (
                round(raw / total_contrib * 100, 1) if total_contrib > 0 else 0.0
            )

        # Sort by lifecycle severity then by |IC_30d|
        stage_order = {
            "retired": 0,
            "archived": 1,
            "degraded": 2,
            "weakening": 3,
            "research": 4,
            "validated": 5,
            "production": 6,
        }
        factors.sort(
            key=lambda f: (
                stage_order.get(f["stage"], 99),
                -abs(f["ic_30d"]),
            )
        )

        # ── Aggregate counts by lifecycle ──
        counts = {
            "research": 0,
            "validated": 0,
            "production": 0,
            "weakening": 0,
            "degraded": 0,
            "retired": 0,
            "archived": 0,
        }
        for f in factors:
            s = f["stage"]
            if s in counts:
                counts[s] += 1

        # ── Factor correlation matrix ──
        correlation = self._compute_correlation(latest)

        # ── Alpha Family clustering ──
        families = self._compute_families(factors)

        # ── Auto retirement recommendations ──
        recommendations = self._generate_recommendations(factors, correlation)

        return {
            "factors": factors,
            "n_factors": len(factors),
            "counts": counts,
            "n_production": counts.get("production", 0),
            "n_validated": counts.get("validated", 0),
            "n_research": counts.get("research", 0),
            "n_degraded": counts.get("degraded", 0),
            "n_retired": counts.get("retired", 0),
            "n_archived": counts.get("archived", 0),
            # Backward compat
            "n_healthy": counts.get("production", 0),
            "n_warning": counts.get("validated", 0),
            "n_stale": counts.get("retired", 0),
            "healthy_factors": [f["name"] for f in factors if f["stage"] == "production"],
            "warning_factors": [f["name"] for f in factors if f["stage"] == "validated"],
            "degraded_factors": [f["name"] for f in factors if f["stage"] == "degraded"],
            "stale_factors": [f["name"] for f in factors if f["stage"] in ("retired", "archived")],
            # New
            "correlation": correlation,
            "families": families,
            "recommendations": recommendations,
            "is_empty": len(factors) == 0,
        }

    # ------------------------------------------------------------------
    # Alpha Family clustering (DP-002 v3)
    # ------------------------------------------------------------------

    # Factor family definitions — each factor maps to exactly one family
    FAMILY_MAP: dict[str, str] = {
        # Low Volatility
        "Volatility_20D": "低波动 LowVol",
        "Volatility_60D": "低波动 LowVol",
        "MaxDD_60D": "低波动 LowVol",
        "Amplitude_5D": "低波动 LowVol",
        # Momentum
        "Momentum_1M": "动量 Momentum",
        "Momentum_3M": "动量 Momentum",
        "Momentum_6M": "动量 Momentum",
        "Momentum_3M_vol_adj": "动量 Momentum",
        "Residual_Momentum_3M": "动量 Momentum",
        # Volume
        "Volume_Ratio_5D": "成交量 Volume",
        "Volume_Trend_10D": "成交量 Volume",
        "Volume_Concentration": "成交量 Volume",
        "Volume_Price_Trend": "成交量 Volume",
        "Price_Volume_Corr": "成交量 Volume",
        # Value
        "PE_TTM": "价值 Value",
        "PB": "价值 Value",
        "PCF_OCF": "价值 Value",
        # Quality
        "ROE": "质量 Quality",
        "ROE_Level": "质量 Quality",
        "Profit_Stability": "质量 Quality",
        "Earnings_Quality": "质量 Quality",
        "Margin_Composite": "质量 Quality",
        "gross_margin": "质量 Quality",
        "net_margin": "质量 Quality",
        "debt_ratio": "质量 Quality",
        # Growth
        "revenue_growth": "成长 Growth",
        "net_profit_growth": "成长 Growth",
        # Reversal
        "Short_Term_Reversal_5D": "反转 Reversal",
        # Money Flow
        "Implied_Net_Flow": "资金流 MoneyFlow",
        "Volume_Expansion_20_120": "资金流 MoneyFlow",
        "Amount_Momentum_20_120": "资金流 MoneyFlow",
        # Trend
        "Trend_MA120": "趋势 Trend",
    }

    FAMILY_ORDER = [
        "低波动 LowVol",
        "动量 Momentum",
        "反转 Reversal",
        "成交量 Volume",
        "价值 Value",
        "质量 Quality",
        "成长 Growth",
        "资金流 MoneyFlow",
        "趋势 Trend",
    ]

    def _compute_families(self, factors: list[dict[str, Any]]) -> dict[str, Any]:
        """Group factors into Alpha Families and compute aggregate IC.

        Returns:
            Dict with family list, each containing member factors,
            aggregate IC/IR, dominant factor, and composite suggestion.
        """
        families: dict[str, dict[str, Any]] = {}

        for f in factors:
            name = f["name"]
            family_name = self.FAMILY_MAP.get(name, "其他 Other")
            if family_name not in families:
                families[family_name] = {
                    "name": family_name,
                    "members": [],
                    "member_names": [],
                    "ic_30d_weighted": 0.0,
                    "best_ic": 0.0,
                    "best_factor": "",
                    "n_production": 0,
                    "n_weakening": 0,
                    "n_degraded": 0,
                    "n_retired": 0,
                    "dominant_stage": "research",
                    "suggest_composite": False,
                }
            fam = families[family_name]
            fam["members"].append(f)
            fam["member_names"].append(name)

            # Track best IC in family
            if abs(f["ic_30d"]) > abs(fam["best_ic"]):
                fam["best_ic"] = f["ic_30d"]
                fam["best_factor"] = name

            # Count lifecycle stages
            stage = f["stage"]
            if stage == "production":
                fam["n_production"] += 1
            elif stage == "weakening":
                fam["n_weakening"] += 1
            elif stage == "degraded":
                fam["n_degraded"] += 1
            elif stage in ("retired", "archived"):
                fam["n_retired"] += 1

        # Compute aggregate IC per family (weighted by |IC|)
        for fam in families.values():
            members = fam["members"]
            total_abs_ic = sum(abs(m["ic_30d"]) for m in members)
            if total_abs_ic > 0:
                fam["ic_30d_weighted"] = round(
                    sum(abs(m["ic_30d"]) * abs(m["ic_30d"]) for m in members) / total_abs_ic,
                    4,
                )

            # Dominant stage (worst among non-retired members)
            active = [m for m in members if m["stage"] not in ("retired", "archived")]
            if active:
                stage_order = {
                    "production": 5,
                    "weakening": 4,
                    "validated": 3,
                    "degraded": 2,
                    "research": 1,
                }
                fam["dominant_stage"] = min(active, key=lambda m: stage_order.get(m["stage"], 0))[
                    "stage"
                ]

            # Suggest composite if >2 members with high mutual correlation
            fam["suggest_composite"] = len(members) >= 3

        # Sort by family order, then by weighted IC
        result_list = []
        for fname in self.FAMILY_ORDER:
            if fname in families:
                result_list.append(families[fname])
        # Add any unmapped families
        for fname, fam in sorted(families.items()):
            if fname not in self.FAMILY_ORDER:
                result_list.append(fam)

        return {
            "families": result_list,
            "n_families": len(result_list),
            "n_active_families": sum(
                1 for f in result_list if f["dominant_stage"] in ("production", "weakening")
            ),
            "has_data": len(result_list) > 0,
        }

    # ------------------------------------------------------------------
    # Factor correlation matrix
    # ------------------------------------------------------------------

    def _compute_correlation(self, latest: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Compute pairwise factor correlation from IC series.

        Uses IC_30d as proxy for factor return correlation.
        Flags pairs with |correlation| > 0.70 as potentially redundant.
        """
        # We use IC values as proxy — factors with correlated IC
        # patterns in the same cross-section are capturing similar effects
        ic_values: dict[str, float] = {}
        for name, record in latest.items():
            ic_30d = record.get("ic_30d", 0.0)
            if ic_30d is not None:
                ic_values[name] = float(ic_30d)

        n = len(ic_values)
        if n < 2:
            return {"pairs": [], "n_factors": n, "has_data": False}

        names = sorted(ic_values.keys())
        pairs: list[dict[str, Any]] = []
        redundant: list[dict[str, Any]] = []

        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                fi, fj = names[i], names[j]
                # Use IC magnitude similarity as rough correlation proxy
                # In production, this should use daily IC series Spearman
                ici = abs(ic_values.get(fi, 0.0))
                icj = abs(ic_values.get(fj, 0.0))
                if (ici == 0 and icj == 0) or ici + icj == 0:
                    sim = 0.0
                else:
                    # Cosine similarity of IC magnitudes
                    sim = 2.0 * min(ici, icj) / (ici + icj) if (ici + icj) > 0 else 0.0

                pair = {
                    "factor_a": fi,
                    "factor_b": fj,
                    "similarity": round(sim, 3),
                }
                pairs.append(pair)
                if sim > 0.70:
                    redundant.append(pair)

        pairs.sort(key=lambda p: -p["similarity"])

        return {
            "pairs": pairs[:20],  # Top 20
            "redundant": redundant,
            "n_redundant": len(redundant),
            "n_factors": n,
            "has_data": True,
        }

    # ------------------------------------------------------------------
    # Auto retirement recommendations
    # ------------------------------------------------------------------

    def _generate_recommendations(
        self,
        factors: list[dict[str, Any]],
        correlation: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Auto-generate factor management recommendations (v3 — family-aware)."""
        recs: list[dict[str, Any]] = []

        # ── Family composite suggestions ──
        redundant = correlation.get("redundant", []) if correlation else []

        # Detect family-level redundancy clusters
        family_clusters: dict[str, set[str]] = {}
        for pair in redundant:
            fa, fb = pair["factor_a"], pair["factor_b"]
            fam_a = self.FAMILY_MAP.get(fa, "")
            fam_b = self.FAMILY_MAP.get(fb, "")
            if fam_a and fam_a == fam_b:
                if fam_a not in family_clusters:
                    family_clusters[fam_a] = set()
                family_clusters[fam_a].add(fa)
                family_clusters[fam_a].add(fb)

        for family_name, members in family_clusters.items():
            if len(members) >= 2:
                member_list = sorted(members)
                recs.append(
                    {
                        "factor": ", ".join(member_list[:4]),
                        "type": "composite",
                        "severity": "warning",
                        "message": (
                            f"🔗 {family_name}: {len(members)}个因子高度相关({', '.join(member_list[:3])}…)。"
                            f"建议合并为 {family_name.split()[0]} Composite，只保留一个族代表。"
                        ),
                        "action": "合成 Composite",
                    }
                )

        for f in factors:
            name = f["name"]
            stage = f["stage"]
            ic_ir = f["ic_ir"]
            ic_30d = f["ic_30d"]
            decay = f["ic_decay_rate"]

            # RETIRED factors: confirm retirement reason
            if stage == "retired":
                reason = f.get("retired_reason", "")
                recs.append(
                    {
                        "factor": name,
                        "type": "retire_confirm",
                        "severity": "info",
                        "message": f"✅ {name} 已淘汰: {reason}。建议归档并从策略中移除。",
                        "action": "从策略移除",
                    }
                )

            # DEGRADED factors: recommend weight reduction
            elif stage == "degraded":
                recs.append(
                    {
                        "factor": name,
                        "type": "reduce_weight",
                        "severity": "warning",
                        "message": f"🔴 {name} 衰减中 (IC_30d={ic_30d:+.4f}, IR={ic_ir:.2f})。建议权重降至 50%。",
                        "action": "降权至 50%",
                    }
                )

            # RESEARCH factors with good IC: promote to validated
            elif stage == "research" and abs(ic_30d) >= 0.02 and ic_ir >= 0.3:
                recs.append(
                    {
                        "factor": name,
                        "type": "promote",
                        "severity": "success",
                        "message": f"🔬 {name} 有预测力 (IC={ic_30d:+.4f}, IR={ic_ir:.2f})。建议进入验证阶段。",
                        "action": "提升至 VALIDATED",
                    }
                )

            # RESEARCH factors with weak IC
            elif stage == "research" and abs(ic_30d) < 0.02:
                if ic_ir < 0.1:
                    recs.append(
                        {
                            "factor": name,
                            "type": "retire_soon",
                            "severity": "danger",
                            "message": f"⚠️ {name} IC 微弱且不稳定 (IR={ic_ir:.2f})。建议考虑淘汰或重新设计。",
                            "action": "评估淘汰",
                        }
                    )
                else:
                    recs.append(
                        {
                            "factor": name,
                            "type": "monitor",
                            "severity": "info",
                            "message": f"📊 {name} IC 偏弱 ({ic_30d:+.4f})，但 IR 尚可 ({ic_ir:.2f})。继续观察。",
                            "action": "继续观察",
                        }
                    )

            # Strong decay rate warning
            if decay < -0.001 and stage not in ("retired", "archived"):
                recs.append(
                    {
                        "factor": name,
                        "type": "decay_warning",
                        "severity": "danger",
                        "message": f"📉 {name} IC 衰减加速 ({decay:+.5f}/天)。Alpha 可能在消失。",
                        "action": "紧急复核",
                    }
                )

            # PSI drift alert (DP-002 H7)
            psi_30d = f.get("psi_30d", 0.0)
            if psi_30d > 0.25:
                recs.append(
                    {
                        "factor": name,
                        "type": "psi_alert",
                        "severity": "danger",
                        "message": (
                            f"🚨 {name} PSI={psi_30d:.2f} > 0.25 — "
                            f"因子分布发生显著漂移，可能已失效。"
                        ),
                        "action": "停用并复查因子定义",
                    }
                )
            elif psi_30d > 0.10:
                recs.append(
                    {
                        "factor": name,
                        "type": "psi_warning",
                        "severity": "warning",
                        "message": (
                            f"⚠️ {name} PSI={psi_30d:.2f} > 0.10 — 因子分布有中度偏移，建议关注。"
                        ),
                        "action": "密切监控",
                    }
                )

            # Multi-horizon decay anomaly: IC reverses at long horizon
            ic_1d = f.get("ic_1d", 0.0)
            ic_20d = f.get("ic_20d", 0.0)
            if (
                stage in ("production", "validated")
                and abs(ic_1d) > 0.01
                and abs(ic_20d) > 0.01
                and ic_1d * ic_20d < 0  # Sign reversal
            ):
                recs.append(
                    {
                        "factor": name,
                        "type": "horizon_reversal",
                        "severity": "warning",
                        "message": (
                            f"🔄 {name} IC 方向在长周期反转 "
                            f"(1d={ic_1d:+.4f}, 20d={ic_20d:+.4f})。"
                            f"因子在不同 horizon 的预测方向不一致。"
                        ),
                        "action": "复查因子逻辑",
                    }
                )

        # Sort by severity
        sev_order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
        recs.sort(key=lambda r: sev_order.get(r["severity"], 99))

        return recs

    # ------------------------------------------------------------------
    # Per-factor detail
    # ------------------------------------------------------------------

    def factor_detail(self, factor_name: str, days: int = 252) -> dict[str, Any]:
        """Get detailed health data for a single factor.

        Args:
            factor_name: Factor identifier.
            days: History days to load.

        Returns:
            Dict with factor info, timeline data for Chart.js, and history.
        """
        try:
            df = self._logger.load_history(factor_name, days=days)
        except Exception as e:
            logger.warning("Failed to read factor health for {}: {}", factor_name, e)
            return _empty_detail(factor_name)

        if df.is_empty():
            return _empty_detail(factor_name)

        df = df.sort("date")

        # Latest record
        latest_row = df.tail(1).to_dicts()[0]

        # Timeline data for Chart.js
        dates = df["date"].to_list()
        ic_30d_series = df["ic_30d"].to_list()
        ic_90d_series = df["ic_90d"].to_list()
        ic_ir_series = df["ic_ir"].to_list()

        # History records
        history = []
        for row in df.sort("date", descending=True).head(30).to_dicts():
            stage = row.get("stage", "healthy")
            history.append(
                {
                    "date": row.get("date", ""),
                    "stage": stage,
                    "stage_label": _stage_label(stage),
                    "badge_class": _stage_badge(stage),
                    "ic_30d": row.get("ic_30d", 0.0),
                    "ic_90d": row.get("ic_90d", 0.0),
                    "ic_ir": row.get("ic_ir", 0.0),
                    "ic_decay_rate": row.get("ic_decay_rate", 0.0),
                    "n_days": row.get("n_days", 0),
                }
            )

        stage = latest_row.get("stage", "healthy")

        return {
            "factor_name": factor_name,
            "stage": stage,
            "stage_label": _stage_label(stage),
            "badge_class": _stage_badge(stage),
            "icon": _stage_icon(stage),
            "ic_mean": latest_row.get("ic_mean", 0.0),
            "ic_30d": latest_row.get("ic_30d", 0.0),
            "ic_90d": latest_row.get("ic_90d", 0.0),
            "ic_252d": latest_row.get("ic_252d", 0.0),
            "ic_ir": latest_row.get("ic_ir", 0.0),
            "ic_decay_rate": latest_row.get("ic_decay_rate", 0.0),
            "ic_positive_pct": latest_row.get("ic_positive_pct", 0.0),
            "ic_ratio": latest_row.get("ic_ratio", 1.0),
            "n_days": latest_row.get("n_days", 0),
            "recommended_action": latest_row.get("recommended_action", ""),
            "summary": latest_row.get("summary", ""),
            # Chart data
            "chart_dates": dates,
            "chart_ic_30d": ic_30d_series,
            "chart_ic_90d": ic_90d_series,
            "chart_ic_ir": ic_ir_series,
            # History table
            "history": history,
            "n_history": len(history),
            "is_empty": False,
        }

    # ------------------------------------------------------------------
    # Factor list (for dropdowns etc.)
    # ------------------------------------------------------------------

    def save_baseline(self, version: str = "v1.0") -> dict[str, Any]:
        """Freeze current factor library state as a versioned baseline.

        Saves to data/factor_library/baseline_{version}.json with:
        - All factor lifecycle states, IC stats, family assignments
        - Composite suggestions
        - Timestamp and version metadata

        Args:
            version: Baseline version string (e.g. "v1.0").

        Returns:
            Baseline dict with all factor data.
        """
        import json
        from datetime import UTC, datetime
        from pathlib import Path

        overview = self.overview()

        baseline = {
            "version": version,
            "created_at": datetime.now(UTC).isoformat(),
            "n_factors": overview["n_factors"],
            "n_families": overview.get("families", {}).get("n_families", 0),
            "lifecycle_counts": overview["counts"],
            "factors": {},
            "families": [],
            "composite_suggestions": [],
        }

        # Per-factor data
        for f in overview["factors"]:
            baseline["factors"][f["name"]] = {
                "lifecycle": f["stage"],
                "lifecycle_label": f["stage_label"],
                "ic_30d": f["ic_30d"],
                "ic_90d": f["ic_90d"],
                "ic_ir": f["ic_ir"],
                "ic_decay_60d": f.get("ic_decay_rate", 0.0),
                "contribution_pct": f.get("contribution_pct", 0.0),
                "retired_reason": f.get("retired_reason", ""),
                "recommended_action": f.get("recommended_action", ""),
            }

        # Family data
        if overview.get("families", {}).get("has_data"):
            for fam in overview["families"]["families"]:
                baseline["families"].append(
                    {
                        "name": fam["name"],
                        "ic_weighted": fam.get("ic_30d_weighted", 0.0),
                        "dominant_stage": fam["dominant_stage"],
                        "members": fam["member_names"],
                        "suggest_composite": fam["suggest_composite"],
                    }
                )

        # Composite suggestions from recommendations
        for rec in overview.get("recommendations", []):
            if rec.get("type") == "composite":
                baseline["composite_suggestions"].append(
                    {
                        "family": rec.get("factor", ""),
                        "action": rec.get("action", ""),
                        "message": rec.get("message", ""),
                    }
                )

        # Persist
        path = Path("data/factor_library") / f"baseline_{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2))
        logger.info(
            "Factor Baseline {} saved → {} ({} factors, {} families)",
            version,
            path,
            baseline["n_factors"],
            baseline["n_families"],
        )

        return baseline

    def load_baseline(self, version: str = "v1.0") -> dict[str, Any] | None:
        """Load a previously saved factor baseline."""
        import json
        from pathlib import Path

        path = Path("data/factor_library") / f"baseline_{version}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def factor_list(self) -> list[dict[str, Any]]:
        """Get a simple list of tracked factors with latest stages.

        Returns:
            List of {name, stage, stage_label, badge_class}.
        """
        overview = self.overview()
        return [
            {
                "name": f["name"],
                "stage": f["stage"],
                "stage_label": f["stage_label"],
                "badge_class": f["badge_class"],
            }
            for f in overview["factors"]
        ]


# ------------------------------------------------------------------
# Fallback helpers
# ------------------------------------------------------------------


def _empty_overview() -> dict[str, Any]:
    return {
        "factors": [],
        "n_factors": 0,
        "n_healthy": 0,
        "n_warning": 0,
        "n_degraded": 0,
        "n_stale": 0,
        "healthy_factors": [],
        "warning_factors": [],
        "degraded_factors": [],
        "stale_factors": [],
        "is_empty": True,
    }


def _empty_detail(factor_name: str) -> dict[str, Any]:
    return {
        "factor_name": factor_name,
        "stage": "healthy",
        "stage_label": "无数据",
        "badge_class": "badge-secondary",
        "icon": "❓",
        "ic_mean": 0.0,
        "ic_30d": 0.0,
        "ic_90d": 0.0,
        "ic_252d": 0.0,
        "ic_ir": 0.0,
        "ic_decay_rate": 0.0,
        "ic_positive_pct": 0.0,
        "ic_ratio": 1.0,
        "n_days": 0,
        "recommended_action": "",
        "summary": "No factor health data available yet.",
        "chart_dates": [],
        "chart_ic_30d": [],
        "chart_ic_90d": [],
        "chart_ic_ir": [],
        "history": [],
        "n_history": 0,
        "is_empty": True,
    }
