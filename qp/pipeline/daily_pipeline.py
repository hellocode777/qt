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
        if (
            pdf is not None
            and not pdf.is_empty()
            and date_col in pdf.columns
            and "close" in pdf.columns
        ):
            frames.append(pdf.select([date_col, "close"]))

    if not frames:
        return pl.DataFrame()

    all_closes = pl.concat(frames, how="vertical")
    return (
        all_closes.group_by(date_col)
        .agg(pl.col("close").mean().alias("close"))
        .sort(date_col)
        .rename({date_col: "date"})
    )


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
                # PIT fix (2026-08-25): fundamentals_latest.parquet already
                # carries the REAL publish_date — do NOT alias report_date
                # over it (that leaked unpublished financials into exit logic).
                result[str(sym)] = sub

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
            # --force-rebalance 可强制当调仓日处理（建仓/手动重平衡用）
            force_rebalance = bool(context.parameters.get("force_rebalance", False))
            is_rebalance_day = force_rebalance or today.day <= 5

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
            # Step 1.5: Factor Calculator — produce factor_values_daily.parquet
            # ================================================================
            skip_factor_calc = bool(context.parameters.get("skip_factor_calc", False))
            if not skip_factor_calc:
                try:
                    from qp.pipeline.factor_calc_pipeline import FactorCalcPipeline

                    factor_calc = FactorCalcPipeline()
                    factor_result = factor_calc.run(context)
                    if factor_result.status == PipelineStatus.FAILED:
                        logger.warning(
                            "Factor calculator failed (non-fatal): {}",
                            factor_result.errors,
                        )
                    else:
                        result.metrics.update(
                            {f"factorcalc_{k}": v for k, v in factor_result.metrics.items()}
                        )
                        result.artifacts.extend(factor_result.artifacts)
                        logger.info(
                            "FactorCalcPipeline: {} rows, {} factors → {}",
                            factor_result.metrics.get("new_rows", 0),
                            factor_result.metrics.get("n_factors", 0),
                            factor_result.artifacts[0] if factor_result.artifacts else "N/A",
                        )
                except Exception as e:
                    logger.warning("Factor calculator unavailable (non-fatal): {}", e)

            # ================================================================
            # Step 1.6: Incremental factor health refresh (DP-002 v4)
            #   - Appends new daily IC days to factor_ic_series.parquet
            #   - Logs fresh health snapshot to factor_health.parquet
            #   - Lightweight (seconds), dedup-safe; non-fatal on failure.
            # ================================================================
            try:
                from qp.monitoring.factor_health_pipeline import FactorHealthPipeline

                fh_pipeline = FactorHealthPipeline()
                fh_result = fh_pipeline.run_incremental()
                if fh_result.status == PipelineStatus.SUCCESS:
                    logger.info(
                        "FactorHealth incremental: {} factors updated, {} skipped",
                        fh_result.metrics.get("n_factors_updated", 0),
                        fh_result.metrics.get("n_factors_skipped", 0),
                    )
                else:
                    logger.warning(
                        "FactorHealth incremental PARTIAL/FAILED: {}",
                        fh_result.errors[:3],
                    )
            except Exception as e:
                logger.warning("Factor health refresh unavailable (non-fatal): {}", e)

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
            # Strategy auto-discovery (implemented): experiments that pass the
            # validation gate auto-register with the StrategyRegistry
            # (multifactor_pipeline._record_experiment).  Manual approval
            # (qp strategy approve) promotes a strategy to APPROVED; the daily
            # pipeline discovers APPROVED strategies from the Registry below —
            # no hardcoding.  See ADR-031 + docs/workflow.md §3.
            registry = StrategyRegistry()
            registered_ids: list[str] = []

            # ADR-031: discover strategies from Registry (auto-populated by
            # experiments that passed Gate).  Weights are read from Registry
            # metadata, NOT from StrategyConfig — the Registry is the single
            # source of truth for frozen production weights.
            validated_strategies: list[str] = []

            # Strict policy (A): ONLY APPROVED strategies run in production.
            # Experiments auto-register RESEARCH strategies — they must be
            # manually approved (qp strategy approve) before the daily
            # pipeline will trade them.  No APPROVED → no strategy runs and
            # the operator is alerted; no silent fallback to research.
            for sid in registry.list_strategies():
                try:
                    if registry.get_lifecycle(sid) == StrategyLifecycle.APPROVED:
                        validated_strategies.append(sid)
                except KeyError:
                    pass

            if not validated_strategies:
                logger.warning(
                    "无 APPROVED 策略，跳过策略执行。请人工批准: "
                    "qp strategy approve <strategy_id> --by <name>"
                )
                result.metadata["warning"] = (
                    "No APPROVED strategies — daily pipeline skipped. "
                    "Run: qp strategy approve <strategy_id> --by <name>"
                )
            today_str = today.isoformat()

            from qp.strategy.config import get_strategy_config
            from qp.strategy.multifactor import compute_today_signals

            logger.info(
                "Daily pipeline — loaded from Registry: {}",
                ", ".join(validated_strategies),
            )

            for strategy_name in validated_strategies:
                try:
                    # ADR-031: read FROZEN weights/parameters from the
                    # ApprovedStrategy snapshot (approve-time freeze), NOT
                    # the mutable StrategyMeta — otherwise a later set_meta
                    # would silently change what production runs.
                    registry_meta = registry.get_meta(strategy_name)
                    approved: Any = registry.get_approved(strategy_name)
                    if approved is not None:
                        weights = dict(approved.weights)
                        params = dict(approved.parameters)
                    else:
                        weights = dict(registry_meta.weights) if registry_meta.weights else {}
                        params = dict(registry_meta.parameters) if registry_meta.parameters else {}

                    if not weights:
                        # Fallback: no weights in snapshot/meta → read from config
                        cfg = get_strategy_config(strategy_name)
                        weights = dict(cfg.factors)

                    logger.info(
                        "   {} — {} factors (today-only scoring{})",
                        strategy_name,
                        len(weights),
                        " [from frozen snapshot]" if approved is not None else " [from Registry]",
                    )

                    # Parameters: prefer frozen snapshot, fall back to meta
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
                        # ADR-031 修复 (2026-08-12): 保留现有 lifecycle，不硬编码 RESEARCH。
                        # 之前每次 daily run 都会把磁盘上已 APPROVED 的策略覆盖回
                        # RESEARCH（register() 无条件写 _lifecycles[sid]，新进程
                        # _strategies 为空不会抛错），导致 approve 后一跑 daily 就
                        # 掉线、下次 pipeline 判定"无 APPROVED 策略"跳过执行。
                        lifecycle=registry.get_lifecycle(strategy_name),
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
                    regime_label,
                    regime_confidence,
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
                    strategy_health_data[sid] = StrategyHealthLogger.health_to_dict(health)
                    result.metrics[f"health_score_{sid}"] = round(health.health_score, 1)

                result.metadata["strategy_health_count"] = str(len(strategy_health_data))
                logger.info(
                    "Strategy health recorded for {} strategies",
                    len(strategy_health_data),
                )

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
                            hist_health = [health_logger.load_latest_health(sid)]
                            hist_health = [h for h in hist_health if h is not None]
                        except Exception:
                            hist_health = []
                        # Build current health from dict
                        hd = strategy_health_data[sid]
                        from qp.monitoring.strategy_monitor import (
                            HealthLevel,
                            StrategyHealth,
                        )

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
            strategy_exposure_scale = 1.0
            if signals_map:
                # Auto-deweighting: consume retrain signals (IC decay / PSI
                # drift / model staleness) emitted by KillSwitchPipeline.
                # A degraded strategy gets a reduced share in the ensemble
                # AND a reduced capital allocation in Step 12 — the
                # REDUCE_WEIGHT feedback loop (L11-1.7).  Signals older
                # than the lookback window are ignored (no permanent
                # deweighting from stale alarms).
                from qp.monitoring.retrain_signal import load_weight_scales

                weight_scales = load_weight_scales(strategy_ids=list(signals_map.keys()))
                degraded = {sid: s for sid, s in weight_scales.items() if s < 1.0}
                if degraded:
                    logger.warning(
                        "⚠️ Auto-deweight: {}",
                        {sid: f"{s:.0%}" for sid, s in degraded.items()},
                    )
                    result.metadata["deweighted_strategies"] = "; ".join(
                        f"{sid}={s:.2f}" for sid, s in degraded.items()
                    )

                n = max(len(signals_map), 1)
                raw_weights = {sid: (1.0 / n) * weight_scales.get(sid, 1.0) for sid in signals_map}
                wsum = sum(raw_weights.values()) or 1.0
                fixed_weights = {k: v / wsum for k, v in raw_weights.items()}

                # Conservative portfolio-level exposure: any degraded strategy
                # scales down the total capital deployed today.
                strategy_exposure_scale = min(weight_scales.get(sid, 1.0) for sid in signals_map)
                result.metrics["strategy_exposure_scale"] = round(strategy_exposure_scale, 4)

                ensemble = EnsembleEngine(
                    universe_policy=UniversePolicy.FILL_ZERO,
                    weight_engine=WeightEngine(method=WeightMethod.EQUAL),
                )
                batch = ensemble.fuse(
                    signals_map,
                    date_str=today.isoformat(),
                    score_col="raw_score",
                    fixed_weights=fixed_weights,
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
                # 审计口径与执行对齐：allocator 用 alloc_capital =
                # total_capital × regime敞口 × 策略健康 做 1/N 分配，
                # 审计也按同样缩放后的权重判断单仓/行业上限，
                # 避免 1/5=20% > 8% 的假阳性（实际 sideways_down 时每只 ~6%）。
                risk_scale = suggested_position_pct * strategy_exposure_scale
                filtered_signals, risk_report = risk_manager.apply_risk_limits_with_prices(
                    combined_signals, prices, weight_scale=risk_scale
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
                            sid,
                            result_item.level,
                            result_item.alerts,
                        )
                    else:
                        logger.debug(
                            "Online monitor [{}]: level={}, score={:.0f}",
                            sid,
                            result_item.level,
                            result_item.health_score,
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
            tp: Any = None
            alloc_capital = total_capital
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
                        pl.lit(0.08).alias("max_weight_limit"),
                        pl.lit("").alias("risk_cluster"),
                    ]
                )
                candidates_pd = candidates_pl.to_pandas()

                # 按 regime 建议敞口缩放分配资本（如 sideways_down → 30%）。
                # 再乘策略健康系数（Step 9 auto-deweight）：IC 衰减被降权的
                # 策略 → 自动减少投入资金，而不是等人工干预。
                # 不缩放时 equal_weight 对 5 只候选会给 20%/只，超过风控 8% 上限。
                alloc_capital = total_capital * suggested_position_pct * strategy_exposure_scale
                alloc_config = CapitalAllocatorConfig(
                    method=alloc_method,
                    cash_buffer=0.05,
                    target_vol=0.15,
                )
                allocator = CapitalAllocator(alloc_config)
                alloc_result = allocator.run(
                    candidates=candidates_pd,
                    total_capital=alloc_capital,
                    date=today.isoformat(),
                )

                tp = alloc_result.target_portfolio
                result.metadata["allocator_used"] = str(alloc_result.allocator_used)
                result.metadata["alloc_capital"] = (
                    f"{alloc_capital:.0f} (regime exposure {suggested_position_pct:.0%} "
                    f"× strategy health {strategy_exposure_scale:.0%})"
                )
                result.metrics["n_positions_out"] = tp.n_equities if tp else 0
                result.metrics["cash_reserve"] = round(tp.cash_reserve, 4) if tp else 0.0
                result.metrics["allocated_positions"] = tp.n_equities if tp else 0

                if alloc_result.warnings:
                    result.metadata["alloc_warnings"] = "; ".join(alloc_result.warnings)

                # Generate orders from TargetPortfolio
                # 最新收盘价 lookup（金额 → 股数）
                px_map: dict[str, float] = {}
                if not prices.is_empty():
                    latest_px = (
                        prices.sort("trade_date", descending=True)
                        .unique(subset=["symbol"], keep="first")
                        .select(["symbol", "close"])
                    )
                    px_map = {
                        str(r["symbol"]): float(r["close"]) for r in latest_px.iter_rows(named=True)
                    }

                for pos in tp.positions if tp else []:
                    sym = str(pos.get("symbol", ""))
                    if sym == "CASH":
                        continue
                    wt = float(pos.get("target_weight", 0))  # type: ignore[arg-type]
                    if wt > 0:
                        amount = wt * alloc_capital
                        px = px_map.get(sym, 0.0)
                        if px <= 0:
                            continue
                        quantity = int(amount / px // 100 * 100)  # 金额→股数→整手
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
                        latest_prices = prices.sort("trade_date", descending=True).unique(
                            subset=["symbol"], keep="first"
                        )
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
                                "reasons": set(),
                                "details": [],
                                "priority": prio,
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
                                    es.symbol,
                                    r,
                                    es.detail,
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
                                        p.shares * current_prices.get(p.symbol, 0) for p in sps
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
                                            sector,
                                            sector_wt,
                                            len(sps),
                                        )
                            result.metrics["sector_exit_checked"] = len(sector_positions)
                        except Exception as exc:
                            logger.debug("Sector exit check skipped: {}", exc)

                    # ── 第三类：Fundamental deterioration (仅调仓日) ──
                    # PIT: 只使用 as_of_date 前已公布的财报（publish_date <= today）
                    if is_rebalance_day and active_positions and fundamental_data:
                        from qp.portfolio.exit_signals import FundamentalExitDetector

                        fund_detector = FundamentalExitDetector()
                        fund_exits = fund_detector.check(
                            active_positions=active_positions,
                            fundamental_data=fundamental_data,
                            as_of_date=today.isoformat(),
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
                                    0.95
                                    if info["priority"] in (Priority.CRITICAL, Priority.HIGH)
                                    else 0.70
                                    if info["priority"] == Priority.MEDIUM
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
                            len(exit_map),
                            len(sell_recommendations),
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
                latest_prices = prices.sort("trade_date", descending=True).unique(
                    subset=["symbol"], keep="first"
                )
                try:
                    from dataclasses import replace

                    engine = DecisionEngine()
                    # 用 allocator 的实际目标权重 + 敞口资本，否则 recommendations
                    # 会按满仓等权 20% 计算股数（与 allocator orders 脱节，
                    # approve 时 PositionLedger 建仓会变成满仓）。
                    alloc_weights = {
                        str(pos.get("symbol", "")): float(pos.get("target_weight", 0.0))
                        for pos in (tp.positions if tp else [])
                        if str(pos.get("symbol", "")) != "CASH"
                    }
                    report_risk = (
                        replace(risk_report, position_weights=alloc_weights)
                        if risk_report is not None and alloc_weights
                        else risk_report
                    )
                    decision_report = engine.generate(
                        signals=filtered_signals,
                        prices=latest_prices,
                        risk_report=report_risk,
                        total_capital=alloc_capital,
                        strategy_id="multi_strategy_ensemble",
                        market_regime=regime_label,
                    )
                except Exception as exc:
                    logger.warning("DecisionEngine failed: {}", exc)
            elif not is_rebalance_day:
                logger.info("非调仓日 — 跳过 BUY 信号生成 (Only Risk/Rank Exit runs daily)")

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
            shadow_cash = total_capital
            try:
                from qp.simulation.shadow_ledger import ShadowLedger

                shadow = ShadowLedger(initial_capital=total_capital)
                # 注入刚生成的决策包（避免 simulation 层反向依赖 decision 层）
                shadow_result = shadow.run_daily(today.isoformat(), decision_package=package)
                shadow_equity = shadow_result.get("total_equity", total_capital)
                shadow_n_positions = shadow_result.get("n_positions", 0)
                shadow_cash = shadow_result.get("cash", shadow_equity)
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

                # Benchmark = 上证指数当日收盘（用于 dashboard alpha / 超额）。
                # 拉不到（网络失败/非交易日）时写 None，绝不伪造基准值。
                benchmark_value: float | None = None
                try:
                    from qp.data.dataset.index_provider import get_index_close

                    benchmark_value = get_index_close("sh000001", today.isoformat())
                except Exception as exc:
                    logger.debug("Benchmark close unavailable: {}", exc)

                nav_ledger = NAVLedger()
                nav_ledger.record_daily(
                    date=today.isoformat(),
                    total_value=shadow_equity,
                    cash=shadow_cash,
                    n_positions=shadow_n_positions,
                    benchmark_value=benchmark_value,
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
