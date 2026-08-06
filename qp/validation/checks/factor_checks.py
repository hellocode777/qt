"""Factor validation checks — Rank IC, IC_IR, t-stat, stratification,
neutralization survival, minimum sample period, coverage, and missing rate.

All checks follow the BaseRule contract. Thresholds are constructor-injected
so they can be overridden from config or CLI without code changes.

See rule.md §7.9.1, §10.1, §10.2 for the complete specification.
DP-002 §4.5: Coverage (>95%) and Missing Rate (<5%) checks added per V7-V8.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from qp.shared.types import ValidationStatus
from qp.validation.engine import BaseRule, RuleResult, ValidationContext

# ------------------------------------------------------------------
# Rank IC Check
# ------------------------------------------------------------------


class RankICCheck(BaseRule):
    """Cross-sectional Rank IC (Spearman) between factor value and forward return.

    Computed daily, then aggregated via mean over the full period.
    Threshold: mean |IC| ≥ min_ic_mean (default 0.02 per rule.md §7.9.1).
    """

    def __init__(self, min_ic_mean: float = 0.02) -> None:
        self._min_ic_mean = min_ic_mean

    @property
    def rule_name(self) -> str:
        return "rank_ic"

    def check(self, context: ValidationContext) -> RuleResult:
        feature_df = context.feature_df
        price_df = context.price_df

        if feature_df is None or price_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df or price_df in validation context.",
            )

        ic_series = _compute_rank_ic(feature_df, price_df)
        if ic_series is None or len(ic_series) == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Could not compute Rank IC — insufficient data.",
            )

        mean_ic = float(ic_series.mean())
        passed = abs(mean_ic) >= self._min_ic_mean

        # Score: map mean_IC to 0-100 linearly, cap at 0.10
        score = min(100.0, (abs(mean_ic) / 0.10) * 100.0)

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_ic_mean,
            actual_value=round(mean_ic, 4),
            detail=(
                f"Mean Rank IC = {mean_ic:.4f} "
                f"({'≥' if passed else '<'} threshold {self._min_ic_mean})"
            ),
        )


# ------------------------------------------------------------------
# IC_IR Check
# ------------------------------------------------------------------


class ICIRCheck(BaseRule):
    """Information Coefficient / Information Ratio (IC_IR).

    IC_IR = mean(IC) / std(IC).  Measures signal consistency.
    Threshold: IC_IR ≥ min_ic_ir (default 0.3 per rule.md §7.9.1).
    """

    def __init__(self, min_ic_ir: float = 0.3) -> None:
        self._min_ic_ir = min_ic_ir

    @property
    def rule_name(self) -> str:
        return "ic_ir"

    def check(self, context: ValidationContext) -> RuleResult:
        feature_df = context.feature_df
        price_df = context.price_df

        if feature_df is None or price_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df or price_df in validation context.",
            )

        ic_series = _compute_rank_ic(feature_df, price_df)
        if ic_series is None or len(ic_series) < 2:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Insufficient IC data for IC_IR computation.",
            )

        mean_ic = float(ic_series.mean())
        std_ic = float(ic_series.std())
        ic_ir = abs(mean_ic) / std_ic if std_ic > 0 else 0.0

        passed = ic_ir >= self._min_ic_ir
        score = min(100.0, (ic_ir / 1.0) * 100.0)  # 1.0 IC_IR → score 100

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_ic_ir,
            actual_value=round(ic_ir, 4),
            detail=(
                f"IC_IR = {ic_ir:.4f} (IC mean={mean_ic:.4f}, IC std={std_ic:.4f}) "
                f"{'≥' if passed else '<'} threshold {self._min_ic_ir}"
            ),
        )


# ------------------------------------------------------------------
# IC t-stat Check
# ------------------------------------------------------------------


class TStatCheck(BaseRule):
    """IC t-statistic — tests whether IC is statistically different from zero.

    t-stat = mean(IC) / (std(IC) / sqrt(n_days))
    Threshold: |t-stat| ≥ min_t_stat (default 2.0 per rule.md §7.9.1).
    """

    def __init__(self, min_t_stat: float = 2.0) -> None:
        self._min_t_stat = min_t_stat

    @property
    def rule_name(self) -> str:
        return "ic_t_stat"

    def check(self, context: ValidationContext) -> RuleResult:
        feature_df = context.feature_df
        price_df = context.price_df

        if feature_df is None or price_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df or price_df in validation context.",
            )

        ic_series = _compute_rank_ic(feature_df, price_df)
        if ic_series is None or len(ic_series) < 6:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Insufficient IC data for t-stat (need ≥ 6 observations).",
            )

        mean_ic = float(ic_series.mean())
        std_ic = float(ic_series.std())
        n = len(ic_series)
        t_stat = abs(mean_ic) / (std_ic / np.sqrt(n)) if std_ic > 0 else 0.0

        passed = t_stat >= self._min_t_stat
        score = min(100.0, (t_stat / 5.0) * 100.0)  # t-stat 5.0 → score 100

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_t_stat,
            actual_value=round(t_stat, 2),
            detail=(
                f"IC t-stat = {t_stat:.2f} (n={n}) "
                f"{'≥' if passed else '<'} threshold {self._min_t_stat}"
            ),
        )


# ------------------------------------------------------------------
# Stratification (Quantile Spread) Check
# ------------------------------------------------------------------


class StratificationCheck(BaseRule):
    """Quantile-based stratification check.

    Groups stocks into quantiles by factor value each day, computes
    equal-weighted forward return per quantile.  Checks that the
    top-bottom spread is directionally consistent (mean spread ≠ 0)
    and statistically significant (t-stat ≥ min_t_stat).

    Threshold: top-bottom spread t-stat ≥ min_t_stat (default 2.0).
    """

    def __init__(self, n_quantiles: int = 5, min_t_stat: float = 2.0) -> None:
        self._n_quantiles = n_quantiles
        self._min_t_stat = min_t_stat

    @property
    def rule_name(self) -> str:
        return "stratification"

    def check(self, context: ValidationContext) -> RuleResult:
        feature_df = context.feature_df
        price_df = context.price_df

        if feature_df is None or price_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df or price_df in validation context.",
            )

        spreads = _compute_quantile_spreads(feature_df, price_df, self._n_quantiles)
        if spreads is None or len(spreads) < 6:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Insufficient data for stratification check.",
            )

        mean_spread = float(spreads.mean())
        std_spread = float(spreads.std())
        t_stat = abs(mean_spread) / (std_spread / np.sqrt(len(spreads))) if std_spread > 0 else 0.0

        passed = t_stat >= self._min_t_stat
        score = min(100.0, (t_stat / 5.0) * 100.0)

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_t_stat,
            actual_value=round(t_stat, 2),
            detail=(
                f"Top-Bottom spread mean = {mean_spread:.4f}, "
                f"t-stat = {t_stat:.2f} (n={len(spreads)}) "
                f"{'≥' if passed else '<'} threshold {self._min_t_stat}"
            ),
        )


# ------------------------------------------------------------------
# Shared computation helpers
# ------------------------------------------------------------------


def _compute_rank_ic(
    feature_df: pl.DataFrame,
    price_df: pl.DataFrame,
    forward_period: int = 1,
) -> np.ndarray | None:
    """Compute daily cross-sectional Rank IC (Spearman) series.

    For each day T: Spearman corr(feature_value_T, forward_return_T→T+forward_period)
    across all stocks with data on that day.

    Args:
        feature_df: [trade_date, symbol, feature_value]
        price_df: [trade_date, symbol, close]
        forward_period: Days ahead for forward return (default 1).

    Returns:
        NumPy array of daily IC values, or None if computation fails.
    """
    # Compute forward return per symbol
    px = price_df.sort(["symbol", "trade_date"]).with_columns(
        pl.col("close").shift(-forward_period).over("symbol").alias("forward_close")
    )
    px = px.with_columns(
        ((pl.col("forward_close") - pl.col("close")) / pl.col("close")).alias("fwd_ret")
    )
    px = px.drop_nulls(subset=["fwd_ret"])

    # Join feature values with forward returns on (trade_date, symbol)
    merged = feature_df.join(
        px.select(["trade_date", "symbol", "fwd_ret"]),
        on=["trade_date", "symbol"],
        how="inner",
    )

    if merged.is_empty():
        return None

    # Per-day Rank IC (Spearman) — skip days with < 5 stocks
    ic_values: list[float] = []
    dates = merged["trade_date"].unique().sort().to_list()

    for d in dates:
        day_data = merged.filter(pl.col("trade_date") == d)
        if day_data.height < 5:
            continue
        # Spearman rank correlation
        feat_rank = day_data["feature_value"].rank()
        ret_rank = day_data["fwd_ret"].rank()
        rho = _spearman_from_ranks(feat_rank, ret_rank)
        ic_values.append(rho)

    return np.array(ic_values) if ic_values else None


def _spearman_from_ranks(rx: pl.Series, ry: pl.Series) -> float:
    """Compute Spearman correlation from ranked series."""
    n = len(rx)
    if n < 3:
        return 0.0
    d2 = float((rx - ry).pow(2).sum())  # type: ignore[arg-type]
    rho = 1.0 - (6.0 * d2) / (n * (n * n - 1))
    return float(rho)


def _compute_quantile_spreads(
    feature_df: pl.DataFrame,
    price_df: pl.DataFrame,
    n_quantiles: int = 5,
) -> np.ndarray | None:
    """Compute daily top-bottom quantile forward-return spreads.

    Returns:
        NumPy array of daily spread values, or None if computation fails.
    """
    # Forward return
    px = price_df.sort(["symbol", "trade_date"]).with_columns(
        pl.col("close").shift(-1).over("symbol").alias("forward_close")
    )
    px = px.with_columns(
        ((pl.col("forward_close") - pl.col("close")) / pl.col("close")).alias("fwd_ret")
    )
    px = px.drop_nulls(subset=["fwd_ret"])

    merged = feature_df.join(
        px.select(["trade_date", "symbol", "fwd_ret"]),
        on=["trade_date", "symbol"],
        how="inner",
    )
    if merged.is_empty():
        return None

    spreads: list[float] = []
    dates = merged["trade_date"].unique().sort().to_list()

    for d in dates:
        day_data = merged.filter(pl.col("trade_date") == d)
        if day_data.height < n_quantiles * 2:
            continue

        # Assign quantile group by feature value rank
        day_data = day_data.with_columns(
            (
                (pl.col("feature_value").rank() / day_data.height * n_quantiles)
                .ceil()
                .clip(1, n_quantiles)
                .cast(pl.Int64)
            ).alias("quantile")
        )

        # Mean forward return per quantile
        q_ret = day_data.group_by("quantile").agg(pl.col("fwd_ret").mean().alias("mean_ret"))
        q_ret = q_ret.sort("quantile")

        if q_ret.height < 2:
            continue
        top_ret = q_ret["mean_ret"][-1]
        bottom_ret = q_ret["mean_ret"][0]
        spreads.append(top_ret - bottom_ret)

    return np.array(spreads) if spreads else None


# ------------------------------------------------------------------
# Neutralization Survival Check (P1 — rule.md §10.2, Rule 9)
# ------------------------------------------------------------------


class NeutralizationCheck(BaseRule):
    """Validates that alpha survives industry/market-cap neutralization.

    Per rule.md Rule 9 "Alpha Must Survive Neutralization":
      "无法通过行业与市值中性化检验的'收益'，只是 Beta 风格暴露，非纯 Alpha。"

    Computes Rank IC before and after neutralization. Fails if the
    post-neutralization IC decays too much relative to pre-neutralization IC.

    Threshold: post_neutralization_IC / pre_neutralization_IC ≥ min_ratio
    (default 0.5 — post-IC must retain at least 50% of pre-IC).
    """

    def __init__(self, min_ratio: float = 0.5) -> None:
        self._min_ratio = min_ratio

    @property
    def rule_name(self) -> str:
        return "neutralization"

    def check(self, context: ValidationContext) -> RuleResult:
        pre_ic = context.metadata.get("pre_neutralization_ic")
        post_ic = context.metadata.get("post_neutralization_ic")

        if pre_ic is None or post_ic is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing pre_neutralization_ic or post_neutralization_ic "
                    "in context.metadata. Compute IC before/after "
                    "neutralize_cross_section_ols() and set both values."
                ),
            )

        pre_ic = abs(float(pre_ic))
        post_ic = abs(float(post_ic))

        if pre_ic == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Pre-neutralization IC is zero — factor has no predictive power.",
            )

        ratio = post_ic / pre_ic
        passed = ratio >= self._min_ratio

        # Score: ratio 1.0 (no decay) → 100, ratio 0.0 → 0
        score = min(100.0, ratio * 100.0)

        if passed:
            detail = (
                f"Alpha survives neutralization: post-IC {post_ic:.4f} = "
                f"{ratio:.0%} of pre-IC {pre_ic:.4f} (≥ {self._min_ratio:.0%})"
            )
        else:
            detail = (
                f"Alpha FAILS neutralization: post-IC {post_ic:.4f} = "
                f"{ratio:.0%} of pre-IC {pre_ic:.4f} (< {self._min_ratio:.0%}). "
                f"Factor is likely Beta exposure, not pure Alpha."
            )

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_ratio,
            actual_value=round(ratio, 3),
            detail=detail,
        )


# ------------------------------------------------------------------
# Minimum Sample Period Check (P1 — rule.md §10.1)
# ------------------------------------------------------------------


class MinSamplePeriodCheck(BaseRule):
    """Validates that training data spans sufficient market history.

    Per rule.md §10.1:
      "最小样本区间 ≥ 3 年（覆盖至少 1 轮牛熊）— 避免单一市场状态下的过拟合"

    Reads training window from context.metadata["train_start"] and
    ["train_end"]. Accepts date strings in ISO format.
    """

    def __init__(self, min_years: float = 3.0) -> None:
        self._min_years = min_years

    @property
    def rule_name(self) -> str:
        return "min_sample_period"

    def check(self, context: ValidationContext) -> RuleResult:
        train_start = context.metadata.get("train_start", "")
        train_end = context.metadata.get("train_end", "")

        if not train_start or not train_end:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=(
                    "Missing train_start or train_end in context.metadata. "
                    "Set context.metadata['train_start'] = '2021-01-01' etc."
                ),
            )

        from datetime import date

        try:
            start = date.fromisoformat(str(train_start)[:10])
            end = date.fromisoformat(str(train_end)[:10])
        except (ValueError, TypeError):
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=f"Cannot parse train_start='{train_start}' or train_end='{train_end}' as ISO date.",
            )

        days = (end - start).days
        years = days / 365.25

        if days <= 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail=f"train_end ({train_end}) is before train_start ({train_start}).",
            )

        passed = years >= self._min_years
        score = min(100.0, (years / 5.0) * 100.0)  # 5 years → score 100

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_years,
            actual_value=round(years, 2),
            detail=(
                f"Training period: {train_start} → {train_end} = {years:.1f} years "
                f"({'≥' if passed else '<'} threshold {self._min_years} years). "
                f"({days} calendar days)"
            ),
        )


# ------------------------------------------------------------------
# Coverage Check (DP-002 §4.5, V7)
# ------------------------------------------------------------------


class CoverageCheck(BaseRule):
    """Validates that factor covers sufficient stock universe each day.

    Per DP-002 §4.5: factor must have coverage > 95% of universe.
    Coverage = (stocks with valid factor value) / (total stocks in universe).

    Threshold: mean coverage ≥ min_coverage_pct (default 0.95).
    """

    def __init__(self, min_coverage_pct: float = 0.95) -> None:
        self._min_coverage_pct = min_coverage_pct

    @property
    def rule_name(self) -> str:
        return "coverage"

    def check(self, context: ValidationContext) -> RuleResult:
        feature_df = context.feature_df
        price_df = context.price_df

        if feature_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df in validation context.",
            )

        # Count total stocks per day from price universe (or feature_df itself)
        if price_df is not None and not price_df.is_empty():
            universe_per_day = price_df.group_by("trade_date").agg(
                pl.col("symbol").n_unique().alias("total_stocks")
            )
        else:
            # Fallback: use feature_df itself as the universe
            universe_per_day = feature_df.group_by("trade_date").agg(
                pl.col("symbol").n_unique().alias("total_stocks")
            )

        # Count stocks with valid factor values per day
        valid_per_day = (
            feature_df.drop_nulls(subset=["feature_value"])
            .group_by("trade_date")
            .agg(pl.col("symbol").n_unique().alias("covered_stocks"))
        )

        # Join to compute daily coverage ratio
        joined = valid_per_day.join(universe_per_day, on="trade_date", how="inner")
        if joined.is_empty():
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="No overlapping dates between feature and universe data.",
            )

        joined = joined.with_columns(
            (pl.col("covered_stocks") / pl.col("total_stocks")).alias("coverage_ratio")
        )

        # Mean coverage across all days
        mean_coverage = float(joined["coverage_ratio"].mean())
        n_days = joined.height

        # Check worst-day coverage too
        min_coverage = float(joined["coverage_ratio"].min())

        passed = mean_coverage >= self._min_coverage_pct
        score = min(100.0, (mean_coverage / 1.0) * 100.0)

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._min_coverage_pct,
            actual_value=round(mean_coverage, 4),
            detail=(
                f"Coverage = {mean_coverage:.1%} (min={min_coverage:.1%}) over {n_days} days "
                f"({'≥' if passed else '<'} threshold {self._min_coverage_pct:.0%})"
            ),
        )


# ------------------------------------------------------------------
# Missing Rate Check (DP-002 §4.5, V8)
# ------------------------------------------------------------------


class MissingRateCheck(BaseRule):
    """Validates that factor has low missing value rate.

    Per DP-002 §4.5: factor missing rate must be < 5%.
    Missing rate = (NaN/None rows) / (total rows) in feature_df.

    Threshold: missing rate ≤ max_missing_rate (default 0.05).
    """

    def __init__(self, max_missing_rate: float = 0.05) -> None:
        self._max_missing_rate = max_missing_rate

    @property
    def rule_name(self) -> str:
        return "missing_rate"

    def check(self, context: ValidationContext) -> RuleResult:
        feature_df = context.feature_df

        if feature_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df in validation context.",
            )

        total_rows = feature_df.height
        if total_rows == 0:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Feature DataFrame is empty.",
            )

        # Count null values in feature_value
        null_count = feature_df["feature_value"].null_count()
        missing_rate = null_count / total_rows

        passed = missing_rate <= self._max_missing_rate
        score = max(0.0, 100.0 - missing_rate * 200.0)  # 0% → 100, 5% → 90, 10% → 80

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._max_missing_rate,
            actual_value=round(missing_rate, 4),
            detail=(
                f"Missing rate = {missing_rate:.2%} ({null_count:,}/{total_rows:,} rows) "
                f"({'≤' if passed else '>'} threshold {self._max_missing_rate:.0%})"
            ),
        )


# ------------------------------------------------------------------
# Max Correlation Check (DP-002 §4.5, V9)
# ------------------------------------------------------------------


class MaxCorrelationCheck(BaseRule):
    """Validates that a new factor is not highly correlated with existing factors.

    Per DP-002 §4.5: correlation with any existing factor must be < 0.85.
    High correlation means the factor adds no new information — it's redundant.

    Reads existing factor columns from feature_df, or accepts a pre-computed
    max_correlation from context.metadata.

    Threshold: max |correlation| < max_corr (default 0.85).
    """

    def __init__(self, max_corr: float = 0.85) -> None:
        self._max_corr = max_corr

    @property
    def rule_name(self) -> str:
        return "max_correlation"

    def check(self, context: ValidationContext) -> RuleResult:
        feature_df = context.feature_df

        # Accept pre-computed from metadata
        pre_max = context.metadata.get("max_correlation")
        if pre_max is not None:
            max_corr = float(pre_max)
            passed = max_corr < self._max_corr
            score = max(0.0, 100.0 - max_corr * 100.0)
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
                score=round(score, 2),
                threshold=self._max_corr,
                actual_value=round(max_corr, 4),
                detail=(
                    f"Max pairwise correlation = {max_corr:.3f} "
                    f"({'<' if passed else '≥'} threshold {self._max_corr})"
                ),
            )

        if feature_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df or max_correlation in context.",
            )

        # Identify factor columns (not trade_date, symbol, feature_value)
        factor_cols = [
            c for c in feature_df.columns if c not in ("trade_date", "symbol", "feature_value")
        ]
        if len(factor_cols) < 2:
            # Single factor — no correlation to check
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=100.0,
                threshold=self._max_corr,
                actual_value=0.0,
                detail="Single factor — no pairwise correlation to check.",
            )

        # Compute pairwise Spearman correlations

        corr_df = feature_df.select(factor_cols).drop_nulls()
        if corr_df.height < 5:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS,
                score=100.0,
                detail="Insufficient data for correlation check.",
            )

        # Compute correlation matrix
        corr_matrix = corr_df.to_pandas().corr(method="spearman")
        n = len(factor_cols)
        max_corr = 0.0
        worst_pair = ("", "")

        for i in range(n):
            for j in range(i + 1, n):
                corr_val = abs(corr_matrix.iloc[i, j])
                if corr_val > max_corr:
                    max_corr = corr_val
                    worst_pair = (factor_cols[i], factor_cols[j])

        passed = max_corr < self._max_corr
        score = max(0.0, 100.0 - max_corr * 100.0)

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._max_corr,
            actual_value=round(max_corr, 4),
            detail=(
                f"Max correlation = {max_corr:.3f} ({worst_pair[0]}↔{worst_pair[1]}) "
                f"({'<' if passed else '≥'} threshold {self._max_corr})"
            ),
        )


# ------------------------------------------------------------------
# Turnover Limit Check (DP-002 §4.5, V10)
# ------------------------------------------------------------------


class TurnoverLimitCheck(BaseRule):
    """Validates that factor turnover is within acceptable bounds.

    Per DP-002 §4.5: day-over-day factor rank turnover should be reasonable.
    Excessive turnover means the factor is unstable / noisy.

    Reads turnover from context.metadata["factor_turnover"], or computes
    from feature_df if multiple days of data are available.

    Threshold: mean turnover ≤ max_turnover (default 0.50).
    """

    def __init__(self, max_turnover: float = 0.50) -> None:
        self._max_turnover = max_turnover

    @property
    def rule_name(self) -> str:
        return "turnover_limit"

    def check(self, context: ValidationContext) -> RuleResult:
        # Accept pre-computed from metadata
        pre_turnover = context.metadata.get("factor_turnover")
        if pre_turnover is not None:
            turnover = float(pre_turnover)
            passed = turnover <= self._max_turnover
            score = max(0.0, 100.0 - turnover * 100.0)
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
                score=round(score, 2),
                threshold=self._max_turnover,
                actual_value=round(turnover, 4),
                detail=(
                    f"Factor turnover = {turnover:.3f} "
                    f"({'≤' if passed else '>'} threshold {self._max_turnover})"
                ),
            )

        feature_df = context.feature_df

        if feature_df is None:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Missing feature_df or factor_turnover in context.",
            )

        # Compute day-over-day rank correlation turnover
        import numpy as np

        dates = feature_df["trade_date"].unique().sort().to_list()
        if len(dates) < 2:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Need ≥ 2 trading days to compute turnover.",
            )

        turnovers: list[float] = []
        for i in range(1, len(dates)):
            prev = feature_df.filter(pl.col("trade_date") == dates[i - 1])
            curr = feature_df.filter(pl.col("trade_date") == dates[i])

            common_symbols = set(prev["symbol"].to_list()) & set(curr["symbol"].to_list())
            if len(common_symbols) < 5:
                continue

            prev_scores = prev.filter(pl.col("symbol").is_in(common_symbols))["feature_value"]
            curr_scores = curr.filter(pl.col("symbol").is_in(common_symbols))["feature_value"]

            # Rank correlation
            n = len(prev_scores)
            rank_prev = prev_scores.rank()
            rank_curr = curr_scores.rank()
            d2 = float((rank_prev - rank_curr).pow(2).sum())
            rho = 1.0 - (6.0 * d2) / (n * (n * n - 1))
            turnovers.append(1.0 - rho)

        if not turnovers:
            return RuleResult(
                rule_name=self.rule_name,
                status=ValidationStatus.FAIL,
                score=0.0,
                detail="Could not compute turnover — insufficient common symbols.",
            )

        mean_turnover = float(np.mean(turnovers))
        passed = mean_turnover <= self._max_turnover
        score = max(0.0, 100.0 - mean_turnover * 100.0)

        return RuleResult(
            rule_name=self.rule_name,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            score=round(score, 2),
            threshold=self._max_turnover,
            actual_value=round(mean_turnover, 4),
            detail=(
                f"Mean turnover = {mean_turnover:.3f} over {len(turnovers)} days "
                f"({'≤' if passed else '>'} threshold {self._max_turnover})"
            ),
        )
