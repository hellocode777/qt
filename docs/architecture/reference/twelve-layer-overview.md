# 十二层架构总览 / Twelve-Layer Architecture Overview

> QP (Quant Platform) 完整架构参考
> 最后更新：2026-08-01

---

## 层级图

```
┌─────────────────────────────────────────────────────────────┐
│                    QP 十二层架构                              │
│                                                              │
│  Layer 10: knowledge/     — 长期记忆（复盘、失败分析）        │
│  Layer 9:  monitoring/    — 只观察不决策（熔断、漂移）        │
│  Layer 8:  decision/      — 可审计决策（非 AI/LLM）          │
│  Layer 7:  simulation/    — 纸交易、影子交易                 │
│  Layer 6:  portfolio/     — 组合构建、风控、资金分配          │
│  Layer 5:  strategy/      — 投资策略（输出 Decision）        │
│  Layer 4:  validation/    — 门控（16 项检查）                │
│  Layer 3:  research/      — 可复现实验（Purged CV）          │
│  Layer 2:  data/          — 可信数据产品（Dataset）          │
│  Layer 1:  platform/      — 运行时内核                        │
│                                                              │
│  shared/  — 跨层协议、类型、常量、异常                       │
│  web/     — Web UI                                          │
│  pipeline/ — 业务管道编排                                    │
└─────────────────────────────────────────────────────────────┘
```

## 层级依赖

**铁律：不允许向上导入。**

```
L10 ← L9 ← L8 ← L7 ← L6 ← L5 ← L4 ← L3 ← L2 ← L1
                                      ↑       ↑
                                  shared/   web/
                                  pipeline/
```

## 各层文件统计

| 层 | 子模块数 | 文件数 | 核心职责 |
|----|---------|--------|----------|
| L1 Platform | 10 | ~49 | 运行时：配置、日志、CLI、调度、存储、管道 |
| L2 Data | 17 | ~55 | 数据产品：适配器→清洗→校验→Dataset |
| L3 Research | 10 | ~24 | 实验：特征、标签、LightGBM、Purged CV |
| L4 Validation | 1 | ~9 | 门控：16 项检查，4 阶段 |
| L5 Strategy | 5 | ~28 | 策略：信号、集成、市场状态、纸交易 |
| L6 Portfolio | 8 | ~36 | 组合：分配、风控、成本、NAV |
| L7 Simulation | flat | 4 | 模拟：券商、滑点、影子账本 |
| L8 Decision | flat | 5 | 决策：引擎、决策包、持仓账本 |
| L9 Monitoring | flat | 14 | 监控：熔断、漂移、健康、告警 |
| L10 Knowledge | flat | 6 | 知识：归档、审计、失败分析 |
| Pipeline | flat | 3 | 编排：Daily, MultiFactor, Fundamental |
| Web | 2 | 15 | UI：FastAPI + Jinja2 + HTMX |
| Shared | 4 | ~15 | 协议(11)、类型、常量、异常 |

## 数据流

```
DailyPipeline:
  DataPipeline → FeaturePipeline → Price Data → Strategy Discovery
    → Market Regime → Strategy Signals → EnsembleEngine.fuse()
      → Risk Management → Cost Estimation → Capital Allocator (BUY)
        → Exit Engine (SELL) → DecisionEngine → DecisionPackage

ExperimentPipeline:
  Data Fetch → Feature Computation → LightGBM Training
    → Purged CV Evaluation → Layered Test → Validation Gate
      → Strategy Registration → Model Registry
```

## 关联文档

| 文档 | 内容 |
|------|------|
| `DP-001` ~ `DP-010` | 各层详细设计提案 |
| `../adr/ADR-*.md` | 架构决策记录（31 份） |
| `../tdr/TDR-*.md` | 技术决策记录（10 份） |
| `../constitution/constitution-v4.2.md` | 项目宪法 |
| `../developer_guide.md` | 开发者指南 |
| `../user_guide.md` | 用户指南 |
