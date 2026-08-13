# ADR-001: Hybrid Architecture（混合架构）

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-013, ADR-009

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

**Decision**：采用 **Data Pipeline + Domain Model** 混合架构。

- **Data Layer、Research Layer**：保持 DataFrame Pipeline（Pandas / Polars / DuckDB），以研究效率优先。
- **Domain Layer（Portfolio、Position、Order、Decision 等）**：采用 Repository + 强类型 Domain Object，保证业务一致性与可维护性。

**Why**：项目本质上有两种完全不同的数据——分析数据（行情、财务、因子、标签、特征）天然适合列式处理；业务对象（Position、Order、Decision、Experiment、Strategy Metadata）天然适合对象模型。把两者统一成一种模式反而会增加复杂度。

---

## 实现状态

✅ 已实现。代码证据：`qp/` 12 层目录结构（L1 platform → L10 knowledge）+ `shared/` `pipeline/` `web/`

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
