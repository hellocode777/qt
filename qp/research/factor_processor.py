"""Factor Processing Pipeline — cross-sectional factor cleaning and combination.

Pipeline:
  Raw factors → Winsorize (MAD) → Normalize (Rank/ZScore) → Combine → Scores

Optional stages:
  - Industry Neutralization: subtract industry median from each factor
  - Factor Orthogonalization: VIF detection → regression residual orthogonalization
  - ML Mode: LightGBM binary classification replaces linear weighted combination

All stage functions operate on a single cross-section (one date, many stocks).

Usage:
    from qp.research.factor_processor import factor_pipeline

    # all_factors: {date_str: {symbol: {factor_name: value}}}
    scores = factor_pipeline(
        all_factors,
        weights={"Momentum_3M": 0.3, "Volatility_20D": -0.15},
        normalize_method="rank",
        winsorize_method="mad",
        industry_map={...},
    )
    # scores: polars DataFrame [trade_date, symbol, score]
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

# ------------------------------------------------------------------
# Winsorize (outlier handling)
# ------------------------------------------------------------------


def winsorize_percentile(
    values: pl.Series,
    limits: float = 0.05,
) -> pl.Series:
    """Clip values beyond given percentile limits.

    Args:
        values: Cross-sectional factor values for one date.
        limits: Fraction to clip on each tail (0.05 = clip top/bottom 5%).

    Returns:
        Clipped Series (same length).
    """
    if values.len() < 5 or values.n_unique() < 5:
        return values
    lower = values.quantile(limits)
    upper = values.quantile(1.0 - limits)
    return values.clip(lower, upper)


def winsorize_mad(
    values: pl.Series,
    n: float = 5.0,
) -> pl.Series:
    """MAD-based winsorize — more robust than percentile method.

    Clips values beyond median ± n * MAD (Median Absolute Deviation).

    Args:
        values: Cross-sectional factor values for one date.
        n: Multiplier for MAD band. Default 5.0.

    Returns:
        Clipped Series.
    """
    if values.len() < 5 or values.n_unique() < 5:
        return values

    median = values.median()
    mad = (values - median).abs().median()
    if mad is None or mad == 0.0:
        return values

    lower = median - n * mad  # type: ignore[reportOperatorIssue]
    upper = median + n * mad  # type: ignore[reportOperatorIssue]
    return values.clip(lower, upper)  # type: ignore[reportArgumentType]


def winsorize(
    values: pl.Series,
    method: str = "mad",
    limits: float = 0.05,
    mad_n: float = 5.0,
) -> pl.Series:
    """Unified winsorize interface.

    Args:
        values: Cross-sectional factor values.
        method: "mad" | "percentile" | None.
        limits: Percentile clip fraction (for "percentile").
        mad_n: MAD multiplier (for "mad").

    Returns:
        Clipped Series (or original if method is None).
    """
    if method == "mad":
        return winsorize_mad(values, n=mad_n)
    elif method == "percentile":
        return winsorize_percentile(values, limits=limits)
    else:
        return values


# ------------------------------------------------------------------
# Normalize (cross-sectional standardization)
# ------------------------------------------------------------------


def zscore(values: pl.Series) -> pl.Series:
    """Z-score: (x - mean) / std. Zero-mean, unit-variance."""
    if values.len() < 3 or values.n_unique() < 3:
        return pl.Series(values.name, [0.0] * values.len())
    mean = values.mean()
    std = values.std(ddof=1)
    if std is None or std == 0.0:
        return pl.Series(values.name, [0.0] * values.len())
    return ((values - mean) / std).fill_null(0.0)


def rank_score(values: pl.Series) -> pl.Series:
    """Rank normalization: map values to [0, 1] via percentile rank.

    Robust to outliers — the default method in the reference pipeline.
    """
    n = values.len()
    if n == 0:
        return values
    # Polars rank(method="average") returns 1-based ranks
    ranks = values.rank(method="average")
    if n <= 1:
        return pl.Series(values.name, [0.0] * n)
    return ((ranks - 1.0) / (n - 1.0)).fill_null(0.5)


def minmax_scale(values: pl.Series) -> pl.Series:
    """MinMax: (x - min) / (max - min). Maps to [0, 1]."""
    n = values.len()
    if n == 0:
        return values
    v_min = values.min()
    v_max = values.max()
    if v_min is None or v_max is None or v_max == v_min:  # type: ignore[reportOperatorIssue]
        return pl.Series(values.name, [0.0] * n)
    return ((values - v_min) / (v_max - v_min)).fill_null(0.0)  # type: ignore[reportOperatorIssue]


def normalize(values: pl.Series, method: str = "rank") -> pl.Series:
    """Unified normalization interface.

    Args:
        values: Cross-sectional factor values.
        method: "rank" | "zscore" | "minmax".

    Returns:
        Normalized Series.
    """
    if method == "zscore":
        return zscore(values)
    elif method == "rank":
        return rank_score(values)
    elif method == "minmax":
        return minmax_scale(values)
    else:
        raise ValueError(f"Unknown normalization method: {method}")


# ------------------------------------------------------------------
# Factor direction adjustment
# ------------------------------------------------------------------


def adjust_direction(values: pl.Series, direction: int) -> pl.Series:
    """Flip sign if direction is negative.

    E.g. PE_TTM has direction=-1 (lower is better), so values are negated.
    """
    if direction < 0:
        return -values
    return values


# ------------------------------------------------------------------
# Factor combination (weighted sum)
# ------------------------------------------------------------------


def combine_factors(
    factor_df: pl.DataFrame,
    weights: dict[str, float],
    normalize_method: str = "rank",
    winsorize_method: str = "mad",
    directions: dict[str, int] | None = None,
) -> pl.Series:
    """Combine multiple factors into a composite score.

    Per-factor pipeline: winsorize → normalize → adjust direction → weight.

    Args:
        factor_df: Cross-sectional factor values (rows = stocks, cols = factors).
        weights: {factor_name: weight}. Weights are normalized by sum(abs(weights)).
        normalize_method: "rank" | "zscore" | "minmax".
        winsorize_method: "mad" | "percentile" | None.
        directions: {factor_name: 1 or -1}. Default all +1.

    Returns:
        Composite score Series (one value per stock).
    """
    if factor_df.is_empty():
        return pl.Series("score", [], dtype=pl.Float64)

    directions = directions or {}

    # Keep only factors present in both weights and DataFrame
    available = {k: v for k, v in weights.items() if k in factor_df.columns}
    if not available:
        return pl.Series("score", [0.0] * factor_df.height)

    # Normalize weights by sum of absolute values
    total_abs = sum(abs(v) for v in available.values())
    if total_abs == 0.0:
        return pl.Series("score", [0.0] * factor_df.height)
    norm_weights = {k: v / total_abs for k, v in available.items()}

    composite = pl.Series("score", [0.0] * factor_df.height)

    for factor_name, weight in norm_weights.items():
        raw = factor_df[factor_name].clone()

        # 1. Winsorize
        cleaned = winsorize(raw, method=winsorize_method)

        # 2. Normalize
        normed = normalize(cleaned, method=normalize_method)

        # 3. Direction adjustment (higher score = better)
        direction = directions.get(factor_name, 1)
        normed = adjust_direction(normed, direction)

        # 4. Weight and accumulate
        composite += normed * weight

    return composite


# ------------------------------------------------------------------
# Industry neutralization
# ------------------------------------------------------------------


def industry_neutralize(
    factor_df: pl.DataFrame,
    industry_map: dict[str, str],
    id_col: str = "symbol",
    strength: float = 1.0,
) -> pl.DataFrame:
    """Remove industry bias by subtracting industry median from each factor.

    For each factor column, subtract strength * median_of_same_industry.
    After neutralization, factor values represent within-industry relative strength.

    Args:
        factor_df: Cross-sectional factor values with an identifier column.
        industry_map: {symbol: industry_name}.
        id_col: Column name for stock identifier (default "symbol").
        strength: Neutralization strength (0.0=off, 1.0=full, 0.5=half).

    Returns:
        Neutralized factor DataFrame (same shape, same column order).
    """
    if factor_df.is_empty() or strength <= 0.0:
        return factor_df

    if id_col not in factor_df.columns:
        return factor_df

    df = factor_df.clone()

    # Build industry column
    symbols = df[id_col].to_list()
    industries = [industry_map.get(str(s), "其他") for s in symbols]
    df = df.with_columns(pl.Series("_industry", industries))

    factor_cols = [c for c in df.columns if c not in (id_col, "_industry")]

    for col in factor_cols:
        df = df.with_columns(
            (pl.col(col) - strength * pl.col(col).median().over("_industry")).alias(col)
        )

    return df.drop("_industry")


def industry_group_score(
    factor_df: pl.DataFrame,
    weights: dict[str, float],
    industry_map: dict[str, str],
    normalize_method: str = "rank",
    winsorize_method: str = "mad",
    strength: float = 1.0,
) -> pl.Series:
    """Score within each industry group, making cross-industry comparison fair.

    For each industry separately: combine factors → rank normalize within group.
    This ensures every industry has representation in final selection.

    Args:
        factor_df: Cross-sectional factor values with "symbol" column.
        weights: {factor_name: weight}.
        industry_map: {symbol: industry_name}.
        normalize_method: "rank" | "zscore" | "minmax".
        winsorize_method: "mad" | "percentile" | None.
        strength: Blend 1.0=within-industry only, 0.0=global only.

    Returns:
        Cross-industry comparable score Series (0-1 range).
    """
    if factor_df.is_empty():
        return pl.Series("score", [], dtype=pl.Float64)

    id_col = "symbol" if "symbol" in factor_df.columns else "code"

    # Global scores for blending
    global_scores = None
    if strength < 1.0:
        factor_cols = [c for c in factor_df.columns if c != id_col]
        global_scores = combine_factors(
            factor_df.select(factor_cols), weights, normalize_method, winsorize_method
        )
        global_scores = normalize(global_scores, method="rank")

    # Build industry column
    symbols = factor_df[id_col].to_list()
    industries = [industry_map.get(str(s), "其他") for s in symbols]
    df = factor_df.with_columns(pl.Series("_industry", industries))

    factor_cols = [c for c in factor_df.columns if c != id_col]
    scores = pl.Series("score", [0.0] * df.height)

    for industry in df["_industry"].unique().to_list():
        mask = df["_industry"] == industry
        group_indices = [i for i, v in enumerate(df["_industry"].to_list()) if v == industry]
        group_df = df.filter(mask)

        if group_df.height < 3:
            group_scores = combine_factors(
                group_df.select(factor_cols), weights, normalize_method, winsorize_method
            )
        else:
            group_scores = combine_factors(
                group_df.select(factor_cols), weights, normalize_method, winsorize_method
            )
            # Rank normalize within group for cross-industry comparability
            group_scores = normalize(group_scores, method="rank")

        for gi, idx in enumerate(group_indices):
            scores[idx] = group_scores[gi]

    # Blend with global scores
    if global_scores is not None and strength < 1.0:
        for i in range(df.height):
            scores[i] = strength * scores[i] + (1.0 - strength) * global_scores[i]  # type: ignore[call-overload]

    return scores


# ------------------------------------------------------------------
# Factor orthogonalization
# ------------------------------------------------------------------


# Cache VIF results across cross-sections (same factor set → same VIF analysis)
_vif_cache: dict[frozenset, list[str]] = {}


def _compute_vif(corr_matrix: np.ndarray, col_names: list[str]) -> dict[str, float]:
    """Compute Variance Inflation Factor for each column.

    VIF_j = 1 / (1 - R²_j) where R²_j is from regressing col_j on all other cols.
    VIF > 10 → high multicollinearity → candidate for orthogonalization.
    """
    n_cols = corr_matrix.shape[0]
    vif: dict[str, float] = {}

    for j in range(n_cols):
        y = corr_matrix[:, j].copy()
        X = np.delete(corr_matrix, j, axis=1)

        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            y_pred = X @ beta
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            vif_val = 1.0 / (1.0 - r_squared) if r_squared < 1.0 else float("inf")
        except np.linalg.LinAlgError:
            vif_val = float("inf")

        vif[col_names[j]] = float(vif_val)

    return vif


def orthogonalize_factors(
    factor_df: pl.DataFrame,
    vif_threshold: float = 10.0,
) -> pl.DataFrame:
    """Orthogonalize high-collinearity factors via regression residuals.

    For each factor with VIF > threshold:
      Regress it on all other factors → replace with residual (unique signal).

    Args:
        factor_df: Cross-sectional factor values (columns = factors).
        vif_threshold: VIF above which a factor is orthogonalized.

    Returns:
        Orthogonalized factor DataFrame (same shape).
    """
    if factor_df.is_empty() or factor_df.width < 2:
        return factor_df

    cols = factor_df.columns
    cols_key = frozenset(cols)

    # Check VIF cache
    if cols_key not in _vif_cache:
        df_clean = factor_df.drop_nulls()
        if df_clean.is_empty() or df_clean.width < 2:
            return factor_df

        corr_data = df_clean.to_numpy()
        corr = np.corrcoef(corr_data.T)
        if corr.ndim < 2:
            return factor_df

        vif = _compute_vif(corr, list(cols))
        high_vif = [k for k, v in vif.items() if v > vif_threshold]
        _vif_cache[cols_key] = high_vif
    else:
        high_vif = _vif_cache[cols_key]

    if not high_vif:
        return factor_df

    # Orthogonalize each high-VIF factor
    df_result = factor_df.clone()
    df_clean = factor_df.drop_nulls()

    for target in high_vif:
        control_cols = [c for c in cols if c != target]
        try:
            X = df_clean.select(control_cols).to_numpy()
            y = df_clean[target].to_numpy()
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            y_pred = X @ beta
            residual = y - y_pred

            # Build residual series aligned to full (possibly NaN-containing) data
            residual_list: list[float] = []
            clean_idx = 0
            for row_i in range(factor_df.height):
                row = factor_df.row(row_i)
                vals = [row[factor_df.columns.index(c)] for c in [target] + control_cols]
                if any(v is None or (isinstance(v, float) and v != v) for v in vals):
                    residual_list.append(row[factor_df.columns.index(target)] or 0.0)
                else:
                    residual_list.append(float(residual[clean_idx]))
                    clean_idx += 1

            df_result = df_result.drop(target).with_columns(pl.Series(target, residual_list))
        except np.linalg.LinAlgError:
            continue

    return df_result


# ------------------------------------------------------------------
# Full pipeline
# ------------------------------------------------------------------


def factor_pipeline(
    all_factors: dict[str, dict[str, dict[str, float]]],
    weights: dict[str, float],
    normalize_method: str = "rank",
    winsorize_method: str = "mad",
    industry_map: dict[str, str] | None = None,
    orthogonalize: bool = False,
    vif_threshold: float = 10.0,
    industry_neutral_strength: float = 1.0,
    return_diagnostics: bool = False,
) -> pl.DataFrame | tuple[pl.DataFrame, dict[str, Any]]:
    """Complete factor processing pipeline.

    For each date (cross-section):
      1. Build factor DataFrame (stocks × factors)
      2. [optional] Orthogonalize (VIF detection → regression residual)
      3. [optional] Industry neutralize (within-industry scoring)
      4. Winsorize → Normalize → Weighted Combine → Score

    Args:
        all_factors: {date_str: {symbol: {factor_name: value}}}
        weights: {factor_name: weight}. Negative = penalize (e.g. Volatility).
        normalize_method: "rank" (default) | "zscore" | "minmax".
        winsorize_method: "mad" (default) | "percentile" | None.
        industry_map: {symbol: industry_name}. Enables industry neutralization.
        orthogonalize: Enable VIF-based factor orthogonalization.
        vif_threshold: VIF threshold for orthogonalization (default 10.0).
        industry_neutral_strength: 0.0=global only, 1.0=within-industry only.
        return_diagnostics: If True, return (scores_df, diagnostics).

    Returns:
        Polars DataFrame [trade_date, symbol, score] sorted by date+symbol,
        or (DataFrame, diagnostics_dict) when return_diagnostics=True.
    """
    dates = sorted(all_factors.keys())
    all_rows: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {
        "n_dates": len(dates),
        "n_factors": len(weights),
        "orthogonalized_factors": [],
    }

    for i, date_str in enumerate(dates):
        stock_factors = all_factors[date_str]
        if not stock_factors:
            continue

        # Build factor DataFrame for this cross-section
        symbols: list[str] = []
        rows: list[dict[str, float]] = []
        for symbol, factors in stock_factors.items():
            symbols.append(symbol)
            rows.append(factors)

        df = pl.DataFrame(rows)
        df = df.with_columns(pl.Series("symbol", symbols))

        factor_cols = [c for c in df.columns if c != "symbol"]
        if not factor_cols:
            continue

        # Step 0: Orthogonalization (on factor-only DataFrame)
        if orthogonalize and len(factor_cols) >= 2:
            factor_only = df.select(factor_cols)
            factor_orth = orthogonalize_factors(factor_only, vif_threshold)
            df = df.drop(factor_cols)
            for col in factor_orth.columns:
                df = df.with_columns(factor_orth[col])
            factor_cols = factor_orth.columns
            if i == 0:
                diagnostics["orthogonalized_factors"] = _vif_cache.get(frozenset(factor_cols), [])

        # Step 1-3: Industry neutralization or direct combination
        if industry_map is not None and len(set(industry_map.values())) > 1:
            scores = industry_group_score(
                df,
                weights,
                industry_map,
                normalize_method,
                winsorize_method,
                strength=industry_neutral_strength,
            )
        else:
            factor_only = df.select(factor_cols)
            scores = combine_factors(
                factor_only,
                weights,
                normalize_method,
                winsorize_method,
            )

        # Collect results
        for j, symbol in enumerate(symbols):
            score_val = scores[j] if j < len(scores) else 0.0
            if score_val is None or (isinstance(score_val, float) and score_val != score_val):
                score_val = 0.0
            all_rows.append(
                {
                    "trade_date": date_str,
                    "symbol": symbol,
                    "score": float(score_val),
                }
            )

    result = pl.DataFrame(all_rows)
    if not result.is_empty():
        result = result.sort(["trade_date", "symbol"])

    if return_diagnostics:
        diagnostics["score_stats"] = {}
        if not result.is_empty():
            diagnostics["score_stats"] = {
                "mean": float(result["score"].mean() or 0.0),  # type: ignore[reportArgumentType]
                "std": float(result["score"].std(ddof=1) or 0.0),  # type: ignore[reportArgumentType]
                "n_rows": result.height,
            }
        return result, diagnostics

    return result
