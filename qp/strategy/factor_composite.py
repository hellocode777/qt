"""Factor Composite Engine — auto-merge correlated factors (DP-002 v3).

Transforms 16 raw factors → 6 composite Alpha Sources:
  LowVol, Momentum, Value, Quality, Volume, Reversal

Each composite = rank() sum of member factors within the cluster.
This eliminates factor redundancy and reduces overfitting.

Usage:
    composite = FactorCompositeEngine()
    scores = composite.compute(date_str, raw_factors)
    # → {factor_name: composite_score}
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl
from loguru import logger

# ------------------------------------------------------------------
# Composite definitions (from factor correlation analysis)
# ------------------------------------------------------------------

# Each composite merges correlated factors into a single signal.
# Weights within composite are equal (rank-based blending).
COMPOSITE_DEFINITIONS: dict[str, dict] = {
    "LowVol_Composite": {
        "label": "低波动",
        "weight": 0.30,
        "direction": +1,  # Low vol → higher score
        "members": [
            "Volatility_20D",
            "Amplitude_5D",
            "Volatility_60D",
        ],
        "description": "Low volatility anomaly — low-risk stocks outperform in A-shares",
    },
    "Momentum_Composite": {
        "label": "动量",
        "weight": 0.20,
        "direction": -1,  # A-share momentum reverses
        "members": [
            "Residual_Momentum_3M",
            "Momentum_3M",
        ],
        "description": "Residual + raw momentum — market-neutral preferred",
    },
    "Value_Composite": {
        "label": "价值",
        "weight": 0.15,
        "direction": -1,  # Cheap = high score
        "members": [
            "PE_TTM",
            "PB",
            "PCF_OCF",
        ],
        "description": "Value anchor — cheap stocks outperform long-term",
    },
    "Quality_Composite": {
        "label": "质量",
        "weight": 0.15,
        "direction": +1,  # High quality = high score
        "members": [
            "ROE",
            "gross_margin",
            "net_margin",
            "debt_ratio",
        ],
        "description": "Profitability + margin + leverage quality",
    },
    "Volume_Composite": {
        "label": "成交量",
        "weight": 0.10,
        "direction": -1,
        "members": [
            "Volume_Concentration",
            "Volume_Trend_10D",
        ],
        "description": "Volume pattern signals",
    },
    "Reversal_Composite": {
        "label": "反转",
        "weight": 0.10,
        "direction": -1,
        "members": [
            "Short_Term_Reversal_5D",
        ],
        "description": "Short-term mean reversion",
    },
}

# Missing-member fallback: try these alternatives
FALLBACK_MEMBERS: dict[str, list[str]] = {
    "Volatility_60D": ["Volatility_20D"],
    "Residual_Momentum_3M": ["Momentum_3M"],
    "PCF_OCF": ["PE_TTM", "PB"],
    "Volume_Trend_10D": ["Volume_Concentration"],
    "Short_Term_Reversal_5D": [],
}

# Composite-level directions
COMPOSITE_DIRECTIONS: dict[str, int] = {
    name: cfg["direction"] for name, cfg in COMPOSITE_DEFINITIONS.items()
}

COMPOSITE_DESCRIPTIONS: dict[str, str] = {
    name: cfg["description"] for name, cfg in COMPOSITE_DEFINITIONS.items()
}

COMPOSITE_WEIGHTS: dict[str, float] = {
    name: cfg["weight"] for name, cfg in COMPOSITE_DEFINITIONS.items()
}


# ------------------------------------------------------------------
# Engine
# ------------------------------------------------------------------


@dataclass
class CompositeResult:
    """Result of computing one composite factor."""

    name: str = ""
    n_members_found: int = 0
    n_members_total: int = 0
    missing_members: list[str] = field(default_factory=list)
    score: pl.DataFrame | None = None  # [trade_date, symbol, score]

    @property
    def coverage_pct(self) -> float:
        if self.n_members_total == 0:
            return 0.0
        return self.n_members_found / self.n_members_total


class FactorCompositeEngine:
    """Merges correlated factors into composite Alpha Sources.

    For each composite, equal-weights rank-normalized member factors,
    then combines into a single score per stock per day.

    Usage:
        engine = FactorCompositeEngine()
        composites = engine.compute_all(all_factors)
        # → {"LowVol_Composite": df, "Momentum_Composite": df, ...}
    """

    def compute_one(
        self,
        composite_name: str,
        all_factors: dict[str, dict[str, dict[str, float]]],
    ) -> CompositeResult:
        """Compute a single composite from raw factor values.

        Args:
            composite_name: e.g. "LowVol_Composite".
            all_factors: {date: {code: {factor_name: value}}} nested dict.

        Returns:
            CompositeResult with score DataFrame.
        """
        cfg = COMPOSITE_DEFINITIONS.get(composite_name)
        if cfg is None:
            return CompositeResult(name=composite_name)

        members = cfg["members"]
        direction = cfg["direction"]
        result = CompositeResult(
            name=composite_name,
            n_members_total=len(members),
        )

        # Find available members
        available_members: list[str] = []
        for m in members:
            if self._factor_exists(m, all_factors):
                available_members.append(m)

        result.n_members_found = len(available_members)
        result.missing_members = [m for m in members if m not in available_members]

        if not available_members:
            logger.debug("Composite '{}': no members available", composite_name)
            return result

        # Build per-date composite scores
        rows: list[dict] = []
        for date_str, stocks in all_factors.items():
            codes = list(stocks.keys())
            if not codes:
                continue

            # Collect member values per stock
            stock_scores: dict[str, list[float]] = {c: [] for c in codes}
            for m in available_members:
                for code in codes:
                    val = stocks[code].get(m)
                    if val is not None and val == val:
                        stock_scores[code].append(val)

            # Rank each member across stocks, then average
            for m in available_members:
                m_values = []
                for code in codes:
                    val = stocks[code].get(m)
                    if val is not None and val == val:
                        m_values.append(val)
                    else:
                        m_values.append(float("nan"))

                if len(m_values) < 3:
                    continue

                s = pl.Series(m, m_values)
                # Rank normalize (0-1)
                ranks = s.rank() / s.len()
                ranks = ranks.fill_null(0.5)

                for i, code in enumerate(codes):
                    stock_scores[code].append(ranks[i] if i < len(ranks) else 0.5)

            # Composite = mean of available member ranks × direction
            for code in codes:
                vals = stock_scores[code]
                if vals:
                    raw = sum(vals) / len(vals)
                    score = raw * direction
                    rows.append(
                        {
                            "trade_date": date_str,
                            "symbol": code,
                            "score": score,
                        }
                    )

        if rows:
            result.score = pl.DataFrame(
                rows,
                schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "score": pl.Float64},
            )

        return result

    def compute_all(
        self,
        all_factors: dict[str, dict[str, dict[str, float]]],
    ) -> dict[str, pl.DataFrame]:
        """Compute all composite factors.

        Returns:
            {composite_name: score_df} for composites with data.
        """
        composites: dict[str, pl.DataFrame] = {}
        for name in COMPOSITE_DEFINITIONS:
            r = self.compute_one(name, all_factors)
            if r.score is not None and not r.score.is_empty():
                composites[name] = r.score
                logger.debug(
                    "Composite '{}': {}/{} members (missing: {})",
                    name,
                    r.n_members_found,
                    r.n_members_total,
                    r.missing_members,
                )
        return composites

    def summary(self) -> dict:
        """Return composite definitions summary."""
        result = {}
        for name, cfg in COMPOSITE_DEFINITIONS.items():
            result[name] = {
                "label": cfg["label"],
                "weight": cfg["weight"],
                "direction": cfg["direction"],
                "n_members": len(cfg["members"]),
                "members": cfg["members"],
                "description": cfg["description"],
            }
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _factor_exists(
        name: str,
        all_factors: dict[str, dict[str, dict[str, float]]],
    ) -> bool:
        """Check if a factor exists in the data."""
        for stocks in all_factors.values():
            for factors in stocks.values():
                if name in factors:
                    return True
        return False
