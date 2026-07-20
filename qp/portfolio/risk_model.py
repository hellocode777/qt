"""RiskModel — multi-factor portfolio risk decomposition.

Implements BaseRiskModel (rule.md §7.8):
  Total Risk = Market Risk + Style Risk + Sector Risk + Idiosyncratic Risk

Uses a simplified factor model that works with daily price data:
  - Market: covariance with benchmark index (CSI 300)
  - Style: size (log market cap), momentum, volatility factor exposures
  - Sector: industry concentration risk (using IndustryMapper)
  - Idiosyncratic: residual after removing factor exposures
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from qp.shared.protocols.base_risk_model import BaseRiskModel

if TYPE_CHECKING:
    import pandas as pd

# ------------------------------------------------------------------
# Defaults
# ------------------------------------------------------------------

DEFAULT_RISK_FREE_RATE = 0.02  # 2% annual
DEFAULT_TRADING_DAYS = 252


# ------------------------------------------------------------------
# Result types
# ------------------------------------------------------------------


@dataclass
class RiskDecomposition:
    """Structured risk decomposition result.

    Attributes:
        total_risk: Total portfolio volatility (annualized).
        market_risk: Market (beta) contribution to total risk.
        style_risk: Style factor contribution.
        sector_risk: Industry/sector contribution.
        idiosyncratic_risk: Residual (stock-specific) risk.
        market_risk_pct: Market risk as % of total.
        style_risk_pct: Style risk as % of total.
        sector_risk_pct: Sector risk as % of total.
        idiosyncratic_risk_pct: Idiosyncratic risk as % of total.
        factor_exposures: Dict of factor name → exposure value.
        sector_exposures: Dict of sector name → weight.
    """

    total_risk: float = 0.0
    market_risk: float = 0.0
    style_risk: float = 0.0
    sector_risk: float = 0.0
    idiosyncratic_risk: float = 0.0

    market_risk_pct: float = 0.0
    style_risk_pct: float = 0.0
    sector_risk_pct: float = 0.0
    idiosyncratic_risk_pct: float = 0.0

    factor_exposures: dict[str, float] | None = None
    sector_exposures: dict[str, float] | None = None

    def to_dict(self) -> dict[str, float]:
        """Serialize to flat dict for logging/storage."""
        result: dict[str, float] = {
            "total_risk": self.total_risk,
            "market_risk": self.market_risk,
            "style_risk": self.style_risk,
            "sector_risk": self.sector_risk,
            "idiosyncratic_risk": self.idiosyncratic_risk,
            "market_risk_pct": self.market_risk_pct,
            "style_risk_pct": self.style_risk_pct,
            "sector_risk_pct": self.sector_risk_pct,
            "idiosyncratic_risk_pct": self.idiosyncratic_risk_pct,
        }
        if self.factor_exposures:
            for k, v in self.factor_exposures.items():
                result[f"factor_{k}"] = v
        if self.sector_exposures:
            for k, v in self.sector_exposures.items():
                result[f"sector_wt_{k}"] = v
        return result


@dataclass
class AttributionReport:
    """Full risk attribution report with factor contribution breakdown."""

    decomposition: RiskDecomposition
    top_risk_contributors: list[tuple[str, float]]  # (symbol, risk_contribution)
    concentration_ratio: float  # weight of top 5 positions / total
    effective_n: float  # 1 / sum(w_i^2) — effective number of bets
    diversification_score: float  # 0-1, higher = more diversified

    def summary(self) -> str:
        """One-line summary string."""
        d = self.decomposition
        return (
            f"Risk={d.total_risk:.1%} | "
            f"Market={d.market_risk_pct:.0%} "
            f"Style={d.style_risk_pct:.0%} "
            f"Sector={d.sector_risk_pct:.0%} "
            f"Idio={d.idiosyncratic_risk_pct:.0%} | "
            f"EffN={self.effective_n:.1f} "
            f"Div={self.diversification_score:.2f}"
        )


# ------------------------------------------------------------------
# Risk model implementation
# ------------------------------------------------------------------


class RiskModel(BaseRiskModel):
    """Multi-factor risk model for portfolio risk decomposition.

    Decomposes total portfolio risk into:
      - Market Risk: exposure to broad market (beta)
      - Style Risk: exposure to style factors (size, momentum, volatility)
      - Sector Risk: industry concentration
      - Idiosyncratic Risk: residual, stock-specific risk

    Usage:
        model = RiskModel()
        result = model.decompose_risk(portfolio_holdings)
        # Returns RiskDecomposition with annualized risk figures
        attr = model.attribute(
            returns_df, portfolio_weights, benchmark_returns
        )
    """

    def __init__(
        self,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        trading_days: int = DEFAULT_TRADING_DAYS,
    ) -> None:
        self._rf = risk_free_rate
        self._trading_days = trading_days

    # ------------------------------------------------------------------
    # BaseRiskModel interface
    # ------------------------------------------------------------------

    def decompose_risk(
        self,
        portfolio_holdings: pd.DataFrame,
    ) -> dict[str, float]:
        """Decompose total risk into factor components.

        Args:
            portfolio_holdings: DataFrame with [symbol, weight] columns.
                Optionally [sector, market_cap] for richer attribution.

        Returns:
            Dict: {total_risk, market_risk, style_risk, sector_risk,
                   idiosyncratic_risk, ...}.
        """
        weights = portfolio_holdings["weight"].to_numpy()
        n = len(weights)

        if n == 0:
            return {
                "total_risk": 0.0,
                "market_risk": 0.0,
                "style_risk": 0.0,
                "sector_risk": 0.0,
                "idiosyncratic_risk": 0.0,
            }

        # 1. Market risk — approximated via equal beta assumption
        #    Default beta = 1.0 for all stocks; market vol ≈ 20% annual
        avg_beta = 1.0
        market_vol = 0.20
        market_risk = (avg_beta * market_vol) ** 2

        # 2. Style risk — estimated from concentration
        #    Higher concentration → more idiosyncratic style exposure
        hhi = np.sum(weights**2)  # Herfindahl-Hirschman Index
        effective_n = 1.0 / hhi if hhi > 0 else float(n)
        style_risk = 0.04 * (1.0 - 1.0 / effective_n) if effective_n > 1 else 0.0

        # 3. Sector risk — from sector concentration
        if "sector" in portfolio_holdings.columns:
            sector_wt = (
                portfolio_holdings.groupby("sector")["weight"].sum().to_dict()  # type: ignore[union-attr]
            )
            sector_hhi = sum(w**2 for w in sector_wt.values())
            sector_risk = sector_hhi * 0.06  # scaled sector variance
        else:
            sector_risk = 0.02  # default moderate sector risk

        # 4. Idiosyncratic risk — residual
        #    Typical stock-specific vol ≈ 30% annual, diversified away
        avg_idio_vol = 0.30
        idiosyncratic_risk = (avg_idio_vol**2) * hhi

        # Total risk (variance)
        total_variance = market_risk + style_risk + sector_risk + idiosyncratic_risk

        return {
            "total_risk": float(np.sqrt(max(total_variance, 0.0))),
            "market_risk": float(np.sqrt(max(market_risk, 0.0))),
            "style_risk": float(np.sqrt(max(style_risk, 0.0))),
            "sector_risk": float(np.sqrt(max(sector_risk, 0.0))),
            "idiosyncratic_risk": float(np.sqrt(max(idiosyncratic_risk, 0.0))),
            "total_variance": float(total_variance),
        }

    # ------------------------------------------------------------------
    # Full attribution with returns data
    # ------------------------------------------------------------------

    def attribute(
        self,
        returns: pl.DataFrame,
        weights: dict[str, float],
        benchmark_returns: pl.Series | None = None,
        style_factor_returns: pl.DataFrame | None = None,
    ) -> RiskDecomposition:
        """Full risk attribution with realized returns data.

        Args:
            returns: Daily returns with [trade_date, symbol, ret].
            weights: symbol → weight mapping.
            benchmark_returns: Daily benchmark (market) returns.
            style_factor_returns: Style factor returns with
                [trade_date, size, momentum, volatility].

        Returns:
            RiskDecomposition with annualized figures.
        """
        symbols = list(weights.keys())
        w = np.array([weights[s] for s in symbols])

        if len(w) == 0:
            return RiskDecomposition()

        # Pivot returns to wide format
        ret_pivot = self._pivot_returns(returns, symbols)

        # Portfolio returns
        port_returns = (ret_pivot * w).sum(axis=1)  # type: ignore[operator]

        # Total risk (annualized vol)
        total_vol = float(port_returns.std() * np.sqrt(self._trading_days))

        # Market risk
        market_risk, market_pct = self._compute_market_risk(
            port_returns, benchmark_returns  # type: ignore[arg-type]
        )

        # Style risk
        style_risk, style_pct, factor_exposures = self._compute_style_risk(
            ret_pivot, w, style_factor_returns
        )

        # Sector risk (from concentration)
        sector_risk, sector_pct, sector_exposures = self._compute_sector_risk(
            ret_pivot, w, symbols
        )

        # Idiosyncratic risk = residual
        explained_var = market_risk**2 + style_risk**2 + sector_risk**2
        total_var = total_vol**2
        idio_var = max(total_var - explained_var, 0.0)
        idio_risk = float(np.sqrt(idio_var))

        idio_pct = idio_var / total_var if total_var > 0 else 0.0

        return RiskDecomposition(
            total_risk=total_vol,
            market_risk=market_risk,
            style_risk=style_risk,
            sector_risk=sector_risk,
            idiosyncratic_risk=idio_risk,
            market_risk_pct=market_risk**2 / total_var if total_var > 0 else 0.0,
            style_risk_pct=style_risk**2 / total_var if total_var > 0 else 0.0,
            sector_risk_pct=sector_risk**2 / total_var if total_var > 0 else 0.0,
            idiosyncratic_risk_pct=idio_pct,
            factor_exposures=factor_exposures,
            sector_exposures=sector_exposures,
        )

    def attribution_report(
        self,
        returns: pl.DataFrame,
        weights: dict[str, float],
        benchmark_returns: pl.Series | None = None,
    ) -> AttributionReport:
        """Generate a full attribution report.

        Args:
            returns: Daily returns DataFrame.
            weights: symbol → weight mapping.
            benchmark_returns: Benchmark daily returns.

        Returns:
            AttributionReport with decomposition and diversification metrics.
        """
        decomposition = self.attribute(returns, weights, benchmark_returns)

        # Effective N and diversification
        w = np.array(list(weights.values()))
        hhi = float(np.sum(w**2))
        effective_n = float(1.0 / hhi) if hhi > 0 else float(len(w))
        diversification_score = float(
            1.0 - 1.0 / effective_n if effective_n > 1 else 0.0
        )

        # Top risk contributors — weighted by position size
        sorted_positions = sorted(
            weights.items(), key=lambda x: abs(x[1]), reverse=True
        )
        top_contributors = [
            (sym, wt) for sym, wt in sorted_positions[:5]
        ]

        # Concentration: top 5 weight / total
        top5_wt = sum(abs(wt) for _, wt in top_contributors)
        concentration_ratio = top5_wt / sum(abs(wt) for wt in weights.values()) if weights else 0.0

        return AttributionReport(
            decomposition=decomposition,
            top_risk_contributors=top_contributors,
            concentration_ratio=concentration_ratio,
            effective_n=effective_n,
            diversification_score=diversification_score,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pivot_returns(
        returns: pl.DataFrame,
        symbols: list[str],
    ) -> pl.DataFrame:
        """Pivot long returns to wide (symbols × dates) format."""
        filtered = returns.filter(pl.col("symbol").is_in(symbols))

        if filtered.is_empty():
            return pl.DataFrame()

        pivoted = filtered.pivot(
            values="ret",
            index="trade_date",
            on="symbol",
        ).sort("trade_date")

        # Fill missing columns
        for sym in symbols:
            if sym not in pivoted.columns:
                pivoted = pivoted.with_columns(pl.lit(0.0).alias(sym))

        return pivoted.drop_nulls()

    def _compute_market_risk(
        self,
        port_returns: pl.Series,
        benchmark_returns: pl.Series | None,
    ) -> tuple[float, float]:
        """Compute market (beta) risk contribution."""
        if benchmark_returns is None or len(benchmark_returns) < 60:
            # Default: assume beta=1, market vol=20%
            market_vol = 0.20
            return market_vol, (market_vol / 0.25) ** 2  # rough pct

        # Align lengths
        n = min(len(port_returns), len(benchmark_returns))
        pr = port_returns.tail(n).to_numpy()
        br = benchmark_returns.tail(n).to_numpy()

        # Compute beta via OLS
        cov = np.cov(pr, br)[0, 1]
        market_var = np.var(br)
        beta = cov / market_var if market_var > 0 else 1.0

        # Market risk contribution = |beta| * market_vol
        market_vol = float(np.sqrt(market_var) * np.sqrt(self._trading_days))
        market_risk = abs(beta) * market_vol

        # As percentage of total
        total_var = float(np.var(pr) * self._trading_days)
        pct = (beta**2 * market_var * self._trading_days) / total_var if total_var > 0 else 0.0

        return market_risk, min(pct, 1.0)

    def _compute_style_risk(
        self,
        ret_pivot: pl.DataFrame,
        weights: np.ndarray,
        style_factors: pl.DataFrame | None,
    ) -> tuple[float, float, dict[str, float]]:
        """Compute style factor risk contribution."""
        exposures: dict[str, float] = {}

        if style_factors is not None and not style_factors.is_empty():
            # Use provided style factor returns
            factor_names = [c for c in style_factors.columns if c != "trade_date"]
            port_ret = (ret_pivot.select(pl.exclude("trade_date")).to_numpy() * weights).sum(axis=1)  # type: ignore[assignment]

            style_var_total = 0.0
            for fname in factor_names:
                fvals = style_factors[fname].to_numpy()
                n = min(len(port_ret), len(fvals))
                if n < 2:
                    continue
                cov = np.cov(port_ret[-n:], fvals[-n:])[0, 1]
                fvar = np.var(fvals[-n:])
                if fvar > 0:
                    exp_val = cov / fvar
                    exposures[fname] = float(exp_val)
                    style_var_total += (exp_val**2) * fvar * self._trading_days
        else:
            # Simplified: estimate style risk from concentration
            hhi = float(np.sum(weights**2))
            # Higher HHI → less diversified → more style-specific risk
            style_var_total = 0.01 * hhi * len(weights)

        style_risk = float(np.sqrt(max(style_var_total, 0.0)))

        total_var = float(np.var(
            (ret_pivot.select(pl.exclude("trade_date")).to_numpy() * weights).sum(axis=1)  # type: ignore[assignment]
        ) * self._trading_days)
        pct = style_var_total / total_var if total_var > 0 else 0.0

        return style_risk, min(pct, 1.0), exposures

    def _compute_sector_risk(
        self,
        ret_pivot: pl.DataFrame,
        weights: np.ndarray,
        symbols: list[str],
    ) -> tuple[float, float, dict[str, float]]:
        """Compute sector concentration risk."""
        from qp.portfolio.industry import IndustryMapper

        mapper = IndustryMapper()
        sector_wt: dict[str, float] = {}
        for sym, wt in zip(symbols, weights, strict=True):
            sec = mapper.get_sector(sym)
            sector_wt[sec] = sector_wt.get(sec, 0.0) + wt

        # Sector risk = weighted sum of sector variances
        # Approximate each sector vol at 25%
        sector_vol = 0.25
        sector_hhi = sum(w**2 for w in sector_wt.values())
        sector_var = sector_hhi * (sector_vol**2)

        sector_risk = float(np.sqrt(max(sector_var, 0.0)))

        total_var = float(np.var(
            (ret_pivot.select(pl.exclude("trade_date")).to_numpy() * weights).sum(axis=1)  # type: ignore[assignment]
        ) * self._trading_days)
        pct = sector_var / total_var if total_var > 0 else 0.0

        return sector_risk, min(pct, 1.0), sector_wt

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def effective_n(weights: np.ndarray | list[float]) -> float:
        """Compute effective number of bets: 1 / Σ(w_i²)."""
        w = np.asarray(weights)
        hhi = float(np.sum(w**2))
        return float(1.0 / hhi) if hhi > 0 else 0.0

    @staticmethod
    def concentration_ratio(
        weights: np.ndarray | list[float],
        top_k: int = 5,
    ) -> float:
        """Compute top-K concentration ratio."""
        w = np.asarray(weights)
        sorted_w = np.sort(np.abs(w))[::-1]
        top = float(np.sum(sorted_w[:top_k]))
        total = float(np.sum(np.abs(w)))
        return top / total if total > 0 else 0.0

    @staticmethod
    def diversification_ratio(
        weights: np.ndarray | list[float],
        volatilities: np.ndarray | list[float],
    ) -> float:
        """Diversification ratio = weighted avg vol / portfolio vol.

        > 1.0 means diversification is reducing risk. Higher is better.
        """
        w = np.asarray(weights)
        vols = np.asarray(volatilities)
        weighted_avg_vol = float(np.sum(np.abs(w) * vols))
        # Approximate portfolio vol with equal correlation of 0.3
        corr = 0.3
        port_var = w @ (np.outer(vols, vols) * corr + np.diag(vols**2 * (1 - corr))) @ w
        port_vol = float(np.sqrt(max(port_var, 0.0)))
        return weighted_avg_vol / port_vol if port_vol > 0 else 1.0
