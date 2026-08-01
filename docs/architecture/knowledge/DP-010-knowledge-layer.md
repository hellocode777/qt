# DP-010: Knowledge Layer (L10)

> Design Proposal — 长期记忆与组织学习

## 职责

轻量级知识管理（Markdown + Parquet）。记录复盘、实验总结、失败分析，形成闭环反馈。

## 模块

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `knowledge/archive.py` | `KnowledgeArchive`, `KnowledgeEntry`, `KnowledgeCategory` | 知识归档（Markdown + YAML） |
| `knowledge/decision_audit_logger.py` | `DecisionAuditLogger` | 交易决策审计（T2 表） |
| `knowledge/failure_archive_logger.py` | `FailureArchiveLogger` | 止损/黑天鹅事件（T3 表） |
| `knowledge/regime_notes.py` | `RegimeNoteLogger` | 市场状态 ↔ 策略表现笔记 |
| `knowledge/cluster_analyzer.py` | `FailureClusterAnalyzer` | 失败聚类 → 黑名单规则 |
| `knowledge/version_tree.py` | VersionTree | 知识版本树 |

## 知识分类

| 类别 | 用途 |
|------|------|
| `RESEARCH_DEBT` | 研究负债 |
| `DECISION_AUDIT` | 决策审计 |
| `EXPERIMENT_SUMMARY` | 实验总结 |
| `FAILURE_ANALYSIS` | 失败分析 |
| `POST_MORTEM` | 复盘 |

## 闭环反馈链路

```
FailureArchiveLogger → ClusterAnalyzer
  → 黑名单规则 (L2 Data)
  → 特征建议 (L3 Research)
  → 策略参数调整 (L5 Strategy)
```

## 依赖

- **依赖**: L1 (Platform), L8 (Decision), L9 (Monitoring)
- **被依赖**: 反馈回路影响 L2, L3, L5
