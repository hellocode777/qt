# Walking Skeleton 落地路线图（已归档）

> 原为 `docs/constitution/rule.md` 第 8 节。
> **状态：✅ 已完成**（2026-07 三阶段全部走通，项目进入完整实现阶段，Phase 0-6 完成）。
> 归档日期：2026-08-11。保留作为 Rule 28（Build Walking Skeleton Before Expansion）的历史落地记录。

---

## 8. Walking Skeleton 落地路线图

**原则**：拒绝过度设计，停止增加架构概念。用 3 周时间打造一条能真正跑通的最小策略闭环。

```
                ┌────────────────────────────────────────┐
                │         Walking Skeleton Pipeline       │
                └───────────────────┬────────────────────┘
                                    │
  [ daily_price.parquet ] ─────────┼──► Data Layer (Simple Ingestion)
                                    │
  [ momentum_20d ] ────────────────┼──► Feature Layer (Basic Momentum)
                                    │
  [ SimpleRankStrategy ] ──────────┼──► Strategy Engine (Top-N Rank)
                                    │
  [ SinglePortfolio ] ─────────────┼──► Portfolio Layer (Equal Weight)
                                    │
  [ SimpleVectorBacktest ] ────────┼──► Backtest & Execution Simulation
                                    │
  [ QuantStats / Markdown Report ] ┼──► Performance Report & Logs
                                    ▼
                        【验证整体架构连通性】
```

### 阶段一：基础设施与核心对象（Week 1）

- [ ] 初始化 Git 仓库、安装 Python 3.12+ / `uv` / `poetry`
- [ ] 部署 `platform/config/`（pydantic）与 `platform/logging/`（loguru）
- [ ] 落实 `platform/alert/`（基础 Terminal / Log / Telegram 告警通道）
- [ ] 创建 9 个 Core Domain Objects 的强类型 `dataclass` / `pydantic` 定义

### 阶段二：核心 Protocol Base Classes（Week 2）

- [ ] 落盘 `BaseDataSource`、`BaseFeature`、`BaseModel`、`BaseStrategy`、`BasePortfolio`、`BaseBroker` 等基类
- [ ] 实现轻量级 `ExperimentTracker`，支持保存参数与结果元数据（JSON / Parquet）

### 阶段三：走通 Walking Skeleton 最小闭环（Week 3）

- [ ] **Data**：接入单个行情数据源，生成 `daily_price.parquet`
- [ ] **Feature**：计算一个简单的 20 日动量因子（`momentum_20d`）
- [ ] **Strategy**：实现 `SimpleRankStrategy`，选取 Top 10 股票
- [ ] **Portfolio**：资金均分，按固定调仓日生成 Order
- [ ] **Backtest & Report**：运行端到端回测，输出一份 Markdown / HTML 绩效报告

> **重要**：第 7 节列出的大部分接口（Registry、Lineage、Risk Model、Capital Allocator 的复杂算法版本等）在这 3 周计划中**不会**被用到。这是有意为之——先用最简实现（甚至是硬编码的简化版）走通全链路，再回头对照第 6、7 节的宪法条文，逐步替换为符合规范的正式实现。不要在骨架跑通之前就把所有抽象都做满。

---
