"""MultiFactorPipeline — multi-factor strategy experiment as a BasePipeline.

End-to-end experiment conforming to ADR-006 ("Everything is a Pipeline"):

  Raw Ingestion              TencentAdapter.fetch_raw()
       │
  Cleaning (4-stage ETL)     ETLPipeline: anomaly→volume→suspension→adjustment
       │
  Repair                     OHLC boundaries, amount validation, missing dates
       │
  Validation                 DailyPriceContract schema check
       │
  PIT & Universe             Suspension + delisted filtering
       │
  Feature Compute            15 price/volume factors (momentum, vol, volume, money flow)
       │
  Cross-sectional Scoring    Winsorize → Normalize → Combine → Rank
       │
  IC Analysis                Spearman Rank IC, ICIR, IC>0 ratio
       │
  Signal Generation          Top-N monthly rebalance with sell buffer
       │
  Backtest + Benchmark       Equal-weight backtest vs buy-and-hold

Usage via CLI:
    qp experiment run multifactor \\
        --symbols 000001,000002,... \\
        --start 2024-01-01 --end 2026-07-20 \\
        --top-n 10 --rebalance 20 \\
        --industry-neutral --orthogonalize
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import polars as pl
from loguru import logger

from qp.data.dataset.registry import DatasetRegistry
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.research.evaluation.layered_test import compute_layered_returns
from qp.research.evaluation.rank_ic import evaluate_factor_ic
from qp.research.factor_processor import factor_pipeline
from qp.research.feature.compute import (
    ALL_FACTOR_DIRECTIONS,
    PRICE_VOLUME_FACTORS,
    compute_all_factors,
)
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus
from qp.strategy.multifactor import generate_rebalance_signals

# Default stock pool: liquid large-cap + representative sectors
DEFAULT_SYMBOLS = [
    "000001",
    "000002",
    "000333",
    "000651",
    "000858",
    "002415",
    "002475",
    "300750",
    "600000",
    "600036",
    "600276",
    "600519",
    "600585",
    "600887",
    "601012",
    "601166",
    "601318",
    "601888",
]


class MultiFactorPipeline(BasePipeline):
    """Run a multi-factor strategy experiment on real A-share data.

    Pipeline stages:
      1. Fetch OHLCV data via TencentAdapter
      2. Compute cross-sectional factor scores
      3. Rank IC analysis (Spearman, forward 5-day)
      4. Generate rebalance signals (monthly, Top-N)
      5. Simple backtest (equal-weight, signal-day rebalance)
      6. Benchmark comparison (equal-weight buy-and-hold)

    Results are logged via Loguru and returned in PipelineResult.metrics.
    """

    @property
    def name(self) -> str:
        return "multifactor_experiment"

    # ------------------------------------------------------------------
    # Pipeline entry point
    # ------------------------------------------------------------------

    def run(self, context: PipelineContext) -> PipelineResult:
        params = context.parameters

        symbols: list[str] = params.get("symbols", [])  # empty = all stocks in dataset
        start_date_str: str = params.get("start_date", "2024-01-01")
        end_date_str: str = params.get("end_date", date.today().isoformat())
        top_n: int = int(params.get("top_n", 10))
        rebalance_freq: int = int(params.get("rebalance_freq", 20))
        sell_buffer: int = int(params.get("sell_buffer_rank", 5))
        industry_neutral: bool = params.get("industry_neutral", False)
        orthogonalize: bool = params.get("orthogonalize", False)
        dataset: str = params.get("dataset", "daily_price_main")

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        logger.info("=" * 70)
        logger.info("多因子策略实验 — A股真实数据")
        logger.info("=" * 70)
        n = len(symbols) if symbols else "全部"
        logger.info(
            "股票池: {} 只 | 区间: {} → {} | Top-{} 每月调仓",
            n,
            start_date_str,
            end_date_str,
            top_n,
        )
        if industry_neutral:
            logger.info("行业中性化: ✅ | 因子正交化: {}", "✅" if orthogonalize else "❌")

        # ── Stage 1: Fetch data ──
        logger.info("[1/6] 获取行情数据...")
        try:
            price_data = self._fetch_data(symbols, start_date_str, end_date_str, dataset)
        except Exception as e:
            logger.error("数据获取失败: {}", e)
            result.status = PipelineStatus.FAILED
            result.errors.append(f"数据获取失败: {e}")
            return result

        total_rows = sum(df.height for df in price_data.values())
        logger.info("   {} 只股票, {} 行日线数据", len(price_data), total_rows)
        result.metrics["n_stocks"] = float(len(price_data))
        result.metrics["n_rows"] = float(total_rows)

        # ── Stage 2: Factor computation → raw factor values ──
        logger.info("[2/6] 计算原始因子值...")
        n_factors = len(PRICE_VOLUME_FACTORS)
        weights = {
            f: ALL_FACTOR_DIRECTIONS.get(f, 1) / n_factors
            for f in PRICE_VOLUME_FACTORS
        }
        n_pos = sum(1 for v in weights.values() if v > 0)
        n_neg = sum(1 for v in weights.values() if v < 0)
        logger.info(
            "   因子: {} 个 ({} IC+, {} IC-) / 方向校准",
            n_factors, n_pos, n_neg,
        )

        # Compute raw factors for all stocks
        all_raw: dict[str, dict[str, dict[str, float]]] = {}
        for code, df in price_data.items():
            factors = compute_all_factors(df.sort("trade_date"))
            if factors.is_empty():
                continue
            for row in factors.iter_rows(named=True):
                date_str = str(row["trade_date"])
                if date_str not in all_raw:
                    all_raw[date_str] = {}
                all_raw[date_str][code] = {
                    f: float(row[f]) for f in PRICE_VOLUME_FACTORS if f in row
                }
        logger.info("   原始因子: {} 天截面", len(all_raw))

        # ── Stage 2.5: Factor pipeline (winsorize → normalize → neutralize → combine) ──
        logger.info("[2.5/6] 因子管线处理 (Winsorize→Normalize→Neutralize→Combine)...")
        neutralize_method = "median" if industry_neutral else None
        scores = factor_pipeline(
            all_raw,
            weights=weights,
            normalize_method="rank",
            winsorize_method="mad",
            industry_map=_build_industry_map(price_data) if industry_neutral else None,
            neutralize_method=neutralize_method,
            orthogonalize=orthogonalize,
        )
        logger.info("   得分矩阵: {} 行", scores.height)
        result.metrics["score_rows"] = float(scores.height)

        # ── Stage 3: IC analysis (using evaluation module) ──
        logger.info("[3/6] Rank IC 分析...")
        if scores.is_empty():
            logger.warning("   无数据，跳过 IC 分析")
            result.status = PipelineStatus.FAILED
            result.errors.append("No score data — check dataset")
            return result

        # Use evaluation module for full IC analysis with threshold checks
        price_flat = _flatten_price_data(price_data)
        ic_record = evaluate_factor_ic(
            scores,
            price_flat,
            forward_days=5,
            min_stocks_per_day=10,
        )
        logger.info("   {}", ic_record.summary())
        result.metrics["ic_mean"] = ic_record.ic_mean
        result.metrics["ic_ir"] = ic_record.ic_ir
        result.metrics["ic_t_stat"] = ic_record.ic_t_stat
        result.metrics["ic_positive_pct"] = ic_record.ic_positive_pct
        result.metrics["ic_mean_pass"] = float(ic_record.ic_mean_pass)
        result.metrics["ic_ir_pass"] = float(ic_record.ic_ir_pass)

        # Layered test for monotonicity validation
        layered = compute_layered_returns(
            scores,
            price_flat,
            n_quantiles=5,
            forward_days=5,
            min_stocks_per_day=50,
        )
        logger.info("   {}", layered.summary())
        result.metrics["top_bottom_spread"] = layered.top_bottom_spread
        result.metrics["spread_t_stat"] = layered.spread_t_stat
        result.metrics["monotonicity_t_stat"] = layered.monotonicity_t_stat
        result.metrics["is_monotonic"] = float(layered.is_monotonic)

        # ── IC Gate (Rule 8/11: IC Before Backtest) ──
        if not ic_record.all_pass:
            logger.warning("   ⛔ IC 检验未通过 — 根据 §10.1 阈值停止回测")
            logger.warning(
                "      IC mean: {:.4f} (需要 ≥0.02) — {}",
                ic_record.ic_mean,
                "✅" if ic_record.ic_mean_pass else "❌",
            )
            logger.warning(
                "      IC_IR: {:.2f} (需要 ≥0.3) — {}",
                ic_record.ic_ir,
                "✅" if ic_record.ic_ir_pass else "❌",
            )
            logger.warning(
                "      IC t-stat: {:.2f} (需要 ≥2.0) — {}",
                ic_record.ic_t_stat,
                "✅" if ic_record.ic_t_stat_pass else "❌",
            )
            result.status = PipelineStatus.FAILED
            result.errors.append(
                "IC gate failed — strategy does not meet minimum thresholds (§10.1). "
                "Fix factors before retrying."
            )
            return result

        # ── Stage 4: Signal generation ──
        logger.info("[4/6] 生成调仓信号...")
        # Filter out stocks with no score (insufficient history)
        n_before = scores.height  # type: ignore[union-attr]
        scores = scores.filter(pl.col("score") != 0.0)  # type: ignore[union-attr]
        n_zero = n_before - scores.height  # type: ignore[union-attr]
        if n_zero > 0:
            logger.info("   过滤 score=0: {} 行 (数据不足)", n_zero)
        signals = generate_rebalance_signals(
            scores,  # type: ignore[arg-type]
            top_n=top_n,
            rebalance_freq=rebalance_freq,
            sell_buffer_rank=sell_buffer,
        )
        if not signals.is_empty():
            buys_n = signals.filter(pl.col("signal") == "buy").height
            sells_n = signals.filter(pl.col("signal") == "sell").height
            rebalance_days = signals["date"].n_unique()
            logger.info(
                "   买入信号: {} 条 | 卖出信号: {} 条 | 调仓日: {} 天",
                buys_n,
                sells_n,
                rebalance_days,
            )
            result.metrics["buy_signals"] = float(buys_n)
            result.metrics["sell_signals"] = float(sells_n)

            # Latest rebalance
            latest_date = signals["date"].max()
            latest = signals.filter(pl.col("date") == latest_date).sort("signal", descending=True)
            for row in latest.iter_rows(named=True):
                emoji = "🟢" if row["signal"] == "buy" else "🔴"
                logger.info(
                    "     {} {:4s}  {:8s}  score={:.4f}",
                    emoji,
                    row["signal"],
                    row["symbol"],
                    row["score"],
                )
        else:
            logger.warning("   无信号生成")
            result.metrics["buy_signals"] = 0.0
            result.metrics["sell_signals"] = 0.0

        # ── Stage 5: Backtest (Layer 7 SimulatedBroker) ──
        logger.info("[5/6] 回测 (SimulatedBroker, 信号日调仓)...")
        bt = self._compute_backtest(signals, price_data)
        logger.info("   总收益:    {:+.2f}%", bt["total_return_pct"])
        logger.info("   年化夏普:  {:.2f}", bt["sharpe"])
        logger.info("   最大回撤:  {:.2f}%", bt["max_dd_pct"])
        logger.info("   期末资产:  ¥{:,.0f}", bt["final_equity"])
        logger.info("   交易次数:  {}", bt["n_trades"])
        logger.info("   总成本:    ¥{:,.0f} (佣金+印花税+滑点)", bt["total_cost"])
        result.metrics["total_return_pct"] = bt["total_return_pct"]
        result.metrics["sharpe"] = bt["sharpe"]
        result.metrics["max_dd_pct"] = bt["max_dd_pct"]
        result.metrics["final_equity"] = bt["final_equity"]
        result.metrics["n_trades"] = float(bt["n_trades"])
        result.metrics["total_cost"] = bt["total_cost"]

        # ── Stage 6: Benchmark ──
        logger.info("[6/6] 基准对比 (等权持有)...")
        bench_ret = self._benchmark_return(price_data, symbols, start_date_str, end_date_str)
        logger.info("   等权买入持有: {:+.2f}%", bench_ret)
        result.metrics["benchmark_return_pct"] = bench_ret

        excess = bt["total_return_pct"] - bench_ret
        logger.info("   超额收益:    {:+.2f}%", excess)
        result.metrics["excess_return_pct"] = excess

        logger.info("=" * 70)
        status_text = "策略跑赢基准 ✅" if excess > 0 else "策略跑输基准 ❌"
        logger.info("实验完成 — {} (超额: {:+.2f}%)", status_text, excess)
        logger.info("=" * 70)

        # ── Auto-record experiment (Rule 6: Everything is Experiment) ──
        self._record_experiment(
            result=result,
            start_date=start_date_str,
            end_date=end_date_str,
            dataset=dataset,
            features=list(PRICE_VOLUME_FACTORS),
            weights=weights,
            top_n=top_n,
            rebalance_freq=rebalance_freq,
            industry_neutral=industry_neutral,
            orthogonalize=orthogonalize,
        )

        return result

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_data(
        symbols: list[str],
        start: str,
        end: str,
        dataset: str = "daily_price_main",
    ) -> dict[str, pl.DataFrame]:
        """Load from Gold dataset (CLAUDE.md: consumers read from Registry or parquet).

        The Gold tier is already ETL-cleaned, Contract-validated, and
        Universe-filtered. No additional processing needed.
        """
        from pathlib import Path

        # Resolve Gold path: try DatasetRegistry first, fallback to direct parquet
        gold_path = ""
        try:
            registry = DatasetRegistry(base_dir="data/dataset")
            entry = registry.resolve(dataset)
            gold_path = entry["path"]
            logger.info("    📂 Gold (Registry): {} (v{})", dataset, entry["version"])
        except KeyError:
            # Fallback: read directly from data/dataset/
            candidate = Path(f"data/dataset/{dataset}_2026-07-21.parquet")
            if candidate.exists():
                gold_path = str(candidate)
                logger.info("    📂 Gold (direct): {}", candidate.name)
            else:
                logger.error("Gold 数据集未找到。请先运行 qp data fetch")
                return {}

        df_all = pl.read_parquet(gold_path)

        # Filter date range
        df_all = df_all.filter(
            (pl.col("trade_date").cast(pl.Utf8) >= start)
            & (pl.col("trade_date").cast(pl.Utf8) <= end)
        )

        # Filter symbols if specified
        if symbols:
            symbol_set = set(symbols)
            df_all = df_all.filter(pl.col("symbol").is_in(symbol_set))

        if df_all.is_empty():
            logger.warning("    数据为空")
            return {}

        # Organize by symbol
        dfs: dict[str, pl.DataFrame] = {}
        for (code,), group in df_all.group_by("symbol"):
            dfs[str(code)] = group.sort("trade_date")

        logger.info("    ✅ {} 只, {} 行 (已清洗/校验/过滤)", len(dfs), df_all.height)
        return dfs

    @staticmethod
    def _compute_backtest(
        signals: pl.DataFrame,
        price_data: dict[str, pl.DataFrame],
        initial_capital: float = 1_000_000,
    ) -> dict[str, Any]:
        """Broker-based backtest via Layer 7 SimulatedBroker.

        On each trading day: mark positions to market via broker.set_prices().
        On signal days: liquidate all → buy new top-N → execute via broker.

        Uses SimulatedBroker for realistic execution with slippage and cost
        tracking, replacing the previous hand-rolled dict loop (ADR-029).
        """
        from qp.simulation.broker import SimulatedBroker

        if signals.is_empty():
            return {
                "total_return_pct": 0.0,
                "sharpe": 0.0,
                "max_dd_pct": 0.0,
                "final_equity": initial_capital,
                "n_trading_days": 0,
                "n_trades": 0,
                "total_cost": 0.0,
            }

        broker = SimulatedBroker(initial_cash=initial_capital)

        # Build flat price DataFrame with volume for ADV
        all_prices = _flatten_price_data_for_backtest(price_data)
        if all_prices.is_empty():
            return {
                "total_return_pct": 0.0,
                "sharpe": 0.0,
                "max_dd_pct": 0.0,
                "final_equity": initial_capital,
                "n_trading_days": 0,
                "n_trades": 0,
                "total_cost": 0.0,
            }

        all_dates = sorted(all_prices["trade_date"].unique().to_list())
        daily_equity: list[float] = []
        total_trades = 0

        for d in all_dates:
            d_str = str(d)

            # Build price & ADV maps for this trading day
            day_prices = all_prices.filter(pl.col("trade_date") == d)
            price_map: dict[str, float] = {}
            adv_map: dict[str, float] = {}
            for row in day_prices.iter_rows(named=True):
                sym = str(row["symbol"])
                px = float(row["close"])
                vol = float(row.get("volume", 0.0) or 0.0)
                price_map[sym] = px
                if vol > 0 and px > 0:
                    adv_map[sym] = px * vol

            broker.set_prices(price_map, adv_map, d_str)

            # Check for rebalance signals on this date
            day_signals = signals.filter(pl.col("date") == d_str)
            if not day_signals.is_empty():
                # Liquidate all current positions
                positions_df = broker.get_positions()
                if not positions_df.empty:
                    for _, row in positions_df.iterrows():
                        shares = int(float(row["shares"]))  # type: ignore[arg-type]
                        if shares > 0:
                            broker.submit_order(
                                {
                                    "symbol": str(row["symbol"]),
                                    "side": "SELL",
                                    "quantity": shares,
                                    "order_type": "market",
                                }
                            )

                # Buy new top-N positions (equal weight)
                buys = day_signals.filter(pl.col("signal") == "buy")
                buy_symbols = buys["symbol"].to_list()
                if buy_symbols:
                    current_equity = broker.get_equity()
                    n_positions = len(buy_symbols)
                    per_stock = current_equity / n_positions

                    for sym in buy_symbols:
                        px = price_map.get(sym, 0.0)
                        if px > 0:
                            qty = int(per_stock / px // 100 * 100)
                            if qty > 0:
                                broker.submit_order(
                                    {
                                        "symbol": sym,
                                        "side": "BUY",
                                        "quantity": qty,
                                        "order_type": "market",
                                    }
                                )

            # Execute pending orders (fills, cost deduction, position updates)
            executed = broker.execute_pending()
            total_trades += len(executed)

            daily_equity.append(broker.get_equity())

        final_equity = daily_equity[-1] if daily_equity else initial_capital
        total_ret = (final_equity / initial_capital - 1) * 100

        # Daily returns from equity curve
        daily_rets = [
            daily_equity[i] / daily_equity[i - 1] - 1
            for i in range(1, len(daily_equity))
            if daily_equity[i - 1] > 0
        ]
        if daily_rets:
            rets = np.array(daily_rets)
            sharpe = float(np.sqrt(252) * rets.mean() / rets.std()) if rets.std() > 0 else 0.0
            cum = np.cumprod(1 + rets)
            running_max = np.maximum.accumulate(cum)
            max_dd = (
                float(np.abs((cum - running_max).min() / running_max.max()) * 100)
                if len(cum) > 0
                else 0.0
            )
        else:
            sharpe = 0.0
            max_dd = 0.0

        return {
            "total_return_pct": round(total_ret, 2),
            "sharpe": round(sharpe, 2),
            "max_dd_pct": round(max_dd, 2),
            "final_equity": round(final_equity, 0),
            "n_trading_days": len(daily_equity),
            "n_trades": total_trades,
            "total_cost": round(broker.total_trading_cost, 2),
            "total_commission": round(broker.total_commission, 2),
            "total_stamp_tax": round(broker.total_stamp_tax, 2),
            "total_slippage": round(broker.total_slippage, 2),
        }

    @staticmethod
    def _benchmark_return(
        price_data: dict[str, pl.DataFrame],
        symbols: list[str],
        start: str,
        end: str,
    ) -> float:
        """Equal-weight buy-and-hold return for comparison."""
        total_ret = 0.0
        count = 0
        # Use all loaded stocks if no symbol filter
        syms = symbols if symbols else list(price_data.keys())
        for sym in syms:
            if sym in price_data:
                df = price_data[sym]
                first = df.filter(pl.col("trade_date").cast(pl.Utf8) >= start)
                last = df.filter(pl.col("trade_date").cast(pl.Utf8) <= end)
                if not first.is_empty() and not last.is_empty():
                    px_first = float(first.head(1)["close"].item())
                    px_last = float(last.tail(1)["close"].item())
                    if px_first > 0:
                        total_ret += px_last / px_first - 1
                        count += 1
        return round(total_ret / count * 100, 2) if count > 0 else 0.0

    @staticmethod
    def _record_experiment(
        result: PipelineResult,
        start_date: str,
        end_date: str,
        dataset: str,
        features: list[str],
        weights: dict[str, float],
        top_n: int,
        rebalance_freq: int,
        industry_neutral: bool,
        orthogonalize: bool,
    ) -> None:
        """Persist experiment to ExperimentTracker (Rule 6: Everything is Experiment)."""
        from datetime import UTC, datetime

        from qp.research.experiment.tracker import ExperimentTracker

        tracker = ExperimentTracker()
        experiment_id = (
            f"multifactor_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        )
        tracker.log_experiment(
            experiment_id=experiment_id,
            config={
                "description": (
                    f"Multi-factor experiment: {len(features)} factors, "
                    f"Top-{top_n}, rebalance={rebalance_freq}d"
                    f"{', industry-neutral' if industry_neutral else ''}"
                    f"{', orthogonalized' if orthogonalize else ''}"
                ),
                "dataset_version": f"{dataset}@{start_date}_{end_date}",
                "features": features,
                "model_params": dict(weights),
                "train_start": start_date,
                "train_end": end_date,
                "tags": ["multifactor", f"top{top_n}", f"rebalance{rebalance_freq}d"],
            },
            metrics={
                "ic_mean": float(result.metrics.get("ic_mean", 0.0)),
                "ic_ir": float(result.metrics.get("ic_ir", 0.0)),
                "sharpe_ratio": float(result.metrics.get("sharpe", 0.0)),
                "max_drawdown_pct": float(result.metrics.get("max_dd_pct", 0.0)),
                "total_return_pct": float(result.metrics.get("total_return_pct", 0.0)),
                "annual_return_pct": 0.0,
                "annual_volatility_pct": 0.0,
            },
            lineage_graph={
                "dataset": f"{dataset}@{start_date}",
                "model_algo": "weighted_linear",
                "strategy_id": f"multifactor_top{top_n}",
            },
        )
        from loguru import logger

        logger.info("📝 实验已记录: {}", experiment_id)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _flatten_price_data(
    price_data: dict[str, pl.DataFrame],
) -> pl.DataFrame:
    """Flatten {symbol: DataFrame} into a single [trade_date, symbol, close] DataFrame."""
    parts: list[pl.DataFrame] = []
    for code, df in price_data.items():
        if df is not None and not df.is_empty():
            if "close" not in df.columns:
                continue
            parts.append(
                df.select(["trade_date", pl.lit(code).alias("symbol"), "close"])
            )
    if not parts:
        return pl.DataFrame(
            schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "close": pl.Float64}
        )
    return pl.concat(parts)


def _flatten_price_data_for_backtest(
    price_data: dict[str, pl.DataFrame],
) -> pl.DataFrame:
    """Flatten {symbol: DataFrame} into [trade_date, symbol, close, volume].

    Includes volume for ADV-based liquidity checks in SimulatedBroker.
    """
    parts: list[pl.DataFrame] = []
    for code, df in price_data.items():
        if df is not None and not df.is_empty():
            if "close" not in df.columns:
                continue
            cols = ["trade_date", "close"]
            if "volume" in df.columns:
                cols.append("volume")
            part = df.select(cols).with_columns(pl.lit(str(code)).alias("symbol"))
            parts.append(part)
    if not parts:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Utf8,
                "symbol": pl.Utf8,
                "close": pl.Float64,
                "volume": pl.Float64,
            }
        )
    return pl.concat(parts)


def _build_industry_map(
    price_data: dict[str, pl.DataFrame],
) -> dict[str, str] | None:
    """Build {symbol: industry} from price data if industry column exists."""
    for df in price_data.values():
        if df is not None and "industry" in df.columns:
            mapping: dict[str, str] = {}
            for code, stock_df in price_data.items():
                if stock_df is not None and "industry" in stock_df.columns:
                    ind = str(stock_df["industry"].tail(1).item() or "")
                    if ind:
                        mapping[code] = ind
            if mapping:
                return mapping
            break
    return None
