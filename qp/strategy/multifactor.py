"""Multi-Factor Stock Selection Strategy — full pipeline engine.

Core pipeline:
  1. Quality filter: remove stocks with poor fundamentals
  2. Factor computation: 15+ factors across 5 categories per stock
  3. Cross-sectional processing: winsorize → normalize → combine → scores
  4. Anti-chase filter: skip stocks that surged recently
  5. Rebalance signal generation: buy Top-N, sell buffer zone, regime-adaptive
  6. Market filter: block buys in bearish markets

Features:
  - PE/PB industry-relative: compare vs industry median instead of absolute
  - Fundamental data filling: missing fundamentals filled with cross-sectional median
  - Residual momentum: beta-adjusted 3M momentum (removes market effect)
  - Live mode: only score most recent N days for speed
  - Sell buffer: don't sell at exact boundary, use wider zone
  - Regime-adaptive: dynamic position count per market regime

Usage:
    from qp.strategy.multifactor import run_multifactor_strategy

    price_data = _load_price_data()
    signals = run_multifactor_strategy(
        price_data,
        weights={"Momentum_3M": 0.20, "Volatility_20D": -0.10, ...},
        top_n=10,
        rebalance_freq=20,
        industry_neutral=True,
        quality_filter=True,
        anti_chase=True,
    )
    # Returns: Polars DataFrame [date, symbol, signal, score, reason]
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np
import polars as pl
from loguru import logger

from qp.research.factor_processor import factor_pipeline
from qp.research.feature.compute import (
    compute_all_factors,
)
from qp.shared.protocols.base_strategy import BaseStrategy

# ------------------------------------------------------------------
# Cross-sectional scoring
# ------------------------------------------------------------------


def compute_cross_sectional_scores(
    price_data: dict[str, pl.DataFrame],
    weights: dict[str, float] | None = None,
    min_history: int = 60,
    fundamental_data: dict[str, pl.DataFrame] | None = None,
    valuation_data: dict[str, pl.DataFrame] | None = None,
    industry_neutral: bool = False,
    orthogonalize: bool = False,
    live_mode: bool = False,
    live_lookback_dates: int = 60,
    return_diagnostics: bool = False,
    model_mode: bool = False,
    extra_factors: dict[str, dict[str, dict[str, float]]] | None = None,
) -> pl.DataFrame | tuple[pl.DataFrame, dict[str, Any]]:
    """Compute daily cross-sectional multi-factor scores for all stocks.

    Args:
        price_data: {code: DataFrame(date, open, high, low, close, volume)}.
        weights: {factor_name: weight}. Default: equal weight all available.
        min_history: Minimum trading days required per stock.
        fundamental_data: {code: DataFrame(report_date, ROE, gross_margin, ...)}.
        valuation_data: {code: DataFrame(date, PE_TTM, PB, ...)}.
        industry_neutral: Enable industry neutralization.
        orthogonalize: Enable VIF-based factor orthogonalization.
        live_mode: Only score last N days (faster for production).
        live_lookback_dates: Days to keep in live mode.
        return_diagnostics: Return (scores, diagnostics) tuple.

    Returns:
        Polars DataFrame [trade_date, symbol, score] sorted by date,
        or (DataFrame, diagnostics) when return_diagnostics=True.
    """
    from qp.research.feature.compute import get_default_factor_weights

    if weights is None:
        weights = get_default_factor_weights()

    fundamental_data = fundamental_data or {}
    valuation_data = valuation_data or {}

    # Separate factor types
    all_factor_names = set(weights.keys())

    # Valuation factors (external data)
    valuation_factor_names = all_factor_names & {
        "PE_TTM",
        "PB",
        "Dividend_Yield",
        "PS_TTM",
        "PCF_OCF",
    }

    # Fundamental factors (external data)
    fundamental_factor_names = all_factor_names & {
        "ROE",
        "revenue_growth",
        "net_profit_growth",
        "gross_margin",
        "net_margin",
        "debt_ratio",
        "EPS",
        "NAV",
    }

    # Price/volume factors (computed from OHLCV)
    price_factor_names = all_factor_names - valuation_factor_names - fundamental_factor_names

    # Collect raw factor values: {date_str: {symbol: {factor_name: value}}}
    all_raw: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))

    total_stocks = len(price_data)
    for stock_idx, (code, df) in enumerate(price_data.items()):
        if df is None or df.is_empty() or df.height < min_history:
            continue

        required = {"trade_date", "close", "volume"}
        if not required.issubset(set(df.columns)):
            continue

        df = df.sort("trade_date")

        # Compute all price/volume factors (vectorized, one pass)
        factors = compute_all_factors(df)
        if factors.is_empty():
            continue

        # ── Pre-extract as numpy arrays (QuantTrading pattern) ──
        dates_arr = factors["trade_date"].cast(pl.Utf8).to_numpy()
        price_dates_dt = df["trade_date"]

        # Price/volume factors → build column → array map
        price_cols_available = [f for f in price_factor_names if f in factors.columns]
        price_arrays = {f: factors[f].to_numpy() for f in price_cols_available}

        # ── Pre-align fundamental data (ffill to stock dates, QuantTrading pattern) ──
        fund_arrays: dict[str, np.ndarray] = {}
        fund_df_src = fundamental_data.get(code)
        if fund_df_src is not None and not fund_df_src.is_empty():
            for fname in fundamental_factor_names:
                if fname in fund_df_src.columns:
                    aligned = _align_to_price_dates(
                        fund_df_src, fname, price_dates_dt, "report_date"
                    )
                    if aligned is not None:
                        fund_arrays[fname] = aligned

        # ── Pre-align valuation data ──
        val_arrays: dict[str, np.ndarray] = {}
        val_df_src = valuation_data.get(code)
        if val_df_src is not None and not val_df_src.is_empty():
            for fname in valuation_factor_names:
                if fname in val_df_src.columns:
                    aligned = _align_to_price_dates(val_df_src, fname, price_dates_dt, "trade_date")
                    if aligned is not None:
                        val_arrays[fname] = aligned

        # ── Build all_raw by position (no per-row DataFrame ops) ──
        n_rows = factors.height
        for row_idx in range(n_rows):
            date_str = dates_arr[row_idx]

            # Price/volume factors — direct array access
            pf_dict: dict[str, float] = {}
            for fname, arr in price_arrays.items():
                v = arr[row_idx]
                if v is not None and v == v:  # not NaN
                    pf_dict[fname] = float(v)
            if pf_dict:
                all_raw[date_str][code] = pf_dict

            # Fundamental factors
            for fname, arr in fund_arrays.items():
                v = arr[row_idx]
                if v is not None and v == v:
                    all_raw[date_str][code][fname] = float(v)

            # Valuation factors
            for fname, arr in val_arrays.items():
                v = arr[row_idx]
                if v is not None and v == v and v > 0:
                    all_raw[date_str][code][fname] = float(v)

        if (stock_idx + 1) % 200 == 0:
            logger.info("🧮 因子计算: {}/{}", stock_idx + 1, total_stocks)

    # Sort dates
    all_dates = sorted(all_raw.keys())

    # ── Industry-relative valuation (PE_TTM / PB) ──
    industry_map = _build_industry_map(price_data) if industry_neutral else None
    if industry_map is not None:
        for rel_factor in ["PE_TTM", "PB"]:
            if rel_factor not in all_factor_names:
                continue
            for date_str in all_dates:
                _make_industry_relative(all_raw[date_str], rel_factor, industry_map)

    # ── Fill missing fundamentals with cross-sectional median ──
    for fname in fundamental_factor_names | valuation_factor_names:
        if fname not in weights:
            continue
        for date_str in all_dates:
            stocks = all_raw[date_str]
            haves = {code: factors[fname] for code, factors in stocks.items() if fname in factors}
            if len(haves) < 5:
                continue
            median_val = sorted(haves.values())[len(haves) // 2]
            for code in price_data:
                if code not in stocks:
                    all_raw[date_str][code] = {}
                if fname not in all_raw[date_str][code]:
                    all_raw[date_str][code][fname] = median_val

    # ── Merge extra factors (pre-computed fundamental/alternative) ──
    if extra_factors:
        for date_str, sym_factors in extra_factors.items():
            for symbol, factors in sym_factors.items():
                for fname, fval in factors.items():
                    if fval is not None and fval == fval:  # not NaN
                        all_raw[date_str][symbol][fname] = float(fval)
        # Re-sort dates after merge
        all_dates = sorted(all_raw.keys())

    # ── Live mode: keep only last N days ──
    if live_mode and len(all_dates) > live_lookback_dates:
        keep_dates = set(all_dates[-live_lookback_dates:])
        all_raw = {d: all_raw[d] for d in all_dates if d in keep_dates}
        all_dates = sorted(all_raw.keys())

    # ── Factor pipeline ──
    # Compute vol/amount risk maps for OLS neutralization
    vol_map, amt_map = _build_risk_maps(price_data)

    scores_result = factor_pipeline(
        all_raw,
        weights=weights,
        normalize_method="rank",
        winsorize_method="mad",
        industry_map=industry_map,
        volatility_map=vol_map,
        amount_map=amt_map,
        neutralize_method="ols" if (industry_map or vol_map) else "median",
        orthogonalize=orthogonalize,
        return_diagnostics=return_diagnostics,
        model_mode=model_mode,
        price_data=price_data,
    )

    if return_diagnostics:
        scores, diagnostics = scores_result  # type: ignore[assignment]
        diagnostics["all_factors"] = all_raw
        return scores, diagnostics  # type: ignore[return-value]

    return scores_result  # type: ignore[return-value]


def _build_risk_maps(
    price_data: dict[str, pl.DataFrame],
) -> tuple[dict[str, float], dict[str, float]]:
    """Build per-stock volatility and average daily amount maps.

    Computes latest 20-day annualized volatility and log average daily
    turnover amount for each stock.  These are used as control variables
    in OLS cross-sectional neutralization to strip vol/liquidity biases.

    Returns:
        (volatility_map, amount_map) — {symbol: float}.
    """
    vol_map: dict[str, float] = {}
    amt_map: dict[str, float] = {}

    for code, df in price_data.items():
        if df is None or df.is_empty():
            continue
        if "close" not in df.columns:
            continue

        df_s = df.sort("trade_date").with_columns(
            pl.col("close").cast(pl.Float64),
        )
        if "volume" in df_s.columns:
            df_s = df_s.with_columns(pl.col("volume").cast(pl.Float64))

        # 20-day annualized volatility
        rets = df_s["close"].pct_change()
        vol_20d = rets.tail(20).std()
        vol_val: float = float(vol_20d) if vol_20d is not None and vol_20d > 0 else 0.0  # type: ignore[arg-type]
        if vol_val > 0:
            vol_map[str(code)] = float(vol_val * np.sqrt(252))

        # Average daily amount (20-day)
        if "volume" in df_s.columns:
            amt = df_s["close"] * df_s["volume"]
            avg_amt = amt.tail(20).mean()
            amt_val: float = float(avg_amt) if avg_amt is not None and avg_amt > 0 else 0.0  # type: ignore[arg-type]
            if amt_val > 0:
                amt_map[str(code)] = amt_val

    return vol_map, amt_map


# ------------------------------------------------------------------
# Rebalance signal generation
# ------------------------------------------------------------------


def generate_rebalance_signals(
    scores: pl.DataFrame,
    top_n: int = 5,
    rebalance_freq: int = 20,
    force_rebalance_today: bool = False,
    holdings: set[str] | None = None,
    chased_codes: set[str] | None = None,
    sell_buffer_rank: int = 0,
    regime_map: dict[str, str] | None = None,
    regime_positions: dict[str, int] | None = None,
    score_percentile_min: float | None = None,
    score_percentile_max: float | None = None,
    price_data: dict | None = None,
    anti_chase: bool = False,
    chase_threshold: float = 0.20,
    chase_lookback: int = 5,
) -> pl.DataFrame:
    """Generate buy/sell signals from cross-sectional scores.

    Rebalance logic:
      - Every `rebalance_freq` trading days, re-evaluate rankings.
      - Stocks newly in Top-N → BUY signal.
      - Stocks falling out of Top-(N+buffer) → SELL signal.
      - On first rebalance day, all Top-N are bought.

    Score band selection (when score_percentile_min/max are set):
      - Instead of selecting absolute Top-N by score, select from a
        specific score percentile range (e.g. 60-80 = Q4 sweet spot).
      - This addresses the inverted-U return pattern where Q4 > Q5.

    Sell buffer: prevents whipsaw at the boundary.
      With top_n=5, buffer=5: buy at rank 1-5, sell at rank 11+.

    Args:
        scores: [trade_date, symbol, score].
        top_n: Number of stocks to hold.
        rebalance_freq: Days between rebalance checks.
        force_rebalance_today: Treat last day as rebalance day.
        holdings: Currently held stock codes.
        chased_codes: DEPRECATED — use price_data + anti_chase instead.
        sell_buffer_rank: Extra ranks before selling (recommend top_n*2).
        regime_map: {date_str: regime} for adaptive position sizing.
        regime_positions: {regime: top_n} — different N per market regime.
        score_percentile_min: If set, only select from scores above this percentile.
        score_percentile_max: If set, only select from scores below this percentile.
        price_data: {code: DataFrame(date, close, ...)} for per-date anti-chase.
        anti_chase: Skip stocks that surged >chase_threshold in last chase_lookback days.
        chase_threshold: Max recent return before skipping (default 20%).
        chase_lookback: Lookback days for chase detection (default 5).

    Returns:
        Polars DataFrame [date, symbol, signal, score, reason].
    """
    all_dates = sorted(scores["trade_date"].unique().to_list())
    if len(all_dates) < rebalance_freq:
        return pl.DataFrame()

    sell_zone = top_n + sell_buffer_rank
    has_regime = regime_map is not None and regime_positions is not None

    # Rebalance day indices
    rebalance_indices = list(range(0, len(all_dates), rebalance_freq))

    # Add last day if it's far enough from last rebalance
    last_idx = len(all_dates) - 1
    if force_rebalance_today:
        if last_idx not in rebalance_indices:
            rebalance_indices.append(last_idx)
    elif last_idx not in rebalance_indices:
        gap = last_idx - rebalance_indices[-1]
        if gap >= rebalance_freq // 2:
            rebalance_indices.append(last_idx)

    signals: list[dict[str, Any]] = []
    bought: set[str] = set()  # Actually purchased (not anti-chase skipped)
    chase_skipped = 0

    for idx in rebalance_indices:
        date_str = all_dates[idx]

        # Determine position count for this date
        if has_regime:
            regime = regime_map.get(date_str, "neutral")  # type: ignore[reportOptionalMemberAccess]
            _tn = regime_positions.get(regime, top_n)  # type: ignore[union-attr]
            _sz = _tn + sell_buffer_rank
        else:
            _tn = top_n
            _sz = sell_zone

        # Get scores for this date
        day_scores = scores.filter(pl.col("trade_date") == date_str)
        if day_scores.is_empty():
            continue

        # Sort by score descending
        day_scores = day_scores.sort("score", descending=True)
        symbols = day_scores["symbol"].to_list()
        score_vals = day_scores["score"].to_list()

        # Score band selection: filter to percentile range if specified
        if score_percentile_min is not None or score_percentile_max is not None:
            n_total = len(score_vals)
            lo = int(n_total * (score_percentile_min or 0) / 100)
            hi = int(n_total * (score_percentile_max or 100) / 100)
            lo = max(0, lo)
            hi = min(n_total, hi)
            top_pool = symbols[lo:hi]
        else:
            top_pool = symbols

        current_top = set(top_pool[:_tn])

        # Per-date anti-chase check (no temporal leakage)
        chased_today: set[str] = set()
        if anti_chase and price_data:
            for code in current_top:
                df = price_data.get(code)
                if df is None or df.is_empty():
                    continue
                # Get rows up to this date, take last (lookback+1) closes
                window = (
                    df.sort("trade_date")
                    .filter(pl.col("trade_date").cast(pl.Utf8) <= date_str)
                    .tail(chase_lookback + 1)["close"]
                    .to_list()
                )
                if len(window) < chase_lookback + 1:
                    continue
                recent_high = float(window[-1])
                recent_low = float(window[0])
                if recent_low > 0 and recent_high / recent_low - 1 > chase_threshold:
                    chased_today.add(code)

        # Merge per-date chased with legacy global chased (backward compat)
        skip_codes = chased_today | (chased_codes or set())

        if idx == 0:
            # First rebalance: buy all Top-N (skip chased)
            logger.debug(
                "   🎯 首次调仓 {}: Top-{}={} | 防追高过滤={}",
                date_str, _tn, current_top, len(skip_codes),
            )
            for j, code in enumerate(current_top):
                if code in skip_codes:
                    chase_skipped += 1
                    continue
                signals.append(
                    {
                        "date": date_str,
                        "symbol": code,
                        "signal": "buy",
                        "score": score_vals[j],
                        "reason": f"初始买入 Top{_tn}",
                    }
                )
                bought.add(code)
        else:
            # New entries to Top-N → BUY
            new_buys = current_top - bought
            for code in new_buys:
                if code in skip_codes:
                    chase_skipped += 1
                    continue
                # Find score
                code_score = 0.0
                for j, s in enumerate(symbols):
                    if s == code:
                        code_score = score_vals[j]
                        break
                signals.append(
                    {
                        "date": date_str,
                        "symbol": code,
                        "signal": "buy",
                        "score": code_score,
                        "reason": f"因子排名进入前{_tn}",
                    }
                )
                bought.add(code)

            # Fallen out of buffer zone → SELL
            current_sell_zone = set(symbols[:_sz])
            if holdings is not None:
                new_sells = holdings - current_sell_zone
            else:
                new_sells = bought - current_sell_zone

            for code in new_sells:
                # Find current rank for the reason string
                try:
                    rank_pos = symbols.index(code) + 1
                    code_score = score_vals[rank_pos - 1]
                    reason = f"因子排名跌至第{rank_pos}名 (卖出阈值: 前{_sz}名)"
                except ValueError:
                    code_score = 0.0
                    reason = "不在选股池 (可能被质量过滤/停牌)"

                signals.append(
                    {
                        "date": date_str,
                        "symbol": code,
                        "signal": "sell",
                        "score": code_score,
                        "reason": reason,
                    }
                )
                bought.discard(code)

    if not signals:
        return pl.DataFrame()

    result = pl.DataFrame(signals)
    result = result.sort(["date", "signal"])
    return result


# ------------------------------------------------------------------
# Main strategy runner
# ------------------------------------------------------------------


def run_multifactor_strategy(
    price_data: dict[str, pl.DataFrame],
    weights: dict[str, float] | None = None,
    top_n: int = 5,
    rebalance_freq: int = 20,
    min_history: int = 60,
    fundamental_data: dict[str, pl.DataFrame] | None = None,
    valuation_data: dict[str, pl.DataFrame] | None = None,
    force_rebalance_today: bool = False,
    industry_neutral: bool = False,
    holdings: set[str] | None = None,
    quality_filter: bool = False,
    anti_chase: bool = True,
    chase_threshold: float = 0.20,
    chase_lookback: int = 5,
    sell_buffer_rank: int = 0,
    orthogonalize: bool = False,
    regime_map: dict[str, str] | None = None,
    regime_positions: dict[str, int] | None = None,
    return_diagnostics: bool = False,
    model_mode: bool = False,
    score_percentile_min: float | None = None,
    score_percentile_max: float | None = None,
    extra_factors: dict[str, dict[str, dict[str, float]]] | None = None,
) -> pl.DataFrame | tuple[pl.DataFrame, dict[str, Any]]:
    """Run the complete multi-factor stock selection strategy.

    This is the primary entry point for strategy execution. It orchestrates:
      Quality filter → Factor computation → Cross-sectional scoring →
      Anti-chase → Rebalance signal generation.

    Args:
        price_data: {code: DataFrame(date, open, high, low, close, volume[, name])}.
        weights: {factor_name: weight}. None = equal weight all available.
        top_n: Number of stocks to select.
        rebalance_freq: Trading days between rebalance checks (~20 = monthly).
        min_history: Minimum trading days required per stock.
        fundamental_data: {code: DataFrame(report_date, ROE, gross_margin, ...)}.
        valuation_data: {code: DataFrame(date, PE_TTM, PB, ...)}.
        force_rebalance_today: Force last date as rebalance day (for live mode).
        industry_neutral: Enable industry neutralization.
        holdings: Current holdings (for sell signal targeting).
        quality_filter: Enable fundamental quality pre-screening.
        anti_chase: Skip stocks that surged recently.
        chase_threshold: Max recent return before skipping (default 20%).
        chase_lookback: Lookback days for chase detection (default 5).
        sell_buffer_rank: Extra ranks before selling (default 0, recommend top_n*2).
        orthogonalize: Enable factor orthogonalization.
        regime_map: {date_str: regime} for adaptive sizing.
        regime_positions: {regime: top_n} for adaptive sizing.
        return_diagnostics: Return (signals, diagnostics) tuple.

    Returns:
        Polars DataFrame [date, symbol, signal, score, reason, name],
        or (DataFrame, diagnostics) when return_diagnostics=True.
    """
    from qp.research.feature.compute import get_default_factor_weights

    if weights is None:
        weights = get_default_factor_weights()

    # ── 0. Quality filter ──
    qualified_codes: set[str] | None = None
    if quality_filter:
        from qp.strategy.quality_filter import apply_quality_filter

        qualified_codes = apply_quality_filter(
            price_data,
            fundamental_data or {},
            valuation_data or {},
        )
        if qualified_codes:
            filtered = len(price_data) - len(qualified_codes)
            if filtered > 0:
                price_data = {k: v for k, v in price_data.items() if k in qualified_codes}

    # ── 1. Cross-sectional scoring ──
    is_live = force_rebalance_today and holdings is not None
    css_result = compute_cross_sectional_scores(
        price_data,
        weights=weights,
        min_history=min_history,
        fundamental_data=fundamental_data,
        valuation_data=valuation_data,
        industry_neutral=industry_neutral,
        orthogonalize=orthogonalize,
        live_mode=is_live,
        live_lookback_dates=rebalance_freq * 3,
        return_diagnostics=return_diagnostics,
        model_mode=model_mode,
        extra_factors=extra_factors,
    )

    diagnostics = None
    if return_diagnostics:
        scores, diagnostics = css_result  # type: ignore[assignment]
    else:
        scores = css_result  # type: ignore[assignment]

    # ── 2. Generate rebalance signals ──
    signals = generate_rebalance_signals(
        scores,  # type: ignore[arg-type]
        top_n=top_n,
        rebalance_freq=rebalance_freq,
        force_rebalance_today=force_rebalance_today,
        holdings=holdings,
        sell_buffer_rank=sell_buffer_rank,
        regime_map=regime_map,
        regime_positions=regime_positions,
        score_percentile_min=score_percentile_min,
        score_percentile_max=score_percentile_max,
        price_data=price_data if anti_chase else None,
        anti_chase=anti_chase,
        chase_threshold=chase_threshold,
        chase_lookback=chase_lookback,
    )

    # ── 3. Add stock names ──
    if not signals.is_empty():
        name_map: dict[str, str] = {}
        for code, df in price_data.items():
            if df is not None and "name" in df.columns and not df.is_empty():
                name_map[code] = str(df["name"].tail(1).item())

        name_col = [name_map.get(c, "") for c in signals["symbol"].to_list()]
        signals = signals.with_columns(pl.Series("name", name_col))

    if return_diagnostics:
        diagnostics = diagnostics or {}
        diagnostics["scores"] = scores
        return signals, diagnostics  # type: ignore[return-value]
    return signals


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _align_to_price_dates(
    src_df: pl.DataFrame,
    field: str,
    price_dates: pl.Series,
    date_col: str,
) -> np.ndarray | None:
    """Forward-fill a fundamental/valuation field to match price dates.

    Uses Polars join_asof (Rust-native asof join). Returns a numpy
    float64 array aligned to price_dates, with NaN for missing values.
    """
    if src_df is None or src_df.is_empty():
        return None
    if field not in src_df.columns:
        return None
    if date_col not in src_df.columns:
        return None

    # Build lookup: [date, value], sorted, no nulls
    lookup = (
        src_df.select(
            [
                pl.col(date_col).cast(pl.Date).alias("_date"),
                pl.col(field).alias("_value"),
            ]
        )
        .drop_nulls("_value")
        .sort("_date")
    )
    if lookup.is_empty():
        return None

    # Build price frame with row index for re-sorting
    prices_frame = pl.DataFrame(
        {
            "_date": price_dates.cast(pl.Date),
        }
    ).with_row_index("_row_idx")

    # asof backward join: last lookup._date <= prices._date
    joined = (
        prices_frame.sort("_date")
        .join_asof(lookup, on="_date", strategy="backward")
        .sort("_row_idx")
    )

    return joined["_value"].to_numpy().astype(np.float64)


def _build_industry_map(
    price_data: dict[str, pl.DataFrame],
) -> dict[str, str] | None:
    """Build {code: industry} from price_data if industry info is available.

    Falls back to a placeholder map. In production, this should use
    actual industry classification data (e.g. 申万一级行业).
    """
    # Check if any DataFrame has an 'industry' column
    for df in price_data.values():
        if df is not None and "industry" in df.columns:
            industry_map: dict[str, str] = {}
            for code, stock_df in price_data.items():
                if stock_df is not None and "industry" in stock_df.columns:
                    ind = str(stock_df["industry"].tail(1).item() or "")
                    if ind:
                        industry_map[code] = ind
            if industry_map:
                return industry_map
            break

    return None


def _make_industry_relative(
    stock_factors: dict[str, dict[str, float]],
    factor_name: str,
    industry_map: dict[str, str],
) -> None:
    """Replace absolute factor values with industry-relative ratios.

    For each stock: factor_value = factor_value / median_of_same_industry.
    This makes cross-industry comparison fair (e.g. tech PE vs bank PE).
    """
    # Collect by industry
    ind_vals: dict[str, list[float]] = defaultdict(list)
    code_industry: dict[str, str] = {}

    for code, factors in stock_factors.items():
        if factor_name in factors:
            val = factors[factor_name]
            if val > 0:
                ind = industry_map.get(code, "")
                if ind:
                    ind_vals[ind].append(val)
                    code_industry[code] = ind

    # Replace
    for code, factors in stock_factors.items():
        if factor_name in factors and code in code_industry:
            ind = code_industry[code]
            vals = ind_vals.get(ind, [])
            if len(vals) >= 3:
                median_val = np.median(vals)
                if median_val > 0:
                    factors[factor_name] = factors[factor_name] / median_val  # type: ignore[operator]


# ------------------------------------------------------------------
# MultiFactorStrategy — BaseStrategy-compliant wrapper (rule.md §7.4)
# ------------------------------------------------------------------


class MultiFactorStrategy(BaseStrategy):
    """Multi-factor stock selection strategy implementing BaseStrategy.

    Binds factor computation + cross-sectional scoring into a PIT-compliant
    signal generator.  Produces ranked stock scores, not Orders (ADR-026).

    Usage:
        from qp.strategy.multifactor import MultiFactorStrategy

        strategy = MultiFactorStrategy(
            price_data,
            weights={"Momentum_3M": -0.10, "Volatility_20D": 0.08, ...},
            top_n=10,
        )
        signals = strategy.generate_signals(as_of_date=date.today())
        # → polars DataFrame [symbol, raw_score, rank]
    """

    def __init__(
        self,
        price_data: dict[str, pl.DataFrame],
        weights: dict[str, float] | None = None,
        top_n: int = 10,
        fundamental_data: dict[str, pl.DataFrame] | None = None,
        valuation_data: dict[str, pl.DataFrame] | None = None,
        industry_neutral: bool = False,
        orthogonalize: bool = False,
    ) -> None:
        from qp.research.feature.compute import (
            ALL_FACTOR_DIRECTIONS,
        )

        self._price_data = price_data
        self._top_n = top_n
        self._fundamental_data = fundamental_data
        self._valuation_data = valuation_data
        self._industry_neutral = industry_neutral
        self._orthogonalize = orthogonalize

        if weights is None:
            # Use calibrated directions as weights
            n = len(ALL_FACTOR_DIRECTIONS)
            weights = {f: d / n for f, d in ALL_FACTOR_DIRECTIONS.items()}

        self._weights = weights

        # Pre-compute cross-sectional scores (expensive, done once)
        self._scores = compute_cross_sectional_scores(
            price_data,
            weights=self._weights,
            min_history=120,
            fundamental_data=fundamental_data,
            valuation_data=valuation_data,
            industry_neutral=industry_neutral,
            orthogonalize=orthogonalize,
        )

    # ------------------------------------------------------------------
    # BaseStrategy protocol (rule.md §7.4)
    # ------------------------------------------------------------------

    @property
    def strategy_id(self) -> str:
        return "multifactor_v1.0"

    def generate_signals(self, as_of_date: date | str | pl.DataFrame) -> pl.DataFrame:
        """Generate PIT Alpha signals for a given date.

        Args:
            as_of_date: Reference date (str or date). No data after this
                        date is used.

        Returns:
            DataFrame[symbol, raw_score, rank] — top-N ranked stocks.
        """
        if isinstance(as_of_date, pl.DataFrame):
            # If a dataframe is passed (e.g. from pipeline), extract date
            as_of_date = str(as_of_date) if not isinstance(as_of_date, str) else as_of_date

        date_str = str(as_of_date)[:10]  # Normalize to YYYY-MM-DD

        # Filter scores to as_of_date (PIT — no future data)
        day_scores = self._scores.filter(pl.col("trade_date").cast(pl.Utf8) <= date_str)  # type: ignore[union-attr]

        if day_scores.is_empty():
            return pl.DataFrame(
                schema={"symbol": pl.Utf8, "raw_score": pl.Float64, "rank": pl.Int64}
            )

        # Get the most recent date's scores
        max_date = day_scores["trade_date"].max()
        day_scores = day_scores.filter(pl.col("trade_date") == max_date)

        # Sort by score descending, rank, take top N
        day_scores = day_scores.sort("score", descending=True)
        day_scores = day_scores.with_columns(
            pl.col("score").rank(descending=True).cast(pl.Int64).alias("rank")
        )
        day_scores = day_scores.filter(pl.col("rank") <= self._top_n)

        return day_scores.select(
            pl.col("symbol"),
            pl.col("score").alias("raw_score"),
            pl.col("rank"),
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def scores(self) -> pl.DataFrame:
        """Full cross-sectional score matrix [trade_date, symbol, score]."""
        return self._scores  # type: ignore[return-value]

    @property
    def top_n(self) -> int:
        return self._top_n

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)
