"""DailyPipeline — orchestrated end-to-end daily decision pipeline.

Phase 7 upgrade: Data → Feature → Lineage → Regime → Strategy Discovery
    → Validation Gate → Strategy Execution → Ensemble Fusion → Risk Audit
    → Cost → Capital Allocation → DecisionPackage.

Produces a structured DecisionPackage (data/decisions/) with full
lineage, validation, risk audit trail, and human review section.
Backtest has been REMOVED — it belongs in the experiment pipeline.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
from loguru import logger

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
from qp.decision.models import DecisionReport
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
from qp.strategy.loader import StrategyLoader
from qp.strategy.market_regime import MarketRegimeDetector
from qp.strategy.multifactor import MultiFactorStrategy
from qp.strategy.registry import StrategyRegistry
from qp.validation.pipeline import ValidationPipeline, ValidationPipelineConfig


def _load_price_data() -> tuple[dict[str, pl.DataFrame], pl.DataFrame]:
    """Load daily price data and index into strategy-ready format.

    Returns:
        (price_data_by_symbol, flat_prices_df)
        price_data_by_symbol: {code: DataFrame[date, open, high, low, close, volume]}
        flat_prices_df: Full Polars DataFrame for risk/backtest.
    """
    today = date.today()
    path = f"data/dataset/daily_price_{today.isoformat()}.parquet"

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

    In production, this should use actual index data (e.g. 000001.SH).
    """
    if not price_data:
        return pl.DataFrame()

    closes: list[pl.DataFrame] = []
    date_col = "trade_date" if "trade_date" in next(iter(price_data.values())).columns else "date"

    for code, pdf in price_data.items():
        if pdf is None or pdf.is_empty():
            continue
        sub = pdf.select([date_col, "close"]).rename({"close": f"close_{code}"})
        closes.append(sub)

    if not closes:
        return pl.DataFrame()

    # Join all closes on date
    merged = closes[0]
    for df in closes[1:]:
        merged = merged.join(df, on=date_col, how="inner")

    # Average close
    close_cols = [c for c in merged.columns if c.startswith("close_")]
    result = merged.select(
        [
            pl.col(date_col).alias("date"),
            (pl.sum_horizontal([pl.col(c) for c in close_cols]) / len(close_cols)).alias("close"),
        ]
    )
    return result


def _build_valuation_data(price_data: dict[str, pl.DataFrame]) -> dict[str, pl.DataFrame]:
    """Build synthetic valuation data for ValueStrategy from price data.

    In production, this should load actual fundamental data.
    Provides minimal PE/PB proxies so ValueStrategy can run.
    """
    valuation: dict[str, pl.DataFrame] = {}
    for code, pdf in price_data.items():
        if pdf is None or pdf.is_empty():
            continue
        date_col = "trade_date" if "trade_date" in pdf.columns else "date"
        dates = pdf[date_col].to_list()
        # Synthetic valuation: use inverse of return as PE proxy
        valuation[code] = pl.DataFrame(
            {
                "date": dates,
                "PE_TTM": [15.0 + (hash(code) % 30)] * len(dates),
                "PB": [2.0 + (hash(code + "pb") % 5)] * len(dates),
            }
        )
    return valuation


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


def _build_validation_context(
    strategy_id: str,
    price_data: dict[str, pl.DataFrame],
    pipeline_metrics: dict[str, Any],
) -> Any:
    """Build a minimal validation context for the ValidationPipeline.

    Creates a lightweight adapter carrying feature_df, price_df, and
    backtest_metrics — enough for the ValidationPipeline._resolve_context()
    to construct a proper ValidationContext.
    """
    # Build a flat price DataFrame from price_data dict
    frames = [pdf for pdf in price_data.values() if pdf is not None and not pdf.is_empty()]
    price_df = pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    class _ValCtx:
        feature_df: pl.DataFrame | None
        price_df: pl.DataFrame
        signal_df: pl.DataFrame | None
        backtest_metrics: dict[str, float]
        strategy_id: str
        metadata: dict[str, str]

    ctx = _ValCtx()
    ctx.feature_df = None  # Features are computed inline, not pre-loaded
    ctx.price_df = price_df
    ctx.signal_df = None
    ctx.backtest_metrics = {
        "sharpe_ratio": pipeline_metrics.get("sharpe_ratio", 0.0),
        "max_drawdown_pct": pipeline_metrics.get("max_drawdown_pct", 0.0),
        "total_return": pipeline_metrics.get("total_return", 0.0),
    }
    ctx.strategy_id = strategy_id
    ctx.metadata = {
        "strategy_id": strategy_id,
    }
    return ctx


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
        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        try:
            total_capital = context.parameters.get("capital", 1_000_000)
            top_n = context.parameters.get("top_n", 10)
            alloc_method = context.parameters.get("allocator", "equal_weight")
            today = date.today()
            run_id_short = context.run_id[:8] if context.run_id else "unknown"

            # ================================================================
            # Step 1: Data ingestion
            # ================================================================
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

            # Build valuation data for value strategy
            valuation_data = _build_valuation_data(price_data)

            # ================================================================
            # Step 4: Build Lineage Snapshot
            # ================================================================
            lineage_snapshot = _build_lineage_snapshot(price_data)
            result.metadata["dataset_version"] = lineage_snapshot.dataset_version

            # ================================================================
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
            # Step 6: Strategy discovery and registration
            # ================================================================
            registry = StrategyRegistry()
            loader = StrategyLoader()

            strategy_configs: dict[str, dict[str, Any]] = {
                "momentum_v1.0": {
                    "lookback": 60,
                    "variant": "residual",
                    "top_n": effective_top_n,
                    "price_data": price_data,
                },
                "value_v1.0": {
                    "top_n": effective_top_n,
                    "valuation_data": valuation_data,
                },
                "quality_v1.0": {
                    "top_n": effective_top_n,
                },
            }

            # Register with BACKTEST_PASSED lifecycle (no lineage gate required)
            registered_ids = loader.register_all(
                registry,
                package="qp.strategy.strategies",
                configs=strategy_configs,
                lifecycle=StrategyLifecycle.BACKTEST_PASSED,
            )
            result.metrics["strategy_count"] = len(registered_ids)
            result.metadata["strategy_ids"] = ", ".join(registered_ids)

            if not registered_ids:
                result.metadata["warning"] = "No strategies discovered"

            # ================================================================
            # Step 6.5: Direct-register MultiFactorStrategy (15-factor pipeline)
            # ================================================================
            # MultiFactorStrategy pre-computes cross-sectional scores from
            # 15 price/volume factors — too heavyweight for StrategyLoader's
            # config-based discover pattern.  Registered directly here so
            # that experiment-validated multifactor signals flow into the
            # same ensemble as momentum/value/quality.
            try:
                multifactor = MultiFactorStrategy(
                    price_data=price_data,
                    top_n=effective_top_n,
                )
                registry.register(multifactor, lifecycle=StrategyLifecycle.BACKTEST_PASSED)
                registered_ids.append(multifactor.strategy_id)
                result.metrics["strategy_count"] = len(registered_ids)
                result.metadata["strategy_ids"] += f", {multifactor.strategy_id}"
            except Exception as exc:
                result.metadata["multifactor_error"] = str(exc)

            # ================================================================
            # Step 7: Validation Gate — check each registered strategy
            # ================================================================
            validation_results: dict[str, dict[str, Any]] = {}
            for sid in registered_ids:
                try:
                    strategy_lifecycle = registry.get_lifecycle(sid)
                    val_config = ValidationPipelineConfig(
                        stage=strategy_lifecycle.value,
                        strategy_id=sid,
                        require_all_passed=False,
                    )
                    val_pipeline = ValidationPipeline(config=val_config)
                    val_ctx = _build_validation_context(sid, price_data, result.metrics)
                    val_result = val_pipeline.run(val_ctx)
                    validation_results[sid] = {
                        "stage": strategy_lifecycle.value,
                        "score": val_result.metrics.get("validation_score", 0),
                        "passed": val_result.status == PipelineStatus.SUCCESS,
                        "rules_total": val_result.metrics.get("rules_total", 0),
                        "rules_failed": val_result.metrics.get("rules_failed", 0),
                        "recommendation": val_result.metadata.get("recommendation", ""),
                    }
                    if val_result.status == PipelineStatus.FAILED:
                        logger.warning(
                            "Validation Gate: {} FAILED (score={}, {}/{} rules failed)",
                            sid,
                            val_result.metrics.get("validation_score", 0),
                            val_result.metrics.get("rules_failed", 0),
                            val_result.metrics.get("rules_total", 0),
                        )
                except Exception as exc:
                    logger.warning("Validation Gate skipped for {}: {}", sid, exc)
                    validation_results[sid] = {
                        "stage": "unknown",
                        "score": 0,
                        "passed": False,
                        "rules_total": 0,
                        "rules_failed": 0,
                        "recommendation": f"Validation error: {exc}",
                    }

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
            # Step 12: Capital allocation (Layer 8 engine)
            # ================================================================
            orders: list[Order] = []
            if not filtered_signals.is_empty():
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
                summary=result.metadata.get("regime_reason", ""),
            )

            # Generate DecisionReport via DecisionEngine
            decision_report = DecisionReport(
                report_id=f"dr-{run_id_short}",
                strategy_id="multi_strategy_ensemble",
                total_capital=total_capital,
            )
            if not filtered_signals.is_empty() and not prices.is_empty():
                try:
                    engine = DecisionEngine()
                    decision_report = engine.generate(
                        signals=filtered_signals,
                        prices=prices,
                        risk_report=risk_report,
                        total_capital=total_capital,
                        strategy_id="multi_strategy_ensemble",
                        market_regime=regime_label,
                    )
                except Exception as exc:
                    logger.warning("DecisionEngine failed: {}", exc)

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
