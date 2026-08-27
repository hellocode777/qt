"""ExperimentService — read-only access to experiment tracking data.

Bridges the QP Research layer (Layer 3) to the Web layer.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from qp.research.experiment.tracker import ExperimentTracker
from qp.shared.json_io import json_load, json_save
from qp.shared.paths import EXPERIMENTS_DIR


class ExperimentService:
    """Read-only service for experiment data.

    Usage:
        svc = ExperimentService()
        recent = svc.list_recent(limit=20)
        detail = svc.get_by_id("multifactor_20260726_124909")
        curve = svc.get_equity_curve("multifactor_20260726_124909")
        trades = svc.get_trade_reconstruction("multifactor_20260726_124909")
    """

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    _experiments_root = Path(EXPERIMENTS_DIR)

    def __init__(self) -> None:
        self._tracker = ExperimentTracker()

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent experiments with key metrics."""
        self._tracker._load_index()  # refresh from disk (new experiments since startup)
        try:
            records = self._tracker.list_experiments()
        except Exception as e:
            logger.warning("Failed to list experiments: {}", e)
            return []

        results = []
        for record in records[:limit]:
            results.append(self._record_to_dict(record))
        return results

    def get_by_id(self, experiment_id: str) -> dict[str, Any] | None:
        """Get a specific experiment by ID."""
        try:
            record = self._tracker.get(experiment_id)
            if record is None:
                return None
            return self._record_to_dict(record)
        except Exception as e:
            logger.warning("Failed to get experiment {}: {}", experiment_id, e)
            return None

    # ------------------------------------------------------------------
    # Equity curve (from daily_nav.parquet saved by pipeline)
    # ------------------------------------------------------------------

    def get_equity_curve(self, experiment_id: str) -> dict[str, Any]:
        """Read daily NAV curve for an experiment.

        Returns a dict suitable for JSON serialization:
            {"dates": [...], "portfolio": [...], "benchmark": [...],
             "drawdown": [...], "daily_return": [...], "has_data": bool}
        """
        nav_path = self._experiments_root / experiment_id / "daily_nav.parquet"
        if not nav_path.exists():
            return {"has_data": False}

        try:
            nav_df = pl.read_parquet(str(nav_path))
            if nav_df.is_empty():
                return {"has_data": False}

            cols = nav_df.columns
            eq_col = "portfolio_value" if "portfolio_value" in cols else "equity"
            bench_col = "benchmark_value" if "benchmark_value" in cols else None
            dd_col = "drawdown" if "drawdown" in cols else None
            ret_col = "daily_return" if "daily_return" in cols else None

            nav_records = nav_df.sort("date").to_dicts()
            dates = [str(r["date"])[:10] for r in nav_records]
            portfolio = [r[eq_col] for r in nav_records]
            benchmark = [r[bench_col] for r in nav_records] if bench_col else None
            drawdown = [r[dd_col] for r in nav_records] if dd_col else None
            daily_return = [r[ret_col] for r in nav_records] if ret_col else None

            return {
                "has_data": True,
                "dates": dates,
                "portfolio": portfolio,
                "benchmark": benchmark,
                "drawdown": drawdown,
                "daily_return": daily_return,
            }
        except Exception as exc:
            logger.warning("Failed to load daily_nav {}: {}", nav_path, exc)
            return {"has_data": False}

    def get_equity_json(self, experiment_id: str) -> tuple[str, bool]:
        """Return (json_string, has_real_nav) for template injection.

        Uses same point format as before for backward compat with templates.
        """
        curve = self.get_equity_curve(experiment_id)
        if not curve["has_data"]:
            return "", False

        records = []
        dates = curve["dates"]
        portfolio = curve["portfolio"]
        benchmark = curve.get("benchmark")
        drawdown = curve.get("drawdown")
        daily_return = curve.get("daily_return")

        for i, date in enumerate(dates):
            rec: dict[str, Any] = {"date": date, "equity": portfolio[i]}
            if benchmark and i < len(benchmark) and benchmark[i] is not None:
                rec["benchmark"] = benchmark[i]
            if drawdown and i < len(drawdown) and drawdown[i] is not None:
                rec["drawdown"] = drawdown[i]
            if daily_return and i < len(daily_return) and daily_return[i] is not None:
                rec["daily_return"] = daily_return[i]
            records.append(rec)

        return json.dumps(records), True

    # ------------------------------------------------------------------
    # Trade reconstruction (from price_data.parquet + config)
    # ------------------------------------------------------------------

    def get_trade_reconstruction(self, experiment_id: str) -> dict[str, Any]:
        """Reconstruct trade events from experiment price data and config.

        Uses the strategy's factor weights to compute scores, then simulates
        periodic rebalancing to determine which stocks were bought/sold each period.
        Results are cached as ``trade_events.json`` in the experiment directory.
        """
        exp_dir = self._experiments_root / experiment_id
        cache_path = exp_dir / "trade_events.json"

        # Return cached result if available
        if cache_path.exists():
            try:
                return json_load(cache_path)
            except Exception:
                pass

        # Load experiment config
        json_path = self._experiments_root / f"{experiment_id}.json"
        if not json_path.exists():
            return {"error": "Experiment JSON not found"}

        exp_data = json_load(json_path)

        cfg = exp_data.get("config", {})
        features = cfg.get("features", [])
        weights = cfg.get("model_params", {})
        top_n = (
            int(cfg.get("tags", {}).get("top_n", 10)) if isinstance(cfg.get("tags"), dict) else 10
        )
        rebalance_freq = (
            int(cfg.get("tags", {}).get("rebalance_freq", 20))
            if isinstance(cfg.get("tags"), dict)
            else 20
        )

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

        # Get sorted unique dates
        dates = sorted(prices["trade_date"].unique().to_list())

        if not features or not weights:
            return {
                "rebalance_periods": [],
                "n_features": len(features),
                "note": "Feature score data not available — cannot reconstruct exact rankings",
            }

        # Pivot close prices to wide format (date × symbol)
        try:
            price_wide = prices.pivot(index="trade_date", on="symbol", values="close").sort(
                "trade_date"
            )
        except Exception:
            return {"error": "Failed to pivot price data"}

        rebalance_periods = self._build_rebalance_periods(
            price_wide, dates, features, weights, top_n, rebalance_freq
        )

        result: dict[str, Any] = {
            "rebalance_periods": rebalance_periods[-20:],
            "total_periods": len(rebalance_periods),
            "n_features": len(features),
            "top_n": top_n,
            "rebalance_freq": rebalance_freq,
        }

        # Build timeline heatmap data
        self._enrich_with_timeline(result, rebalance_periods)

        # Cache result
        exp_dir.mkdir(parents=True, exist_ok=True)
        try:
            json_save(cache_path, result)
        except Exception:
            pass

        return result

    def _build_rebalance_periods(
        self,
        price_wide: pl.DataFrame,
        dates: list[Any],
        features: list[str],
        weights: dict[str, float],
        top_n: int,
        rebalance_freq: int,
    ) -> list[dict[str, Any]]:
        """Build rebalance period data from price pivot and factor weights."""
        price_cols = [c for c in price_wide.columns if c != "trade_date"]
        periods: list[dict[str, Any]] = []
        rebalance_dates = [dates[i] for i in range(0, len(dates), rebalance_freq)]
        previous_holdings: set[str] = set()

        for rb_date in rebalance_dates:
            if rb_date not in price_wide["trade_date"].to_list():
                continue

            row_idx = price_wide["trade_date"].to_list().index(rb_date)
            if row_idx < 20:
                continue

            scores: dict[str, float] = {}
            window_start = max(0, row_idx - 60)

            for sym in price_cols[:300]:
                col_data = price_wide[sym]
                if col_data[row_idx] is None:
                    continue

                total_score = 0.0
                for feat_name, feat_weight in weights.items():
                    try:
                        feat_val = self._compute_feature_proxy(
                            feat_name, col_data, row_idx, window_start
                        )
                        total_score += feat_val * feat_weight
                    except Exception:
                        continue
                scores[sym] = total_score

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            current_holdings = {s for s, _ in ranked[:top_n]}

            buys = current_holdings - previous_holdings
            sells = previous_holdings - current_holdings

            buy_details = []
            for sym in sorted(buys):
                try:
                    px = float(price_wide[sym][row_idx] or 0)
                except Exception:
                    px = 0.0
                rank = [s for s, _ in ranked].index(sym) + 1 if sym in {s for s, _ in ranked} else 0
                buy_details.append(
                    {
                        "symbol": sym,
                        "price": round(px, 2),
                        "score": round(scores.get(sym, 0), 4),
                        "rank": rank,
                    }
                )

            sell_details = []
            for sym in sorted(sells):
                try:
                    px = float(price_wide[sym][row_idx] or 0)
                except Exception:
                    px = 0.0
                sell_details.append({"symbol": sym, "price": round(px, 2)})

            periods.append(
                {
                    "date": str(rb_date),
                    "n_buys": len(buys),
                    "n_sells": len(sells),
                    "n_hold": top_n - len(buys),
                    "top_n": top_n,
                    "buys": buy_details,
                    "sells": sell_details,
                }
            )
            previous_holdings = current_holdings

        return periods

    @staticmethod
    def _enrich_with_timeline(result: dict[str, Any], periods: list[dict[str, Any]]) -> None:
        """Add timeline heatmap and turnover stats to result dict (mutates)."""
        all_symbols: list[str] = []
        symbol_periods: dict[str, dict[str, Any]] = {}
        for p in periods:
            for b in p.get("buys", []):
                sym = b["symbol"]
                if sym not in all_symbols:
                    all_symbols.append(sym)
                if sym not in symbol_periods:
                    symbol_periods[sym] = {
                        "count": 0,
                        "first": p["date"],
                        "last": p["date"],
                    }
                symbol_periods[sym]["count"] += 1
                symbol_periods[sym]["last"] = p["date"]

        all_symbols.sort(key=lambda s: symbol_periods.get(s, {}).get("count", 0), reverse=True)

        timeline_symbols = all_symbols[:30]
        timeline_periods = periods[-12:]
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
            timeline_rows.append(
                {
                    "symbol": sym,
                    "count": symbol_periods.get(sym, {}).get("count", 0),
                    "cells": cells,
                }
            )

        total_buys = sum(p.get("n_buys", 0) for p in periods)
        total_sells = sum(p.get("n_sells", 0) for p in periods)
        avg_hold = sum(v["count"] for v in symbol_periods.values()) / max(len(symbol_periods), 1)

        result.update(
            {
                "timeline_symbols": timeline_rows,
                "timeline_dates": [p["date"][-5:] for p in timeline_periods],
                "total_buys": total_buys,
                "total_sells": total_sells,
                "n_symbols_traded": len(all_symbols),
                "avg_hold_periods": round(avg_hold, 1),
            }
        )

    @staticmethod
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
            return -0.5

        if "volume" in name_lower and "trend" in name_lower:
            return 0.02

        return 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_to_dict(record: Any) -> dict[str, Any]:
        """Convert ExperimentRecord to template-friendly nested dict."""
        cfg = record.config
        met = record.metrics
        lin = record.lineage

        return {
            "experiment_id": cfg.experiment_id,
            "description": cfg.description,
            "status": record.status.value
            if hasattr(record.status, "value")
            else str(record.status),
            "created_at": str(cfg.created_at)[:19] if cfg.created_at else "",
            "completed_at": str(record.completed_at)[:19] if record.completed_at else "",
            # Nested config block (matches experiment_detail.html)
            "config": {
                "strategy_name": cfg.strategy_name,
                "model_mode": cfg.model_mode,
                "features": cfg.features,
                "model_params": cfg.model_params,
                "dataset_version": cfg.dataset_version,
                "train_start": cfg.train_start,
                "train_end": cfg.train_end,
                "tags": cfg.tags,
            },
            # Nested metrics block (matches experiment_detail.html)
            "metrics": {
                "ic_mean": met.ic_mean,
                "ic_ir": met.ic_ir,
                "ic_t_stat": met.ic_t_stat,
                "sharpe_ratio": met.sharpe_ratio,
                "max_drawdown_pct": met.max_drawdown_pct,
                "excess_return_pct": met.excess_return_pct,
                "annual_return_pct": met.annual_return_pct,
                "annual_volatility_pct": met.annual_volatility_pct,
                "total_return_pct": met.total_return_pct,
                "turnover_pct": met.turnover_pct,
                "n_days": met.n_days,
            },
            # Nested lineage block
            "lineage": {
                "model_algo": lin.model_algo,
                "strategy_id": lin.strategy_id,
                "dataset": f"{lin.dataset_name}@{lin.dataset_version}" if lin.dataset_name else "",
            },
        }
