"""Rank IC computation — the primary factor evaluation metric.

Computes cross-sectional Spearman Rank IC between factor scores and
forward returns.  Includes significance testing (IC_IR, IC t-stat).

Forward returns are prepared in a separate step (:func:`prepare_forward_returns`)
so a caller evaluating many factors — each over the same horizons — pays the
sort/shift over the price history once per horizon instead of once per factor
per horizon.

Thresholds from rule.md §10.1:
  - Rank IC mean abs ≥ 0.02
  - IC_IR ≥ 0.3
  - IC t-stat ≥ 2.0
  - Minimum sample interval ≥ 3 years
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

# Trading days kept after each score date's forward horizon.  Suspended stocks
# make `shift(-n).over("symbol")` reach past the n-th calendar day; see
# `_restrict_price_to_dates` for why this buffer exists.
_FORWARD_WINDOW_BUFFER_DAYS = 10

# Default IC-decay horizons (used by `compute_ic_decay*`).
DEFAULT_DECAY_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20)


@dataclass
class ICRecord:
    """Result of a single Rank IC computation."""

    ic_mean: float
    ic_ir: float
    ic_t_stat: float
    ic_std: float
    ic_positive_pct: float  # % of days with positive IC
    n_days: int
    daily_ics: list[float]
    # Threshold checks
    ic_mean_pass: bool = False
    ic_ir_pass: bool = False
    ic_t_stat_pass: bool = False
    all_pass: bool = False

    def __post_init__(self) -> None:
        self.ic_mean_pass = abs(self.ic_mean) >= 0.02
        self.ic_ir_pass = self.ic_ir >= 0.3
        self.ic_t_stat_pass = self.ic_t_stat >= 2.0
        self.all_pass = self.ic_mean_pass and self.ic_ir_pass and self.ic_t_stat_pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "ic_mean": self.ic_mean,
            "ic_ir": self.ic_ir,
            "ic_t_stat": self.ic_t_stat,
            "ic_std": self.ic_std,
            "ic_positive_pct": self.ic_positive_pct,
            "n_days": self.n_days,
            "ic_mean_pass": self.ic_mean_pass,
            "ic_ir_pass": self.ic_ir_pass,
            "ic_t_stat_pass": self.ic_t_stat_pass,
            "all_pass": self.all_pass,
        }

    def summary(self) -> str:
        status = "✅" if self.all_pass else "❌"
        return (
            f"{status} IC={self.ic_mean:+.4f} | IC_IR={self.ic_ir:.2f} | "
            f"t={self.ic_t_stat:.2f} | IC>0={self.ic_positive_pct:.1f}% | N={self.n_days}"
        )


def compute_rank_ic(
    factor_values: pl.Series | np.ndarray,
    forward_returns: pl.Series | np.ndarray,
) -> float:
    """Compute Spearman rank correlation between factor and forward returns.

    Uses the efficient formula: ρ = 1 - 6·Σd²/(n·(n²-1))

    Args:
        factor_values: Factor scores for one cross-section.
        forward_returns: Corresponding forward returns.

    Returns:
        Spearman rank correlation in [-1, 1]. Returns 0.0 if < 5 samples.
    """
    if isinstance(factor_values, pl.Series):
        factor_values = factor_values.to_numpy()
    if isinstance(forward_returns, pl.Series):
        forward_returns = forward_returns.to_numpy()

    valid = np.isfinite(factor_values) & np.isfinite(forward_returns)
    x = factor_values[valid]
    y = forward_returns[valid]

    n = len(x)
    if n < 5:
        return 0.0

    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    d2 = np.sum((rx - ry) ** 2)
    return float(1.0 - 6.0 * d2 / (n * (n * n - 1)))


def _aligned_dates(dates: pl.Series | Sequence[Any], price_df: pl.DataFrame) -> pl.Series | None:
    """Cast `dates` to the price frame's date dtype; None when unalignable."""
    date_dtype = price_df.schema["trade_date"]
    series = dates if isinstance(dates, pl.Series) else pl.Series("trade_date", list(dates))
    if series.dtype == date_dtype:
        return series
    try:
        return (
            series.str.to_date()
            if series.dtype == pl.Utf8 and date_dtype == pl.Date
            else series.cast(date_dtype)
        )
    except pl.exceptions.PolarsError:
        return None


def _restrict_price_to_dates(
    price_df: pl.DataFrame,
    dates: pl.Series | Sequence[Any],
    forward_days: int,
    buffer_days: int = _FORWARD_WINDOW_BUFFER_DAYS,
) -> pl.DataFrame:
    """Keep only the price rows that some ``dates`` forward return can reach.

    The forward-return sort/shift over the whole price history dominates the
    runtime of this module (measured: 1.1s for 7.3M rows, per call, regardless
    of how many score dates are requested).  A score date only ever reads
    ``forward_days`` rows ahead of itself, so every price row outside
    ``[date, date + forward_days + buffer_days]`` is dead weight and can be
    dropped without changing the resulting IC series.

    Why the buffer: ``shift(-forward_days).over("symbol")`` counts rows *present
    for that symbol*, so a suspended stock's forward return can come from a
    calendar date beyond the horizon.  The buffer keeps those rows reachable;
    a suspension longer than ``buffer_days`` yields a null forward return and
    that stock simply leaves the cross-section for that date.

    Returns ``price_df`` unchanged when the dates cannot be aligned with the
    price calendar or when nothing matches — this is a pure optimisation, never
    a filter that could silently empty the frame.
    """
    if price_df.is_empty():
        return price_df

    aligned = _aligned_dates(dates, price_df)
    if aligned is None or aligned.is_empty():
        return price_df

    calendar = price_df["trade_date"].unique().sort()
    if calendar.is_empty():
        return price_df

    position = {date: i for i, date in enumerate(calendar.to_list())}
    span = forward_days + buffer_days
    keep = np.zeros(calendar.len(), dtype=bool)
    matched = False
    for date in aligned.to_list():
        pos = position.get(date)
        if pos is None:
            continue
        keep[pos : min(pos + span + 1, calendar.len())] = True
        matched = True

    if not matched:
        return price_df

    keep_dates = calendar.filter(pl.Series(keep))
    return price_df.join(keep_dates.to_frame(), on="trade_date", how="semi")


def _restrict_price_to_score_windows(
    score_df: pl.DataFrame,
    price_df: pl.DataFrame,
    forward_days: int,
    buffer_days: int = _FORWARD_WINDOW_BUFFER_DAYS,
) -> pl.DataFrame:
    """`_restrict_price_to_dates` for a [trade_date, symbol, score] score frame."""
    if price_df.is_empty() or score_df.is_empty() or "trade_date" not in score_df.columns:
        return price_df
    return _restrict_price_to_dates(price_df, score_df["trade_date"], forward_days, buffer_days)


def prepare_forward_returns(
    price_df: pl.DataFrame,
    forward_days: int,
    score_dates: pl.Series | Sequence[Any] | None = None,
    buffer_days: int = _FORWARD_WINDOW_BUFFER_DAYS,
) -> pl.DataFrame:
    """Compute ``(trade_date, symbol) → forward_return`` once, for reuse.

    Evaluate many factors over the same horizon by calling this once and then
    passing the result to :func:`compute_daily_ic_series_from_forward` /
    :func:`evaluate_factor_ic_from_forward` — the sort/shift over the price
    history is the dominant cost, so hoisting it out of the per-factor loop is
    the single biggest speedup available to bulk factor evaluation.

    Args:
        price_df: [trade_date, symbol, close] — price data.
        forward_days: Forward horizon for returns.
        score_dates: Dates the caller will query. When given, irrelevant price
            rows are dropped first (see :func:`_restrict_price_to_dates`).
        buffer_days: Extra trading days kept past each horizon (suspensions).

    Returns:
        [trade_date (Utf8), symbol, forward_return] with null returns dropped.
    """
    if score_dates is not None:
        price_df = _restrict_price_to_dates(price_df, score_dates, forward_days, buffer_days)

    px = price_df.sort(["symbol", "trade_date"])
    px = px.with_columns(
        (pl.col("close").shift(-forward_days).over("symbol") / pl.col("close") - 1).alias(
            "forward_return"
        )
    )
    px = px.drop_nulls(subset=["forward_return"])
    px = px.with_columns(pl.col("trade_date").cast(pl.Utf8))
    return px.select(["trade_date", "symbol", "forward_return"])


def compute_daily_ic_series_from_forward(
    score_df: pl.DataFrame,
    forward_df: pl.DataFrame,
    min_stocks_per_day: int = 10,
) -> list[dict[str, Any]]:
    """Daily Rank IC from a prepared forward-return frame.

    Args:
        score_df: [trade_date, symbol, score] — factor scores per date.
        forward_df: output of :func:`prepare_forward_returns`.
        min_stocks_per_day: Skip dates with fewer stocks.

    Returns:
        List of {date, ic, n_stocks} dicts, sorted by date.
    """
    score_df = score_df.with_columns(pl.col("trade_date").cast(pl.Utf8))
    merged = score_df.join(
        forward_df.select(["trade_date", "symbol", "forward_return"]),
        on=["trade_date", "symbol"],
        how="inner",
    )
    if merged.is_empty():
        return []

    # One hash-based partition pass instead of re-filtering the whole merged
    # frame per date (measured: 0.75s → ~0.2s for a 420-date, 1M-row cross-section).
    results: list[dict[str, Any]] = []
    for part in merged.partition_by("trade_date", maintain_order=True):
        if part.height < min_stocks_per_day:
            continue
        ic = compute_rank_ic(
            part["score"].to_numpy(),
            part["forward_return"].to_numpy(),
        )
        results.append({"date": part["trade_date"][0], "ic": ic, "n_stocks": part.height})

    results.sort(key=lambda record: record["date"])
    return results


def compute_daily_ic_series(
    score_df: pl.DataFrame,
    price_df: pl.DataFrame,
    forward_days: int = 5,
    min_stocks_per_day: int = 10,
) -> list[dict[str, Any]]:
    """Compute Rank IC for each date in the score DataFrame.

    For each date, joins forward returns to the factor scores and computes
    cross-sectional Spearman Rank IC.

    Args:
        score_df: [trade_date, symbol, score] — factor scores per date.
        price_df: [trade_date, symbol, close] — price data.
        forward_days: Forward horizon for returns.
        min_stocks_per_day: Skip dates with fewer stocks.

    Returns:
        List of {date, ic, n_stocks} dicts, sorted by date.
    """
    if score_df.is_empty():
        return []
    forward_df = prepare_forward_returns(price_df, forward_days, score_df["trade_date"])
    return compute_daily_ic_series_from_forward(score_df, forward_df, min_stocks_per_day)


def _ic_record_from_daily(daily: list[dict[str, Any]]) -> ICRecord:
    """Summary statistics (with significance tests) from a daily IC series."""
    if not daily:
        return ICRecord(
            ic_mean=0.0,
            ic_ir=0.0,
            ic_t_stat=0.0,
            ic_std=0.0,
            ic_positive_pct=0.0,
            n_days=0,
            daily_ics=[],
        )

    ics = np.array([r["ic"] for r in daily])
    n = len(ics)

    ic_mean = float(np.mean(ics))
    ic_std = float(np.std(ics, ddof=1)) if n > 1 else 1.0
    ic_ir = abs(ic_mean) / ic_std if ic_std > 0 else 0.0
    ic_t_stat = abs(ic_mean) / (ic_std / np.sqrt(n)) if ic_std > 0 and n > 1 else 0.0
    ic_positive_pct = float(np.sum(ics > 0) / n * 100)

    return ICRecord(
        ic_mean=round(ic_mean, 4),
        ic_ir=round(ic_ir, 2),
        ic_t_stat=round(ic_t_stat, 2),
        ic_std=round(ic_std, 4),
        ic_positive_pct=round(ic_positive_pct, 1),
        n_days=n,
        daily_ics=ics.tolist(),
    )


def evaluate_factor_ic(
    score_df: pl.DataFrame,
    price_df: pl.DataFrame,
    forward_days: int = 5,
    min_stocks_per_day: int = 10,
) -> ICRecord:
    """Full Rank IC evaluation for a factor or composite score.

    Computes daily IC series, then summary statistics with significance tests.

    Args:
        score_df: [trade_date, symbol, score].
        price_df: [trade_date, symbol, close].
        forward_days: Forward return horizon.
        min_stocks_per_day: Minimum stocks per cross-section.

    Returns:
        ICRecord with all statistics and threshold checks.
    """
    return _ic_record_from_daily(
        compute_daily_ic_series(score_df, price_df, forward_days, min_stocks_per_day)
    )


def evaluate_factor_ic_from_forward(
    score_df: pl.DataFrame,
    forward_df: pl.DataFrame,
    min_stocks_per_day: int = 10,
) -> ICRecord:
    """`evaluate_factor_ic` from a prepared forward-return frame."""
    return _ic_record_from_daily(
        compute_daily_ic_series_from_forward(score_df, forward_df, min_stocks_per_day)
    )


def compute_ic_decay(
    score_df: pl.DataFrame,
    price_df: pl.DataFrame,
    horizons: list[int] | None = None,
    min_stocks_per_day: int = 10,
) -> dict[int, ICRecord]:
    """Compute Rank IC across multiple forward horizons (IC decay analysis).

    A healthy factor should show gradually decaying IC as horizon increases,
    not a sharp drop-off or increase.

    Args:
        score_df: [trade_date, symbol, score].
        price_df: [trade_date, symbol, close].
        horizons: Forward horizons to evaluate (default: 1, 3, 5, 10, 20).
        min_stocks_per_day: Minimum stocks per cross-section.

    Returns:
        {horizon: ICRecord} mapping.
    """
    if horizons is None:
        horizons = list(DEFAULT_DECAY_HORIZONS)

    results: dict[int, ICRecord] = {}
    for h in horizons:
        results[h] = evaluate_factor_ic(
            score_df, price_df, forward_days=h, min_stocks_per_day=min_stocks_per_day
        )
    return results


def compute_ic_decay_from_forward(
    score_df: pl.DataFrame,
    forward_by_horizon: Mapping[int, pl.DataFrame],
    horizons: Sequence[int] | None = None,
    min_stocks_per_day: int = 10,
) -> dict[int, ICRecord]:
    """`compute_ic_decay` from forward-return frames prepared once per horizon.

    Args:
        score_df: [trade_date, symbol, score].
        forward_by_horizon: {horizon: :func:`prepare_forward_returns` output}.
        horizons: Horizons to evaluate (default: the mapping's keys).
        min_stocks_per_day: Minimum stocks per cross-section.

    Returns:
        {horizon: ICRecord} mapping. Raises KeyError for a horizon missing from
        ``forward_by_horizon`` — silent zeros would look like a real result.
    """
    if horizons is None:
        horizons = (
            sorted(forward_by_horizon) if forward_by_horizon else list(DEFAULT_DECAY_HORIZONS)
        )

    results: dict[int, ICRecord] = {}
    for h in horizons:
        results[h] = evaluate_factor_ic_from_forward(
            score_df, forward_by_horizon[h], min_stocks_per_day=min_stocks_per_day
        )
    return results
