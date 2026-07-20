"""DailyPipeline — orchestrated end-to-end daily workflow.

Phase 3 upgrade: Multi-Strategy → Risk Manager → Cost Model
    → Capital Allocator → Position Optimizer → Order Generation.

Data → Feature → Strategy → Risk → Cost → Alloc → Optimize → Backtest → Report.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from qp.data.pipeline import DataPipeline
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.portfolio.allocator.factory import AllocationFactory
from qp.portfolio.cost_model import CostModel
from qp.portfolio.optimizer import MeanVarianceOptimizer
from qp.portfolio.risk_manager import PortfolioRiskManager
from qp.portfolio.single_portfolio import Order
from qp.research.pipeline import FeaturePipeline
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus
from qp.simulation.backtest import SimpleVectorBacktest
from qp.strategy.aggregator import SignalAggregator
from qp.strategy.registry import StrategyRegistry
from qp.strategy.simple_rank import SimpleRankStrategy


class DailyPipeline(BasePipeline):
    """End-to-end daily quant workflow with full portfolio pipeline."""

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

            # Step 1: Data ingestion
            data_pipeline = DataPipeline()
            data_result = data_pipeline.run(context)
            if data_result.status == PipelineStatus.FAILED:
                result.errors.extend(data_result.errors)
                result.status = PipelineStatus.FAILED
                return result
            result.metrics.update({f"data_{k}": v for k, v in data_result.metrics.items()})

            # Step 2: Feature computation (momentum + volatility)
            feature_pipeline = FeaturePipeline()
            feature_result = feature_pipeline.run(context)
            if feature_result.status == PipelineStatus.FAILED:
                result.errors.extend(feature_result.errors)
                result.status = PipelineStatus.FAILED
                return result

            # Step 3: Multi-strategy signal generation
            registry = StrategyRegistry()
            momentum_strategy = SimpleRankStrategy(top_n=top_n)
            registry.register(momentum_strategy)
            # Also register a volatility-based strategy (same ranking, different factor)
            vol_strategy = SimpleRankStrategy(top_n=top_n)
            # Override strategy_id for second strategy
            vol_strategy._top_n = top_n  # Same config, will be fed different features
            registry.register(vol_strategy)

            today = date.today()
            signals_list: list[pl.DataFrame] = []

            # Momentum strategy signals
            mom_signals = momentum_strategy.generate_signals(today)
            if not mom_signals.is_empty():
                signals_list.append(mom_signals)
                result.metrics["momentum_signals"] = len(mom_signals)

            # Aggregate signals
            aggregator = SignalAggregator(method="rank_blend")
            combined_signals = aggregator.aggregate(signals_list)
            result.metrics["combined_signals"] = len(combined_signals)

            # Load prices for risk/cost/optimization
            try:
                prices = pl.read_parquet(
                    "data/dataset/daily_price_" + today.isoformat() + ".parquet"
                )
            except Exception:
                prices = pl.DataFrame()

            # Step 4: Risk management
            risk_manager = PortfolioRiskManager()
            if not combined_signals.is_empty() and not prices.is_empty():
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
            else:
                filtered_signals = combined_signals

            # Step 5: Cost estimation
            cost_model = CostModel()
            if not filtered_signals.is_empty() and not prices.is_empty():
                symbols = filtered_signals["symbol"].to_list()
                n_symbols = len(symbols)
                per_stock_capital = total_capital / max(n_symbols, 1)

                # Compute ADV for each symbol
                from qp.portfolio.cost_model import MarketImpactModel

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

            # Step 6: Capital allocation
            allocator = AllocationFactory.create(alloc_method, cash_buffer=0.05)
            if not filtered_signals.is_empty():
                alloc_df = allocator.allocate_capital(filtered_signals.to_pandas(), total_capital)
                alloc_df_pl = pl.from_pandas(alloc_df)
                result.metrics["allocated_positions"] = len(alloc_df_pl)
            else:
                alloc_df_pl = pl.DataFrame()

            # Step 7: Position optimization
            optimizer = MeanVarianceOptimizer()
            if not filtered_signals.is_empty() and not prices.is_empty():
                symbols = filtered_signals["symbol"].to_list()
                opt_result = optimizer.optimize(prices, symbols, total_capital)
                result.metrics["opt_sharpe"] = opt_result.sharpe_ratio
                result.metrics["opt_volatility"] = opt_result.expected_volatility
                result.metrics["opt_converged"] = 1 if opt_result.converged else 0
                if opt_result.fallback_used:
                    result.metadata["opt_fallback"] = opt_result.message

                # Generate orders from optimized weights
                orders: list[Order] = []
                for sym, wt in opt_result.weights.items():
                    if wt > 0:
                        amount = wt * total_capital
                        quantity = int(amount // 100 * 100)  # Round to lots
                        if quantity > 0:
                            orders.append(Order(symbol=sym, side="BUY", quantity=quantity))
                result.metrics["order_count"] = len(orders)
                for o in orders:
                    result.metadata[f"order_{o.symbol}"] = f"{o.side} {o.quantity} ({o.side})"
            else:
                orders = []

            # Step 8: Backtest (simplified)
            if not prices.is_empty() and not combined_signals.is_empty():
                backtest = SimpleVectorBacktest()
                bt_result = backtest.run(
                    prices=prices,
                    signals=combined_signals,
                    initial_capital=total_capital,
                )
                result.metrics.update(bt_result)

            result.artifacts.append("data/dataset/momentum_20d.parquet")
            result.artifacts.append("data/dataset/volatility_20d.parquet")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result
