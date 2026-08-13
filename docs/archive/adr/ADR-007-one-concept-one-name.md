# ADR-007: One Concept, One Name

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-008

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

一个概念只能有一个名字。如只能叫 `Pipeline`，绝不能 Workflow、Flow、Process、Task Chain 混着出现。

---

## 实现状态

✅ 已实现。代码证据：`qp/shared/constants/` + 全库统一命名

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
