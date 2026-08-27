"""CLI command handlers for the "lineage" group.

Builds and persists the full Data → Feature → Model → Strategy lineage
graph (Rule 7: Full Data Lineage) from the existing registries.
"""

from __future__ import annotations

from qp.shared.paths import FACTOR_REGISTRY


def cmd_lineage_snapshot() -> int:
    """Build the lineage graph from existing registries and persist it."""
    from qp.lineage.engine import LineageRegistry
    from qp.strategy.registry import StrategyRegistry

    print("═══ QP 数据血缘快照 / Lineage Snapshot ═══")
    print()

    lineage = LineageRegistry()
    counts: dict[str, int] = {}

    # 1. Datasets (Data Layer — DatasetRegistry)
    try:
        from qp.data.dataset.registry import DatasetRegistry

        counts["datasets"] = lineage.sync_from_dataset_registry(DatasetRegistry())
        print(f"  ✅ 数据集 / Datasets:  {counts['datasets']}")
    except Exception as e:
        print(f"  ⚠ 数据集跳过 / Datasets skipped: {e}")

    # 2. Features (Research Layer — persisted FeatureRegistry)
    try:
        from qp.research.feature.registry import FeatureRegistry as ResearchFeatureRegistry

        feature_registry = ResearchFeatureRegistry.load_from_json(FACTOR_REGISTRY)
        counts["features"] = lineage.sync_from_feature_registry(feature_registry)
        print(f"  ✅ 特征 / Features:    {counts['features']}")
    except FileNotFoundError:
        print(
            "  ⚠ 特征跳过 / Features skipped: data/factor_registry.json 不存在，先跑 `qp factor register`"
        )
        counts["features"] = 0
    except Exception as e:
        print(f"  ⚠ 特征跳过 / Features skipped: {e}")
        counts["features"] = 0

    # 3. Models (Research Layer — ModelRegistry)
    try:
        from qp.research.trainer.registry import ModelRegistry

        counts["models"] = lineage.sync_from_model_registry(ModelRegistry())
        print(f"  ✅ 模型 / Models:      {counts['models']}")
    except Exception as e:
        print(f"  ⚠ 模型跳过 / Models skipped: {e}")

    # 4. Strategies (Strategy Layer — StrategyRegistry)
    try:
        counts["strategies"] = lineage.sync_from_strategy_registry(StrategyRegistry())
        print(f"  ✅ 策略 / Strategies:  {counts['strategies']}")
    except Exception as e:
        print(f"  ⚠ 策略跳过 / Strategies skipped: {e}")

    # Persist
    from pathlib import Path

    out_path = Path("data/metadata/lineage_graph.json")
    lineage.save(out_path)

    print()
    print(f"  📦 血缘图已落盘 / Saved: {out_path}")
    print(f"     节点 / Nodes: {lineage.node_count}   边 / Edges: {lineage.edge_count}")

    # Downstream impact example: what depends on the price dataset?
    try:
        data_nodes = [n for n in lineage.list_nodes() if n.startswith("data::")]
        if data_nodes:
            affected = lineage.trace_downstream_impact(data_nodes[0])
            print(f"     📉 '{data_nodes[0]}' 下游影响: {len(affected)} 个节点")
            for a in affected[:5]:
                print(f"        - {a}")
    except Exception:
        pass

    print()
    return 0
