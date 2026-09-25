# 文档重建追踪器 / Documentation Rebuild Tracker

> 方法论来源：文档重建流程（Phase 0-6），从"代码 → 架构 → 文档 → 操作手册"逐层恢复知识体系。
>
> 创建时间：2026-08-01
> **上次全量校对：2026-09-25**（按代码/文件系统实测重核，修正清单见文末）
> 当前状态：**Phase 0-6 全部完成**，文档体系已重建。本文件转为「重建历史记录 + 现状实测快照」用途，
> 不再作为待办清单。计数规则：目录文件数 = 该层非 `__init__.py` 的一级 `.py` 文件数。

---

## 校对结论（2026-09-25）

本次逐条核对发现并修正了四类问题：

1. **头部状态自相矛盾**：原写「最后更新 2026-08-01 / 当前阶段 Phase 1 — 代码地图」，
   而 Phase 2-6 均标注已完成，且在 Phase 3 之后又出现两份「全部完成 ✅」。现合并为一份。
2. **计数全面过时**：源文件 337 → 378、代码行数 ~67,000 → 86,717、测试 1049+ → 1,823 个 test 函数、
   CLI 20+ → 26 个顶层命令、docs 根目录 5 → 10 个 `.md`。§0.1、Phase 2 各表已按实测更新。
3. **Phase 4 调用链有 3 处与代码不符**（已修，详见该节）：
   - 策略选择写成「三级回退 APPROVED → RESEARCH → 兜底 momentum_vol_full」，实际是 ADR-031 Policy A 严格只跑 APPROVED，无回退；
   - 调仓日写成 `today.day ≤ 5`，实际自 V2.2 起是「每月第一个真实交易日」；
   - Step 编号漏了 1.5 / 1.6，且 Shadow/NAV 已从 12.8 / 12.9 变为 **13.1 / 13.2**。
4. **归档动作已完成但文件仍写着"待归档"，且对 `rule.md` 的判定与现行地位相反**：
   原判「`rule.md` 被 `constitution-v4.2.md` 取代」——实际 `docs/constitution/rule.md` 是**权威完整版宪法**，
   `constitution-v4.2.md` 是精简版（见 `AGENTS.md` 附录 C）。已纠正。

---

## 目标状态（2026-09-25 实测）

```
Project
├── README.md                          ✅ 存在（2.6 KB）
├── CLAUDE.md                           ✅ 存在（7.9 KB，AI 辅助开发入口）
├── AGENTS.md                          ✅ 存在（Agent 行为规范，2026-09 新增）
│
├── docs/                              （.md 共 119 份；根目录 10 份）
│   ├── user_guide.md                  ✅ 完成（18 章，2026-09-25 更新）
│   ├── developer_guide.md             ✅ 511 行
│   ├── api.md                         ✅ 435 行
│   ├── architecture.md                ✅ 166 行
│   ├── module_overview.md             ✅ 147 行
│   ├── workflow.md                    ✅ 160 行
│   ├── strategy_research.md           ✅ 133 行
│   ├── investigation_portfolio_leak.md ✅ 178 行
│   ├── 与QuantTrading差异对照.md       ✅ 226 行
│   ├── doc_rebuild_tracker.md         ← 本文件
│   │
│   ├── constitution/                  ✅ rule.md（742 行，权威完整版）+ constitution-v4.2.md（149 行，精简版）
│   ├── archive/adr/                   ✅ 33 份（ADR-001 ~ ADR-033）
│   ├── tdr/                           ✅ 10 份（TDR-001 ~ TDR-010）
│   ├── architecture/<layer>/          ✅ DP-001 ~ DP-010（10 份，按层分目录）
│   ├── architecture/reference/        ✅ twelve-layer-overview.md
│   ├── implementation/                ✅ coding-style / naming / testing（3 份）
│   ├── ai/                            ✅ PROJECT_MAP / MODULE_MAP / COMMAND_MAP / DATA_FLOW / QUANT_VERIFICATION_CHECKLIST
│   ├── tracking/                      ✅ 专项追踪（含 rolling_ic_false_stale.md）
│   └── archive/                       ✅ 66 份历史文档（adr/ dp.md duplicates/ gap_trackers/ notes/ old_plans/）
```

---

## Phase 0: 现状摸底 [已完成]

### 0.1 项目规模（2026-09-25 实测）

| 指标 | 2026-08-01 记录 | 2026-09-25 实测 |
|------|------|------|
| Python 源文件（`qp/`） | 337 | **378** |
| 代码行数 | ~67,000 | **86,717** |
| 测试文件 / test 函数 | `tests/` 1049+ | **75 个文件 / 1,823 个 `def test_`** |
| 层数 | 12 层（全部实现） | 12 层（全部实现，不变） |
| CLI 命令 | 20+ | **26 个顶层命令 + 47 个 Click 子命令**（另有 `qp pipeline list` 走 argv 分发） |
| 文档 | 70+ .md | **119 份 .md**（docs 根目录 10 份） |

### 0.2 代码结构（12 层架构，路径已实测存在）

```
qp/
├── platform/          L1: 运行时基础设施（config, logging, scheduler, storage, CLI, pipeline engine）
├── data/              L2: 可信数据产品（adapter, dataset, loader, feature_store, fundamental, valuation）
├── research/          L3: 可复现实验（feature, label, trainer, experiment, evaluation, split）
├── validation/        L4: 门控（checks, rule engine）
├── strategy/          L5: 投资策略（signal, ensemble, runner, strategies）
├── portfolio/         L6: 组合构建（allocator, constraints, exposure, optimization, sizing）
├── simulation/        L7: 模拟交易（broker, slippage, shadow_ledger）
├── decision/          L8: 可审计决策（engine, decision_package, position_ledger, state_machine）
├── monitoring/        L9: 只观察不决策（drift, kill switch, health, factor health）
├── knowledge/         L10: 长期记忆（archive, failure_analysis, cluster_analyzer, version_tree）
├── shared/           跨层共享（protocols, types, constants, exceptions）
├── web/              Web UI（routers 14, services 7, templates, static+spa）
└── pipeline/         管道编排（daily_pipeline, multifactor_pipeline, fundamental_pipeline, …）
```

### 0.3 文档清单与状态判定 [已执行完毕]

原表是 2026-08-01 的「待归档」清单；**归档动作已全部完成**。下表给出当前实际位置。

#### ✅ 权威文档（保留，实测存在）

| 文件 | 现状 |
|------|------|
| `CLAUDE.md` / `README.md` | ✅ 仓库根目录（7.9 KB / 2.6 KB） |
| `constitution/rule.md` | ✅ 742 行 — **权威完整版宪法**（28 条） |
| `constitution/constitution-v4.2.md` | ✅ 149 行 — 精简版 |
| `archive/adr/ADR-001 ~ ADR-033` | ✅ 33 份 |
| `tdr/TDR-001 ~ TDR-010` | ✅ 10 份 |
| `architecture/<layer>/DP-001 ~ DP-010` | ✅ 10 份 + reference/twelve-layer-overview.md |
| `implementation/coding-style.md` / `naming.md` / `testing.md` | ✅ 128 / 77 / 174 行 |
| `ai/`（4 张地图 + 量化验证清单） | ✅ 2026-09 新增，Agent 导航层 |

#### ✅ 已归档（原判"需归档"，动作已完成）

| 文件 | 现有位置 |
|------|----------|
| `dp.md`（1229 行） | `archive/dp.md` |
| `plan.md` / `plan_v1.md` / `progress.md` / `PHASE1_ROADMAP.md` / `strategy_freeze_roadmap.md` | `archive/old_plans/` |
| `phase2_gap_tracking.md` / `11_12_gap_tracking.md` / `data_layer_progress.md` | `archive/old_plans/` |
| `gap_analysis.md` | `archive/old_plans/` |
| 6 份 `*_gap_tracker.md`（research / strategy_engine / portfolio_risk / capital_allocation / validation_gate / registry_lineage） | `archive/gap_trackers/` |
| `test.md`（540 行）/ `low_vol_reversal_发现报告.md` / `credibility_check.md` | `archive/notes/` |
| `量化投资买卖规则说明书.md`（464 行） | `archive/notes/` |
| `4_Registry_LineageLayer.md` ~ `8_Capital_Allocation_Layer.md`（5 份） | `archive/notes/` |
| `data_layer.md` / `research_layer.md` | `archive/notes/` |
| `comparison_qp_vs_quanttrading.md` / `qtvsQuantTrading.md` | `archive/duplicates/` |

#### ✅ 已融合 / 已消失

| 文件 | 结局 |
|------|------|
| `使用指南.md`（941 行） | **已不存在** — Phase 5 融合进 `user_guide.md` |
| `量化投资买卖规则说明书.md` | 内容并入 `user_guide.md` 第 4 章，原件归档 |
| `与QuantTrading差异对照.md` | 保留在 docs 根目录（226 行） |

> ⚠️ `rule.md` 判定纠正：原表把 `rule.md`（787 行）判为「被 constitution-v4.2.md 取代，需归档」。
> 实际它现在是 `docs/constitution/rule.md`（742 行）**完整版宪法**，是权威；v4.2 是精简版。

---

## Phase 1: 代码地图 [已完成]

### 1.1 入口

| 入口 | 文件 | 说明 |
|------|------|------|
| CLI 入口 | `qp/platform/cli/main.py:main()` | 唯一入口点（ADR-002） |
| Web 入口 | `qp/web/app.py` | FastAPI 应用（页面式 `/` + SPA `/proto/`） |
| Pipeline 入口 | `qp/platform/pipeline/runner.py:PipelineRunner` | 管道执行器 |

### 1.2 核心类地图（路径已逐个实测存在）

| 类 | 位置 | 层级 |
|----|------|------|
| `Config` | `platform/config/models.py` | L1 |
| `StorageFactory` | `platform/storage/factory.py` | L1 |
| `JobRegistry` | `platform/scheduler/registry.py` | L1 |
| `PipelineRunner` | `platform/pipeline/runner.py` | L1 |
| `ExperimentTracker` | `research/experiment/tracker.py` | L3 |
| `FeatureRegistry` | `research/feature/registry.py` | L3 |
| `ModelRegistry` | `research/trainer/registry.py` | L3 |
| `LightGBMRankModel` | `research/trainer/lgb_rank.py` | L3 |
| `StrategyMonitor` | `monitoring/strategy_monitor.py` | L9 |
| `StrategyHealthLogger` | `monitoring/strategy_health_logger.py` | L9 |
| `KillSwitchPipeline` | `monitoring/kill_switch_pipeline.py` | L9 |
| `MonthlyRetrainPipeline` | `research/trainer/auto_retrain.py` | L3 |

### 1.3 CLI 命令地图（26 个顶层命令，2026-09-25 `qp --help` 实测）

> 原表列出的 `qp backtest run` 从不存在（CLI 无 `cmd_backtest`）。
> 该幽灵命令已在 2026-09-25 从 `meta.py` 死代码与本文档中清除；权威版见 `docs/ai/COMMAND_MAP.md`。

```
qp
├── version, doctor
├── data fetch, index
├── ingest, capital-flow, fundamental, industry heat
├── run daily, pipeline list
├── validate
├── decide
├── factor list, health, report, update-health, validate, compute, catalog, register
├── experiment list, show, run, compare, validate, clean, optuna
├── model list, show, retrain
├── strategy list, approve, approved, deactivate
├── proposal list, show, create, approve, reject, withdraw
├── portfolio report, risk
├── position list, show, close, pnl, history
├── paper start, status
├── simulation shadow
├── monitor check, regime, alert-test
├── knowledge stats, search
├── lineage snapshot
├── web start
├── scheduler start
```

---

## Phase 2: 模块地图 [已完成]

按层级逐一建立：模块 → 子模块 → 文件数 → 核心功能。
**下表文件数为 2026-09-25 实测（非 `__init__.py` 的一级 `.py`）**，括号内为 2026-08-01 旧值。

### 2.1 Platform 层 (L1) — 运行时基础设施

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `platform/config/` | 4 | `Config`, `ProjectConfig`, `StorageConfig`, `LoggingConfig` | 4 层优先级配置（CLI > env > config.toml > defaults），启动后冻结 |
| `platform/logging/` | 3 | Loguru 集成 | 统一日志，禁止 `print()` |
| `platform/storage/` | 4 | `StorageFactory`, `DuckDBStorage`, `SQLiteStorage`, `ParquetStorage` | 多后端存储工厂（不提供业务 Repository） |
| `platform/scheduler/` | 4 | `JobRegistry` | systemd timer → CLI → APScheduler → Job |
| `platform/pipeline/` | 4 | `PipelineRunner`, `PipelineContext`, `BasePipeline` | 管道引擎，所有长运行任务都是 Pipeline |
| `platform/cli/` | 2 + 21（旧 2+18） | `main()`, `cmd_*` | 单入口 CLI（ADR-002），无第二个入口点 |
| `platform/runtime/` | 5 | 状态机 CREATED→…→TERMINATED | 应用生命周期 + 组合根 |
| `platform/metadata/` | 3 | 版本/环境元数据 | 运行时元信息 |
| `platform/proposals/` | 2 | `StrategyProposal`, `ProposalStore` | 策略生命周期审批流程 |
| `platform/alert/` | 0（bridge） | re-export from `monitoring.alerts` | 桥接层，兼容旧 import 路径 |

### 2.2 Data 层 (L2) — 可信数据产品

| 子模块 | 文件数 | 核心功能 |
|--------|--------|----------|
| `data/adapter/` | 5（旧 7） | 数据源适配器（腾讯 / AkShare / Sina / Demo），消费者不知道源 |
| `data/loader/` | 2（旧 4） | 数据加载器，从 Parquet/DuckDB 加载 |
| `data/dataset/` | 3（旧 1） | 数据产品定义 + 复权因子 / 指数 provider |
| `data/feature_store/` | 7 | 特征存储 + 因子计算（动量、波动率、反转等） |
| `data/fundamental/` | 2 | 基本面数据 |
| `data/valuation/` | 1（旧 2） | PE/PB 估值计算（PIT 对齐） |
| `data/calendar/` | 1 | A 股交易日历（`first_trading_day_of_month`，调仓日判定依赖） |
| `data/universe/` | 4 | 股票池定义与筛选 |
| `data/cleaning/` | 5 | 数据清洗管道 |
| `data/validation/` | 7 | 数据质量验证（pandera schema） |
| `data/metadata/` | 3 | 数据血缘与元信息 |
| `data/industry/` | 3（旧 2） | 行业分类映射 |
| `data/corporate_action/` | 1 | 公司行为（分红、拆股、复权） |
| `data/capital_flow/` | 2 | 资金流向数据 |
| `data/contract/` | 1 | 数据合约（接口约定） |
| `data/builder/` | 3 | 数据产品构建器 |

### 2.3 Research 层 (L3) — 可复现实验

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `research/feature/` | 11（旧 7） | `FeatureRegistry`, 因子类（momentum / volatility / volume / money_flow / quality / interaction） | 特征工程：动量、反转、波动率、量能、资金流、质量 |
| `research/label/` | 2 | 标签构建 | 未来收益率标签 |
| `research/trainer/` | 4（旧 3） | `LightGBMRankModel`, `ModelRegistry`, `MonthlyRetrainPipeline` | LightGBM Rank 训练 + 模型注册 + 自动重训 |
| `research/evaluation/` | 11（旧 2） | `LayeredTest` + 诊断脚本（IC / 分层 / 增量归因 / 分位） | 评价与诊断 |
| `research/experiment/` | 4（旧 5） | `ExperimentTracker`, `ExperimentConfig` | 实验记录、追踪、快照、恢复 |
| `research/split/` | 1 | `PurgedKFold` | Purged K-Fold 交叉验证（ADR-021 强制） |
| `research/importance/` | 1 | SHAP | 特征重要性分析 |
| `research/pipeline/` | 1 | `FeaturePipeline` | 研究管道编排 |
| `research/artifact/` | 1 | 实验产物管理 | 模型文件、报告存储 |
| `research/dataset/` | 1 | 研究数据集 | 实验用数据集封装 |

### 2.4 Validation 层 (L4) — 门控

| 子模块 | 文件数 | 核心功能 |
|--------|--------|----------|
| `validation/checks/` | 6 | 16 项检查，4 阶段：Factor(6) + Backtest(4) + Overfit(2) + PaperTrading(3) + Shadow→Prod(2) + Process(2) |
| `validation/engine.py` | 1 | `RuleEngine` — 规则引擎执行所有检查 |
| `validation/result.py` | 1 | `ValidationResult` — 门控结果（pass/fail + 详情） |
| `validation/pipeline.py` | 1 | `ValidationPipeline` — 验证管道 |

### 2.5 Strategy 层 (L5) — 投资策略

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `strategy/signal/` | 4 | `SignalGenerator`, `GeneratorConfig` | 信号生成（Alpha → Signal） |
| `strategy/ensemble/` | 2 | `EnsembleEngine`, `WeightEngine`, `WeightMethod` | 多策略信号融合 |
| `strategy/runner/` | 1 | 策略执行器 | 运行策略并产生结果 |
| `strategy/strategies/` | 7（旧 5） | 具体策略实现（momentum_vol_full / alpha_multi_factor / lvr_* / ensemble_v*） | 各类投资策略 |
| `strategy/models/` | 2 | `AlphaSignal`, `AlphaSignalBatch`, `StrategyResult` | 策略领域模型 |
| `strategy/`（flat） | 13（旧 12） | `StrategyRegistry`, `MarketRegimeDetector`, `PaperTrading`, `multifactor`, `config` | 策略加载、注册、市场状态、纸交易 |

### 2.6 Portfolio 层 (L6) — 组合构建与风控

| 子模块 | 文件数 | 核心类 | 功能 |
|--------|--------|--------|------|
| `portfolio/allocator/` | 5 | `EqualWeightAllocator`, `KellyAllocator`, `RiskParityAllocator`, `VolatilityTargetAllocator` | 资金分配策略 |
| `portfolio/optimization/` | 1 | `PortfolioOptimizer` | 组合优化器 |
| `portfolio/constraints/` | 1 | `TrimAndRefill` | 约束：换仓限制 |
| `portfolio/exposure/` | 3 | `FactorExposureAnalyzer`, `MarketCapExposure`, `LiquidityExposure` | 风险暴露分析 |
| `portfolio/sizing/` | 2 | 仓位计算 | 个股权重计算 |
| `portfolio/budget/` | 3 | `RiskBudget`, `VaRBudget`, `CVaRBudget`, `VolatilityBudget` | 风险预算 |
| `portfolio/cash/` | 2 | `CashManager`, `CashDecision` | 现金管理 |
| `portfolio/models/` | 4 | `AllocationResult`, `PortfolioState` | 组合领域模型 |
| `portfolio/`（flat） | 15 | `CapitalAllocator`, `RiskManager`, `CostModel`, `PortfolioMetrics`, `NAVLedger`, `CorrelationAnalyzer`, `IndustryMapper`, `risk_exit`, `exit_signals` | 组合核心：资金分配、风控、成本、绩效、NAV、退出引擎 |

### 2.7 Simulation 层 (L7) — 模拟交易

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `simulation/broker.py` | `SimulatedBroker`, `Position`, `Trade` | 模拟券商：订单执行、持仓管理 |
| `simulation/slippage.py` | `FixedSlippage`, `SqrtImpactModel`, `VolatilitySlippage` | 滑点模型 |
| `simulation/result.py` | `SimulationResult` | 模拟结果 |
| `simulation/shadow_ledger.py` | `ShadowLedger` | 影子账本（假钱按决策包建仓，与实盘解耦） |

### 2.8 Decision 层 (L8) — 可审计决策

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `decision/engine.py` | `DecisionEngine` | 决策引擎：信号 → 交易建议 |
| `decision/models.py` | `DecisionReport`, `TradeRecommendation` | 决策模型 |
| `decision/decision_package.py` | `DecisionPackage` | 决策包（每日输出） |
| `decision/position_ledger.py` | `PositionLedger` | 持仓账本（WebUI approve 会写它） |
| `decision/state_machine.py` | 状态机 | 决策生命周期状态 |

### 2.9 Monitoring 层 (L9) — 只观察不决策

18 个模块（旧表只列了 14 个，补因子健康 4 件套）：

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `monitoring/alerts.py` | `AlertManager`，7 个通道类（Terminal / Log / Telegram / DingTalk / WeCom / Email / File） | 告警系统；实际启用哪些由配置注册决定 |
| `monitoring/drift.py` | `DriftMonitor`, `DriftReport` | 特征/预测分布漂移（PSI） |
| `monitoring/kill_switch.py` | `KillSwitch` + 7 个 Trigger | 熔断开关 |
| `monitoring/kill_switch_pipeline.py` | `KillSwitchPipeline` | 熔断管道（09:07 full / 16:53 fast） |
| `monitoring/model_decay.py` | `ModelDecayDetector` | 模型衰减检测（滚动 IC） |
| `monitoring/model_decay_lifecycle.py` | `ModelDecayLifecycle` | 衰减 → 策略生命周期联动 |
| `monitoring/regime.py` | `MarketRegimeEngine` | 市场状态检测 |
| `monitoring/strategy_monitor.py` | `StrategyMonitor`, `StrategyHealth` | 策略健康监控 |
| `monitoring/strategy_health_logger.py` | `StrategyHealthLogger` | 健康分记录 |
| `monitoring/strategy_health_report.py` | `StrategyHealthReport` | 健康报告生成 |
| `monitoring/factor_health.py` | 因子健康判定 | 滚动 IC / IC_IR / 衰减斜率 → 生命周期 |
| `monitoring/factor_health_logger.py` | `FactorHealthLogger` | 因子健康快照读写 |
| `monitoring/factor_health_pipeline.py` | 因子健康管道 | 全量重算 / 增量更新 |
| `monitoring/factor_report.py` | 因子研究报告 | Markdown 报告生成 |
| `monitoring/health_logger.py` | `SystemHealthLogger` | 系统健康日志 |
| `monitoring/online_monitor.py` | `OnlineSignalMonitor` | 在线信号质量监控（ADR-031） |
| `monitoring/retrain_signal.py` | `RetrainSignalLogger` | 重训信号触发与去重 |
| `monitoring/system_state.py` | `SystemStateManager` | 系统状态机（NORMAL/WARNING/PAUSED/STOPPED/RECOVERY） |

### 2.10 Knowledge 层 (L10) — 长期记忆

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `knowledge/archive.py` | `KnowledgeArchive`, `KnowledgeEntry`, `KnowledgeCategory` | 知识归档（Markdown + YAML） |
| `knowledge/decision_audit_logger.py` | `DecisionAuditLogger` | 交易决策审计（T2 表） |
| `knowledge/failure_archive_logger.py` | `FailureArchiveLogger` | 止损/黑天鹅事件记录（T3 表） |
| `knowledge/regime_notes.py` | `RegimeNoteLogger` | 市场状态 ↔ 策略表现笔记 |
| `knowledge/cluster_analyzer.py` | `FailureClusterAnalyzer` | 失败聚类分析 |
| `knowledge/version_tree.py` | Version Tree | 知识版本树 |

### 2.11 Pipeline 编排层

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `pipeline/daily_pipeline.py` | `DailyPipeline` | 每日投资管道：数据→因子→特征→策略→风控→决策→影子/NAV |
| `pipeline/multifactor_pipeline.py` | `MultifactorPipeline` | 多因子实验管道：数据→特征→训练→评估→Gate→注册 |
| `pipeline/fundamental_pipeline.py` | `FundamentalPipeline` | 基本面数据管道 |
| `pipeline/factor_calc_pipeline.py` | — | 每日因子值计算（→ `factor_values_daily.parquet`） |
| `pipeline/capital_flow_pipeline.py` | — | 资金流数据管道 |

### 2.12 Web UI 层

| 子模块 | 文件数 | 功能 |
|--------|--------|------|
| `web/app.py` | 1 | FastAPI 应用入口（挂载 `/proto` SPA + routers） |
| `web/routers/` | 14（旧 10） | dashboard, decisions, experiments, factors, health, models, paper, portfolio, proposals, simulation, stocks, strategies, **api_v1**（SPA 的 JSON 端点）, _templates |
| `web/services/` | 7（旧 4） | data_quality, decision, experiment, factor_health, health, position, stock |
| `web/templates/` | — | Jinja2 模板（页面式旧 UI） |
| `web/static/` + `web/static/spa` | — | 静态资源 + SPA 构建产物（`scripts/spa_deploy.sh` 生成） |

### 2.13 Shared 共享层

| 子模块 | 文件数 | 内容 |
|--------|--------|------|
| `shared/protocols/` | 11 | 抽象接口：`BaseStrategy`, `BaseModel`, `BasePipeline`, `BaseStorage`, `BaseBroker`, `BaseFeature`, `BaseDataSource`, `BaseExperimentTracker`, `BaseCapitalAllocator`, `BasePortfolioRisk`, `BaseRiskModel` |
| `shared/types/` | — | 枚举和类型定义 |
| `shared/constants/` | — | 常量（`DEFAULT_TIMEZONE`、`seed`） |
| `shared/exceptions/` | — | 自定义异常类 |
| `shared/time.py` / `paths.py` / `json_io.py` | — | 时间/路径/JSON 的唯一入口（禁止裸 `now()`、路径字面量、`json.dump`） |

---

## Phase 3: 文档可信度判定 [已完成 — 结论均已落地]

对关键文档做"事实一致性"验证：文档描述 vs 当前代码行为。

### 3.1 `使用指南.md` → 已归档 [结案]

该文件已不存在（Phase 5 融合进 `user_guide.md`），原始 8 条问题随之失效。其中两条需要澄清：

| 原判定 | 复核结论（2026-09-25） |
|--------|------------------------|
| `qp backtest run` 文档列出但 CLI 无 `cmd_backtest` | ✅ **确认是幽灵命令**。已在 2026-09-25 从 `meta.py` 死代码 `cmd_help()`、`user_guide.md`、本文档中清除 |
| 「`cmd_validate()` 不支持 `--stage` 参数」 | ❌ **原判定有误**。`commands/validate.py:33` 明确解析 `--stage` / `--strategy-id` / `--json` |
| 「缺少新命令 `qp shadow run/summary`」 | ⚠️ 命名本身有误：正确用法是 `qp simulation shadow [DATE]`（无参=摘要） |
| 文档末尾被对话内容污染 / 章节编号混乱 | 已随文件归档而消失；`user_guide.md` 于 2026-09-25 重校章节编号（15.x / 16.x） |

### 3.2 `gap_analysis.md` → 已归档 [结案]

已归档至 `docs/archive/old_plans/gap_analysis.md`（172 行）。
原判定「22 个 gap 中至少 10+ 已修复，保留会误导」成立，归档动作已完成。

### 3.3 `4_Registry_LineageLayer.md` → 已归档 [结案]

已归档至 `docs/archive/notes/4_Registry_LineageLayer.md`（230 行）。
原判定成立：描述的是理论架构（Neo4j / 集中式 LineageGraph），与当前实现（Registry 分散在各层 + `qp lineage snapshot` 生成 DAG）不符，仅作设计讨论记录。

### 3.4 验证汇总（现状）

| 文档 | 判定 | 现状 |
|------|------|------|
| `使用指南.md` | ⚠️ 需更新 | ✅ 已融合进 `user_guide.md`，原件消失 |
| `gap_analysis.md` | 🔴 严重过时 | ✅ 已归档 `archive/old_plans/` |
| `4_Registry_LineageLayer.md` | 🔴 纯设计文档 | ✅ 已归档 `archive/notes/` |
| `5_Validation_Gate_Research_Review_Process.md` | 待验证 | ✅ 已归档 `archive/notes/`（198 行，设计笔记） |
| `6_Strategy_Engine.md` | 待验证 | ✅ 已归档 `archive/notes/`（426 行，设计笔记） |

---

## Phase 4: 核心工作流 — `qp run daily` 调用链 [已完成，2026-09-25 重核]

完整追踪从 CLI 入口到 DecisionPackage 输出的管道。**步骤编号与行号均为 2026-09-25 实测**
（旧版漏了 1.5 / 1.6，且 Shadow/NAV 已从 12.8 / 12.9 迁到 **13.1 / 13.2**）。

### 4.1 调用链全景图

```
qp run daily [--demo] [--skip-fetch] [--skip-factor-calc] [--force-rebalance]
│
└── cmd_run()                                    # CLI 入口: qp/platform/cli/commands/ingest.py:112
    │   PipelineContext(pipeline_name="daily", parameters={demo, skip_fetch, start_date})
    │
    └── DailyPipeline.run(context)               # 主管道: qp/pipeline/daily_pipeline.py:199
        │
        ├── [Step 0]    SystemStateManager.current()      # :246 系统状态检查（PAUSED+ → 跳过全部）
        │
        ├── [Step 1]    DataPipeline.run()                # :282 数据摄入（--skip-fetch 可跳过）
        │
        ├── [Step 1.5]  Factor Calculator                 # :297 → factor_values_daily.parquet
        │
        ├── [Step 1.6]  因子健康增量更新（DP-002 v4）      # :326 → factor_health.parquet
        │
        ├── [Step 2]    FeaturePipeline.run()             # :351 特征计算
        │
        ├── [Step 3]    _load_price_data()                # :361 价格 + 指数代理 + 基本面
        │
        ├── [Step 4]    _build_lineage_snapshot()          # :379 数据血缘快照
        │
        ├── [Step 5]    MarketRegimeDetector.detect()      # :387 市场状态 + effective_top_n
        │
        ├── [Step 6]    策略发现（ADR-031 快速通道）        # :437
        │   │   ★ 严格 Policy A：只取 lifecycle == APPROVED 的策略
        │   │     无 APPROVED → 跳过当日策略执行 + 告警，不退回 research、无兜底
        │   │     权重取 registry.get_approved() 冻结快照（不读可变 meta）
        │   └── compute_today_scores_full()                # 只算今日截面 O(stocks)
        │       MultiFactorStrategy.from_today_scores()
        │
        ├── [Step 7]    每日策略状态（替代完整 Gate）       # :585
        │
        ├── [Step 7.5]  Daily Quality Gate                 # :605
        │           → regime ∈ dangerous_regimes 且 confidence > 70% → BLOCKED，跳过当日交易
        │
        ├── [Step 8]    策略执行                            # :655
        │   │   strategy.generate_signals(today)
        │   └── [Step 8.5] StrategyHealthLogger             # :671 健康分 0-100 + 报告
        │
        ├── [Step 9]    EnsembleEngine.fuse()               # :749 等权融合所有 APPROVED 策略
        │           → UniversePolicy.FILL_ZERO / WeightMethod.EQUAL
        │
        ├── [Step 10]   PortfolioRiskManager.apply_risk_limits_with_prices()   # :802
        │           → 单票/行业上限、相关性检查 → RiskAudit(violations, dropped, exposure)
        │
        ├── [Step 10.5] OnlineSignalMonitor.check()         # :861 全截面 IC 采样（ADR-031）
        │
        ├── [Step 11]   CostModel.estimate_trade()          # :915 佣金/印花税/冲击成本
        │
        ├── [Step 12]   CapitalAllocator.run()              # :939 ★ 仅调仓日
        │           → 等权 / 风险平价 / 凯利 → TargetPortfolio → BUY Orders
        │
        ├── [Step 12.5] Exit Engine（V2.1 Final）           # :1036 三类退出信号
        │   ├── 第二类 Risk Exit（每日必检）: RiskExitManager.evaluate_daily()
        │   │   → 止损 -10% / ST / 退市 / 停牌 / 流动性
        │   ├── 第一类 Rank Exit（仅调仓日）: Top10 买入 / 11-20 缓冲 / >20 卖出
        │   ├── 第三类 Sector Overconcentration（仅调仓日）: 单行业 > 40% → 降仓
        │   ├── 第三类 Fundamental Deterioration（仅调仓日）: FundamentalExitDetector
        │   └── V2.1 Merge: 同 symbol 合并为单条 SELL + 保留全部 reason tags，按优先级排序
        │
        ├── [Step 13]   DecisionPackage 构建与持久化        # :1252
        │   ├── DecisionEngine.generate() → BUY 建议（仅调仓日）
        │   ├── + SELL 建议（来自 Exit Engine）
        │   └── → data/decisions/dp-{date}-{run_id}.json
        │         data/decisions/{date}.md
        │         data/decisions/index.json
        │
        ├── [Step 13.1] ShadowLedger.run_daily()            # :1389 影子盘（假钱，按决策包建仓）
        │
        └── [Step 13.2] NAVLedger.record_daily()            # :1414 组合 NAV 记录（KPI 追踪）
```

### 4.2 关键决策点

**调仓日 = 每月第一个真实交易日**（V2.2，`daily_pipeline.py:215-239`）。
旧版实现用 `today.day <= 5`（自然日窗口），导致每月 1-5 号连续调仓；
现仅在 akshare 日历不可用时才退回 `day <= 5` 近似并打 warning。

| 决策点 | 调仓日 | 非调仓日 |
|--------|--------|----------|
| BUY 信号 | ✅ 生成 | ❌ 跳过 |
| Rank Exit | ✅ 检查 | ❌ 跳过 |
| Risk Exit | ✅ 检查 | ✅ 检查 |
| Sector Exit | ✅ 检查 | ❌ 跳过 |
| Fundamental Exit | ✅ 检查 | ❌ 跳过 |
| Capital Allocation | ✅ 执行 | ❌ 跳过 |
| Regime Gate | ✅ 检查 | ✅ 检查 |
| Strategy Health | ✅ 记录 | ✅ 记录 |
| Shadow Production（13.1） | ✅ 运行 | ✅ 运行 |
| NAV Recording（13.2） | ✅ 记录 | ✅ 记录 |

### 4.3 数据流

```
DataPipeline ──→ Factor Calc (1.5) ──→ FeaturePipeline ──→ Price Data ──→ Today Signals
                                                        │
                                          ┌─────────────┴─────────────┐
                                          ▼                           ▼
                                  Strategy Discovery            Market Regime
                                 (APPROVED only, ADR-031)       (Step 5)
                                          │                           │
                                          ▼                           ▼
                                   Strategy Signals             Regime Gating (7.5)
                                          │                           │
                                          └───────────┬───────────────┘
                                                      ▼
                                              EnsembleEngine.fuse() (9)
                                                      │
                                          ┌───────────┴───────────┐
                                          ▼                       ▼
                                   Risk Management (10)     Online Monitor (10.5)
                                          │                       │
                                          ▼                       ▼
                                   Cost Estimation (11)     Health Report (8.5)
                                          │
                                          ▼
                                   Capital Allocator (12) ──→ Orders (BUY，仅调仓日)
                                          │
                                          ▼
                                   Exit Engine (12.5) ──→ SELL Recommendations
                                          │
                                          ▼
                                   DecisionEngine (13) ──→ DecisionPackage
                                          │
                                          ▼
                                   ┌──────┴──────┐
                                   ▼              ▼
                              dp-*.json      dp-*.md
                                   │
                                   ▼
                              index.json
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
                     Shadow (13.1)     NAV (13.2)
```

### 4.4 涉及的核心模块（按调用顺序）

| 步骤 | 模块 | 文件 |
|------|------|------|
| 入口 | CLI | `qp/platform/cli/commands/ingest.py`（cmd_run） |
| 0 | SystemState | `qp/monitoring/system_state.py` |
| 1 | DataPipeline | `qp/data/pipeline.py` |
| 1.5 | Factor Calc | `qp/pipeline/factor_calc_pipeline.py` |
| 1.6 | Factor Health | `qp/monitoring/factor_health_pipeline.py` |
| 2 | FeaturePipeline | `qp/research/pipeline/feature_pipeline.py` |
| 3 | Price/Fundamental loader | `qp/pipeline/daily_pipeline.py:_load_price_data` |
| 4 | LineageSnapshot | `qp/pipeline/daily_pipeline.py:_build_lineage_snapshot` |
| 5 | MarketRegimeDetector | `qp/strategy/market_regime.py` |
| 6 | StrategyRegistry + compute_today_scores | `qp/strategy/registry.py` + `qp/strategy/multifactor.py` |
| 7 | 每日策略状态（轻量） | 内联 in `daily_pipeline.py` |
| 7.5 | Daily Quality Gate | 内联 in `daily_pipeline.py`（`daily_pipeline.py:616`） |
| 8 | Strategy.generate_signals | `qp/strategy/strategies/` |
| 8.5 | StrategyHealthLogger | `qp/monitoring/strategy_health_logger.py` |
| 9 | EnsembleEngine | `qp/strategy/ensemble/` |
| 10 | PortfolioRiskManager | `qp/portfolio/risk_manager.py` |
| 10.5 | OnlineSignalMonitor | `qp/monitoring/online_monitor.py` |
| 11 | CostModel | `qp/portfolio/cost_model.py` |
| 12 | CapitalAllocator | `qp/portfolio/capital_allocator.py` |
| 12.5 | RiskExitManager + FundamentalExitDetector | `qp/portfolio/risk_exit.py` + `qp/portfolio/exit_signals.py` |
| 13 | DecisionEngine + DecisionPackage | `qp/decision/engine.py` + `qp/decision/decision_package.py` |
| 13.1 | ShadowLedger | `qp/simulation/shadow_ledger.py` |
| 13.2 | NAVLedger | `qp/portfolio/nav_ledger.py` |

---

## Phase 5: 操作指南 [已完成]

- [x] `user_guide.md` — 融合 `使用指南.md` + `量化投资买卖规则说明书.md`，**18 章**（2026-09-25 全文重校：
  修 8 处与代码不符的内容，含 SPA `/proto/` 章节、配置项真实字段、registry 冻结权重、幽灵命令清理）
- [x] `workflow.md` — 每日 / 开发 / 策略上线 / 数据 / 实验五类工作流

---

## Phase 6: 架构文档 [已完成]

### 6.1 已完成的文档

| 目标文件 | 状态 |
|----------|------|
| `developer_guide.md` | ✅ 511 行 |
| `user_guide.md` | ✅ Phase 5 完成（18 章） |
| `architecture/<layer>/DP-001 ~ DP-010` | ✅ 10 份（按层分目录） |
| `architecture/reference/twelve-layer-overview.md` | ✅ 架构总览 |
| `archive/` | ✅ 66 份历史文档已归档（adr/ dp.md duplicates/ gap_trackers/ notes/ old_plans/） |
| `ai/`（PROJECT_MAP / MODULE_MAP / COMMAND_MAP / DATA_FLOW / QUANT_VERIFICATION_CHECKLIST） | ✅ 2026-09 新增，Agent 导航层 |

### 6.2 可选（信息已在其他文档中）

| 目标文件 | 说明 |
|----------|------|
| `architecture.md` | ✅ 已存在（166 行），与 `twelve-layer-overview.md` + ADR 互补 |
| `module_overview.md` | ✅ 已存在（147 行），Phase 2 模块地图的人读版 |
| `workflow.md` | ✅ 已存在（160 行），Phase 4 调用链的操作版 |

---

## 完成清单 [全部完成 ✅]

| # | 阶段 | 内容 | 状态 |
|---|------|------|------|
| 1 | Phase 0 | 现状摸底（70+ → docs 根目录 10 份 .md） | ✅ |
| 2 | Phase 1 | 代码地图 + CLI 地图（26 命令，2026-09-25 重核） | ✅ |
| 3 | Phase 2 | 15 个模块地图（文件数 2026-09-25 重核） | ✅ |
| 4 | Phase 3 | 文档可信度验证（结论已落地：归档 / 融合） | ✅ |
| 5 | Phase 4 | `qp run daily` 调用链（22 个唯一步骤编号：Step 0 → 13.2，2026-09-25 重核） | ✅ |
| 6 | Phase 5 | `user_guide.md`（18 章） | ✅ |
| 7 | Phase 6 | `developer_guide.md` + 10 DP + 10 TDR + 3 impl + constitution | ✅ |
| 8 | — | `api.md`（435 行） | ✅ |
| 9 | — | 归档历史文档（现 `archive/` 66 份） | ✅ |
| 10 | — | 修复 pyright + 6 test failures | ✅ |
| 11 | — | WebUI 健康记录去重 | ✅ |
| 12 | — | 2026-09-25 全量校对（见文首「校对结论」） | ✅ |

---

## 执行记录

| 日期 | 阶段 | 做了什么 |
|------|------|----------|
| 2026-08-01 | Phase 0 | 创建本文档，完成现状摸底 |
| 2026-08-01 | Phase 0 | 完成文档清单与状态判定（70+ 文件 → 5 类） |
| 2026-08-01 | Phase 1 | 完成代码入口分析、核心类地图 |
| 2026-08-01 | Phase 1 | 完成 CLI 命令地图（当时 20+ 命令） |
| 2026-08-01 | 归档 | 20 份过期文档归档 → `docs/archive/` |
| 2026-08-01 | 归档 | docs 根目录从 70+ 降到 15 个 .md 文件 |
| 2026-08-01 | Phase 2 | 完成 12 层 + Pipeline + Web + Shared 共 15 个模块地图 |
| 2026-08-01 | Phase 3 | `使用指南.md` → 判定需更新 |
| 2026-08-01 | Phase 3 | `gap_analysis.md` → 已归档 |
| 2026-08-01 | Phase 3 | `4_Registry_LineageLayer.md` → 已归档 |
| 2026-08-01 | Phase 4 | `qp run daily` 调用链完整追踪（CLI → DecisionPackage） |
| 2026-08-01 | Phase 5 | 融合完成 `user_guide.md`（`使用指南.md` + `量化投资买卖规则说明书.md`） |
| 2026-08-01 | 归档 | 7 份对话体设计文档归档（`5_`~`8_`、`11_12`、`data_layer`、`research_layer`） |
| 2026-08-01 | 文档 | docs 根目录：70+ → 5 个 .md 文件 |
| 2026-08-01 | Phase 6 | `developer_guide.md` 完成（8 章） |
| 2026-08-01 | Phase 6 | 11 个 DP 文件填充完成（DP-001 ~ DP-010 + twelve-layer-overview） |
| **2026-09-25** | **校对** | **全量事实核对：修头部状态矛盾、计数、Phase 4 三处错误、rule.md 判定、归档状态；`qp backtest run` 幽灵命令从 `meta.py` 死代码 + 文档中清除** |

---

## 校对修正清单（2026-09-25）

| # | 位置 | 原文 | 修正为 | 依据 |
|---|------|------|--------|------|
| 1 | 头部 | 最后更新 2026-08-01 / 当前阶段 Phase 1 — 代码地图 | 已全部完成 + 校对日期 2026-09-25 | Phase 2-6 均已完成，原头自相矛盾 |
| 2 | 结构 | 两份「全部完成 ✅」章节 | 合并为一份完成清单 | 内容重复 |
| 3 | 目标状态 | `user_guide.md` ⚠️ 部分（使用指南.md） | ✅ 完成（18 章） | `使用指南.md` 已不存在 |
| 4 | 目标状态 | `adr/` 33 份（ADR-001~030） | 33 份（ADR-001 ~ **ADR-033**） | `ls docs/archive/adr/` = 33，末号为 ADR-033 |
| 5 | 目标状态 | `architecture/` DP-001~DP-010 | `architecture/<layer>/` 分目录 | `find docs/architecture -name "DP-*.md"` |
| 6 | §0.1 | 源文件 337 / 67k 行 / 测试 1049+ / CLI 20+ / 文档 70+ | 378 / 86,717 / 1,823 test 函数 / 26 命令 / 119 .md | 实测 |
| 7 | §0.3 | `rule.md` 被 constitution-v4.2 取代，需归档 | `constitution/rule.md` 是**权威完整版**（742 行） | `AGENTS.md` 附录 C |
| 8 | §0.3 | 17 份文件标「需要归档」（未执行） | 全部已归档，表内给出实际路径 | 逐个 `find` 实测 |
| 9 | §3.1 | 「`cmd_validate()` 不支持 `--stage`」 | 该判定**有误**，`validate.py:33` 支持 | 读代码 |
| 10 | §3.1/3.4 | 使用指南 / gap_analysis / 4_Registry 待处理 | 已归档 / 已融合，结案 | 文件系统实测 |
| 11 | Phase 2 各表 | 15 个子模块文件数过时（如 evaluation 2→11、adapter 7→5、routers 10→14、services 4→7） | 按实测更新，标注计数规则 | `find … \| wc -l` |
| 12 | §2.9 | monitoring 列 14 个模块 | 18 个（补 factor_health / _logger / _pipeline / factor_report） | `ls qp/monitoring/*.py` |
| 13 | Phase 4 | Step 6「三级回退：APPROVED → RESEARCH → 兜底」 | 严格 Policy A：只跑 APPROVED，无回退 | `daily_pipeline.py:459-477` |
| 14 | Phase 4 | Step 12 与 4.2 表头「调仓日 = `today.day ≤ 5`」 | 每月第一个真实交易日（V2.2） | `daily_pipeline.py:215-239` |
| 15 | Phase 4 | Step 编号缺 1.5/1.6；Shadow=12.8 / NAV=12.9 | 补 1.5/1.6；Shadow=**13.1** / NAV=**13.2** | `grep -n "Step " daily_pipeline.py` |
| 16 | Phase 4 | `cmd_run()` 行号 :81、`DailyPipeline.run` 行号 :258 | :112 / :199（并补各 Step 行号） | `grep -n` |
| 17 | §1.3 | CLI 地图含 `backtest run`、漏 6 个命令组 | 按 `qp --help` 实测重写（26 命令） | 实测 |
| 18 | §6.1 | 「归档 32 份」「归档 63 份」不一致 | `archive/` 共 66 份 | `find docs/archive -type f` |
| 19 | §3.1 | `qp shadow run/summary` 记为「新命令」 | 正确用法 `qp simulation shadow [DATE]` | `parser.py:213` |

### 未验证 / 待确认（不虚构）

- Phase 2 中标注「核心类/函数」的条目，只核到**文件存在 + 部分类名**；未逐个核验每个类名在该文件内定义（抽样核对了 §1.2 全部 12 项，均存在）。
- §2.4「16 项检查，4 阶段」的检查项数量未逐个数过，沿用原始记录。
- `archive/` 各文件的**行数**与 2026-08-01 记录有 ±1~3 行差异（如 4_Registry 232→230、data_layer 557→556），未追溯差异来源，故新版只保留状态与路径、不再维护易漂移的行数。
- `monitoring/alerts.py` 定义了 7 个通道类（含 `FileAlert`），但 `user_guide.md` §7.6 写「支持 6 种告警通道」（未列 File）。
  两边不算矛盾（启用取决于配置注册），但措辞不统一，待定稿时统一表述。

---

## 附：实验管道调用链（2026-09-25 沿用，步骤标记未重核）

```
qp experiment run multifactor [options]
  └── cmd_experiment_run() → MultifactorPipeline.run()
       ├── [Stage 1]   _fetch_data() or _load_snapshot()     # 数据获取
       ├── [Stage 2]   _run_full_strategy() or factor_pipeline()  # 因子/策略
       ├── [Stage 3]   evaluate_factor_ic()                  # Rank IC
       ├── [Stage 3.5] _compute_factor_ic_attribution()      # 因子归因
       ├── [Stage 3.6] _optimize_weights_from_ic()           # 权重优化
       ├── [Gate]      compute_layered_returns() + IC Gate   # 门禁
       ├── [Stage 4]   generate_rebalance_signals()          # 信号（legacy）
       ├── [Stage 5]   _compute_backtest()                   # 回测
       ├── [Stage 6]   _benchmark_return()                   # 基准对比
       ├── [Snapshot]  price_data → data/experiments/{id}/   # 数据快照
       ├── [Record]    ExperimentTracker.log_experiment()    # 实验记录
       └── [Register]  StrategyRegistry (if gate_passed)     # 自动注册
```

> `multifactor_pipeline.py` 的 Stage 标记未在本次校对中逐条重核（该文件 2400+ 行）；
> 需要时可单独跑一次 `grep -n "Stage " qp/pipeline/multifactor_pipeline.py` 复核。
