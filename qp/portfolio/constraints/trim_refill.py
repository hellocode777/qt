"""Trim & Refill — gradient position trimming with low-correlation rotation.

Per docs/7_Portfolio_Risk_Layer.md 精细化建议 §2:
  "先截断、后补位" (Trim & Refill):
  - 硬限制（ST、停牌、单股上限）：直接 Cut/Reject
  - 集中度限制（行业/Cluster）：梯度截断
  - 多余额度向 Alpha 排序靠后且低相关性的股票轮换

Algorithm:
  1. Sort candidates by alpha_score descending
  2. Iterate: apply hard constraints (reject immediately)
  3. Track cumulative sector/cluster/position weights
  4. When a limit is exceeded, gradient-trim (reduce weight)
  5. Collect freed weight budget
  6. Redistribute to lower-ranked, low-correlation candidates

Usage:
    from qp.portfolio.constraints import TrimAndRefill

    trimmer = TrimAndRefill()
    result = trimmer.process(candidates, cluster_labels, correlation_pairs)
    for c in result.approved:
        print(f"{c.symbol}: weight={c.max_weight_limit:.1%}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrimResult:
    """Output of the Trim & Refill process.

    Attributes:
        approved: Candidates that passed (possibly with trimmed weights).
        rejected: Candidates that were hard-rejected.
        freed_weight: Total weight freed by trimming/rejection.
        redistributed_weight: Weight successfully redistributed to refill candidates.
        refill_candidates: Candidates that received redistributed weight.
        summary: Human-readable summary.
    """

    approved: list[Any] = field(default_factory=list)
    rejected: list[Any] = field(default_factory=list)
    freed_weight: float = 0.0
    redistributed_weight: float = 0.0
    refill_candidates: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class TrimAndRefill:
    """Gradient position trimming with low-correlation refill.

    Attributes:
        max_single_position: Hard cap per stock (default 15%).
        max_single_sector: Hard cap per sector (default 30%).
        max_single_cluster: Hard cap per risk cluster (default 30%).
        trim_step: How much to trim per gradient step (e.g. 0.02 = 2%).
        max_iterations: Max number of trim-and-redistribute rounds.
        correlation_threshold: Above this → considered correlated pair.
    """

    max_single_position: float = 0.15
    max_single_sector: float = 0.30
    max_single_cluster: float = 0.30
    trim_step: float = 0.02
    max_iterations: int = 10
    correlation_threshold: float = 0.70

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process(
        self,
        candidates: list[Any],
        cluster_labels: dict[str, str] | None = None,
        correlation_pairs: list[tuple[str, str, float]] | None = None,
        sector_map: dict[str, str] | None = None,
    ) -> TrimResult:
        """Run Trim & Refill on a list of RiskApprovedCandidates.

        Args:
            candidates: Sorted candidates (by alpha_score descending).
            cluster_labels: {symbol: cluster_label} from RiskClusterer.
            correlation_pairs: [(sym_a, sym_b, corr)] from CorrelationAnalyzer.
            sector_map: {symbol: sector} from IndustryMapper.

        Returns:
            TrimResult with approved/rejected/refill info.
        """
        if cluster_labels is None:
            cluster_labels = {}
        if correlation_pairs is None:
            correlation_pairs = []
        if sector_map is None:
            sector_map = {}

        if not candidates:
            return TrimResult(summary="No candidates to process")

        # Sort by alpha_score descending
        sorted_candidates = sorted(
            candidates, key=lambda c: c.alpha_score, reverse=True
        )

        # Track cumulative weights
        cum_sector: dict[str, float] = {}
        cum_cluster: dict[str, float] = {}

        # Build correlation graph for refill lookup
        correlated_of: dict[str, set[str]] = {}
        for a, b, _ in correlation_pairs:
            correlated_of.setdefault(a, set()).add(b)
            correlated_of.setdefault(b, set()).add(a)

        approved: list[Any] = []
        rejected: list[Any] = []
        freed_weight: float = 0.0

        # ── Phase 1: Gradient Trim ──
        for c in sorted_candidates:
            sym = c.symbol
            sector = getattr(c, "sector", sector_map.get(sym, "Other"))
            cluster = cluster_labels.get(sym, "")
            max_wt = getattr(c, "max_weight_limit", self.max_single_position)
            wt = min(max_wt, self.max_single_position)

            # Hard constraints → immediate reject
            if getattr(c, "pass_status", True) is False:
                # Already rejected by engine
                if max_wt > 0:
                    freed_weight += max_wt
                rejected.append(c)
                continue

            # Gradient-trim for sector concentration
            sector_current = cum_sector.get(sector, 0.0)
            if sector_current + wt > self.max_single_sector:
                available = max(0.0, self.max_single_sector - sector_current)
                trimmed = wt - available
                if trimmed > 0:
                    freed_weight += trimmed
                wt = available if available > 0 else 0.0

            # Gradient-trim for cluster concentration
            if cluster and wt > 0:
                cluster_current = cum_cluster.get(cluster, 0.0)
                if cluster_current + wt > self.max_single_cluster:
                    available = max(0.0, self.max_single_cluster - cluster_current)
                    trimmed = wt - available
                    if trimmed > 0:
                        freed_weight += trimmed
                    wt = available if available > 0 else 0.0

            # Gradient-trim for position cap
            original_wt = getattr(c, "max_weight_limit", self.max_single_position)
            if original_wt > self.max_single_position:
                trimmed = original_wt - self.max_single_position
                freed_weight += trimmed
            wt = min(wt, self.max_single_position)

            if wt <= 0:
                rejected.append(c)
                continue

            # Apply trimmed weight
            c.max_weight_limit = round(wt, 6)
            cum_sector[sector] = cum_sector.get(sector, 0.0) + wt
            cum_cluster[cluster] = cum_cluster.get(cluster, 0.0) + wt
            approved.append(c)

        # ── Phase 2: Refill ──
        redistributed = 0.0
        refill_symbols: list[str] = []

        if freed_weight > 0.001 and rejected:
            # Find rejected candidates that are NOT correlated with approved ones
            approved_syms = {c.symbol for c in approved}
            refill_pool = []

            for c in rejected:
                sym = c.symbol
                # Skip if correlated with any approved stock
                correlated = correlated_of.get(sym, set())
                if correlated & approved_syms:
                    continue
                # Skip if hard-rejected (ST, etc.)
                if not c.pass_status:
                    continue
                refill_pool.append(c)

            # Sort refill pool by alpha_score descending
            refill_pool.sort(key=lambda c: c.alpha_score, reverse=True)

            for c in refill_pool:
                if freed_weight - redistributed <= 0.001:
                    break

                wt_to_add = min(self.trim_step, freed_weight - redistributed)
                new_wt = getattr(c, "max_weight_limit", 0.0) + wt_to_add
                new_wt = min(new_wt, self.max_single_position)

                # Check concentration limits again
                sector = getattr(c, "sector", sector_map.get(c.symbol, "Other"))
                cluster = cluster_labels.get(c.symbol, "")
                if cum_sector.get(sector, 0.0) + new_wt > self.max_single_sector:
                    new_wt = max(
                        0.0, self.max_single_sector - cum_sector.get(sector, 0.0)
                    )
                if (
                    cluster
                    and cum_cluster.get(cluster, 0.0) + new_wt > self.max_single_cluster
                ):
                    new_wt = max(
                        0.0, self.max_single_cluster - cum_cluster.get(cluster, 0.0)
                    )

                if new_wt > 0:
                    old_wt = getattr(c, "max_weight_limit", 0.0)
                    delta = new_wt - old_wt
                    redistributed += delta
                    c.max_weight_limit = round(new_wt, 6)
                    c.pass_status = True
                    c.rejection_reason = ""
                    cum_sector[sector] = cum_sector.get(sector, 0.0) + delta
                    if cluster:
                        cum_cluster[cluster] = cum_cluster.get(cluster, 0.0) + delta
                    approved.append(c)
                    refill_symbols.append(c.symbol)
                    rejected.remove(c)

        # Build summary
        reject_reasons: dict[str, int] = {}
        for c in rejected:
            reason = c.rejection_reason or "Unknown"
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

        summary_parts = [
            f"Approved: {len(approved)}, Rejected: {len(rejected)}",
            f"Freed weight: {freed_weight:.1%}",
        ]
        if refill_symbols:
            summary_parts.append(
                f"Refilled: {len(refill_symbols)} stocks ({', '.join(refill_symbols[:3])})"
            )
        if rejected:
            top_reasons = sorted(reject_reasons.items(), key=lambda x: -x[1])[:3]
            summary_parts.append(f"Top reject reasons: {top_reasons}")

        return TrimResult(
            approved=approved,
            rejected=rejected,
            freed_weight=round(freed_weight, 4),
            redistributed_weight=round(redistributed, 4),
            refill_candidates=refill_symbols,
            summary=" | ".join(summary_parts),
        )
