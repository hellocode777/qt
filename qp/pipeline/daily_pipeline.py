"""DailyPipeline — orchestrated end-to-end daily workflow.

Data → Feature → Strategy → Portfolio → Backtest → Report.
"""

from __future__ import annotations

from datetime import date

from qp.data.pipeline import DataPipeline
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.portfolio.single_portfolio import SinglePortfolio
from qp.research.pipeline import FeaturePipeline
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus
from qp.simulation.backtest import SimpleVectorBacktest
from qp.strategy.simple_rank import SimpleRankStrategy


class DailyPipeline(BasePipeline):
    """End-to-end daily quant workflow."""

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
            # Step 1: Data ingestion
            data_pipeline = DataPipeline()
            data_result = data_pipeline.run(context)
            if data_result.status == PipelineStatus.FAILED:
                result.errors.extend(data_result.errors)
                result.status = PipelineStatus.FAILED
                return result
            result.metrics.update(
                {f"data_{k}": v for k, v in data_result.metrics.items()}
            )

            # Step 2: Feature computation
            feature_pipeline = FeaturePipeline()
            feature_result = feature_pipeline.run(context)
            if feature_result.status == PipelineStatus.FAILED:
                result.errors.extend(feature_result.errors)
                result.status = PipelineStatus.FAILED
                return result
            result.metrics.update(
                {f"feature_{k}": v for k, v in feature_result.metrics.items()}
            )

            # Step 3: Strategy signal generation
            strategy = SimpleRankStrategy(top_n=context.parameters.get("top_n", 10))
            today = date.today()
            signals = strategy.generate_signals(today)
            result.metrics["signal_count"] = len(signals)

            # Step 4: Portfolio construction
            portfolio = SinglePortfolio(
                total_capital=context.parameters.get("capital", 1_000_000)
            )
            orders = portfolio.generate_orders(signals)
            result.metrics["order_count"] = len(orders)
            for order in orders:
                result.metadata[f"order_{order.symbol}"] = f"{order.side} {order.quantity}"

            # Step 5: Backtest (simplified)
            import polars as pl

            try:
                prices = pl.read_parquet("data/dataset/daily_price_" + date.today().isoformat() + ".parquet")
            except Exception:
                prices = pl.DataFrame()

            if not prices.is_empty() and not signals.is_empty():
                backtest = SimpleVectorBacktest()
                bt_result = backtest.run(prices=prices, signals=signals)
                result.metrics.update(bt_result)

            result.artifacts.append("data/dataset/momentum_20d.parquet")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result
