"""Dataset Builder — assembles validated DataFrames into published Data Products.

Implements dp.md §7.5-7.9:
  - DatasetMetadata: 12-field contract per dp.md §7.7
  - DatasetBuilder: Silver → Gold assembly with contract validation
  - build_dataset(): convenience function

Quick start::

    from qp.data.builder import DatasetBuilder, BuildConfig, DatasetMetadata

    builder = DatasetBuilder()
    builder.register_source("akshare", DailyPriceContract)

    metadata = DatasetMetadata(
        name="daily_price", owner="data-layer", source="akshare",
        schema={"trade_date": "date", "symbol": "str", "close": "float64"},
        frequency="daily", primary_key=["trade_date", "symbol"],
    )
    result = builder.build(df, metadata)
    assert result.success
"""

from qp.data.builder.builder import DatasetBuilder, build_dataset
from qp.data.builder.config import BuildConfig, DatasetMetadata
from qp.data.builder.result import BuildResult

__all__ = [
    "DatasetBuilder",
    "BuildConfig",
    "DatasetMetadata",
    "BuildResult",
    "build_dataset",
]
