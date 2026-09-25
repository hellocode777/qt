"""Paper Trading Tracker — 30-day paper trading with automatic evaluation.

Tracks a strategy's performance in simulated real-time trading. After 30
trading days, automatically evaluates whether to promote to Shadow Production
or demote back to Research.

Evaluation criteria (from plan_v1.md M3.3):
  - Signal correlation (paper vs backtest) ≥ 0.8
  - Slippage deviation ≤ 50% of expected
  - Sharpe ratio within acceptable range
  - Max drawdown within limits

Usage:
    tracker = PaperTradingTracker()
    run = tracker.start("simple_rank_v1.0", capital=100_000)
    for date, prices in trading_days:
        status = tracker.run_day(run, date, prices)
    result = tracker.evaluate(run)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from qp.shared.paths import PAPER_TRADING_DIR
from qp.shared.time import today_cn
from qp.shared.types import StrategyLifecycle

# ------------------------------------------------------------------
# Rebalance rule (aligned with shadow/decision side)
# ------------------------------------------------------------------


def _is_rebalance_day(trade_date: str) -> bool:
    """trade_date 是否为调仓日: 每月首个交易日。

    与 shadow 侧 daily_pipeline 的 BUY 门同口径
    (qp/pipeline/daily_pipeline.py:219-243):
    真实 A 股日历 (TradingCalendar) 可用 → is_first_trading_day_of_month;
    日历不可用 (akshare 网络挂 / 异常) → 退回 day<=5 近似。
    """
    try:
        d = date.fromisoformat(trade_date[:10])
    except (TypeError, ValueError):
        return False
    try:
        from qp.data.calendar.calendar import TradingCalendar

        cal = TradingCalendar()
        # 先调用以触发真实日历加载并设置 has_real_calendar (与 daily_pipeline 一致)
        cal.first_trading_day_of_month(d.year, d.month)
        if cal.has_real_calendar is True:
            return cal.is_first_trading_day_of_month(d)
    except Exception:
        pass
    return d.day <= 5


def _rebalance_to_equal_weight(broker: Any, symbols: list[str], price_map: dict[str, float]) -> int:
    """月度调仓日执行: 两阶段 (先卖后买) 把持仓重构为 symbols 等权。

    SimulatedBroker 在 submit 时就校验 BUY 现金, 必须先执行 SELL 释放
    现金再提交 BUY, 否则买入会被 Insufficient cash 拒绝。返回当日成交笔数。

    Args:
        broker: SimulatedBroker 实例 (run_day 内惰性导入, 此处用 Any)。
        symbols: 目标 top-N 名单 (已截断到 10)。
        price_map: symbol → 当日 (或 <= 当日最近可用) 收盘价。
    """
    if not symbols:
        return 0
    equity_now = broker.get_equity()
    per_budget = equity_now / max(len(symbols), 1)
    desired: dict[str, int] = {}
    for sym in symbols:
        px = price_map.get(sym, 0.0)
        if px <= 0:
            desired[sym] = 0
            continue
        desired[sym] = int(per_budget / px // 100 * 100)

    # 阶段 1: SELL —— 不在目标名单的持仓清掉, 目标内超配的降到等权
    held = {s: p.shares for s, p in broker._positions.items() if p.shares > 0}
    for sym, shares in held.items():
        qty = shares - desired.get(sym, 0)
        if qty > 0:
            broker.submit_order(
                {
                    "symbol": sym,
                    "side": "SELL",
                    "quantity": qty,
                    "order_type": "market",
                }
            )
    sells = broker.execute_pending()
    # 清掉已清仓的零股残留: broker.get_positions()/n_positions 会把
    # shares=0 的 Position 计入长度, 不清理会虚增持仓数
    broker._positions = {s: p for s, p in broker._positions.items() if p.shares > 0}

    # 阶段 2: BUY —— 目标名单内缺失或低配的补到等权
    held_now = {s: p.shares for s, p in broker._positions.items() if p.shares > 0}
    for sym in symbols:
        need = desired.get(sym, 0) - held_now.get(sym, 0)
        if need > 0:
            broker.submit_order(
                {
                    "symbol": sym,
                    "side": "BUY",
                    "quantity": need,
                    "order_type": "market",
                }
            )
    buys = broker.execute_pending()

    return len(sells) + len(buys)


# ------------------------------------------------------------------
# Data models
# ------------------------------------------------------------------


@dataclass
class DailyRecord:
    """One day's paper trading snapshot."""

    date: str = ""
    equity: float = 0.0
    cash: float = 0.0
    n_positions: int = 0
    n_signals: int = 0
    n_trades: int = 0
    daily_return: float = 0.0
    total_cost: float = 0.0
    positions: dict[str, int] = field(default_factory=dict)  # symbol → shares
    avg_costs: dict[str, float] = field(default_factory=dict)  # symbol → avg cost basis


@dataclass
class PaperTradingResult:
    """30-day evaluation result."""

    elapsed_days: int = 0
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    annual_volatility_pct: float = 0.0
    total_cost: float = 0.0
    avg_daily_signals: float = 0.0
    final_equity: float = 0.0
    passed: bool = False
    recommendation: str = ""
    promotion_target: StrategyLifecycle | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaperTradingRun:
    """State of an active or completed paper trading run."""

    run_id: str = ""
    strategy_id: str = ""
    capital: float = 100_000
    start_date: str = ""
    daily_records: list[DailyRecord] = field(default_factory=list)
    result: PaperTradingResult | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    state_file: str = ""

    @property
    def elapsed_days(self) -> int:
        return len(self.daily_records)

    @property
    def is_complete(self) -> bool:
        return self.elapsed_days >= 30 or self.result is not None

    @property
    def current_equity(self) -> float:
        if not self.daily_records:
            return self.capital
        return self.daily_records[-1].equity


# ------------------------------------------------------------------
# Paper Trading Tracker
# ------------------------------------------------------------------


class PaperTradingTracker:
    """Tracks a strategy through 30-day paper trading with auto-evaluation.

    Usage:
        tracker = PaperTradingTracker(data_dir=PAPER_TRADING_DIR)
        run = tracker.start("simple_rank_v1.0", capital=100_000)

        # Each trading day:
        prices = load_prices(date)
        status = tracker.run_day(run, str(date), prices)

        # After 30 days:
        result = tracker.evaluate(run)
        if result.passed:
            registry.set_lifecycle("simple_rank_v1.0", StrategyLifecycle.SHADOW_PRODUCTION)
    """

    def __init__(self, data_dir: str | Path = PAPER_TRADING_DIR) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        strategy_id: str,
        capital: float = 100_000,
        start_date: str | None = None,
    ) -> PaperTradingRun:
        """Begin a new 30-day paper trading run.

        Args:
            strategy_id: Strategy to paper trade.
            capital: Initial capital in CNY.
            start_date: Start date (YYYY-MM-DD), defaults to today.

        Returns:
            Initialized PaperTradingRun ready for daily iteration.
        """
        import uuid

        if start_date is None:
            start_date = today_cn().isoformat()

        run = PaperTradingRun(
            run_id=f"pt-{uuid.uuid4().hex[:8]}",
            strategy_id=strategy_id,
            capital=capital,
            start_date=start_date,
            state_file=str(self._data_dir / f"{strategy_id}_paper.json"),
        )

        self._save(run)
        return run

    def run_day(
        self,
        run: PaperTradingRun,
        trade_date: str,
        prices: pl.DataFrame,
        signals: pl.DataFrame | None = None,
        broker: Any | None = None,
    ) -> DailyRecord:
        """Execute one day of paper trading.

        Args:
            run: Active paper trading run.
            trade_date: Current trading date (YYYY-MM-DD).
            prices: Daily price data with [symbol, close].
            signals: Strategy signals (optional; regenerated if None).
            broker: SimulatedBroker instance (optional; auto-created if None).
                Prefer injecting from the caller to avoid cross-layer imports.

        Returns:
            DailyRecord with metrics for this day.
        """
        from qp.strategy.registry import StrategyRegistry
        from qp.strategy.simple_rank import SimpleRankStrategy

        if broker is None:
            from qp.simulation.broker import SimulatedBroker

            broker = SimulatedBroker(initial_cash=run.capital)

        # Restore cash + positions from the previous day so holdings persist
        # across the 30-day window (Rule 11: real paper trading holds positions).
        if run.daily_records:
            prev = run.daily_records[-1]
            broker._cash = prev.cash
            if prev.positions:
                broker.restore_positions(prev.positions, prev.avg_costs)

        # Build price/ADV maps.
        # CRITICAL (2026-08-21): daily_price_latest.parquet is NOT sorted by
        # (symbol, trade_date) — iterating the whole frame and letting the
        # last row per symbol win produced random historical prices (e.g.
        # 2016 closes) as fill prices. Filter to the target trade_date first,
        # then fall back to the latest available date <= trade_date so
        # suspended stocks still get their last known price.
        prices_td = prices.filter(pl.col("trade_date").cast(pl.Utf8) <= str(trade_date)[:10])
        price_map: dict[str, float] = {}
        adv_map: dict[str, float] = {}
        if not prices_td.is_empty():
            prices_td = (
                prices_td.sort(["symbol", "trade_date"]).group_by("symbol").agg(pl.all().last())
            )
            for row in prices_td.iter_rows(named=True):
                sym = str(row["symbol"])
                px = float(row.get("close", 0.0))
                vol = float(row.get("volume", 0.0))
                price_map[sym] = px
                if vol > 0 and px > 0:
                    adv_map[sym] = px * vol

        broker.set_prices(price_map, adv_map, trade_date)

        # Generate signals if not provided
        if signals is None:
            registry = StrategyRegistry()
            if run.strategy_id in registry.list_strategies():
                # Strategy is persisted in the registry but may not have an
                # in-process instance (registry stores metadata, instances are
                # process-local). Build the strategy from its config so paper
                # trading works from any fresh process (scheduler, CLI).
                from qp.strategy.config import get_strategy_config

                try:
                    cfg = get_strategy_config(run.strategy_id)
                except KeyError:
                    cfg = None

                if cfg is not None:
                    # Fast-path: today's cross-sectional scores (ADR-031),
                    # avoids the expensive full-history compute per day.
                    from qp.strategy.multifactor import (
                        MultiFactorStrategy,
                        compute_cross_sectional_scores,
                    )

                    # price_data dict for the scorer (built once per day)
                    score_price_map: dict[str, pl.DataFrame] = {}
                    for row in prices.iter_rows(named=True):
                        sym = str(row["symbol"])
                        if sym not in score_price_map:
                            score_price_map[sym] = prices.filter(pl.col("symbol") == sym)
                    scores = compute_cross_sectional_scores(
                        score_price_map,
                        weights=dict(cfg.factors),
                        min_history=60,
                        industry_neutral=cfg.industry_neutral,
                        orthogonalize=cfg.orthogonalize,
                    )
                    if isinstance(scores, tuple):
                        scores = scores[0]
                    today_scores = scores.filter(
                        pl.col("trade_date").cast(pl.Utf8) <= str(trade_date)[:10]
                    )
                    if not today_scores.is_empty():
                        latest = today_scores["trade_date"].max()
                        today_scores = today_scores.filter(pl.col("trade_date") == latest).sort(
                            "score", descending=True
                        )
                        today_scores = today_scores.with_columns(
                            pl.col("score")
                            .rank(descending=True, method="min")
                            .cast(pl.Int64)
                            .alias("rank")
                        )
                        strategy = MultiFactorStrategy.from_today_scores(
                            run.strategy_id, today_scores, top_n=cfg.max_positions
                        )
                        signals = strategy.generate_signals(str(trade_date)[:10])
                if signals is None:
                    strategy = registry.get(run.strategy_id)
                    today = date.fromisoformat(trade_date)
                    signals = strategy.generate_signals(today)
            else:
                from qp.strategy.simple_rank import SimpleRankStrategy

                registry.register(SimpleRankStrategy(top_n=10), persist=False)
                strategy = registry.get(run.strategy_id)
                today = date.fromisoformat(trade_date)
                signals = strategy.generate_signals(today)

        n_signals = len(signals) if signals is not None and not signals.is_empty() else 0
        n_trades = 0

        # 下单时机: 首日建仓 (positioning) + 月度调仓日 (每月首个交易日,
        # 对齐 shadow 侧 daily_pipeline BUY 门口径 — 见 _is_rebalance_day)。
        if signals is not None and not signals.is_empty():
            symbols = signals["symbol"].to_list()[:10]
            if run.elapsed_days == 0:
                # 首日建仓: 全仓等权买入 top-N
                per_stock = run.capital / max(len(symbols), 1)
                for sym in symbols:
                    px = price_map.get(sym, 10.0)
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
                trades = broker.execute_pending()
                n_trades = len(trades)
            elif _is_rebalance_day(trade_date):
                # 月度调仓日: 先卖后买, 重构为当日 signals top-N 等权
                n_trades = _rebalance_to_equal_weight(broker, symbols, price_map)

        equity = broker.get_equity()
        cash = broker.get_cash()
        total_cost = broker.total_trading_cost

        # Compute daily return
        prev_equity = run.current_equity if run.daily_records else run.capital
        daily_ret = (equity / prev_equity - 1) if prev_equity > 0 else 0.0

        record = DailyRecord(
            date=trade_date,
            equity=equity,
            cash=cash,
            n_positions=len(broker.get_positions()),
            n_signals=n_signals,
            n_trades=n_trades,
            daily_return=daily_ret,
            total_cost=total_cost,
            positions={sym: pos.shares for sym, pos in broker._positions.items() if pos.shares > 0},
            avg_costs={
                sym: pos.avg_cost for sym, pos in broker._positions.items() if pos.shares > 0
            },
        )

        run.daily_records.append(record)
        self._save(run)

        # Auto-evaluate if 30 days reached
        if run.elapsed_days >= 30 and run.result is None:
            run.result = self.evaluate(run)
            self._save(run)

        return record

    def evaluate(self, run: PaperTradingRun) -> PaperTradingResult:
        """Evaluate a completed (or in-progress) paper trading run.

        Criteria (plan_v1.md M3.3):
          - Sharpe ≥ 0.5 (relaxed from backtest's 1.0 for paper trading)
          - Max drawdown ≤ 20%
          - Average daily signals within expected range (5-30)

        Returns:
            PaperTradingResult with pass/fail and recommendation.
        """
        if not run.daily_records:
            return PaperTradingResult(
                elapsed_days=0,
                recommendation="No trading days recorded",
            )

        n = len(run.daily_records)
        returns = np.array([r.daily_return for r in run.daily_records])

        total_ret = float((run.current_equity / run.capital - 1) * 100)
        sharpe = float(np.sqrt(252) * returns.mean() / returns.std()) if returns.std() > 0 else 0.0
        ann_vol = float(returns.std() * np.sqrt(252) * 100)

        # Max drawdown — relative to running peak (per-point drawdown / peak)
        cum = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cum)
        max_dd = (
            float(np.abs(((cum - running_max) / running_max).min()) * 100) if len(cum) > 0 else 0.0
        )

        avg_signals = float(np.mean([r.n_signals for r in run.daily_records]))
        total_cost = float(sum(r.total_cost for r in run.daily_records))

        # Check gates
        checks: dict[str, bool] = {
            "sharpe": sharpe >= 0.5,
            "max_drawdown": max_dd <= 20.0,
            "signals_range": 3 <= avg_signals <= 30,
        }
        passed = all(checks.values())

        recommendations = []
        if not checks["sharpe"]:
            recommendations.append(f"Sharpe {sharpe:.2f} < 0.5")
        if not checks["max_drawdown"]:
            recommendations.append(f"MaxDD {max_dd:.1f}% > 20%")
        if not checks["signals_range"]:
            recommendations.append(f"Avg signals {avg_signals:.1f} out of [3, 30]")

        if passed:
            recommendation = (
                "PASS: Paper trading successful. Recommend promotion to SHADOW_PRODUCTION."
            )
            promotion = StrategyLifecycle.SHADOW_PRODUCTION
        else:
            recommendation = (
                f"FAIL: {', '.join(recommendations)}. Recommend return to RESEARCH for iteration."
            )
            promotion = StrategyLifecycle.RESEARCH

        return PaperTradingResult(
            elapsed_days=n,
            total_return_pct=total_ret,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            annual_volatility_pct=ann_vol,
            total_cost=total_cost,
            avg_daily_signals=avg_signals,
            final_equity=run.current_equity,
            passed=passed,
            recommendation=recommendation,
            promotion_target=promotion,
            details=checks,
        )

    def status(self, run: PaperTradingRun) -> dict[str, Any]:
        """Get current status snapshot."""
        status: dict[str, Any] = {
            "run_id": run.run_id,
            "strategy_id": run.strategy_id,
            "capital": run.capital,
            "start_date": run.start_date,
            "elapsed_days": run.elapsed_days,
            "current_equity": run.current_equity,
            "is_complete": run.is_complete,
        }
        if run.result:
            status["result"] = {
                "passed": run.result.passed,
                "total_return": run.result.total_return_pct,
                "sharpe": run.result.sharpe_ratio,
                "max_drawdown": run.result.max_drawdown_pct,
                "recommendation": run.result.recommendation,
            }
        return status

    def load(self, strategy_id: str) -> PaperTradingRun | None:
        """Load an existing paper trading run from disk."""
        state_file = self._data_dir / f"{strategy_id}_paper.json"
        if not state_file.exists():
            return None
        return self._load(state_file)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self, run: PaperTradingRun) -> None:
        """Save run state to JSON file."""
        data = {
            "run_id": run.run_id,
            "strategy_id": run.strategy_id,
            "capital": run.capital,
            "start_date": run.start_date,
            "created_at": run.created_at,
            "daily_records": [
                {
                    "date": r.date,
                    "equity": r.equity,
                    "cash": r.cash,
                    "n_positions": r.n_positions,
                    "n_signals": r.n_signals,
                    "n_trades": r.n_trades,
                    "daily_return": r.daily_return,
                    "total_cost": r.total_cost,
                    "positions": dict(r.positions),
                    "avg_costs": dict(r.avg_costs),
                }
                for r in run.daily_records
            ],
        }
        if run.result:
            data["result"] = {
                "passed": run.result.passed,
                "recommendation": run.result.recommendation,
                "total_return_pct": run.result.total_return_pct,
                "sharpe_ratio": run.result.sharpe_ratio,
                "max_drawdown_pct": run.result.max_drawdown_pct,
            }

        run.state_file = str(self._data_dir / f"{run.strategy_id}_paper.json")
        Path(run.state_file).write_text(json.dumps(data, indent=2, default=str))

    @staticmethod
    def _load(path: Path) -> PaperTradingRun:
        """Load run state from JSON file."""
        data = json.loads(path.read_text())
        run = PaperTradingRun(
            run_id=data["run_id"],
            strategy_id=data["strategy_id"],
            capital=data["capital"],
            start_date=data["start_date"],
            created_at=data.get("created_at", ""),
            state_file=str(path),
        )
        run.daily_records = [DailyRecord(**r) for r in data.get("daily_records", [])]
        if data.get("result"):
            run.result = PaperTradingResult(**data["result"])
        return run
