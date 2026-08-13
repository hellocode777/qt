# ADR-013: Data Product Architecture

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-014, ADR-015, ADR-017

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

Data Layer 管理的是 Data Product（数据产品），而不是 Data Source（数据源）。Research Layer 永远不碰 AkShare、CSV、Parquet，只知道 Dataset。

```python
dataset = data.load_dataset("daily_price", version="2026-07-20")
```

Research 不知道数据来自 AkShare 还是 Tushare。这是整个十二层架构最重要的一条边界——依赖倒置。

---

## 实现状态

✅ 已实现。代码证据：`qp/data/dataset/`（Dataset registry + parquet 数据产品）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
