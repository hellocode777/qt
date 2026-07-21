"""Data Layer metadata — source info, schema tracking, and data lineage.

Three categories (dp.md §7.7-7.8):
  1. Source Metadata — origin, access patterns, freshness, reliability per adapter
  2. Schema Tracking — column definitions, types, constraints, version evolution
  3. Lineage Tracking — complete chain source → cleaning → validation → PIT → dataset

Fills the gap from credibility_check.md §1:
  "日常 Pipeline 运行不记录数据版本"

Quick start::

    from qp.data.metadata import (
        SourceMetadata, SourceMetadataStore,
        SchemaVersion, SchemaTracker,
        DataLineage, LineageTracker,
    )

    # Track source health
    store = SourceMetadataStore()
    store.record_success("akshare", latency_seconds=2.3)

    # Track schema evolution
    schemas = SchemaTracker()
    schemas.record(SchemaVersion(
        dataset_name="daily_price", version="2026-07-20",
        columns={"trade_date": "date", "symbol": "str", "close": "float64"},
        primary_key=["trade_date", "symbol"],
    ))

    # Track data lineage
    lineage = LineageTracker()
    lineage.record(DataLineage(
        source_name="akshare", dataset_name="daily_price",
        dataset_version="2026-07-20", pipeline_run_id="run_abc",
    ))
"""

from qp.data.metadata.lineage_tracker import DataLineage, LineageTracker
from qp.data.metadata.schema_tracker import SchemaTracker, SchemaVersion
from qp.data.metadata.source_metadata import SourceMetadata, SourceMetadataStore

__all__ = [
    "SourceMetadata",
    "SourceMetadataStore",
    "SchemaVersion",
    "SchemaTracker",
    "DataLineage",
    "LineageTracker",
]
