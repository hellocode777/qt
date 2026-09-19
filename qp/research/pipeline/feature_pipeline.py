"""FeaturePipeline — computes features from Data Products."""

from __future__ import annotations

from qp.data.loader.loader import load_dataset
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.research.feature.momentum import Momentum20dFeature
from qp.research.feature.registry import FeatureRegistry
from qp.research.feature.volatility import Volatility20dFeature
from qp.shared.paths import DATASET_DIR
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus

# Feature factory — maps name to class
_FEATURE_CLASSES: dict[str, type] = {
    "momentum_20d": Momentum20dFeature,
    "volatility_20d": Volatility20dFeature,
}


class FeaturePipeline(BasePipeline):
    """Compute features from trusted Data Products."""

    @property
    def name(self) -> str:
        return "feature_compute"

    def run(self, context: PipelineContext) -> PipelineResult:
        feature_names = context.parameters.get("features", list(_FEATURE_CLASSES.keys()))

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        try:
            # Load daily price dataset
            ds = load_dataset("daily_price")
            result.metrics["dataset_rows"] = len(ds)

            registry = FeatureRegistry()

            for fname in feature_names:
                if fname not in _FEATURE_CLASSES:
                    result.metrics["feature_rows"] = -1
                    result.metadata["skip_" + fname] = "unknown — skipped"
                    continue

                feature = _FEATURE_CLASSES[fname]()
                registry.register(feature)

                feature_df = feature.compute({"daily_price": ds})
                result.metrics[f"feature_{fname}_rows"] = len(feature_df)

                # Save feature
                import polars as pl

                path = str(DATASET_DIR / f"{fname}.parquet")
                pl.from_pandas(feature_df.to_pandas()).write_parquet(path)
                result.artifacts.append(path)

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result
