# ADR-012: Runtime Owns Everything

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-003, ADR-011

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

任何基础设施（Logger、Storage、Clock、Scheduler、Configuration、Metadata、Environment）都属于 Runtime。Pipeline 不能 `new Logger()`，只能 `runtime.logger`。

---

## 实现状态

✅ 已实现。代码证据：`qp/platform/runtime/`（Runtime 拥有 logger/storage/config 等）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
