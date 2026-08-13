# ADR-015: Dataset Is The Only Public Interface

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-013, ADR-017

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

Data Layer 对外只暴露 Dataset，不暴露内部实现。

---

## 实现状态

✅ 已实现。代码证据：`qp/data/dataset/registry.py` 唯一公开接口

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
