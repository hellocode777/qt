"""MultiFactorPipeline — multi-factor strategy experiment as a BasePipeline.

End-to-end experiment conforming to ADR-006 ("Everything is a Pipeline"):
  Data fetch → Factor compute → Cross-sectional scoring → IC analysis →
  Signal generation → Backtest → Benchmark comparison

Usage via CLI:
    qp experiment run multifactor \\
        --symbols 000001,000002,... \\
        --start 2024-01-01 --end 2026-07-20 \\
        --top-n 10 --rebalance 20 \\
        --industry-neutral --orthogonalize

Implements CLAUDE.md rules:
  - No print() — all output via Loguru
  - Data source access through BaseDataSource adapter (never direct akshare)
  - PipelineContext for all infrastructure access (ADR-012)
  - Single CLI entry point (ADR-002)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import polars as pl
from loguru import logger

from qp.data.adapter.tencent_adapter import TencentAdapter
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus
from qp.strategy.multifactor import (
    compute_cross_sectional_scores,
    generate_rebalance_signals,
)

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

        symbols: list[str] = params.get("symbols", DEFAULT_SYMBOLS)
        start_date_str: str = params.get("start_date", "2024-01-01")
        end_date_str: str = params.get("end_date", date.today().isoformat())
        top_n: int = int(params.get("top_n", 10))
        rebalance_freq: int = int(params.get("rebalance_freq", 20))
        sell_buffer: int = int(params.get("sell_buffer_rank", 5))
        industry_neutral: bool = params.get("industry_neutral", False)
        orthogonalize: bool = params.get("orthogonalize", False)

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        logger.info("=" * 70)
        logger.info("多因子策略实验 — A股真实数据")
        logger.info("=" * 70)
        logger.info(
            "股票池: {} 只 | 区间: {} → {} | Top-{} 每月调仓",
            len(symbols),
            start_date_str,
            end_date_str,
            top_n,
        )
        if industry_neutral:
            logger.info("行业中性化: ✅ | 因子正交化: {}", "✅" if orthogonalize else "❌")

        # ── Stage 1: Fetch data ──
        logger.info("[1/6] 获取行情数据...")
        try:
            price_data = self._fetch_data(symbols, start_date_str, end_date_str)
        except Exception as e:
            logger.error("数据获取失败: {}", e)
            result.status = PipelineStatus.FAILED
            result.errors.append(f"数据获取失败: {e}")
            return result

        total_rows = sum(df.height for df in price_data.values())
        logger.info("   {} 只股票, {} 行日线数据", len(price_data), total_rows)
        result.metrics["n_stocks"] = float(len(price_data))
        result.metrics["n_rows"] = float(total_rows)

        # ── Stage 2: Factor weights ──
        logger.info("[2/6] 计算截面多因子得分...")
        from qp.research.feature.compute import PRICE_VOLUME_FACTORS

        n_factors = len(PRICE_VOLUME_FACTORS)
        weights = dict.fromkeys(PRICE_VOLUME_FACTORS, 1.0 / n_factors)
        logger.info("   因子: {} 个价量因子, 等权", n_factors)

        scores = compute_cross_sectional_scores(
            price_data,
            weights=weights,
            min_history=120,
            industry_neutral=industry_neutral,
            orthogonalize=orthogonalize,
        )
        logger.info("   得分矩阵: {} 行 × {} 只股票", scores.height, len(price_data))  # type: ignore[union-attr]
        result.metrics["score_rows"] = float(scores.height)  # type: ignore[union-attr]

        # ── Stage 3: IC analysis ──
        logger.info("[3/6] Rank IC 分析...")
        ic_stats = self._compute_ic(scores, price_data)  # type: ignore[arg-type]
        logger.info("   IC Mean:  {:.4f}", ic_stats["ic_mean"])
        logger.info("   IC IR:    {:.2f}", ic_stats["ic_ir"])
        logger.info("   IC > 0:   {:.1f}% 天数", ic_stats["ic_positive_pct"])
        logger.info("   样本量:   {} 天", ic_stats["n_days"])
        result.metrics["ic_mean"] = ic_stats["ic_mean"]
        result.metrics["ic_ir"] = ic_stats["ic_ir"]
        result.metrics["ic_positive_pct"] = ic_stats["ic_positive_pct"]

        # ── Stage 4: Signal generation ──
        logger.info("[4/6] 生成调仓信号...")
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

        # ── Stage 5: Backtest ──
        logger.info("[5/6] 简单回测 (等权, 信号日调仓)...")
        bt = self._compute_backtest(signals, price_data)
        logger.info("   总收益:    {:+.2f}%", bt["total_return_pct"])
        logger.info("   年化夏普:  {:.2f}", bt["sharpe"])
        logger.info("   最大回撤:  {:.2f}%", bt["max_dd_pct"])
        logger.info("   期末资产:  ¥{:,.0f}", bt["final_equity"])
        result.metrics["total_return_pct"] = bt["total_return_pct"]
        result.metrics["sharpe"] = bt["sharpe"]
        result.metrics["max_dd_pct"] = bt["max_dd_pct"]
        result.metrics["final_equity"] = bt["final_equity"]

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

        return result

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_data(
        symbols: list[str],
        start: str,
        end: str,
    ) -> dict[str, pl.DataFrame]:
        """Fetch OHLCV data through BaseDataSource adapter."""
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)

        adapter = TencentAdapter()
        raw = adapter.fetch_raw(start_date, end_date, symbols=symbols)

        if raw.empty:
            return {}

        # Standardize column names (TencentAdapter returns Chinese columns)
        raw["trade_date"] = raw["日期"]
        raw["close"] = raw["收盘"]
        raw["open"] = raw["开盘"]
        raw["high"] = raw["最高"]
        raw["low"] = raw["最低"]
        raw["volume"] = raw["成交量"]

        dfs: dict[str, pl.DataFrame] = {}
        for code, group in raw.groupby("symbol"):
            df = pl.from_pandas(group)
            df = df.sort("trade_date")
            dfs[str(code)] = df

        return dfs

    @staticmethod
    def _get_price(
        code: str,
        date_str: str,
        price_data: dict[str, pl.DataFrame],
    ) -> float | None:
        """Get closing price for a stock on a given date."""
        if code not in price_data:
            return None
        row = price_data[code].filter(pl.col("trade_date") == date_str)
        if row.is_empty():
            return None
        return float(row["close"].item())

    @staticmethod
    def _compute_ic(
        scores: pl.DataFrame,
        price_data: dict[str, pl.DataFrame],
        forward_days: int = 5,
    ) -> dict[str, Any]:
        """Compute rolling Spearman Rank IC between score and forward return."""
        from qp.research.experiment.runner import ExperimentRunner

        all_dates = sorted(scores["trade_date"].unique().to_list())
        daily_ics: list[float] = []

        for i, d in enumerate(all_dates[:-forward_days]):
            day_scores = scores.filter(pl.col("trade_date") == d)
            if day_scores.height < 5:
                continue

            future_date = all_dates[min(i + forward_days, len(all_dates) - 1)]
            scores_vals: list[float] = []
            fwd_returns: list[float] = []

            for row in day_scores.iter_rows(named=True):
                sym = row["symbol"]
                s_val = row["score"]
                if sym in price_data:
                    df = price_data[sym]
                    today_row = df.filter(pl.col("trade_date") == d)
                    future_row = df.filter(pl.col("trade_date") == future_date)
                    if not today_row.is_empty() and not future_row.is_empty():
                        px_today = float(today_row["close"].item())
                        px_future = float(future_row["close"].item())
                        if px_today > 0:
                            scores_vals.append(float(s_val))
                            fwd_returns.append(px_future / px_today - 1)

            if len(scores_vals) >= 5:
                ic = ExperimentRunner._spearman_ic(
                    np.array(scores_vals),
                    np.array(fwd_returns),
                )
                daily_ics.append(ic)

        if not daily_ics:
            return {"ic_mean": 0.0, "ic_ir": 0.0, "ic_positive_pct": 0.0, "n_days": 0}

        ics = np.array(daily_ics)
        return {
            "ic_mean": round(float(np.mean(ics)), 4),
            "ic_ir": round(
                float(abs(np.mean(ics)) / np.std(ics)) if np.std(ics) > 0 else 0.0,
                2,
            ),
            "ic_positive_pct": round(float(np.sum(ics > 0) / len(ics) * 100), 1),
            "n_days": len(daily_ics),
        }

    @staticmethod
    def _compute_backtest(
        signals: pl.DataFrame,
        price_data: dict[str, pl.DataFrame],
        initial_capital: float = 1_000_000,
    ) -> dict[str, Any]:
        """Simple equal-weight backtest with rebalance on signal days."""
        if signals.is_empty():
            return {
                "total_return_pct": 0.0,
                "sharpe": 0.0,
                "max_dd_pct": 0.0,
                "final_equity": initial_capital,
                "n_trading_days": 0,
            }

        all_dates = sorted(
            set().union(*(df["trade_date"].unique().to_list() for df in price_data.values()))
        )

        cash = initial_capital
        holdings: dict[str, float] = {}
        equity_curve: list[float] = []

        for d in all_dates:
            d_str = str(d)

            # Mark to market
            stock_value = 0.0
            for sym, shares in list(holdings.items()):
                px = MultiFactorPipeline._get_price(sym, d_str, price_data)
                if px is not None:
                    stock_value += shares * px

            equity = cash + stock_value
            equity_curve.append(equity)

            # Check for rebalance signals on this date
            day_signals = signals.filter(pl.col("date") == d_str)
            if day_signals.is_empty():
                continue

            # Liquidate
            for sym, shares in list(holdings.items()):
                px = MultiFactorPipeline._get_price(sym, d_str, price_data)
                if px is not None:
                    cash += shares * px
            holdings.clear()
            total_equity = cash

            # Buy new positions
            buys = day_signals.filter(pl.col("signal") == "buy")
            buy_symbols = buys["symbol"].to_list()
            if not buy_symbols:
                continue

            n_positions = len(buy_symbols)
            per_stock = total_equity / n_positions

            for sym in buy_symbols:
                px = MultiFactorPipeline._get_price(sym, d_str, price_data)
                if px is not None and px > 0:
                    shares = int(per_stock / px // 100 * 100)
                    if shares > 0:
                        holdings[sym] = shares
                        cash -= shares * px

        final_equity = equity_curve[-1] if equity_curve else initial_capital
        total_ret = (final_equity / initial_capital - 1) * 100

        # Daily returns
        daily_rets = [
            equity_curve[i] / equity_curve[i - 1] - 1
            for i in range(1, len(equity_curve))
            if equity_curve[i - 1] > 0
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
            "n_trading_days": len(equity_curve),
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
        for sym in symbols:
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
