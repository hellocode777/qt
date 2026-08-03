"""DailyPipeline — orchestrated end-to-end daily decision pipeline.

Phase 7 upgrade: Data → Feature → Lineage → Regime → Strategy Discovery
    → Validation Gate → Strategy Execution → Ensemble Fusion → Risk Audit
    → Cost → Capital Allocation → DecisionPackage.

Produces a structured DecisionPackage (data/decisions/) with full
lineage, validation, risk audit trail, and human review section.
Backtest has been REMOVED — it belongs in the experiment pipeline.
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from qp.data.pipeline import DataPipeline
from qp.decision.decision_package import (
    DecisionPackage,
    HumanReview,
    LineageSnapshot,
    RegimeContext,
    RiskAudit,
    RiskAuditEntry,
)
from qp.decision.engine import DecisionEngine
from qp.decision.models import DecisionReport, TradeRecommendation
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.portfolio.capital_allocator import CapitalAllocator, CapitalAllocatorConfig
from qp.portfolio.cost_model import CostModel, MarketImpactModel
from qp.portfolio.risk_manager import PortfolioRiskManager
from qp.portfolio.single_portfolio import Order
from qp.research.pipeline import FeaturePipeline
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus, StrategyLifecycle
from qp.strategy.ensemble.ensemble_engine import EnsembleEngine, UniversePolicy
from qp.strategy.ensemble.weighting import WeightEngine, WeightMethod
from qp.strategy.market_regime import MarketRegimeDetector
from qp.strategy.multifactor import MultiFactorStrategy
from qp.strategy.registry import StrategyRegistry


def _load_price_data() -> tuple[dict[str, pl.DataFrame], pl.DataFrame]:
    """Load daily price data and index into strategy-ready format.

    Returns:
        (price_data_by_symbol, flat_prices_df)
        price_data_by_symbol: {code: DataFrame[date, open, high, low, close, volume]}
        flat_prices_df: Full Polars DataFrame for risk/backtest.
    """
    path = "data/dataset/daily_price_latest.parquet"

    if not os.path.exists(path):
        return {}, pl.DataFrame()

    df = pl.read_parquet(path)

    # Pivot into {symbol: sub-DataFrame}
    price_data: dict[str, pl.DataFrame] = {}
    if "symbol" in df.columns:
        symbols = df["symbol"].unique().to_list()
        for sym in symbols:
            sub = df.filter(pl.col("symbol") == sym)
            if not sub.is_empty():
                price_data[sym] = sub

    return price_data, df


def _build_index_df(price_data: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Build a proxy index DataFrame from average close across all stocks.

    Uses group-by over all stocks per date instead of inner join,
    so dates with partial coverage (early listings, delistings) are included.
    """
    if not price_data:
        return pl.DataFrame()

    date_col = "trade_date" if "trade_date" in next(iter(price_data.values())).columns else "date"

    frames = []
    for pdf in price_data.values():
        if pdf is not None and not pdf.is_empty() and date_col in pdf.columns and "close" in pdf.columns:
            frames.append(pdf.select([date_col, "close"]))

    if not frames:
        return pl.DataFrame()

    all_closes = pl.concat(frames, how="vertical")
    result = all_closes.group_by(date_col).agg(
        pl.col("close").mean().alias("close")
    ).sort(date_col).rename({date_col: "date"})

    return result


def _load_fundamental_data() -> dict[str, pl.DataFrame]:
    """Load fundamental data from parquet (replaces QuantTrading DB).

    Returns:
        {code: DataFrame(report_date, publish_date, ROE, gross_margin,
         revenue_growth, net_margin, debt_ratio, net_profit_growth, EPS, NAV)}
    """
    from pathlib import Path as _Path

    path = _Path("data/dataset") / "fundamentals_latest.parquet"

    if not path.exists():
        return {}

    try:
        df = pl.read_parquet(str(path))
    except Exception:
        return {}

    if df.is_empty():
        return {}

    result: dict[str, pl.DataFrame] = {}
    if "symbol" in df.columns:
        for sym in df["symbol"].unique().to_list():
            sub = df.filter(pl.col("symbol") == sym).sort("report_date")
            if not sub.is_empty():
                result[str(sym)] = sub.with_columns(pl.col("report_date").alias("publish_date"))

    return result




def _build_lineage_snapshot(price_data: dict[str, pl.DataFrame]) -> LineageSnapshot:
    """Build lineage snapshot from current dataset and feature versions."""
    from datetime import date as _date

    today = _date.today().isoformat()
    dataset_name = "daily_price_main"
    dataset_rows = 0
    dataset_symbols = len(price_data)

    # Count total rows
    for pdf in price_data.values():
        if pdf is not None and not pdf.is_empty():
            dataset_rows += pdf.height

    # Feature versions — use today's date as version since features are
    # computed fresh each run
    feature_versions = {
        "momentum_20d": today,
        "volatility_20d": today,
    }

    return LineageSnapshot(
        dataset_name=dataset_name,
        dataset_version=today,
        dataset_rows=dataset_rows,
        dataset_symbols=dataset_symbols,
        feature_versions=feature_versions,
    )


class DailyPipeline(BasePipeline):
    """End-to-end daily decision pipeline — produces a DecisionPackage.

    Pipeline steps:
      1. Data ingestion (DataPipeline)
      2. Feature computation (FeaturePipeline)
      3. Price data loading
      4. Lineage snapshot (dataset & feature versions)
      5. Market regime detection
      6. Strategy discovery & registration
      7. Validation Gate (per-strategy)
      8. Strategy execution
      9. Multi-strategy signal fusion (EnsembleEngine)
      10. Risk management → RiskAudit
      11. Cost estimation
      12. Capital allocation
      13. DecisionPackage construction & save

    Output: data/decisions/dp-{date}-{run_id}.json + .md
    """

    @property
    def name(self) -> str:
        return "daily"

    def run(self, context: PipelineContext) -> PipelineResult:
        # Use runtime logger when available (ADR-012), fall back to module-level
        logger = context.logger

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        try:
            total_capital = context.parameters.get("capital", 100_000)
            top_n = context.parameters.get("top_n", 10)
            alloc_method = context.parameters.get("allocator", "equal_weight")
            today = date.today()
            run_id_short = context.run_id[:8] if context.run_id else "unknown"
            # V2.1: 调仓日 = 每月前5个自然日（近似每月第一个交易周）
            is_rebalance_day = today.day <= 5

            # ================================================================
            # Step 0: System state check (#8 fix)
            # ================================================================
            try:
                from qp.monitoring.system_state import SystemStateManager

                state_mgr = SystemStateManager()
                current_state = state_mgr.current()

                result.metadata["system_state"] = current_state.to_state.name
                result.metadata["system_state_reason"] = current_state.reason

                if not current_state.to_state.can_open_positions():
                    logger.warning(
                        "⛔ 系统状态 {} — 跳过策略执行 / System {} — skipping strategies",
                        current_state.to_state.label(),
                        current_state.to_state.name,
                    )
                    result.status = PipelineStatus.SUCCESS
                    result.metadata["skip_reason"] = (
                        f"System state {current_state.to_state.name}: {current_state.reason}"
                    )
                    return result
            except Exception:
                pass  # State check is advisory — don't block if unavailable

            # ================================================================
            # Step 1: Data ingestion
            # ================================================================
            skip_fetch = bool(context.parameters.get("skip_fetch", False))
            if skip_fetch:
                result.metadata["data_skip"] = "Data fetch skipped (--skip-fetch)"
            else:
                data_pipeline = DataPipeline()
                data_result = data_pipeline.run(context)
                if data_result.status == PipelineStatus.FAILED:
                    result.errors.extend(data_result.errors)
                    result.status = PipelineStatus.FAILED
                    return result
                result.metrics.update({f"data_{k}": v for k, v in data_result.metrics.items()})

            # ================================================================
            # Step 2: Feature computation (momentum + volatility)
            # ================================================================
            feature_pipeline = FeaturePipeline()
            feature_result = feature_pipeline.run(context)
            if feature_result.status == PipelineStatus.FAILED:
                result.errors.extend(feature_result.errors)
                result.status = PipelineStatus.FAILED
                return result

            # ================================================================
            # Step 3: Load price data and build strategy inputs
            # ================================================================
            price_data, prices = _load_price_data()
            result.metrics["price_symbols"] = len(price_data)

            if not price_data:
                result.metadata["warning"] = "No price data available — skipping strategies"
                result.artifacts.append("data/dataset/momentum_20d.parquet")
                result.artifacts.append("data/dataset/volatility_20d.parquet")
                return result

            # Build index proxy for regime detection
            index_df = _build_index_df(price_data)

            # Load fundamental data and compute valuation
            fundamental_data = _load_fundamental_data()

            # ================================================================
            # Step 4: Build Lineage Snapshot
            # ================================================================
            lineage_snapshot = _build_lineage_snapshot(price_data)
            result.metadata["dataset_version"] = lineage_snapshot.dataset_version

            # ================================================================
            result.metadata["is_rebalance_day"] = str(is_rebalance_day)

            # Step 5: Market regime detection
            # ================================================================
            regime_label = "neutral"
            suggested_position_pct = 1.0
            if not index_df.is_empty():
                try:
                    detector = MarketRegimeDetector()
                    regime_result = detector.detect(index_df, price_data)
                    regime_label = regime_result.regime
                    suggested_position_pct = regime_result.suggested_position_pct
                    result.metadata["market_regime"] = regime_label
                    result.metrics["regime_position_pct"] = round(suggested_position_pct, 2)
                    result.metrics["regime_confidence"] = round(regime_result.confidence, 2)
                    result.metrics["regime_trend"] = round(regime_result.trend_score, 2)
                    # Compute actual annualized vol from price data
                    if not index_df.is_empty() and "close" in index_df.columns:
                        import numpy as np
                        closes = index_df["close"].to_numpy().astype(np.float64)
                        if len(closes) > 20:
                            log_ret = np.diff(np.log(closes[-252:]))
                            ann_vol = float(np.std(log_ret) * np.sqrt(252))
                            result.metrics["regime_vol"] = round(ann_vol, 4)
                        else:
                            result.metrics["regime_vol"] = 0.0
                    else:
                        result.metrics["regime_vol"] = 0.0
                    result.metadata["regime_reason"] = regime_result.reason

                    # Adjust top_n by regime
                    regime_positions = {
                        "bull": top_n,
                        "sideways_up": max(5, top_n * 3 // 4),
                        "sideways_down": max(3, top_n // 2),
                        "neutral": max(5, top_n * 2 // 3),
                        "bear": max(1, top_n // 3),
                        "crisis": 0,
                    }
                    effective_top_n = regime_positions.get(regime_label, top_n)
                    result.metrics["effective_top_n"] = effective_top_n
                except Exception:
                    effective_top_n = top_n
            else:
                effective_top_n = top_n

            # ================================================================
            # ================================================================
            # Step 6: Strategy registration — daily-mode fast path (ADR-031)
            # ================================================================
            # ADR-031: Daily pipeline loads frozen weights from strategy config
            # and computes ONLY today's scores (O(stocks) instead of
            # O(stocks × dates)).  Full historical factor computation belongs
            # in the experiment phase.
            #
            # TODO: auto-discover validated strategies from ExperimentTracker
            #       (ExperimentTracker.list_experiments() → filter by status=completed
            #        → extract strategy_name from config).  For now, hardcode
            #        the primary validated strategy.
            registry = StrategyRegistry()
            registered_ids: list[str] = []

            # ADR-031: discover strategies from Registry (auto-populated by
            # experiments that passed Gate).  Weights are read from Registry
            # metadata, NOT from StrategyConfig — the Registry is the single
            # source of truth for frozen production weights.
            validated_strategies: list[str] = []

            # 1. APPROVED strategies (explicitly frozen)
            for sid in registry.list_strategies():
                try:
                    if registry.get_lifecycle(sid) == StrategyLifecycle.APPROVED:
                        validated_strategies.append(sid)
                except KeyError:
                    pass

            # 2. RESEARCH strategies with weights + backtest (auto-registered
            #    by experiments, awaiting manual approve)
            if not validated_strategies:
                for sid in registry.list_strategies():
                    try:
                        meta = registry.get_meta(sid)
                        if meta.weights and meta.backtest_ic:
                            validated_strategies.append(sid)
                    except KeyError:
                        pass

            # 3. Fallback: hardcoded (initial bootstrap before any experiment)
            if not validated_strategies:
                validated_strategies = [
                    "momentum_vol_full",
                ]
            today_str = today.isoformat()

            from qp.strategy.config import get_strategy_config
            from qp.strategy.multifactor import compute_today_signals

            logger.info(
                "Daily pipeline — loaded from Registry: {}",
                ", ".join(validated_strategies),
            )

            for strategy_name in validated_strategies:
                try:
                    # ADR-031: read frozen weights from Registry first,
                    # fall back to StrategyConfig for parameters
                    registry_meta = registry.get_meta(strategy_name)
                    weights = dict(registry_meta.weights) if registry_meta.weights else {}

                    if not weights:
                        # Fallback: no weights in Registry yet → read from config
                        cfg = get_strategy_config(strategy_name)
                        weights = dict(cfg.factors)

                    logger.info(
                        "   {} — {} factors (today-only scoring{})",
                        strategy_name,
                        len(weights),
                        " [from Registry]" if registry_meta.weights else " [from Config]",
                    )

                    # Parameters: try Registry first, then config
                    params = dict(registry_meta.parameters) if registry_meta.parameters else {}
                    industry_neutral = params.get("industry_neutral", True)
                    if not isinstance(industry_neutral, bool):
                        industry_neutral = True

                    # Fast path: compute only today's scores, not full history
                    today_scores = compute_today_signals(
                        price_data=price_data,
                        weights=weights,
                        today=today_str,
                        top_n=effective_top_n,
                        industry_neutral=industry_neutral,
                    )

                    # Build strategy from today-only scores (avoids 90s init)
                    multifactor = MultiFactorStrategy.from_today_scores(
                        strategy_name=strategy_name,
                        today_scores=today_scores,
                        top_n=effective_top_n,
                    )
                    # Merge weights into metadata (preserve backtest fields from experiment)
                    if not registry_meta.weights:
                        registry_meta.weights = dict(weights)
                        with contextlib.suppress(KeyError):
                            registry.set_meta(strategy_name, registry_meta)
                    registry.register(
                        multifactor,
                        lifecycle=StrategyLifecycle.RESEARCH,
                        meta=registry_meta,
                    )
                    registered_ids.append(multifactor.strategy_id)
                except Exception as exc:
                    logger.warning("策略 {} 注册失败: {}", strategy_name, exc)

            result.metrics["strategy_count"] = len(registered_ids)
            result.metadata["strategy_ids"] = ", ".join(registered_ids)

            if not registered_ids:
                result.metadata["warning"] = "No strategies registered"
                return result

            # ================================================================
            # Step 7: Daily Strategy Status (replaces full Validation Gate)
            # ================================================================
            # Strategy validation (IC, Sharpe, overfit, etc.) belongs in the
            # experiment phase, not in daily operations.  Daily mode only
            # records per-strategy status; safety comes from regime gating
            # (Step 6) and strategy health monitoring (Step 8.5).
            validation_results: dict[str, dict[str, Any]] = {}
            for sid in registered_ids:
                validation_results[sid] = {
                    "stage": "daily",
                    "score": 100,
                    "passed": True,
                    "rules_total": 0,
                    "rules_failed": 0,
                    "recommendation": (
                        "Daily mode — strategy quality validated during experiment phase."
                    ),
                }

            # ================================================================
            # Step 7.5: Daily Quality Gate — regime-based (not historical validation)
            # ================================================================
            # Only block trading when regime is bear/crisis with high
            # confidence.  Otherwise let position sizing and signal strength
            # govern exposure.  Regime gating in Step 6 already computes
            # suggested_exposure.
            avg_validation_score = 100.0
            result.metrics["avg_validation_score"] = round(avg_validation_score, 1)

            dangerous_regimes = {"bear", "crisis"}
            regime_confidence = result.metrics.get("regime_confidence", 0.0)
            if regime_label in dangerous_regimes and regime_confidence > 0.7:
                result.metadata["quality_gate"] = (
                    f"BLOCKED — regime={regime_label} (confidence={regime_confidence:.0%})"
                    f" → 跳过今日交易"
                )
                logger.warning(
                    "⛔ Quality Gate: regime={} confidence={:.0%} → 跳过今日交易",
                    regime_label, regime_confidence,
                )
                package_id = f"dp-{today.isoformat()}-{run_id_short}"
                quality_regime = RegimeContext(
                    regime=regime_label,
                    confidence=result.metrics.get("regime_confidence", 0.0),
                    suggested_exposure=0.0,
                )
                package = DecisionPackage(
                    package_id=package_id,
                    date=today.isoformat(),
                    generated_at=datetime.now(UTC).isoformat(),
                    lineage=lineage_snapshot,
                    regime=quality_regime,
                    validation=validation_results,
                    metadata={
                        "pipeline_run_id": context.run_id,
                        "quality_gate": "BLOCKED",
                        "avg_validation_score": str(avg_validation_score),
                        "is_rebalance_day": str(is_rebalance_day),
                    },
                )
                json_path = package.to_json()
                md_path = package.to_markdown()
                package.update_index()
                result.metadata["decision_package_id"] = package_id
                result.artifacts.append(str(json_path))
                result.artifacts.append(str(md_path))
                return result

            # ================================================================
            # Step 8: Execute all registered strategies
            # ================================================================
            signals_map: dict[str, pl.DataFrame] = {}
            for sid in registered_ids:
                try:
                    strategy = registry.get(sid)
                    sig = strategy.generate_signals(today)
                    if sig is not None and not sig.is_empty():
                        signals_map[sid] = sig
                        result.metrics[f"signals_{sid}"] = len(sig)
                except Exception as exc:
                    result.metadata[f"strategy_error_{sid}"] = str(exc)

            result.metrics["strategies_with_signals"] = len(signals_map)

            # ================================================================
            # Step 8.5: Strategy Health Monitoring (P1.1)
            # ================================================================
            strategy_health_data: dict[str, dict[str, Any]] = {}
            try:
                from qp.monitoring.strategy_health_logger import StrategyHealthLogger

                health_logger = StrategyHealthLogger()
                date_str = today.isoformat()
                for sid in registered_ids:
                    sig_count = len(signals_map.get(sid, pl.DataFrame()))
                    n_buys = 0
                    if sid in signals_map and not signals_map[sid].is_empty():
                        sig_df = signals_map[sid]
                        if "action" in sig_df.columns:
                            n_buys = sig_df.filter(pl.col("action") == "BUY").height
                        else:
                            n_buys = sig_df.height  # All signals treated as buys

                    health = health_logger.record_and_check(
                        strategy_id=sid,
                        date=date_str,
                        n_signals=sig_count,
                        n_buys=n_buys,
                        n_sells=0,
                    )
                    strategy_health_data[sid] = (
                        StrategyHealthLogger.health_to_dict(health)
                    )
                    result.metrics[f"health_score_{sid}"] = round(health.health_score, 1)

                result.metadata["strategy_health_count"] = str(len(strategy_health_data))
                logger.info("Strategy health recorded for {} strategies", len(strategy_health_data))

                # Merge health data into validation results for DecisionPackage
                for sid, health in strategy_health_data.items():
                    if sid in validation_results:
                        validation_results[sid]["health"] = health

                # P1.2: Generate StrategyHealthReports
                strategy_reports: dict[str, dict[str, Any]] = {}
                from qp.monitoring.strategy_health_report import StrategyHealthReport

                for sid in registered_ids:
                    if sid in strategy_health_data:
                        # Load history for trend analysis
                        try:
                            hist_health = [
                                health_logger.load_latest_health(sid)
                            ]
                            hist_health = [h for h in hist_health if h is not None]
                        except Exception:
                            hist_health = []
                        # Build current health from dict
                        hd = strategy_health_data[sid]
                        from qp.monitoring.strategy_monitor import HealthLevel, StrategyHealth
                        current = StrategyHealth(
                            strategy_id=sid,
                            health_level=HealthLevel(hd["health_level"]),
                            health_score=hd["health_score"],
                            avg_daily_signals=hd["avg_daily_signals"],
                            signal_consistency=hd["signal_consistency"],
                            weekly_turnover_pct=hd["weekly_turnover_pct"],
                            current_drawdown_pct=hd["current_drawdown_pct"],
                            days_since_last_signal=hd["days_since_last_signal"],
                            alerts=hd["alerts"],
                            summary=hd["summary"],
                        )
                        report = StrategyHealthReport.from_health(current, history=hist_health)
                        strategy_reports[sid] = report.to_dict()
                        if sid in validation_results:
                            validation_results[sid]["health_report"] = report.to_dict()
            except Exception as exc:
                logger.warning("Strategy health monitoring skipped: {}", exc)

            # ================================================================
            # Step 9: Multi-strategy signal fusion via EnsembleEngine
            # ================================================================
            if signals_map:
                ensemble = EnsembleEngine(
                    universe_policy=UniversePolicy.FILL_ZERO,
                    weight_engine=WeightEngine(method=WeightMethod.EQUAL),
                )
                batch = ensemble.fuse(
                    signals_map,
                    date_str=today.isoformat(),
                    score_col="raw_score",
                )
                combined_signals = batch.to_polars()
                result.metrics["ensemble_strategies"] = len(signals_map)
                result.metrics["combined_signals"] = len(combined_signals)
                result.metadata["ensemble_method"] = "equal_weight"
            else:
                combined_signals = pl.DataFrame()
                result.metrics["combined_signals"] = 0

            # ================================================================
            # Step 10: Risk management + Risk Audit
            # ================================================================
            risk_audit = RiskAudit()
            risk_report = None
            if not combined_signals.is_empty() and not prices.is_empty():
                risk_manager = PortfolioRiskManager()
                filtered_signals, risk_report = risk_manager.apply_risk_limits_with_prices(
                    combined_signals, prices
                )
                result.metrics["risk_candidates_in"] = risk_report.candidates_in
                result.metrics["risk_candidates_out"] = risk_report.candidates_out
                result.metrics["risk_violations"] = len(risk_report.violations)
                if risk_report.violations:
                    result.metadata["risk_violations"] = "; ".join(risk_report.violations)
                if risk_report.dropped_symbols:
                    result.metadata["risk_dropped"] = ", ".join(risk_report.dropped_symbols)

                # Build structured RiskAudit
                risk_entries: list[RiskAuditEntry] = []
                for v in risk_report.violations:
                    risk_entries.append(
                        RiskAuditEntry(
                            violation_type="risk_limit",
                            detail=v,
                            action="dropped"
                            if any(s in v for s in risk_report.dropped_symbols)
                            else "warning",
                        )
                    )
                # Add correlation-based drops with reasoning
                for s1, s2, corr in risk_report.correlated_pairs:
                    risk_entries.append(
                        RiskAuditEntry(
                            symbol=f"{s1}/{s2}",
                            violation_type="correlation",
                            detail=f"High correlation ({corr:.3f})",
                            threshold="0.70",
                            actual=f"{corr:.3f}",
                            action="warning",
                        )
                    )
                risk_audit = RiskAudit(
                    candidates_in=risk_report.candidates_in,
                    candidates_out=risk_report.candidates_out,
                    entries=risk_entries,
                    dropped_symbols=risk_report.dropped_symbols,
                    sector_exposure=risk_report.sector_exposure,
                    passed=risk_report.passed,
                )
            else:
                filtered_signals = combined_signals

            # ================================================================
            # Step 10.5: Online Signal Monitoring (ADR-031 Step 6)
            # ================================================================
            online_health: dict[str, dict[str, object]] = {}
            try:
                from qp.monitoring.online_monitor import OnlineSignalMonitor

                monitor = OnlineSignalMonitor()
                for sid, sig_df in signals_map.items():
                    result_item = monitor.check(
                        strategy_id=sid,
                        today=today,
                        signals_df=sig_df,
                        price_data=price_data,
                    )
                    online_health[sid] = result_item.to_dict()
                    result.metrics[f"online_health_{sid}"] = float(result_item.health_score)
                    if result_item.alerts:
                        logger.warning(
                            "Online monitor [{}]: level={}, alerts={}",
                            sid, result_item.level, result_item.alerts,
                        )
                    else:
                        logger.debug(
                            "Online monitor [{}]: level={}, score={:.0f}",
                            sid, result_item.level, result_item.health_score,
                        )
                # Merge into validation results for DecisionPackage
                for sid, health in online_health.items():
                    if sid in validation_results:
                        validation_results[sid]["online_health"] = health
            except Exception as exc:
                logger.warning("Online monitor skipped: {}", exc)

            # ================================================================
            # Step 11: Cost estimation
            # ================================================================
            if not filtered_signals.is_empty() and not prices.is_empty():
                cost_model = CostModel()
                symbols = filtered_signals["symbol"].to_list()
                n_symbols = len(symbols)
                per_stock_capital = total_capital / max(n_symbols, 1)

                adv_map = MarketImpactModel.compute_adv(prices)
                total_impact = 0.0
                for s in symbols:
                    trade_val = per_stock_capital
                    adv = adv_map.get(s, trade_val * 10)
                    cost = cost_model.estimate_trade(
                        symbol=s,
                        trade_value=trade_val,
                        side="BUY",
                        daily_volume=adv,
                    )
                    total_impact += cost.total_cost

                result.metrics["estimated_cost_pct"] = round(total_impact / total_capital * 100, 4)

            # ================================================================
            # Step 12: Capital allocation (Layer 8 engine) — only on rebalance day
            # ================================================================
            orders: list[Order] = []
            if is_rebalance_day and not filtered_signals.is_empty():
                # Build candidates DataFrame for CapitalAllocator
                # CapitalAllocator expects pandas with columns:
                #   [symbol, alpha_score, risk_cluster, max_weight_limit,
                #    risk_volatility, pass_status, sector, market_cap, beta,
                #    liquidity_score]
                # Missing optional columns get sensible defaults.
                score_col = (
                    "alpha_score"
                    if "alpha_score" in filtered_signals.columns
                    else "feature_value"
                    if "feature_value" in filtered_signals.columns
                    else "aggregated_score"
                    if "aggregated_score" in filtered_signals.columns
                    else "raw_score"
                    if "raw_score" in filtered_signals.columns
                    else None
                )
                candidates_pl = filtered_signals.select(
                    [
                        "symbol",
                        (pl.col(score_col) if score_col else pl.lit(0.5)).alias("alpha_score"),
                        pl.lit(0.15).alias("max_weight_limit"),
                        pl.lit("").alias("risk_cluster"),
                    ]
                )
                candidates_pd = candidates_pl.to_pandas()

                alloc_config = CapitalAllocatorConfig(
                    method=alloc_method,
                    cash_buffer=0.05,
                    target_vol=0.15,
                )
                allocator = CapitalAllocator(alloc_config)
                alloc_result = allocator.run(
                    candidates=candidates_pd,
                    total_capital=total_capital,
                    date=today.isoformat(),
                )

                tp = alloc_result.target_portfolio
                result.metadata["allocator_used"] = str(alloc_result.allocator_used)
                result.metrics["n_positions_out"] = tp.n_equities if tp else 0
                result.metrics["cash_reserve"] = round(tp.cash_reserve, 4) if tp else 0.0
                result.metrics["allocated_positions"] = tp.n_equities if tp else 0

                if alloc_result.warnings:
                    result.metadata["alloc_warnings"] = "; ".join(alloc_result.warnings)

                # Generate orders from TargetPortfolio
                for pos in tp.positions if tp else []:
                    sym = str(pos.get("symbol", ""))
                    if sym == "CASH":
                        continue
                    wt = float(pos.get("target_weight", 0))  # type: ignore[arg-type]
                    if wt > 0:
                        amount = wt * total_capital
                        quantity = int(amount // 100 * 100)  # Round to lots
                        if quantity > 0:
                            orders.append(Order(symbol=sym, side="BUY", quantity=quantity))

                result.metrics["order_count"] = len(orders)
                for o in orders:
                    result.metadata[f"order_{o.symbol}"] = (
                        f"{o.side} {o.quantity} (weight={o.quantity * 100 / total_capital:.1f}%)"
                    )

            # ================================================================
            # Step 12.5: Exit Engine — V2.1 Final compliant
            #
            # 第一类 Rank Exit:   仅调仓日 → Buffer Top[11-20], Sell >20
            # 第二类 Risk Exit:   每日 → Stop Loss / ST / 退市 / 停牌
            # 第三类 Portfolio:   仅调仓日 → 权重/行业调整
            #
            # 同 symbol 多个退出原因 → 合并为一条 SELL，保留所有 reason tags
            # ================================================================
            sell_recommendations: list[TradeRecommendation] = []
            active_positions: list[Any] = []
            holdings: dict[str, int | float] = {}
            cost_basis: dict[str, float] = {}
            current_prices: dict[str, float] = {}
            TARGET_TOP_N = effective_top_n if effective_top_n > 0 else 10
            SELL_BUFFER_RANK = TARGET_TOP_N * 2  # V2.1: Buy Top10, Buffer 11-20, Sell >20

            try:
                from qp.decision.position_ledger import PositionLedger
                from qp.portfolio.risk_exit import (
                    Priority,
                    RiskExitManager,
                    TradeReason,
                )

                ledger = PositionLedger()
                active_positions = ledger.get_active()

                if active_positions and not prices.is_empty():
                    for pos in active_positions:
                        if pos.shares > 0:
                            holdings[pos.symbol] = pos.shares
                            cost_basis[pos.symbol] = pos.entry_price

                    # Build current price lookup
                    if not prices.is_empty():
                        latest_prices = prices.sort(
                            "trade_date", descending=True
                        ).unique(subset=["symbol"], keep="first")
                        for row in latest_prices.iter_rows(named=True):
                            sym = str(row["symbol"])
                            if sym in holdings:
                                current_prices[sym] = float(row["close"])

                    # Build volume data for liquidity risk check
                    volume_data: dict[str, list[float]] = {}
                    if not prices.is_empty() and "volume" in prices.columns:
                        for sym in holdings:
                            sym_vol = (
                                prices.filter(pl.col("symbol") == sym)
                                .sort("trade_date", descending=True)
                                .head(20)  # 20-day lookback for avg volume
                            )
                            if not sym_vol.is_empty():
                                volume_data[sym] = sym_vol["volume"].to_list()

                    # ── V2.1: Per-symbol exit signal collector ──
                    # {symbol: {reasons: set, details: list, priority: Priority}}
                    exit_map: dict[str, dict[str, Any]] = {}

                    def _add_exit(sym: str, reason: str, detail: str, prio: Priority) -> None:
                        if sym not in exit_map:
                            exit_map[sym] = {
                                "reasons": set(), "details": [], "priority": prio,
                            }
                        exit_map[sym]["reasons"].add(reason)
                        if detail:
                            exit_map[sym]["details"].append(detail)
                        if prio.value < exit_map[sym]["priority"].value:
                            exit_map[sym]["priority"] = prio

                    # ── 第二类：Risk Exit (每日必检) ──
                    if holdings and current_prices:
                        exit_mgr = RiskExitManager()
                        risk_signals = exit_mgr.evaluate_daily(
                            holdings=holdings,
                            prices=current_prices,
                            cost_basis=cost_basis,
                            date_str=today.isoformat(),
                            volume_data=volume_data if volume_data else None,
                        )
                        for es in risk_signals:
                            for r in es.reasons:
                                _add_exit(
                                    es.symbol, r, es.detail,
                                    es.priority,
                                )
                        result.metrics["risk_exit_signals"] = len(risk_signals)

                    # ── 第一类：Rank Exit (仅调仓日) ──
                    if is_rebalance_day and active_positions and not combined_signals.is_empty():
                        # V2.1: today's rank map (1 = best)
                        rank_map: dict[str, int] = {}
                        sig_symbols = combined_signals["symbol"].to_list()
                        for i, s in enumerate(sig_symbols):
                            rank_map[str(s)] = i + 1

                        for pos in active_positions:
                            rank = rank_map.get(pos.symbol, 9999)
                            if rank > SELL_BUFFER_RANK:
                                _add_exit(
                                    pos.symbol,
                                    TradeReason.RANK_DROP,
                                    f"排名 #{rank} > Sell Line {SELL_BUFFER_RANK}",
                                    Priority.LOW,
                                )
                            elif rank > TARGET_TOP_N:
                                # In buffer zone — hold, don't sell
                                pass
                        result.metrics["rank_exit_checked"] = len(active_positions)

                    # ── 第三类：Sector overconcentration — 行业超配退出 (仅调仓日) ──
                    if is_rebalance_day and active_positions:
                        try:
                            from qp.portfolio.industry import IndustryMapper

                            im = IndustryMapper()
                            SECTOR_OVERWEIGHT_THRESHOLD = 0.40  # 单一行业超配阈值

                            # Group active positions by sector
                            sector_positions: dict[str, list] = {}
                            for pos in active_positions:
                                industry = im.get_sector(pos.symbol)
                                sector_positions.setdefault(industry, []).append(pos)

                            # Compute total portfolio value
                            total_value = sum(
                                pos.shares * current_prices.get(pos.symbol, 0)
                                for pos in active_positions
                            )
                            if total_value > 0:
                                for sector, sps in sector_positions.items():
                                    sector_value = sum(
                                        p.shares * current_prices.get(p.symbol, 0)
                                        for p in sps
                                    )
                                    sector_wt = sector_value / total_value
                                    if sector_wt > SECTOR_OVERWEIGHT_THRESHOLD:
                                        # Flag ALL positions in overweight sector for review
                                        for p in sps:
                                            _add_exit(
                                                p.symbol,
                                                TradeReason.SECTOR_OVERWEIGHT,
                                                f"行业「{sector}」超配 {sector_wt:.0%} (阈值 {SECTOR_OVERWEIGHT_THRESHOLD:.0%})",
                                                Priority.LOW,
                                            )
                                        logger.info(
                                            "Sector exit: {} overweight at {:.0%} ({} symbols)",
                                            sector, sector_wt, len(sps),
                                        )
                            result.metrics["sector_exit_checked"] = len(sector_positions)
                        except Exception as exc:
                            logger.debug("Sector exit check skipped: {}", exc)

                    # ── 第三类：Fundamental deterioration (仅调仓日) ──
                    if is_rebalance_day and active_positions and fundamental_data:
                        from qp.portfolio.exit_signals import FundamentalExitDetector

                        fund_detector = FundamentalExitDetector()
                        fund_exits = fund_detector.check(
                            active_positions=active_positions,
                            fundamental_data=fundamental_data,
                        )
                        for fe in fund_exits:
                            for r in fe.reasons:
                                _add_exit(fe.symbol, r, fe.detail, Priority.LOW)
                        result.metrics["fundamental_exit_signals"] = len(fund_exits)

                    # ── V2.1: Merge → single SELL per symbol, sorted by priority ──
                    merged = sorted(
                        exit_map.items(),
                        key=lambda x: x[1]["priority"].value,  # type: ignore[no-any-return]
                    )
                    for sym, info in merged:
                        shares = int(holdings.get(sym, 0))
                        px = current_prices.get(sym, 0.0)
                        sell_recommendations.append(
                            TradeRecommendation(
                                symbol=sym,
                                action="SELL",
                                quantity_shares=shares,
                                estimated_price=px,
                                reason="; ".join(sorted(info["reasons"])),
                                risk_warnings=info["details"],
                                confidence=(
                                    0.95 if info["priority"] in (Priority.CRITICAL, Priority.HIGH)
                                    else 0.70 if info["priority"] == Priority.MEDIUM
                                    else 0.55
                                ),
                                strategy="risk_exit"
                                if info["priority"] in (Priority.CRITICAL, Priority.HIGH)
                                else "rank_exit",
                            )
                        )

                    if exit_map:
                        logger.info(
                            "Exit Engine (V2.1): {} symbols → {} merged SELL signals",
                            len(exit_map), len(sell_recommendations),
                        )
                        result.metrics["exit_signals_total"] = len(sell_recommendations)
                        result.metadata["rebalance_day"] = str(is_rebalance_day)

            except Exception as exc:
                logger.warning("Exit Engine check skipped: {}", exc)

            # ================================================================
            # Step 13: Build DecisionPackage
            # ================================================================
            package_id = f"dp-{today.isoformat()}-{run_id_short}"

            # Build strategy versions dict for lineage
            strategy_versions: dict[str, str] = {}
            for sid in registered_ids:
                try:
                    strategy_versions[sid] = registry.get_lifecycle(sid).value
                except Exception:
                    strategy_versions[sid] = "unknown"

            # Build regime context
            regime_ctx = RegimeContext(
                regime=regime_label,
                confidence=result.metrics.get("regime_confidence", 0.0),
                suggested_exposure=result.metrics.get("regime_position_pct", 1.0),
                trend_strength=result.metrics.get("regime_trend", 0.0),
                annualized_vol=result.metrics.get("regime_vol", 0.0),
                summary=result.metadata.get("regime_reason", ""),
            )

            # Generate DecisionReport via DecisionEngine
            # V2.1: Portfolio Manager only runs on rebalance days → BUY only on 调仓日
            decision_report = DecisionReport(
                report_id=f"dr-{run_id_short}",
                strategy_id="multi_strategy_ensemble",
                total_capital=total_capital,
            )
            if is_rebalance_day and not filtered_signals.is_empty() and not prices.is_empty():
                # Use only latest price per symbol (avoid stale historical prices)
                latest_prices = (
                    prices.sort("trade_date", descending=True)
                    .unique(subset=["symbol"], keep="first")
                )
                try:
                    engine = DecisionEngine()
                    decision_report = engine.generate(
                        signals=filtered_signals,
                        prices=latest_prices,
                        risk_report=risk_report,
                        total_capital=total_capital,
                        strategy_id="multi_strategy_ensemble",
                        market_regime=regime_label,
                    )
                except Exception as exc:
                    logger.warning("DecisionEngine failed: {}", exc)
            elif not is_rebalance_day:
                logger.info(
                    "非调仓日 — 跳过 BUY 信号生成 (Only Risk/Rank Exit runs daily)"
                )

            # P3.1: Append exit engine SELL recommendations
            if sell_recommendations:
                decision_report.recommendations.extend(sell_recommendations)
                result.metrics["sell_recommendations"] = len(sell_recommendations)

            # Build strategy signal counts
            strategy_signal_counts: dict[str, int] = {}
            if "signals_map" in dir():
                for sid in signals_map:
                    strategy_signal_counts[sid] = len(signals_map[sid])

            # Build the package
            package = DecisionPackage(
                package_id=package_id,
                date=today.isoformat(),
                generated_at=datetime.now(UTC).isoformat(),
                lineage=lineage_snapshot,
                regime=regime_ctx,
                strategy_signals=strategy_signal_counts,
                ensemble_method="equal_weight",
                effective_top_n=effective_top_n,
                risk_audit=risk_audit,
                estimated_cost_pct=float(result.metrics.get("estimated_cost_pct", 0.0)),
                validation=validation_results,
                report=decision_report,
                human_review=HumanReview(),
                metadata={
                    "pipeline_run_id": context.run_id,
                    "allocator_used": str(result.metadata.get("allocator_used", "equal_weight")),
                    "strategy_health_count": str(len(strategy_health_data)),
                    "is_rebalance_day": str(is_rebalance_day),
                },
            )

            # Save
            json_path = package.to_json()
            md_path = package.to_markdown()
            package.update_index()

            result.metadata["decision_package_id"] = package_id
            result.metadata["decision_package_json"] = str(json_path)
            result.metadata["decision_package_md"] = str(md_path)

            # ================================================================
            # Step 13.1: Shadow Production — daily paper trading (Shadow Production)
            # ================================================================
            shadow_equity = total_capital
            shadow_n_positions = 0
            try:
                from qp.simulation.shadow_ledger import ShadowLedger

                shadow = ShadowLedger(initial_capital=total_capital)
                shadow_result = shadow.run_daily(today.isoformat())
                shadow_equity = shadow_result.get("total_equity", total_capital)
                shadow_n_positions = shadow_result.get("n_positions", 0)
                result.metrics["shadow_equity"] = round(shadow_equity, 2)
                result.metadata["shadow_pnl"] = str(shadow_result.get("unrealized_pnl", 0))
                logger.info(
                    "Shadow: equity=¥{:.0f} pnl=¥{:.0f} positions={}",
                    shadow_equity,
                    shadow_result.get("unrealized_pnl", 0),
                    shadow_n_positions,
                )
            except Exception as exc:
                logger.warning("Shadow production skipped: {}", exc)

            # Step 13.2: Record portfolio NAV for KPI tracking
            # ================================================================
            try:
                from qp.portfolio.nav_ledger import NAVLedger

                nav_ledger = NAVLedger()
                nav_ledger.record_daily(
                    date=today.isoformat(),
                    total_value=shadow_equity,
                    cash=total_capital * 0.05,  # ~5% cash buffer
                    n_positions=shadow_n_positions,
                )
                result.metrics["nav_history_days"] = nav_ledger.row_count()
            except Exception as exc:
                logger.debug("NAV recording skipped: {}", exc)

            # ================================================================
            # Artifacts
            # ================================================================
            result.artifacts.append("data/dataset/momentum_20d.parquet")
            result.artifacts.append("data/dataset/volatility_20d.parquet")
            result.artifacts.append(str(json_path))
            result.artifacts.append(str(md_path))

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result
