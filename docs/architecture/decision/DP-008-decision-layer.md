# DP-008: Decision Layer (L8)

> Design Proposal — 可解释、可审计的决策
> 关联 ADR: 026

## 职责

将策略信号转化为人类可审核的交易建议。**QP 是决策辅助系统，非自动交易系统。**（ADR-026）

## 模块

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `decision/engine.py` | `DecisionEngine` | 信号 → 交易建议（BUY） |
| `decision/models.py` | `DecisionReport`, `TradeRecommendation` | 决策领域模型 |
| `decision/decision_package.py` | `DecisionPackage` | 每日决策包（JSON + Markdown） |
| `decision/position_ledger.py` | `PositionLedger` | 持仓账本 |
| `decision/state_machine.py` | 状态机 | 决策生命周期 |

## DecisionPackage 内容

每份 DecisionPackage 包含：
- 数据血缘（Dataset + Feature 版本）
- 市场状态（Regime + 置信度 + 建议敞口）
- 策略执行摘要（每个策略的信号数）
- 验证门禁（评分 + 失败规则）
- 风控审计（违规项：阈值 vs 实际值）
- 交易建议（具体买卖标的、数量、理由、风险警告）
- 人工审核区（待填写：是否通过、是否执行）

## 持久化

```
data/decisions/
├── dp-2026-08-01-abc12345.json    ← 结构化数据
├── 2026-08-01.md                  ← Markdown 报告
└── index.json                     ← 决策索引
```

## 依赖

- **依赖**: L1 (Platform), L5 (Strategy), L6 (Portfolio), L7 (Simulation)
- **被依赖**: L9 (Monitoring) — 只读
