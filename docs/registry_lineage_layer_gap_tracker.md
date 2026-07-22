# Registry & Lineage Layer 差距追踪文档

> 对照 `docs/4_Registry_LineageLayer.md` 与 `docs/rule.md` §4，逐项追踪 Layer 4（Registry & Lineage）的待实现项。
> 最后更新：2026-07-22（Week 1 P0 + Week 2 P1 收尾 + P2 完成）

---

## 状态说明

- ⬜ `[ ]` 待实现
- 🟡 `[~]` 部分实现，有缺陷
- ✅ `[x]` 已完成

---

## 一、P0 — 核心引擎缺失（统一血缘图谱）

### 1.1 统一 `LineageRegistry` 类

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §3 "Python 落地实现"
- **已实现**: `qp/lineage/engine.py` → `LineageRegistry` 类，含 4 个内部 Registry、NetworkX DAG 后端、完整注册 API

---

### 1.2 NetworkX DAG 血缘图谱

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §2 "有向无环图强行关联"
- **已实现**: `networkx>=3.0` 已添加到 `pyproject.toml`；`LineageRegistry._graph` 使用 `nx.DiGraph`

---

### 1.3 `trace_downstream_impact()` 下游影响分析

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §4 "血缘链路回溯与影响度查询"
- **已实现**: `trace_downstream_impact()` + `get_impact_report()` + `trace_upstream()` + `get_full_lineage()`

---

### 1.4 `_generate_code_hash()` 因子代码哈希

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §3 "提取函数源代码并生成 Git 级别的 MD5 签名"
- **已实现**: `LineageRegistry._generate_code_hash()` — `inspect.getsource` + `hashlib.md5`，与文档参考实现一致

---

### 1.5 跨 Registry 自动建边机制

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §3 "建立血缘边：Data → Feature → Model"
- **已实现**: `register_feature(input_data_nodes=...)` → `DERIVED_FROM` 边；`register_model(used_feature_nodes=...)` → `TRAINED_ON` 边；`register_strategy(model_nodes=...)` → `DEPLOYED_AS` 边

---

## 二、P1 — 元数据字段缺失

### 2.1 Feature 缺 `point_in_time_safe` 标记

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §1② "point_in_time_safe: True（标记是否已做 shift/无未来函数）"
- **已实现**: `BaseFeature.__init__` 新增 `point_in_time_safe: bool = True` 参数
- **涉及文件**: `qp/data/feature_store/base_feature.py`

---

### 2.2 Feature 缺 `owner` 字段

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §1② "owner: 作者与审核记录"
- **已实现**: `BaseFeature.__init__` 新增 `owner: str = ""` 参数
- **涉及文件**: `qp/data/feature_store/base_feature.py`

---

### 2.3 ModelMetadata 缺 `random_seed` 字段

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §1③ "随机种子（Seed）与超参数配置"
- **已实现**: `ModelMetadata.__init__` 新增 `random_seed: int = 0` 参数，同步更新 `to_dict()`
- **涉及文件**: `qp/research/trainer/registry.py`

---

### 2.4 ModelMetadata 缺 `dataset_version` / `feature_versions` 绑定

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §1③ "训练数据集的版本 + 特征集版本"
- **已实现**: `ModelMetadata.__init__` 新增 `dataset_version: str = ""` + `feature_versions: dict[str, str] | None = None`，同步更新 `to_dict()`
- **涉及文件**: `qp/research/trainer/registry.py`

---

### 2.5 StrategyRegistry 缺血缘完整性关卡

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 4_Registry_LineageLayer.md §1④
- **已实现**: `StrategyRegistry.set_lineage_registry()` + `validate_lineage()`；`register()` 和 `set_lifecycle()` 在提升到 PAPER_TRADING/PRODUCTION 时校验血缘完整性；无 `LineageRegistry` 时抛 `ValueError`
- **涉及文件**: `qp/strategy/registry.py`

---

## 三、P2 — 整合与规范化

### 3.1 两套 FeatureRegistry 统一

- **状态**: `[~]` 已标注差异，暂不合并
- **当前情况**:
  - `qp/data/feature_store/registry.py` → 完整版（Data Layer，追踪 `data.feature_store.BaseFeature`）
  - `qp/research/feature/registry.py` → 简化版（Research Layer，追踪 `shared.protocols.BaseFeature`）
- **说明**: 两套 Registry 服务不同架构层，使用不兼容的 `BaseFeature` 类型（ABC vs concrete）。已在 `research/feature/registry.py` 添加文档说明差异。合并需先统一 `BaseFeature` 类体系 — 纳入远期规划。

---

### 3.2 DatasetRegistry 磁盘持久化

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 每次 `register()` 自动保存到 `<base_dir>/registry.json`；`__init__` 自动加载；`save(path)` / `load(path)` 类方法；`count` 属性 + `__len__` / `__contains__`
- **涉及文件**: `qp/data/dataset/registry.py`

---

### 3.3 LineageRegistry 与现有 Registry 的桥接

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `sync_from_dataset_registry()` / `sync_from_feature_registry()` / `sync_from_model_registry()` / `sync_from_strategy_registry()` + `sync_all()` 一键同步
- **涉及文件**: `qp/lineage/engine.py`

---

## 四、P3 — 远期目标（暂缓）

### 4.1 Lakehouse / Time-Travel (Delta Lake / Iceberg)

- **状态**: `[ ]` 暂缓
- **文档出处**: 4_Registry_LineageLayer.md §1① "基于 Lakehouse 架构"

### 4.2 MLflow / W&B 集成

- **状态**: `[ ]` 暂缓
- **文档出处**: 4_Registry_LineageLayer.md §1③ "通常集成 MLflow / Weights & Biases"

### 4.3 Neo4j / 图数据库

- **状态**: `[ ]` 暂缓
- **文档出处**: 4_Registry_LineageLayer.md §2 架构图

---

## 五、实现顺序建议

```
Week 1 ─ P0（核心引擎）
  ├── 1.1  LineageRegistry 类
  ├── 1.2  NetworkX DAG 血缘图谱
  ├── 1.4  _generate_code_hash()
  ├── 1.5  跨 Registry 自动建边机制
  └── 1.3  trace_downstream_impact() + trace_upstream()

Week 2 ─ P1（元数据补齐 + 串联）
  ├── 2.1  Feature point_in_time_safe
  ├── 2.2  Feature owner
  ├── 2.3  ModelMetadata random_seed
  ├── 2.4  ModelMetadata dataset/feature version 绑定
  └── 2.5  StrategyRegistry 血缘关卡

Week 3 ─ P2（整合收尾）
  ├── 3.1  统一两套 FeatureRegistry
  ├── 3.2  DatasetRegistry 磁盘持久化
  └── 3.3  LineageRegistry ↔ 现有 Registry 桥接
```

---

## 六、完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 1.1 LineageRegistry 类 | 创建 `qp/lineage/engine.py`，实现完整 `LineageRegistry` 类（NetworkX DAG + 4 内部 Registry + 注册 API） |
| 2026-07-22 | 1.2 NetworkX DAG | `pyproject.toml` 添加 `networkx>=3.0`；`LineageRegistry._graph` 使用 `nx.DiGraph` |
| 2026-07-22 | 1.3 trace_downstream_impact | `trace_downstream_impact()` + `get_impact_report()` + `trace_upstream()` + `get_full_lineage()` |
| 2026-07-22 | 1.4 _generate_code_hash | `inspect.getsource` + `hashlib.md5` 实现，与文档参考代码一致 |
| 2026-07-22 | 1.5 跨 Registry 自动建边 | `register_feature(input_data_nodes)` → `DERIVED_FROM`；`register_model(used_feature_nodes)` → `TRAINED_ON`；`register_strategy(model_nodes)` → `DEPLOYED_AS` |
| 2026-07-22 | 2.1 Feature point_in_time_safe | `BaseFeature.__init__` 新增 `point_in_time_safe: bool = True` |
| 2026-07-22 | 2.2 Feature owner | `BaseFeature.__init__` 新增 `owner: str = ""` |
| 2026-07-22 | 2.3 ModelMetadata random_seed | `ModelMetadata.__init__` 新增 `random_seed: int = 0` + `to_dict()` |
| 2026-07-22 | 2.4 ModelMetadata version 绑定 | `ModelMetadata.__init__` 新增 `dataset_version` + `feature_versions` + `to_dict()` |
| 2026-07-22 | 配套 | 创建 `qp/lineage/__init__.py`、`qp/lineage/types.py`（NodeType/EdgeRelation 枚举 + 元数据 dataclass + 节点 ID 工具函数）；桥接方法 `sync_from_*()` + `sync_all()`；61 项单元测试 |
| 2026-07-22 | 2.5 Strategy 血缘关卡 | `StrategyRegistry.set_lineage_registry()` + `validate_lineage()`；`set_lifecycle()` 提升到 PAPER_TRADING+ 时自动校验；无 LineageRegistry 时抛 ValueError |
| 2026-07-22 | 3.1 FeatureRegistry 差异标注 | `research/feature/registry.py` 添加文档说明两套 Registry 服务不同架构层（ABC vs concrete），合并需先统一 BaseFeature 体系 |
| 2026-07-22 | 3.2 DatasetRegistry 持久化 | `register()` 自动保存到 `registry.json`；`__init__` 自动加载；`save()` / `load()` 类方法；新增 `count` / `__len__` / `__contains__` |
| 2026-07-22 | 3.3 LineageRegistry 桥接 | `sync_from_*()` 4 个方法 + `sync_all()` 一键同步已在 Week 1 完成 |
