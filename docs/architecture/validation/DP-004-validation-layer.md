# DP-004: Validation Layer (L4)

> Design Proposal — Research 与 Strategy 之间的门控
> 关联 ADR: 023, 024, 025

## 职责

规则引擎驱动的门控。阻止未达标实验进入策略层。

## 检查清单（16 项，4 阶段）

| 阶段 | 检查项 | 数量 |
|------|--------|------|
| **Factor** | RankIC, IC_IR, t-stat, Stratification, Neutralization, MinSample | 6 |
| **Backtest** | Sharpe, MaxDrawdown, Turnover, CostAdjusted | 4 |
| **Overfit** | Overfit (OOS/IS ratio), FeatureImportance | 2 |
| **Paper Trading** | SignalCorrelation, Slippage, SignalInterruption | 3 |
| **Shadow→Prod** | KillSwitchHistory, HighVolSurvival | 2 |
| **Process** | CodeReview, ExperimentRecord | 2 |

## 模块

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `validation/engine.py` | `RuleEngine` | 规则引擎 |
| `validation/result.py` | `ValidationResult` | 门控结果 |
| `validation/pipeline.py` | `ValidationPipeline` | 验证管道 |
| `validation/checks/` | 6 文件 | 16 项检查实现 |

## 关键设计决策

- **ADR-023**: Validation 是 Gate
- **ADR-024**: 一切皆规则
- **ADR-025**: 只有 Validation 可以提升策略生命周期

## 依赖

- **依赖**: L1 (Platform), L3 (Research) — 读取实验产物
- **被依赖**: L5 (Strategy) — 控制策略注册准入
