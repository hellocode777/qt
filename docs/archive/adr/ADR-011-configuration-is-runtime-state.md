# ADR-011: Configuration Is Runtime State

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-003, ADR-012

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

Configuration 不是普通文件，而是 Runtime State Definition。整个 Runtime 只能拥有一个 Config，不能 reload，不能 dynamic update。否则实验、日志、Scheduler 都会失去一致性。

---

## 实现状态

✅ 已实现。代码证据：`qp/platform/config/models.py`（FreezableBaseModel 启动后冻结）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
