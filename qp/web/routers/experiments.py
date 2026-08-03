"""Experiments router — browse experiment results in WebUI.

GET /experiments          — List all experiments
GET /experiments/{id}     — Experiment detail
GET /experiments/compare  — Side-by-side comparison
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import polars as pl
from fastapi import APIRouter, Query, Request
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["experiments"])


@router.get("/experiments")
async def experiments_list(
    request: Request,
    status: str = Query(default=""),
    strategy: str = Query(default=""),
) -> Any:
    """List all experiments with optional filters."""
    experiments: list[dict[str, Any]] = []

    try:
        from qp.research.experiment.tracker import ExperimentTracker

        tracker = ExperimentTracker()
        all_exps = tracker.list_experiments()  # type: ignore[call-arg]

        for exp in all_exps:
            d: dict[str, Any] = exp.to_dict() if hasattr(exp, "to_dict") else {}  # type: ignore[assignment]
            if isinstance(d, dict) and d:
                if strategy and d.get("config", {}).get("strategy_name", "") != strategy:
                    continue
                experiments.append(d)
    except Exception as exc:
        logger.warning("Experiment list error: {}", exc)

    # Sort by experiment_id descending
    experiments.sort(key=lambda e: str(e.get("experiment_id", "")), reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="experiments.html",
        context={
            "experiments": experiments[:50],
            "has_experiments": len(experiments) > 0,
            "filter_status": status,
            "filter_strategy": strategy,
            "page_title": "Experiments — QP Decision Center",
        },
    )


@router.get("/experiments/{experiment_id}")
async def experiment_detail(request: Request, experiment_id: str) -> Any:
    """Show experiment detail."""
    exp: dict[str, Any] | None = None

    try:
        from qp.research.experiment.tracker import ExperimentTracker

        tracker = ExperimentTracker()
        record = tracker.get(experiment_id)
        if record is not None:
            exp = record.to_dict() if hasattr(record, "to_dict") else {}  # type: ignore[assignment]
            if not isinstance(exp, dict) or not exp:
                exp = None
    except Exception as exc:
        logger.warning("Experiment detail error: {}", exc)

    return templates.TemplateResponse(
        request=request,
        name="experiment_detail.html",
        context={
            "experiment_id": experiment_id,
            "experiment": exp,
            "found": exp is not None,
            "page_title": f"Experiment {experiment_id} — QP Decision Center",
        },
    )


def _reconstruct_trades(experiment_id: str) -> dict[str, Any]:
    """Reconstruct trade events from experiment price data and config.

    Uses the strategy's factor weights to compute scores, then simulates
    periodic rebalancing to determine which stocks were bought/sold each period.
    Results are cached as ``trade_events.json`` in the experiment directory.
    """
    exp_dir = Path("data/experiments") / experiment_id
    cache_path = exp_dir / "trade_events.json"

    # Return cached result if available
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception:
            pass

    # Load experiment config
    json_path = Path("data/experiments") / f"{experiment_id}.json"
    if not json_path.exists():
        return {"error": "Experiment JSON not found"}

    with open(json_path) as f:
        exp_data = json.load(f)

    cfg = exp_data.get("config", {})
    features = cfg.get("features", [])
    weights = cfg.get("model_params", {})
    top_n = int(cfg.get("tags", {}).get("top_n", 10)) if isinstance(cfg.get("tags"), dict) else 10
    rebalance_freq = int(cfg.get("tags", {}).get("rebalance_freq", 20)) if isinstance(cfg.get("tags"), dict) else 20

    # Try to extract top_n/rebalance from tags list
    tags = cfg.get("tags", [])
    if isinstance(tags, list):
        for t in tags:
            if t.startswith("top"):
                with contextlib.suppress(ValueError):
                    top_n = int(t.replace("top", ""))
            if t.startswith("rebalance") and t.endswith("d"):
                with contextlib.suppress(ValueError):
                    rebalance_freq = int(t.replace("rebalance", "").replace("d", ""))

    # Load price data
    price_path = exp_dir / "price_data.parquet"
    if not price_path.exists():
        return {"error": "Price data not found"}

    prices = pl.read_parquet(str(price_path))

    # Ensure required columns exist
    required_cols = {"trade_date", "symbol", "close"}
    missing = required_cols - set(prices.columns)
    if missing:
        return {"error": f"Missing columns in price data: {missing}"}

    # Get sorted unique dates and symbols
    dates = sorted(prices["trade_date"].unique().to_list())
    sorted(prices["symbol"].unique().to_list())

    if not features or not weights:
        # Cannot reconstruct detailed trades without feature data,
        # but we can still show basic rebalance schedule
        return {
            "rebalance_periods": [],
            "n_features": len(features),
            "note": "Feature score data not available — cannot reconstruct exact rankings",
        }

    # Pivot close prices to wide format (date × symbol)
    try:
        price_wide = prices.pivot(
            index="trade_date", columns="symbol", values="close"
        ).sort("trade_date")
    except Exception:
        return {"error": "Failed to pivot price data"}

    # Compute approximate scores using price-derived proxies for each feature
    price_cols = [c for c in price_wide.columns if c != "trade_date"]

    rebalance_periods = []
    rebalance_dates = [dates[i] for i in range(0, len(dates), rebalance_freq)]
    previous_holdings: set[str] = set()

    for _period_idx, rb_date in enumerate(rebalance_dates):
        if rb_date not in price_wide["trade_date"].to_list():
            continue

        row_idx = price_wide["trade_date"].to_list().index(rb_date)
        if row_idx < 20:  # Need at least 20 days of history for features
            continue

        # Compute feature scores using price data
        scores: dict[str, float] = {}
        window_start = max(0, row_idx - 60)

        for sym in price_cols[:300]:  # Limit to 300 symbols for performance
            col_data = price_wide[sym]
            if col_data[row_idx] is None:
                continue

            total_score = 0.0
            for feat_name, feat_weight in weights.items():
                try:
                    # Compute feature proxies from price data
                    feat_val = _compute_feature_proxy(
                        feat_name, col_data, row_idx, window_start
                    )
                    total_score += feat_val * feat_weight
                except Exception:
                    continue
            scores[sym] = total_score

        # Rank and select top-N
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        current_holdings = {s for s, _ in ranked[:top_n]}

        # Determine buys and sells
        buys = current_holdings - previous_holdings
        sells = previous_holdings - current_holdings

        # Get prices for the selected symbols
        buy_details = []
        for sym in sorted(buys):
            try:
                px = float(price_wide[sym][row_idx] or 0)
            except Exception:
                px = 0.0
            buy_details.append({
                "symbol": sym,
                "price": round(px, 2),
                "score": round(scores.get(sym, 0), 4),
                "rank": ranked.index((sym, scores[sym])) + 1 if sym in scores else 0,
            })

        sell_details = []
        for sym in sorted(sells):
            try:
                px = float(price_wide[sym][row_idx] or 0)
            except Exception:
                px = 0.0
            sell_details.append({
                "symbol": sym,
                "price": round(px, 2),
            })

        rebalance_periods.append({
            "date": str(rb_date),
            "n_buys": len(buys),
            "n_sells": len(sells),
            "n_hold": top_n - len(buys),
            "top_n": top_n,
            "buys": buy_details,
            "sells": sell_details,
        })

        previous_holdings = current_holdings

    result = {
        "rebalance_periods": rebalance_periods[-20:],  # Last 20 periods
        "total_periods": len(rebalance_periods),
        "n_features": len(features),
        "top_n": top_n,
        "rebalance_freq": rebalance_freq,
    }

    # Build timeline heatmap data (symbol × period matrix)
    all_symbols: list[str] = []
    symbol_periods: dict[str, dict[str, Any]] = {}
    for p in rebalance_periods:
        for b in p.get("buys", []):
            sym = b["symbol"]
            if sym not in all_symbols:
                all_symbols.append(sym)
            if sym not in symbol_periods:
                symbol_periods[sym] = {"count": 0, "first": p["date"], "last": p["date"]}
            symbol_periods[sym]["count"] += 1
            symbol_periods[sym]["last"] = p["date"]

    # Sort by appearance count (most held first)
    all_symbols.sort(key=lambda s: symbol_periods.get(s, {}).get("count", 0), reverse=True)

    # Build period-by-period status for each top symbol
    timeline_symbols = all_symbols[:30]
    timeline_periods = rebalance_periods[-12:]  # Last 12 periods
    timeline_rows: list[dict[str, Any]] = []
    for sym in timeline_symbols:
        cells: list[str] = []
        info = symbol_periods.get(sym, {})
        first_date = info.get("first", "")
        last_date = info.get("last", "")
        for p in timeline_periods:
            p_date = p["date"]
            is_buy = any(b["symbol"] == sym for b in p.get("buys", []))
            is_sell = any(s["symbol"] == sym for s in p.get("sells", []))
            is_held = first_date <= p_date <= last_date and not is_sell
            if is_buy:
                cells.append("buy")
            elif is_sell:
                cells.append("sell")
            elif is_held:
                cells.append("hold")
            else:
                cells.append("none")
        timeline_rows.append({
            "symbol": sym,
            "count": symbol_periods.get(sym, {}).get("count", 0),
            "cells": cells,
        })

    # Compute turnover stats
    total_buys = sum(p.get("n_buys", 0) for p in rebalance_periods)
    total_sells = sum(p.get("n_sells", 0) for p in rebalance_periods)
    avg_hold = sum(v["count"] for v in symbol_periods.values()) / max(len(symbol_periods), 1)

    result.update({
        "timeline_symbols": timeline_rows,
        "timeline_dates": [p["date"][-5:] for p in timeline_periods],
        "total_buys": total_buys,
        "total_sells": total_sells,
        "n_symbols_traded": len(all_symbols),
        "avg_hold_periods": round(avg_hold, 1),
        "equity_curve": _compute_equity_curve(rebalance_periods, price_wide, top_n),
    })

    # Cache result
    exp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, default=str)
    except Exception:
        pass

    return result


def _compute_feature_proxy(
    feat_name: str, col_data: Any, row_idx: int, window_start: int
) -> float:
    """Compute a price-derived proxy for a feature."""
    name_lower = feat_name.lower()

    if row_idx < 1 or row_idx >= len(col_data):
        return 0.0

    current = float(col_data[row_idx] or 0.0)
    if current <= 0:
        return 0.0

    if "amplitude" in name_lower and "5" in name_lower:
        prev_5 = float(col_data[max(0, row_idx - 5)] or current)
        return (current - prev_5) / prev_5

    if "volatility" in name_lower or "vol" in name_lower:
        returns = []
        for j in range(max(window_start, row_idx - 20), row_idx):
            p = float(col_data[j] or 0)
            p_prev = float(col_data[j - 1] or p) if j > window_start else p
            if p_prev > 0:
                returns.append((p - p_prev) / p_prev)
        if returns:
            import statistics
            return statistics.stdev(returns) if len(returns) > 1 else 0.0
        return 0.0

    if "momentum" in name_lower:
        if "3m" in name_lower or "60" in name_lower:
            lookback = min(60, row_idx)
        elif "1m" in name_lower or "20" in name_lower:
            lookback = min(20, row_idx)
        else:
            lookback = min(20, row_idx)
        prev = float(col_data[max(0, row_idx - lookback)] or current)
        return (current - prev) / prev if prev > 0 else 0.0

    if "volume" in name_lower and "concentration" in name_lower:
        return -0.5  # Placeholder for volume concentration

    if "volume" in name_lower and "trend" in name_lower:
        return 0.02  # Placeholder for volume trend

    return 0.0


def _compute_equity_curve(
    rebalance_periods: list[dict[str, Any]],
    price_wide: pl.DataFrame,
    top_n: int,
) -> list[dict[str, Any]]:
    """Compute portfolio equity at each rebalance date.

    Uses equal-weight allocation across Top-N holdings. Returns a list of
    {{date, equity, benchmark}} dicts for Chart.js rendering.
    """
    import statistics

    if not rebalance_periods:
        return []

    # Get all symbols from price data for benchmark
    price_cols = [c for c in price_wide.columns if c != "trade_date"]

    # Build date lookup (date objects → index)
    date_list = price_wide["trade_date"].to_list()
    date_to_idx: dict[str, int] = {}
    for i, d in enumerate(date_list):
        date_to_idx[str(d)] = i

    points: list[dict[str, Any]] = []
    holdings: dict[str, float] = {}  # symbol -> shares
    initial_capital = 1_000_000.0
    base_avg_price: float | None = None

    for period in rebalance_periods:
        date_str = period["date"]
        if date_str not in date_to_idx:
            continue

        row_idx = date_to_idx[date_str]

        # Sell: remove from holdings, record proceeds
        for s in period.get("sells", []):
            sym = s["symbol"]
            holdings.pop(sym, None)

        # Buy: allocate equal weight to new positions
        buys = period.get("buys", [])
        if buys:
            weight_per_stock = 1.0 / top_n
            for b in buys:
                sym = b["symbol"]
                px = b["price"]
                if px > 0 and sym in price_cols:
                    holdings[sym] = (initial_capital * weight_per_stock) / px

        # Mark to market
        total_value = 0.0
        for sym, shares in holdings.items():
            try:
                px = float(price_wide[sym][row_idx] or 0)
            except Exception:
                px = 0.0
            total_value += shares * px

        # Benchmark: average price of all stocks, normalized to start at ¥1M
        bench_value = 0.0
        valid_prices = []
        for c in price_cols:
            try:
                v = float(price_wide[c][row_idx] or 0)
                if v > 0:
                    valid_prices.append(v)
            except Exception:
                continue
        if valid_prices:
            if base_avg_price is None:
                base_avg_price = statistics.mean(valid_prices)
                bench_value = float(initial_capital)
            elif base_avg_price > 0:
                bench_value = statistics.mean(valid_prices) / base_avg_price * initial_capital

        points.append({
            "date": date_str,
            "equity": round(total_value, 0),
            "benchmark": round(bench_value, 0) if not points else round(
                bench_value, 0
            ),
        })

    # Normalize: start both at initial_capital
    if points:
        first_equity = points[0]["equity"]
        if first_equity > 0:
            scale = initial_capital / first_equity
            for p in points:
                p["equity"] = round(p["equity"] * scale, 0)

    return points


@router.get("/experiments/{experiment_id}/trades")
async def experiment_trades(request: Request, experiment_id: str) -> Any:
    """Show trade details (buy/sell per rebalance) for an experiment."""
    trades = _reconstruct_trades(experiment_id)

    equity_json = json.dumps(trades.get("equity_curve", []))

    return templates.TemplateResponse(
        request=request,
        name="experiment_trades.html",
        context={
            "experiment_id": experiment_id,
            "trades": trades,
            "equity_json": equity_json,
            "has_trades": len(trades.get("rebalance_periods", [])) > 0,
            "page_title": f"Trade Details — {experiment_id}",
        },
    )
