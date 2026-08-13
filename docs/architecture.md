# QP 架构文档 / Architecture

> QP (Quant Platform) — 个人量化研究与投资决策操作系统。
> 本文档从 `docs/ai/PROJECT_MAP.md`（导航）、`docs/architecture/**/DP-*.md`（分层设计）、代码与宪法综合合成。
> 最后更新：2026-08-13
> 对 AI：架构问题先读 `docs/ai/`；人读架构从这里开始。

---

## 1. 系统目的

量化投资研究与投资决策操作系统：**人执行交易，系统不出自动订单**（输出 Decisions，不是 Orders）。

- 从数据 → 因子 → 模型 → 策略 → 组合 → 决策，全链路可复现、可审计、可解释
- 12 层严格单向依赖（上层可依赖下层，反之禁止）
- 规模：359 源文件 / ~77K 行 / 1488 测试（2026-08-11 实测）

## 2. 十二层架构

```
┌─────────────────────────────────────────────────────────────┐
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
└─────────────────────────────────────────────────────────────┘
```

| 层 | 目录 | 一句话职责 | 详细设计 |
|----|------|-----------|---------|
| L1 | `qp/platform/` | 运行框架：CLI、配置、日志、调度器、存储、Pipeline 引擎、runtime | [DP-001](architecture/platform/DP-001-platform-layer.md) |
| L2 | `qp/data/` | 可信 Data Products（数据集），消费方永远不知道数据源 | [DP-002](architecture/data/DP-002-data-layer.md) |
| L3 | `qp/research/` | 可复现实验：因子、标签、模型、Purged CV | [DP-003](architecture/research/DP-003-research-layer.md) |
| L4 | `qp/validation/` | 研究与策略之间的 Gate（规则引擎） | [DP-004](architecture/validation/DP-004-validation-layer.md) |
| L5 | `qp/strategy/` | 投资策略；输出 Decisions，不是 Orders | [DP-005](architecture/strategy/DP-005-strategy-layer.md) |
| L6 | `qp/portfolio/` | 组合构建、风控、资金分配 | [DP-006](architecture/portfolio/DP-006-portfolio-layer.md) |
| L7 | `qp/simulation/` | 回测 / 影子交易 / Paper Trading | [DP-007](architecture/simulation/DP-007-simulation-layer.md) |
| L8 | `qp/decision/` | 可解释、可审计的决策 | [DP-008](architecture/decision/DP-008-decision-layer.md) |
| L9 | `qp/monitoring/` | 只观察、不决策；漂移检测、熔断 | [DP-009](architecture/monitoring/DP-009-monitoring-layer.md) |
| L10 | `qp/knowledge/` | 长期记忆：post-mortem、实验摘要、失败分析 | [DP-010](architecture/knowledge/DP-010-knowledge-layer.md) |

**辅助模块**（非 12 层主体）：

| 目录 | 职责 |
|------|------|
| `qp/shared/` | protocols（BaseStrategy 等）、types、constants、exceptions |
| `qp/pipeline/` | 长任务 Pipeline 编排：daily、factor_calc、multifactor、fundamental |
| `qp/lineage/` | 血缘图（LineageRegistry DAG → `data/metadata/lineage_graph.json`） |
| `qp/web/` | Web UI（FastAPI 前端） |
| `data/` | 所有数据与运行时产物 |

## 3. 铁律（架构边界）

1. **不允许向上导入**：L10 ← L9 ← … ← L1，上层可依赖下层，反之禁止（ADR-008/009）
2. **跨层捷径禁止**：没有 utils/helpers/common；`shared/` 只放 protocols/types/constants/exceptions（ADR-009）
3. **数据层只出 Data Product**：`data/` 对外只暴露 Dataset，消费方不碰 AkShare 等原始源（ADR-013/015/017）
4. **research 禁止直调数据源**：`ak.stock_zh_a_hist(...)` 只允许在 data 层（ADR-017）
5. **Purged KFold 强制**：所有模型训练必须用 Purged CV（ADR-021）
6. **monitoring 永不 decide**：L9 只观察，不做决策（宪法 Rule）
7. **CLI 唯一入口**：`qp`，无第二个入口点（ADR-002）
8. **配置启动后冻结**：FreezableBaseModel（ADR-011）

> ⚠️ 2026-08-11 架构审计发现 80 条向上依赖，最严重 5 条待整改（见 `doc_rebuild_tracker.md` 与 Obsidian `qt宪法合规整改`）。

## 4. 数据流总览

```
AkShare (数据源)
  → data/raw（原始，不可变，只追加）[ADR-014]
  → data/bronze → data/silver（清洗/标准化）
  → data/dataset/*.parquet（Gold Data Product）[ADR-013/015]
  → qp/research（因子/特征/模型，Purged CV）[ADR-021]
  → qp/validation（Gate，只允许 APPROVED 策略进产线）[ADR-023/025/031]
  → qp/strategy（信号）
  → qp/portfolio（组合/风控）[ADR-029/030]
  → qp/decision（DecisionPackage → data/decisions/）[ADR-026]
  → qp/monitoring（观察 + 熔断 + 重训信号）
```

详细见 [DATA_FLOW.md](ai/DATA_FLOW.md)。

## 5. 三个执行系统（容易混淆）

全部消费**同一个 DecisionPackage**，但目的、资金、审核完全不同：

| | Paper Trading | Shadow 影子运行 | Portfolio 投资组合 |
|---|---|---|---|
| 目的 | 策略上线前验证 | 每日决策无脑执行对照 | 真实账户记账 |
| 触发 | `qp paper start` | daily_pipeline 自动 | WebUI 人工 approve |
| 资金 | 纸面（独立） | 假钱 10 万（独立） | 真实账户现金（ADR-032） |
| 审核 | 无 | 无 | 有状态机 + 驳回 |
| 存储 | `data/paper_trading/` | `data/simulation/` | `data/positions/` |

⚠️ 现金账本（ADR-032）只属于 Portfolio；Shadow/Paper 各有独立假钱，互不干扰。

## 6. 关键设计决策（ADR 索引）

| ADR | 决策 | 状态 |
|-----|------|------|
| ADR-001 | 混合架构（分层 + 领域驱动） | ⚠️ 空文档 |
| ADR-002 | CLI 唯一入口 `qp` | ⚠️ 空文档 |
| ADR-003 | 显式组合根（无 DI 框架） | ⚠️ 空文档 |
| ADR-004 | StorageFactory 而非 Repository | ⚠️ 空文档 |
| ADR-006 | 一切皆 Pipeline | ⚠️ 空文档 |
| ADR-009 | 禁止跨层捷径 | ⚠️ 空文档 |
| ADR-011 | 配置是运行时状态，启动后冻结 | ⚠️ 空文档 |
| ADR-012 | Runtime 拥有一切（ADR 有实现代码，文档为空） | ⚠️ 空文档 |
| ADR-013/015 | 数据产品架构 / Dataset 唯一接口 | ⚠️ 空文档 |
| ADR-014 | 原始数据不可变 | ⚠️ 空文档 |
| ADR-017 | 消费者永不知道数据源 | ⚠️ 空文档 |
| ADR-018 | 一切皆实验 | ⚠️ 空文档 |
| ADR-021 | Purged KFold 强制 | ⚠️ 空文档 |
| ADR-022 | Notebook 永不进生产 | ⚠️ 空文档 |
| ADR-023/025 | 验证是 Gate / 只有验证能提升策略 | ⚠️ 空文档 |
| ADR-026 | 策略产生决策 | ⚠️ 空文档 |
| ADR-027 | 模型在策略之前结束 | ⚠️ 空文档 |
| ADR-028 | 策略优于算法 | ⚠️ 空文档 |
| ADR-029/030 | Portfolio 拥有风控 / 资金分配 | ⚠️ 空文档 |
| **ADR-031** | Research 与 Production 彻底分离 | ✅ 有内容 |
| **ADR-032** | 账户现金账本 | ✅ 有内容 |
| **ADR-033** | 游离目录归属（pipeline 组合根 / web 人类接口层） | ✅ 有内容 |

> ⚠️ **注意**：ADR-001~030 文件为 0 字节占位（决策以当前代码 + rule.md 宪法为准）。补全这些 ADR 是文档重建的后续项。

## 7. 运行时产物位置（查状态先看这些）

| 路径 | 内容 |
|------|------|
| `data/strategy_registry.json` | 策略注册表（WebUI/实验自动改写）；APPROVED 冻结快照在 `strategies.<id>.approved` 字段 |
| `data/decisions/` | DecisionPackage（三个执行系统的共同输入） |
| `data/positions/` | Portfolio 真实账户（positions.parquet + account.json） |
| `data/simulation/` | Shadow 影子盘 |
| `data/paper_trading/` | Paper Trading 状态 |
| `data/experiments/` | 实验产物 |
| `data/metadata/lineage_graph.json` | 血缘图 |
| `logs/{日期}/{job}.log` | 调度任务日志（7 天清理） |

## 8. 相关文档导航

| 文档 | 用途 |
|------|------|
| `ai/PROJECT_MAP.md` | AI 导航第一站（问题 → 层/模块/入口） |
| `ai/MODULE_MAP.md` | AI 模块地图（问题 → 相关文件） |
| `ai/COMMAND_MAP.md` | CLI 命令速查 |
| `ai/DATA_FLOW.md` | 数据流与落盘位置 |
| `developer_guide.md` | 开发者指南（环境/质量门/How-To） |
| `api.md` | 公开 API 参考（protocols 契约） |
| `user_guide.md` | 用户操作指南 |
| `constitution/rule.md` | 宪法（28 条） |
