# DP-003: Research Layer (L3)

> Design Proposal — 可复现实验
> 关联 ADR: 018, 019, 020, 021, 022

## 职责

可复现的实验：特征、标签、模型训练、评估。**禁止**直接调用 `ak.stock_zh_a_hist(...)`。

## 子模块

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `research/feature/` | 7 | `FeatureRegistry`, `compute_all_factors` | 特征工程：动量(1M/3M/6M/20D)、反转(5D)、波动率(20D/60D) |
| `research/label/` | 2 | 标签构建 | 未来收益率标签 |
| `research/trainer/` | 3 | `LightGBMRankModel`, `ModelRegistry`, `MonthlyRetrainPipeline` | LightGBM LambdaRank + 自动重训 |
| `research/evaluation/` | 2 | `LayeredTest` | 分层测试：Rank IC, ICIR, 分层收益, 单调性 |
| `research/experiment/` | 5 | `ExperimentTracker`, `ExperimentRunner` | 实验记录、快照、恢复 |
| `research/split/` | 1 | `PurgedKFold` | Purged K-Fold CV（ADR-021 强制） |
| `research/importance/` | 1 | SHAP | 特征重要性分析 |
| `research/pipeline/` | 1 | `FeaturePipeline` | 研究管道编排 |
| `research/artifact/` | 1 | 实验产物 | 模型文件、报告存储 |
| `research/dataset/` | 1 | 研究数据集 | 实验用数据集封装 |

## 关键设计决策

- **ADR-018**: 一切皆实验
- **ADR-019**: 特征是头等资产
- **ADR-020**: 标签即 Dataset
- **ADR-021**: Purged KFold 强制（不允许普通 KFold）
- **ADR-022**: Notebook 仅供探索，不进生产

## 依赖

- **依赖**: L1 (Platform), L2 (Data) — 通过 Dataset
- **被依赖**: L4 (Validation), L5 (Strategy)
