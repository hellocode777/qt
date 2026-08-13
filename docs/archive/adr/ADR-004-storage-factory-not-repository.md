# ADR-004: Platform 提供 Storage Factory，不提供 Repository

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-010, ADR-003

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

**Decision**：Platform Layer 提供 StorageFactory、Connection Lifecycle、Config、Database Initialization。Platform 不提供 Repository，Repository 属于各业务 Layer。

**Why**：Repository 已经开始表达业务语义（如 ExperimentRepository 知道 Experiment 是什么），Platform 不应该知道业务。否则 Platform 最终会变成 Business Platform，造成 Layer Corruption。

---

## 实现状态

✅ 已实现。代码证据：`qp/platform/storage/factory.py` StorageFactory（DuckDB/SQLite/Parquet）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
