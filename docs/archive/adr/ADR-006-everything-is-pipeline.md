# ADR-006: Everything Is Pipeline

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-003, ADR-012

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

**Decision**：系统所有长期任务全部表示为 Pipeline，而不是 Script。

如 `TrainingPipeline`、`FeaturePipeline`、`BacktestPipeline`（而非 `train.py`、`feature.py`、`backtest.py`）。

**Why**：Pipeline 天然具有 Input → Transform → Output，与量化平台的数据流完全一致。Scheduler 调度 Pipeline，CLI 执行 Pipeline，Experiment 记录 Pipeline。

---

## 实现状态

✅ 已实现。代码证据：`qp/platform/pipeline/`（BasePipeline / PipelineRunner / PipelineContext）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
