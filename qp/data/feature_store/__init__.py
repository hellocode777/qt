"""Feature Store — batch+stream feature computation, storage, and serving.

Implements data_layer.md §1.5: Feature Store（特征商店）

  "Feature Store 的核心职责：
   将特征计算解耦，一次计算，双重服务。既为离线回测提供高效的批量读取，
   也为实盘交易提供毫秒级的流式读取，并保证两者的计算逻辑 100% 绝对一致。"

Module structure:
  - base_feature.py: Concrete BaseFeature with batch/stream + shift(1)
  - registry.py: FeatureRegistry with versioning
  - engine.py: FeatureEngine orchestrating computation
  - offline_store.py: Parquet-based offline store with year partitioning
  - online_cache.py: Thread-safe in-memory online cache
  - standardization.py: Cross-sectional z-score + anti-leakage utilities

Quick start::

    from qp.data.feature_store import (
        BaseFeature,
        FeatureRegistry,
        FeatureEngine,
        OfflineStore,
        OnlineCache,
        cross_sectional_zscore,
        shift_features,
    )


    # 1. Define a feature
    class Momentum20(BaseFeature):
        feature_name = "momentum_20"
        required_data = ["close"]
        window = 20

        def transform_batch(self, df):
            return df.with_columns(pl.col("close").pct_change(20).alias("momentum_20"))

        def update_stream(self, new_value):
            self._buffer.append(new_value)
            if not self.is_ready:
                return None
            return self._buffer[-1] / self._buffer[0] - 1


    # 2. Register & compute
    registry = FeatureRegistry()
    registry.register(Momentum20())

    engine = FeatureEngine(registry)
    features = engine.compute(raw_df)

    # 3. Store for later use
    offline = OfflineStore(FEATURES_DIR)
    offline.write(features, factor_group="momentum")

    # 4. Serve in real-time
    online = OnlineCache()
    online.update("600519", {"momentum_20": 0.05})
"""

from qp.data.feature_store.base_feature import BaseFeature
from qp.data.feature_store.duckdb_engine import DuckDBEngine
from qp.data.feature_store.engine import FeatureEngine
from qp.data.feature_store.offline_store import OfflineStore
from qp.data.feature_store.online_cache import OnlineCache
from qp.data.feature_store.registry import FeatureRegistry
from qp.data.feature_store.standardization import (
    cross_sectional_rank,
    cross_sectional_zscore,
    resample_safe,
    rolling_zscore,
    shift_features,
    standardize_features,
    validate_no_future_leakage,
)

__all__ = [
    # Core
    "BaseFeature",
    "DuckDBEngine",
    "FeatureEngine",
    "FeatureRegistry",
    # Storage
    "OfflineStore",
    "OnlineCache",
    "cross_sectional_rank",
    # Standardization & Anti-leakage
    "cross_sectional_zscore",
    "resample_safe",
    "rolling_zscore",
    "shift_features",
    "standardize_features",
    "validate_no_future_leakage",
]
