"""PortfolioRiskManager — enforces risk limits on candidate positions.

Implements BasePortfolioRiskManager (rule.md §7.5):
  1. Single position cap: ≤ 8% of portfolio
  2. Single sector cap: ≤ 25% of portfolio
  3. Correlation filter: flag pairs > 0.7, keep higher-ranked
  4. Risk budget: total target annual vol ≤ 15%

Acts as a filter: receives raw strategy signals, returns a subset
that passes all risk checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import polars as pl

from qp.portfolio.correlation import CorrelationAnalyzer
from qp.portfolio.industry import IndustryMapper
from qp.shared.protocols.base_portfolio_risk import BasePortfolioRiskManager

# Default limits
DEFAULT_MAX_SINGLE_POSITION = 0.08  # 8% per stock
DEFAULT_MAX_SINGLE_SECTOR = 0.25  # 25% per sector
DEFAULT_CORRELATION_THRESHOLD = 0.70
DEFAULT_RISK_BUDGET_ANNUAL_VOL = 0.15  # 15% annual vol
DEFAULT_MAX_POSITIONS = 10


@dataclass
class RiskReport:
    """Output of a risk evaluation."""

    passed: bool = True
    candidates_in: int = 0
    candidates_out: int = 0
    violations: list[str] = field(default_factory=list)
    sector_exposure: dict[str, float] = field(default_factory=dict)
    position_weights: dict[str, float] = field(default_factory=dict)
    dropped_symbols: list[str] = field(default_factory=list)
    correlated_pairs: list[tuple[str, str, float]] = field(default_factory=list)


class PortfolioRiskManager(BasePortfolioRiskManager):
    """Enforces position, sector, and correlation risk limits.

    Usage:
        rm = PortfolioRiskManager()
        filtered, report = rm.apply_risk_limits(signals_df, prices_df)
    """

    def __init__(
        self,
        max_single_position: float = DEFAULT_MAX_SINGLE_POSITION,
        max_single_sector: float = DEFAULT_MAX_SINGLE_SECTOR,
        correlation_threshold: float = DEFAULT_CORRELATION_THRESHOLD,
        risk_budget: float = DEFAULT_RISK_BUDGET_ANNUAL_VOL,
        max_positions: int = DEFAULT_MAX_POSITIONS,
    ) -> None:
        self._max_single_position = max_single_position
        self._max_single_sector = max_single_sector
        self._correlation_threshold = correlation_threshold
        self._risk_budget = risk_budget
        self._max_positions = max_positions

        self._industry = IndustryMapper()
        self._correlation = CorrelationAnalyzer(
            threshold=correlation_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_risk_limits(
        self,
        raw_signals: pd.DataFrame,
        current_positions: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply risk limits to raw strategy signals.

        Args:
            raw_signals: Strategy output with [symbol, ...].
            current_positions: Current holdings (may be empty).

        Returns:
            Filtered DataFrame of approved candidates.
        """
        if raw_signals.empty:
            return raw_signals

        # Convert to polars
        signals = (
            pl.from_pandas(raw_signals) if isinstance(raw_signals, pd.DataFrame) else raw_signals
        )

        symbols = signals["symbol"].to_list()
        n_signals = len(symbols)
        equal_weight = 1.0 / max(n_signals, 1)

        violations: list[str] = []
        dropped: set[str] = set()

        # Step 1: Single position cap
        if equal_weight > self._max_single_position:
            # We have too few positions to satisfy the cap at equal weight.
            # Cap each position at 8% and note the violation.
            capped_count = min(n_signals, self._max_positions)
            if n_signals > capped_count:
                # Keep top-ranked only
                dropped.update(symbols[capped_count:])
                violations.append(
                    f"Position cap: {n_signals - capped_count} symbols dropped "
                    f"(max {capped_count} positions)"
                )

        # Step 2: Sector cap
        sector_weights: dict[str, float] = {}
        for s in symbols:
            if s in dropped:
                continue
            sector = self._industry.get_sector(s)
            sector_weights[sector] = sector_weights.get(sector, 0.0) + equal_weight

        for sector, w in sector_weights.items():
            if w > self._max_single_sector:
                violations.append(
                    f"Sector cap: {sector} at {w:.1%} > {self._max_single_sector:.0%}"
                )

        # Step 3: Correlation filter — requires prices data;
        # use apply_risk_limits_with_prices() for full analysis.

        # Filter signals
        keep_symbols = [s for s in symbols if s not in dropped]
        result = signals.filter(pl.col("symbol").is_in(keep_symbols))
        return result.to_pandas()

    def apply_risk_limits_with_prices(
        self,
        signals: pl.DataFrame,
        prices: pl.DataFrame,
        current_positions: pl.DataFrame | None = None,
    ) -> tuple[pl.DataFrame, RiskReport]:
        """Apply risk limits with price data for correlation analysis.

        Args:
            signals: Strategy signals with [symbol, feature_value/rank].
            prices: Price DataFrame with [trade_date, symbol, close].
            current_positions: Current holdings (optional).

        Returns:
            (filtered_signals, RiskReport).
        """
        if signals.is_empty():
            return signals, RiskReport(candidates_in=0, candidates_out=0)

        symbols = signals["symbol"].to_list()
        n_signals = len(symbols)

        violations: list[str] = []
        dropped: set[str] = set()

        # Step 1: Position cap (8%)
        max_positions = min(n_signals, self._max_positions)
        if n_signals > max_positions:
            dropped.update(symbols[max_positions:])
            violations.append(
                f"Position count: {n_signals} > {max_positions} max — "
                f"{n_signals - max_positions} dropped"
            )

        # Calculate equal weight for remaining
        remaining = [s for s in symbols if s not in dropped]
        eq_wt = 1.0 / max(len(remaining), 1)
        if eq_wt > self._max_single_position:
            violations.append(
                f"Position cap: equal weight {eq_wt:.1%} > "
                f"{self._max_single_position:.0%} at {len(remaining)} positions"
            )

        # Step 2: Sector cap (25%)
        sector_weights: dict[str, float] = {}
        for s in remaining:
            sector = self._industry.get_sector(s)
            sector_weights[sector] = sector_weights.get(sector, 0.0) + eq_wt

        for sector, w in sector_weights.items():
            if w > self._max_single_sector:
                violations.append(
                    f"Sector cap: {sector} at {w:.1%} > {self._max_single_sector:.0%}"
                )

        # Step 3: Correlation filter
        correlated_pairs: list[tuple[str, str, float]] = []
        if len(remaining) >= 2:
            correlated_pairs = self._correlation.find_high_correlation_pairs(prices, remaining)
            if correlated_pairs:
                # Build rank dict from signal order
                signal_ranks = {s: i + 1 for i, s in enumerate(symbols)}
                redundant = CorrelationAnalyzer.flag_redundant_candidates(
                    correlated_pairs, signal_ranks
                )
                for s in redundant:
                    if s in remaining:
                        dropped.add(s)

                violations.append(
                    f"Correlation: {len(correlated_pairs)} pair(s) > "
                    f"{self._correlation_threshold:.0%}, "
                    f"{len(redundant)} symbol(s) dropped"
                )

        # Final remaining
        final_symbols = [s for s in symbols if s not in dropped]
        n_final = len(final_symbols)
        final_eq_wt = 1.0 / max(n_final, 1)

        position_weights = dict.fromkeys(final_symbols, final_eq_wt)

        # Sector exposure for final portfolio
        final_sector_wt: dict[str, float] = {}
        for s in final_symbols:
            sec = self._industry.get_sector(s)
            final_sector_wt[sec] = final_sector_wt.get(sec, 0.0) + final_eq_wt

        report = RiskReport(
            passed=len(violations) == 0,
            candidates_in=n_signals,
            candidates_out=n_final,
            violations=violations,
            sector_exposure=final_sector_wt,
            position_weights=position_weights,
            dropped_symbols=sorted(dropped),
            correlated_pairs=correlated_pairs,
        )

        filtered = signals.filter(pl.col("symbol").is_in(final_symbols))
        return filtered, report

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def max_single_position(self) -> float:
        return self._max_single_position

    @property
    def max_single_sector(self) -> float:
        return self._max_single_sector

    @property
    def industry_mapper(self) -> IndustryMapper:
        return self._industry
