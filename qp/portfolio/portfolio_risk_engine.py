"""PortfolioRiskEngine — Layer 7 orchestrator.

Per docs/7_Portfolio_Risk_Layer.md:
  "Layer 7 不负责赚钱，它负责让你活下来。"

Pipeline:
  1. Exposure Analysis — sector, market cap, beta, liquidity
  2. Dynamic Clustering — correlation-based risk clusters
  3. Risk Constraints — position, sector, cluster, ST, beta limits
  4. Risk Budgeting — volatility-based weight caps
  5. Output: RiskApprovedCandidate list → Layer 8 Capital Allocation

Usage:
    from qp.portfolio.portfolio_risk_engine import PortfolioRiskEngine

    engine = PortfolioRiskEngine()
    approved = engine.evaluate(alpha_batch, prices_df)
    for candidate in approved:
        if candidate.pass_status:
            print(f"  {candidate.symbol}: max_wt={candidate.max_weight_limit:.1%}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
import polars as pl

from qp.portfolio.clustering import RiskClusterer
from qp.portfolio.correlation import CorrelationAnalyzer
from qp.portfolio.exposure.factor_exposure import FactorExposureAnalyzer
from qp.portfolio.exposure.marketcap_exposure import MarketCapExposure
from qp.portfolio.industry import IndustryMapper
from qp.portfolio.models.risk_approved_candidate import RiskApprovedCandidate

# ------------------------------------------------------------------
# Default limits (per docs/7_Portfolio_Risk_Layer.md §第三部分)
# ------------------------------------------------------------------

DEFAULT_LIMITS: dict[str, float] = {
    "max_single_position": 0.15,  # 单只股票 ≤ 15%
    "max_single_sector": 0.30,  # 单行业 ≤ 30%
    "max_single_cluster": 0.30,  # 单 Risk Cluster ≤ 30%
    "max_top3": 0.45,  # Top 3 ≤ 45%
    "max_small_cap": 0.20,  # 小市值 ≤ 20%
    "max_beta": 1.2,  # 单股 Beta < 1.2
    "max_st": 0.0,  # ST = 0%
    "max_suspended": 0.0,  # 停牌 = 0%
}
DEFAULT_CORRELATION_THRESHOLD: float = 0.85
DEFAULT_ANNUAL_VOL_TARGET: float = 0.15  # 15% target portfolio vol


# ------------------------------------------------------------------
# Engine config
# ------------------------------------------------------------------


@dataclass
class RiskEngineConfig:
    """Configuration for PortfolioRiskEngine.

    Attributes:
        limits: Dict of risk limit values (see DEFAULT_LIMITS).
        correlation_threshold: Flag pairs with correlation above this.
        annual_vol_target: Target portfolio annualized volatility.
        n_clusters: (min, max) for dynamic clustering.
        cluster_linkage: Linkage method for hierarchical clustering.
        enable_clustering: Whether to use dynamic clustering.
        enable_beta_check: Whether to enforce beta constraints.
        enable_st_check: Whether to reject ST/PT stocks.
        lookback: Days of history for correlation/vol estimates.
    """

    limits: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD
    annual_vol_target: float = DEFAULT_ANNUAL_VOL_TARGET
    n_clusters: tuple[int, int] = (3, 5)
    cluster_linkage: str = "ward"
    enable_clustering: bool = True
    enable_beta_check: bool = False
    enable_st_check: bool = True
    lookback: int = 60


# ------------------------------------------------------------------
# Engine
# ------------------------------------------------------------------


@dataclass
class PortfolioRiskEngine:
    """Orchestrate Layer 7 risk assessment pipeline.

    Input: Alpha signals (from Layer 6) + price data
    Output: RiskApprovedCandidate list (for Layer 8)

    Usage:
        engine = PortfolioRiskEngine()
        candidates = engine.evaluate(signals_df, prices_df)
        for c in candidates:
            print(f"{c.symbol}: {'PASS' if c.pass_status else 'FAIL'}")
    """

    config: RiskEngineConfig = field(default_factory=RiskEngineConfig)

    def __post_init__(self) -> None:
        self._industry = IndustryMapper()
        self._correlation = CorrelationAnalyzer(
            threshold=self.config.correlation_threshold,
            lookback=self.config.lookback,
        )
        self._clusterer = RiskClusterer(
            n_clusters=self.config.n_clusters,
            linkage_method=self.config.cluster_linkage,
            lookback=self.config.lookback,
        )
        self._market_cap = MarketCapExposure()
        self._factor_exposure = FactorExposureAnalyzer(
            momentum_lookback=self.config.lookback,
            volatility_lookback=self.config.lookback,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def evaluate(
        self,
        signals: pl.DataFrame,
        prices: pl.DataFrame,
        current_positions: pl.DataFrame | None = None,
    ) -> list[RiskApprovedCandidate]:
        """Run the full Layer 7 pipeline on candidate signals.

        Args:
            signals: Strategy signals with [symbol, raw_score/alpha_score].
            prices: Price data with [trade_date, symbol, close, volume].
            current_positions: Current holdings (optional).

        Returns:
            List of RiskApprovedCandidate, each with pass_status.
        """
        if signals.is_empty():
            return []

        # Determine score column
        score_col = "alpha_score" if "alpha_score" in signals.columns else "raw_score"
        if score_col not in signals.columns:
            score_col = signals.columns[1]  # guess second column

        symbols = signals["symbol"].to_list()

        # ── 1. Exposure Analysis ──
        exposures = self._analyze_exposures(prices, symbols)

        # ── 2. Dynamic Clustering ──
        cluster_labels: dict[str, str] = {}
        if self.config.enable_clustering and len(symbols) >= 3:
            # Only cluster symbols that exist in price data
            price_symbols = (
                set(prices["symbol"].unique().to_list())
                if "symbol" in prices.columns
                else set()
            )
            clusterable = [s for s in symbols if s in price_symbols]
            if len(clusterable) >= 3:
                cluster_labels = self._clusterer.fit_predict(prices, clusterable)

        # ── 3. Risk Constraints ──
        candidates = self._apply_constraints(
            signals,
            exposures,
            cluster_labels,
            prices,
            score_col,
        )

        # ── 4. Risk Budgeting ──
        return self._apply_risk_budget(candidates, prices)

    # ------------------------------------------------------------------
    # 1. Exposure Analysis
    # ------------------------------------------------------------------

    def _analyze_exposures(
        self,
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Compute exposure metrics for each symbol.

        Returns:
            {symbol: {sector, market_cap, beta, volatility, liquidity_score,
                       factor_exposures}}.
        """
        # Compute volatilities (annualized)
        vols = self._compute_volatilities(prices, symbols)

        # Compute ADVs for liquidity
        advs = self._compute_advs(prices, symbols)

        # Market cap classification (ADV-based proxy)
        cap_labels: dict[str, str] = {}
        for sym in symbols:
            adv = advs.get(sym, 0.0)
            tier = self._market_cap.classify_single(adv * 250)  # annualize ADV
            cap_labels[sym] = tier

        # Factor exposures (ex-ante style factors)
        factor_exps = self._factor_exposure.compute(prices, symbols)

        exposures: dict[str, dict[str, Any]] = {}
        for sym in symbols:
            exp: dict[str, Any] = {
                "sector": self._industry.get_sector(sym),
                "market_cap": cap_labels.get(sym, "mid"),
                "beta": 1.0,
                "volatility": vols.get(sym, 0.30),
                "liquidity_score": self._liquidity_score(advs.get(sym, 0.0)),
                "factor_exposures": factor_exps.get(sym, {}),
            }
            exposures[sym] = exp

        return exposures

    # ------------------------------------------------------------------
    # 3. Risk Constraints
    # ------------------------------------------------------------------

    def _apply_constraints(
        self,
        signals: pl.DataFrame,
        exposures: dict[str, dict[str, Any]],
        cluster_labels: dict[str, str],
        prices: pl.DataFrame,
        score_col: str,
    ) -> list[RiskApprovedCandidate]:
        """Apply all hard and soft constraints."""
        symbols = signals["symbol"].to_list()
        scores = signals[score_col].to_list()
        score_map = dict(zip(symbols, scores, strict=True))
        n = len(symbols)

        # Pre-compute equal weight
        eq_wt = 1.0 / max(n, 1)

        # Sector weights (from equal weight)
        sector_wt: dict[str, float] = {}
        for sym in symbols:
            sec = exposures[sym]["sector"]
            sector_wt[sec] = sector_wt.get(sec, 0.0) + eq_wt

        # Cluster weights
        cluster_wt: dict[str, float] = {}
        if cluster_labels:
            for sym in symbols:
                lbl = cluster_labels.get(sym, "Unknown")
                cluster_wt[lbl] = cluster_wt.get(lbl, 0.0) + eq_wt

        # Correlation pairs
        correlated_pairs: list[tuple[str, str, float]] = []
        if len(symbols) >= 2:
            correlated_pairs = self._correlation.find_high_correlation_pairs(
                prices, symbols
            )

        # Build rank map for redundancy detection
        rank_map = {s: i + 1 for i, s in enumerate(symbols)}
        redundant = set()
        if correlated_pairs:
            redundant = set(
                CorrelationAnalyzer.flag_redundant_candidates(
                    correlated_pairs, rank_map
                )
            )

        # Evaluate each candidate
        candidates: list[RiskApprovedCandidate] = []
        limits = self.config.limits

        for i, sym in enumerate(symbols):
            exp = exposures[sym]
            reasons: list[str] = []

            # ST/PT check
            if self.config.enable_st_check and self._is_st_stock(sym):
                reasons.append("ST/PT stock — hard reject")

            # Single position cap
            max_pos = limits["max_single_position"]
            if eq_wt > max_pos:
                reasons.append(f"Position weight {eq_wt:.1%} > {max_pos:.0%}")

            # Sector cap
            max_sec = limits["max_single_sector"]
            sec = exp["sector"]
            if sector_wt.get(sec, 0.0) > max_sec:
                reasons.append(f"Sector {sec} at {sector_wt[sec]:.1%} > {max_sec:.0%}")

            # Cluster cap
            max_cl = limits["max_single_cluster"]
            lbl = cluster_labels.get(sym, "")
            if lbl and cluster_wt.get(lbl, 0.0) > max_cl:
                reasons.append(f"Cluster {lbl} at {cluster_wt[lbl]:.1%} > {max_cl:.0%}")

            # Correlation redundancy (keep higher-ranked)
            if sym in redundant:
                reasons.append("Correlated with higher-ranked candidate")

            # Beta check
            if self.config.enable_beta_check:
                beta = exp["beta"]
                max_beta = limits["max_beta"]
                if beta > max_beta:
                    reasons.append(f"Beta {beta:.2f} > {max_beta}")

            # Small cap limit (per stock in small-cap tier)
            max_small = limits["max_small_cap"]
            if exp["market_cap"] == "small":
                small_wt_total = sum(
                    eq_wt for s2 in symbols if exposures[s2]["market_cap"] == "small"
                )
                if small_wt_total > max_small:
                    reasons.append(
                        f"Small-cap total {small_wt_total:.1%} > {max_small:.0%}"
                    )

            # Top 3 concentration
            if n >= 3:
                top3_wt = round(eq_wt * 3, 6)
                max_top3 = limits["max_top3"]
                if top3_wt > max_top3 and i < 3:
                    reasons.append(f"Top3 concentration {top3_wt:.1%} > {max_top3:.0%}")
                    # flag on individual candidates if in top 3

            passed = len(reasons) == 0
            vol = exp["volatility"]

            # Compute max weight limit from risk budget
            if vol > 0:
                weight_cap = min(
                    max_pos,
                    self.config.annual_vol_target / (vol * max(n, 1)),
                )
            else:
                weight_cap = max_pos

            candidates.append(
                RiskApprovedCandidate(
                    symbol=sym,
                    alpha_score=score_map.get(sym, 0.0),
                    risk_cluster=lbl,
                    max_weight_limit=round(weight_cap, 4),
                    risk_volatility=round(vol, 4),
                    pass_status=passed,
                    rejection_reason="; ".join(reasons),
                    sector=sec,
                    market_cap=exp["market_cap"],
                    beta=round(exp["beta"], 3),
                    liquidity_score=round(exp["liquidity_score"], 3),
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # 4. Risk Budgeting (Inverse Volatility)
    # ------------------------------------------------------------------

    def _apply_risk_budget(
        self,
        candidates: list[RiskApprovedCandidate],
        prices: pl.DataFrame,
    ) -> list[RiskApprovedCandidate]:
        """Apply volatility-based risk budgeting.

        Inverse volatility: lower vol → higher weight budget.
        Higher vol → tighter weight cap.
        """
        passed = [c for c in candidates if c.pass_status]
        if not passed:
            return candidates

        # Compute target vol per position
        n = max(len(passed), 1)
        target_vol_per_position = self.config.annual_vol_target / n

        for c in candidates:
            if c.risk_volatility > 0:
                # Weight needed to achieve target vol from this position
                vol_budget_wt = target_vol_per_position / c.risk_volatility
                # Cap at the existing max_weight_limit
                c.max_weight_limit = min(c.max_weight_limit, vol_budget_wt)
                c.max_weight_limit = round(max(c.max_weight_limit, 0.0), 4)

        return candidates

    # ------------------------------------------------------------------
    # Convenience: evaluate from AlphaSignalBatch
    # ------------------------------------------------------------------

    def evaluate_batch(
        self,
        batch: Any,  # AlphaSignalBatch
        prices: pl.DataFrame,
    ) -> list[RiskApprovedCandidate]:
        """Evaluate from an AlphaSignalBatch."""
        df = batch.to_polars() if hasattr(batch, "to_polars") else batch
        return self.evaluate(df, prices)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self, candidates: list[RiskApprovedCandidate]) -> dict[str, Any]:
        """Generate a pipeline summary."""
        passed = [c for c in candidates if c.pass_status]
        rejected = [c for c in candidates if not c.pass_status]

        sectors: dict[str, int] = {}
        clusters: dict[str, int] = {}
        for c in passed:
            sectors[c.sector] = sectors.get(c.sector, 0) + 1
            if c.risk_cluster:
                clusters[c.risk_cluster] = clusters.get(c.risk_cluster, 0) + 1

        return {
            "total_candidates": len(candidates),
            "passed": len(passed),
            "rejected": len(rejected),
            "pass_rate": f"{len(passed) / max(len(candidates), 1):.1%}",
            "sectors_represented": len(sectors),
            "risk_clusters": len(clusters),
            "avg_max_weight": (
                round(float(np.mean([c.max_weight_limit for c in passed])), 4)
                if passed
                else 0.0
            ),
            "avg_volatility": (
                round(float(np.mean([c.risk_volatility for c in passed])), 4)
                if passed
                else 0.0
            ),
            "rejection_reasons": [
                {"symbol": c.symbol, "reason": c.rejection_reason} for c in rejected
            ],
        }

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_st_stock(symbol: str) -> bool:
        """Heuristic ST detection from symbol or name patterns."""
        return any(tag in str(symbol).upper() for tag in ("ST", "*ST", "PT"))

    @staticmethod
    def _liquidity_score(adv: float) -> float:
        """Convert ADV (CNY) to a liquidity score [0, 1]."""
        if adv <= 0:
            return 0.0
        # Log-scale: 1M CNY → 0.1, 100M → 0.5, 1B → 0.9
        import math

        score = math.log10(max(adv, 1e4)) / 10.0
        return round(max(0.0, min(1.0, score)), 3)

    @staticmethod
    def _compute_volatilities(
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, float]:
        """Compute annualized volatility per symbol from daily returns."""
        if prices.is_empty():
            return {}

        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return {}

        px = px.sort(["symbol", "trade_date"])
        px = px.with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol") - 1).alias("ret")
        )
        px = px.drop_nulls(subset=["ret"])

        vols: dict[str, float] = {}
        for sym in symbols:
            sym_ret = px.filter(pl.col("symbol") == sym)["ret"]
            if len(sym_ret) < 20:
                vols[sym] = 0.30  # default 30% annual
            else:
                vols[sym] = round(float(sym_ret.std() * np.sqrt(252)), 4)

        return vols

    @staticmethod
    def _compute_advs(
        prices: pl.DataFrame,
        symbols: list[str],
    ) -> dict[str, float]:
        """Compute average daily value (close * volume) in CNY."""
        if prices.is_empty() or "volume" not in prices.columns:
            return {}

        px = prices.filter(pl.col("symbol").is_in(symbols))
        if px.is_empty():
            return {}

        px = px.with_columns((pl.col("close") * pl.col("volume")).alias("dv"))
        px = px.group_by("symbol").tail(20)

        advs: dict[str, float] = {}
        for sym in symbols:
            sym_data = px.filter(pl.col("symbol") == sym)["dv"]
            if len(sym_data) == 0:
                advs[sym] = 0.0
            else:
                advs[sym] = round(float(cast("float", sym_data.mean())), 2)

        return advs
