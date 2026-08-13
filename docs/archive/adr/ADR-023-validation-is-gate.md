# ADR-023: Validation Is Gate

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-016, ADR-025

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

Validation 永远不能被跳过。整个系统唯一允许进入 Strategy 的入口就是 Validation。

---

## 实现状态

✅ 已实现。代码证据：`qp/validation/`（RuleEngine + checks/ + pipeline）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
