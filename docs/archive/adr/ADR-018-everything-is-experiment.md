# ADR-018: Everything Is Experiment

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-019, ADR-021, ADR-022

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

任何训练都是 Experiment，不能直接 `train.py`，必须用 `ExperimentRunner`。

---

## 实现状态

✅ 已实现。代码证据：`qp/research/experiment/`（ExperimentRunner/ExperimentTracker）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
