# 文档重建追踪器 / Documentation Rebuild Tracker

> 方法论来源：文档重建流程（Phase 0-6），从"代码 → 架构 → 文档 → 操作手册"逐层恢复知识体系。
>
> 创建时间：2026-08-01
> 最后更新：2026-08-01
> 当前阶段：Phase 1 — 代码地图

---

## 目标状态

```
Project
├── README.md                          ✅ 已存在，基本可用
│
├── docs/
│   ├── architecture.md                ✅ 2026-08-13 从 ADR+DP+PROJECT_MAP 合成
│   ├── module_overview.md             ✅ 2026-08-13 从 MODULE_MAP 提炼人读版
│   ├── workflow.md                    ✅ 2026-08-13 新建（每日/开发/策略上线/数据/实验）
│   ├── user_guide.md                  ⚠️ 部分（使用指南.md）
│   ├── developer_guide.md             ✅ 已存在（511 行，8/1）
│   ├── api.md                         ✅ 已存在（435 行，8/1）
│   │
│   ├── adr/                           ✅ 33 份完整（ADR-001~030 于 2026-08-13 从 dp.md 补全）
│   ├── tdr/                           ✅ 完整（10 份）
│   ├── architecture/                  ✅ 完整（DP-001 ~ DP-010）
│   ├── constitution/                  ✅ 完整（v4.2）
│   ├── implementation/                ✅ 完整（coding-style, naming, testing）
│   │
│   └── archive/                       ✅ 已存在（old_plans 已迁入）
```

---

## Phase 0: 现状摸底

### 0.1 项目规模

| 指标 | 数值 |
|------|------|
| Python 源文件 | 337 |
| 代码行数 | ~67,000 |
| 测试文件 | `tests/` 目录，1049+ 测试 |
| 层数 | 12 层（全部实现） |
| CLI 命令 | 20+ |
| 文档文件 | 70+ .md |

### 0.2 代码结构（12 层架构）

```
qp/
├── platform/          L1: 运行时基础设施（config, logging, scheduler, storage, CLI, pipeline engine）
├── data/              L2: 可信数据产品（adapter, dataset, loader, feature_store, fundamental, valuation）
├── research/          L3: 可复现实验（feature, label, model, trainer, experiment, evaluation）
├── validation/        L4: 门控（checks, rule engine）
├── strategy/          L5: 投资策略（signal, ensemble, runner, strategies）
├── portfolio/         L6: 组合构建（allocator, constraints, exposure, optimization, sizing）
├── simulation/        L7: 模拟交易（broker, slippage, shadow_ledger）
├── decision/          L8: 可审计决策
├── monitoring/        L9: 只观察不决策（drift, kill switch, health）
├── knowledge/         L10: 长期记忆（post_mortem, experiment_summary, failure_analysis）
├── shared/           跨层共享（protocols, types, constants, exceptions）
├── web/              Web UI（routers, services, templates）
└── pipeline/         管道编排（daily_pipeline, multifactor_pipeline）
```

### 0.3 现有文档清单与状态判定

#### ✅ 权威文档（匹配代码，保留）

| 文件 | 大小 | 说明 |
|------|------|------|
| `CLAUDE.md` | 7K | 项目入口指南，AI 辅助开发 |
| `README.md` | 3K | 项目入口 |
| `constitution/constitution-v4.2.md` | - | 项目宪法，最高准则 |
| `adr/ADR-001 ~ ADR-031` | 31 份 | 架构决策记录 |
| `tdr/TDR-001 ~ TDR-010` | 10 份 | 技术决策记录 |
| `architecture/DP-001 ~ DP-010` | 10 份 | 10 层设计提案 |
| `implementation/coding-style.md` | - | 编码规范 |
| `implementation/naming.md` | - | 命名规范 |
| `implementation/testing.md` | - | 测试规范 |

#### ⚠️ 过期/重复（需要归档）

| 文件 | 大小 | 判定理由 |
|------|------|----------|
| `rule.md` | 787 行 | 被 `constitution/constitution-v4.2.md` 取代 |
| `dp.md` | 1229 行 | 设计讨论整理稿，内容已被 ADR+TDR 覆盖 |
| `plan.md` | - | 旧执行计划，已不反映当前状态 |
| `plan_v1.md` | 1025 行 | 旧执行计划 v1，已不反映当前状态 |
| `progress.md` | 346 行 | 旧进度追踪 |
| `phase2_gap_tracking.md` | 266 行 | 旧 gap 追踪 |
| `11_12_gap_tracking.md` | 211 行 | 旧 gap 追踪 |
| `data_layer_progress.md` | 324 行 | 旧进度追踪 |
| `PHASE1_ROADMAP.md` | 362 行 | 旧路线图 |
| `research_layer_gap_tracker.md` | 290 行 | 旧 gap 追踪 |
| `strategy_engine_gap_tracker.md` | 247 行 | 旧 gap 追踪 |
| `portfolio_risk_gap_tracker.md` | 212 行 | 旧 gap 追踪 |
| `capital_allocation_gap_tracker.md` | 211 行 | 旧 gap 追踪 |
| `validation_gate_gap_tracker.md` | 202 行 | 旧 gap 追踪 |
| `registry_lineage_layer_gap_tracker.md` | 194 行 | 旧 gap 追踪 |
| `strategy_freeze_roadmap.md` | 211 行 | 旧路线图 |

#### ⚠️ 专家笔记（需归档到 knowledge/）

| 文件 | 大小 | 说明 |
|------|------|------|
| `test.md` | 540 行 | 某次实验的诊断分析笔记 |
| `low_vol_reversal_发现报告.md` | 267 行 | 因子发现报告 |
| `credibility_check.md` | - | 架构可信性自查 |

#### ⚠️ 用户文档（需更新后保留）

| 文件 | 大小 | 说明 |
|------|------|------|
| `使用指南.md` | 941 行 | 用户操作指南，需验证是否匹配当前 CLI |
| `量化投资买卖规则说明书.md` | 466 行 | 交易规则说明 |

#### ⚠️ 对比文档（可选保留）

| 文件 | 大小 | 说明 |
|------|------|------|
| `comparison_qp_vs_quanttrading.md` | 195 行 | 与 QuantTrading 对比 |
| `qtvsQuantTrading.md` | 505 行 | 同上（重复？） |
| `与QuantTrading差异对照.md` | 226 行 | 同上（中文版） |

#### ⚠️ 层级文档（代码已演进，可能过时）

| 文件 | 大小 | 说明 |
|------|------|------|
| `4_Registry_LineageLayer.md` | 232 行 | 需验证 |
| `5_Validation_Gate_Research_Review_Process.md` | 200 行 | 需验证 |
| `6_Strategy_Engine.md` | 426 行 | 需验证 |
| `7_Portfolio_Risk_Layer.md` | 459 行 | 需验证 |
| `8_Capital_Allocation_Layer.md` | 577 行 | 需验证 |
| `data_layer.md` | 557 行 | 需验证 |
| `research_layer.md` | 520 行 | 需验证 |
| `strategy_research.md` | - | 需验证 |
| `gap_analysis.md` | - | 需验证 |
| `investigation_portfolio_leak.md` | - | 需验证 |

---

## Phase 1: 代码地图 [进行中]

### 1.1 入口

| 入口 | 文件 | 说明 |
|------|------|------|
| CLI 入口 | `qp/platform/cli/main.py:main()` | 唯一入口点（ADR-002） |
| Web 入口 | `qp/web/app.py` | FastAPI/Starlette 应用 |
| Pipeline 入口 | `qp/platform/pipeline/runner.py:PipelineRunner` | 管道执行器 |

### 1.2 核心类地图

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

### 1.3 CLI 命令地图

```
qp
├── version, doctor
├── ingest
├── run daily, fundamental, pipeline
├── validate
├── portfolio report, risk
├── position list, show, close, pnl, history
├── simulation shadow
├── experiment list, show, run, compare, validate, clean
├── model list, show
├── data fetch
├── backtest run
├── monitor check, regime, alert-test
├── knowledge stats, search
├── decide
├── paper start, status
├── web start
├── retrain
├── scheduler start
├── proposal list, show, create, approve, reject
```

---

## Phase 2: 模块地图 [已完成]

按层级逐一建立：模块 → 子模块 → 文件数 → 核心功能。

### 2.1 Platform 层 (L1) — 运行时基础设施

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `platform/config/` | 4 | `Config`, `ProjectConfig`, `StorageConfig`, `LoggingConfig` | 4 层优先级配置（CLI > env > config.toml > defaults），启动后冻结 |
| `platform/logging/` | 3 | `Loguru` 集成 | 统一日志，禁止 `print()` |
| `platform/storage/` | 4 | `StorageFactory`, `DuckDBStorage`, `SQLiteStorage`, `ParquetStorage` | 多后端存储工厂（不提供业务 Repository） |
| `platform/scheduler/` | 4 | `JobRegistry` | systemd timer → CLI → APScheduler → Job |
| `platform/pipeline/` | 4 | `PipelineRunner`, `PipelineContext`, `BasePipeline` | 管道引擎，所有长运行任务都是 Pipeline |
| `platform/cli/` | 2 + 18 | `main()`, `cmd_*` (20+ 命令) | 单入口 CLI（ADR-002），无第二个入口点 |
| `platform/runtime/` | 5 | 状态机 (CREATED→INITIALIZING→READY→RUNNING→STOPPING→TERMINATED) | 应用生命周期 + 组合根 |
| `platform/metadata/` | 3 | 版本/环境元数据 | 运行时元信息 |
| `platform/proposals/` | 2 | `StrategyProposal`, `ProposalStore` | 策略生命周期审批流程 |
| `platform/alert/` | 0 (bridge) | re-export from `monitoring.alerts` | 桥接层，兼容旧 import 路径 |

### 2.2 Data 层 (L2) — 可信数据产品

| 子模块 | 文件数 | 核心功能 |
|--------|--------|----------|
| `data/adapter/` | 7 | 数据源适配器（AkShare 等），消费者永远不知道原始数据源 |
| `data/loader/` | 4 | 数据加载器，从 Parquet/DuckDB 加载 |
| `data/dataset/` | 1 | 数据产品定义（Dataset = 可信的、版本化的数据产品） |
| `data/feature_store/` | 7 + 4 factors | 特征存储 + 因子计算（动量、波动率、反转等） |
| `data/fundamental/` | 2 | 基本面数据（EPS, NAV 等） |
| `data/valuation/` | 2 | PE/PB 估值计算（PIT 对齐） |
| `data/calendar/` | 1 | A 股交易日历 |
| `data/universe/` | 4 | 股票池定义与筛选 |
| `data/cleaning/` | 5 | 数据清洗管道 |
| `data/validation/` | 7 | 数据质量验证 |
| `data/metadata/` | 3 | 数据血缘与元信息 |
| `data/industry/` | 2 | 行业分类映射 |
| `data/corporate_action/` | 1 | 公司行为（分红、拆股、复权） |
| `data/capital_flow/` | 2 | 资金流向数据 |
| `data/contract/` | 1 | 数据合约（接口约定） |
| `data/builder/` | 3 | 数据产品构建器 |

### 2.3 Research 层 (L3) — 可复现实验

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `research/feature/` | 7 | `FeatureRegistry`, `compute_all_factors`, 6 个因子类 | 特征工程：动量(1M/3M/6M/20D)、反转(5D)、波动率(20D/60D) |
| `research/label/` | 2 | 标签构建 | 未来收益率标签 |
| `research/trainer/` | 3 | `LightGBMRankModel`, `ModelRegistry`, `MonthlyRetrainPipeline` | LightGBM Rank 训练 + 模型注册 + 自动重训 |
| `research/evaluation/` | 2 | `LayeredTest` | 分层测试：Rank IC, ICIR, 分层收益, 单调性, 方向正确性 |
| `research/experiment/` | 5 | `ExperimentTracker`, `ExperimentConfig`, `ExperimentRunner` | 实验记录、追踪、快照、恢复 |
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
| `strategy/ensemble/` | 2 | `EnsembleEngine`, `WeightEngine`, `WeightMethod` | 多因子集成融合 |
| `strategy/runner/` | 1 | 策略执行器 | 运行策略并产生结果 |
| `strategy/strategies/` | 5 | 具体策略实现 | 各类投资策略（动量、低波等） |
| `strategy/models/` | 2 | `AlphaSignal`, `AlphaSignalBatch`, `StrategyResult` | 策略领域模型 |
| `strategy/` (flat) | 12 | `StrategyLoader`, `StrategyRegistry`, `MarketRegimeDetector`, `PaperTrading` | 策略加载、注册、市场状态、纸交易 |

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
| `portfolio/` (flat) | 15 | `CapitalAllocator`, `RiskManager`, `CostModel`, `PortfolioMetrics`, `NAVLedger`, `CorrelationAnalyzer`, `IndustryMapper` | 组合核心：资金分配、风险管理、成本模型、绩效指标、NAV 账本 |

### 2.7 Simulation 层 (L7) — 模拟交易

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `simulation/broker.py` | `SimulatedBroker`, `Position`, `Trade` | 模拟券商：订单执行、持仓管理 |
| `simulation/slippage.py` | `FixedSlippage`, `SqrtImpactModel`, `VolatilitySlippage` | 滑点模型 |
| `simulation/result.py` | `SimulationResult` | 模拟结果 |
| `simulation/shadow_ledger.py` | Shadow Ledger | 影子账本（与实盘同步） |

### 2.8 Decision 层 (L8) — 可审计决策

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `decision/engine.py` | `DecisionEngine` | 决策引擎：信号 → 交易建议 |
| `decision/models.py` | `DecisionReport`, `TradeRecommendation` | 决策模型 |
| `decision/decision_package.py` | `DecisionPackage` | 决策包（每日输出） |
| `decision/position_ledger.py` | `PositionLedger` | 持仓账本 |
| `decision/state_machine.py` | 状态机 | 决策生命周期状态 |

### 2.9 Monitoring 层 (L9) — 只观察不决策

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `monitoring/alerts.py` | `AlertManager`, 7 通道（Terminal, Log, Telegram, Email, DingTalk, WeCom, File） | 告警系统 |
| `monitoring/drift.py` | `DriftMonitor`, `DriftReport` | 特征/预测分布漂移检测 |
| `monitoring/kill_switch.py` | `KillSwitch` | 熔断开关 |
| `monitoring/kill_switch_pipeline.py` | `KillSwitchPipeline` | 熔断管道 |
| `monitoring/model_decay.py` | `ModelDecayDetector` | 模型衰减检测（滚动 IC） |
| `monitoring/model_decay_lifecycle.py` | `ModelDecayLifecycle` | 衰减 → 策略生命周期联动 |
| `monitoring/regime.py` | `MarketRegimeEngine` | 市场状态检测 |
| `monitoring/strategy_monitor.py` | `StrategyMonitor`, `StrategyHealth` | 策略健康监控 |
| `monitoring/strategy_health_logger.py` | `StrategyHealthLogger` | 健康分记录 |
| `monitoring/strategy_health_report.py` | `StrategyHealthReport` | 健康报告生成 |
| `monitoring/health_logger.py` | Health Logger | 通用健康日志 |
| `monitoring/online_monitor.py` | Online Monitor | 在线监控 |
| `monitoring/retrain_signal.py` | Retrain Signal | 重训信号触发 |
| `monitoring/system_state.py` | System State | 系统状态检查 |

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
| `pipeline/daily_pipeline.py` | `DailyPipeline` | 每日投资管道：数据→因子→信号→组合→决策→健康检查 |
| `pipeline/multifactor_pipeline.py` | `MultifactorPipeline` | 多因子实验管道：数据→特征→训练→评估→Gate→注册 |
| `pipeline/fundamental_pipeline.py` | `FundamentalPipeline` | 基本面数据管道 |

### 2.12 Web UI 层

| 子模块 | 文件数 | 功能 |
|--------|--------|------|
| `web/app.py` | 1 | FastAPI 应用入口 |
| `web/routers/` | 10 | 页面路由：dashboard, experiments, models, strategies, proposals, portfolio, decisions, simulation, health, templates |
| `web/services/` | 4 | 业务服务：data_quality, decision, experiment, health |
| `web/templates/` | - | Jinja2 模板（15+ 页面） |
| `web/static/` | - | CSS, JS 静态资源 |

### 2.13 Shared 共享层

| 子模块 | 文件数 | 内容 |
|--------|--------|------|
| `shared/protocols/` | 11 | 抽象接口：`BaseStrategy`, `BaseModel`, `BasePipeline`, `BaseStorage`, `BaseBroker`, `BaseFeature`, `BaseDataSource`, `BaseExperimentTracker`, `BaseCapitalAllocator`, `BasePortfolioRisk`, `BaseRiskModel`, `BaseCorporateAction` |
| `shared/types/` | - | 枚举和类型定义 |
| `shared/constants/` | - | 常量（`DEFAULT_TIMEZONE` 等） |
| `shared/exceptions/` | - | 自定义异常类 |

---

## Phase 3: 文档可信度判定 [已完成 3/5]

对关键文档做"事实一致性"验证：文档描述 vs 当前代码行为。

### 3.1 `使用指南.md` — ⚠️ 需更新

| 问题 | 严重度 | 详情 |
|------|--------|------|
| 文档末尾被污染 | 🔴 严重 | 第 919-942 行是原始对话记录（`--resume` 功能说明），不是文档内容 |
| 第 590 行混入原始命令 | 🟡 中等 | 表格中混入了 shell 命令文本 |
| `qp backtest run` | 🔴 严重 | 文档列出此命令，但实际 CLI 无 `cmd_backtest` |
| `qp validate --stage` | 🔴 严重 | `cmd_validate()` 不支持 `--stage` 参数 |
| 缺少新命令 | 🟡 中等 | 未记录 `qp shadow run/summary`, `qp proposal *`, `qp strategy *` |
| 引用已归档文件 | 🟡 中等 | 引用 `docs/rule.md`（已归档） |
| 章节编号混乱 | 🟢 轻微 | Section 14 之后出现 15、16、12.1 等不一致编号 |
| 更新日期为 2026-07-23 | 🟡 中等 | 之后有大量 CLI 变更未反映 |

**判定**: 保留但需大幅更新。核心内容 70% 仍然正确，但有一批命令已变化 + 文档被对话内容污染。

### 3.2 `gap_analysis.md` — 🔴 严重过时

| 问题 | 详情 |
|------|------|
| 文档标记 6 个已修复 | 实际上至少 9 个已修复（G-002, G-003, G-011, G-018 也已修复但未更新） |
| G-002 (`platform/alert/`) | ✅ 已修复 — `platform/alert/__init__.py` 存在（bridge 重导出） |
| G-003 (`parser.py` 空) | ✅ 已修复 — `parser.py` 现在是 18KB，使用 Click |
| G-011 (策略提案) | ✅ 已修复 — `platform/proposals/` 实现完整 + CLI `proposal` 命令组 |
| G-018 (experiment CLI) | ✅ 已修复 — `experiment` 命令组完整（run/list/show/compare/clean/validate） |
| G-005 (e2e 测试) | 需验证 |
| G-016 (估值 lookahead bias) | 需验证 |
| 修复建议顺序 | 大量过时 — 前 4 优先项中的 3 个已修复 |

**判定**: 归档。这份文档已完成历史使命（22 个 gap 中至少 10+ 已修复），保留它会误导。

### 3.3 `4_Registry_LineageLayer.md` — 🔴 纯设计文档，非代码文档

| 问题 | 详情 |
|------|------|
| 描述的是理论架构 | Neo4j 图数据库、NetworkX DAG、4 个集中式 Registry |
| 实际代码完全不同 | Registry 分散在各层（FeatureRegistry, ModelRegistry, ExperimentTracker, StrategyRegistry），没有集中式 LineageGraph |
| 实际 Layer 4 是 Validation | 不是 "Registry & Lineage Layer" |
| 包含虚构代码示例 | `LineageRegistry` 类不存在于代码库中 |

**判定**: 归档到 `docs/archive/notes/`。这是一份有价值的设计讨论记录，但绝不应被当作当前代码的文档。

### 3.4 验证汇总

| 文档 | 判定 | 行动 |
|------|------|------|
| `使用指南.md` | ⚠️ 需更新 | 保留，需清理污染 + 更新过时命令 |
| `gap_analysis.md` | 🔴 严重过时 | 归档 |
| `4_Registry_LineageLayer.md` | 🔴 纯设计文档 | 归档 |
| `5_Validation_Gate_Research_Review_Process.md` | 待验证 | — |
| `6_Strategy_Engine.md` | 待验证 | — |

---

## Phase 4: 核心工作流 — `qp run daily` 调用链 [已完成]

完整追踪从 CLI 入口到 DecisionPackage 输出的 13 步管道。

### 4.1 调用链全景图

```
qp run daily [--demo] [--skip-fetch]
│
└── cmd_run()                                    # CLI 入口: qp/platform/cli/commands/ingest.py:81
    │   PipelineContext(pipeline_name="daily", parameters={demo, skip_fetch, start_date})
    │
    └── DailyPipeline.run(context)               # 主管道: qp/pipeline/daily_pipeline.py:258
        │
        ├── [Step 0] SystemStateManager.current()          # 系统状态检查 (PAUSED+ → 跳过全部)
        │
        ├── [Step 1] DataPipeline.run()                    # 数据摄入 (可 --skip-fetch 跳过)
        │
        ├── [Step 2] FeaturePipeline.run()                 # 特征计算 (动量 + 波动率)
        │
        ├── [Step 3] _load_price_data()                    # 加载行情数据
        │           _build_index_df()                      # 构建指数代理 (regime 检测用)
        │           _load_fundamental_data()               # 加载基本面数据
        │
        ├── [Step 4] _build_lineage_snapshot()             # 数据血缘快照 (dataset + feature 版本)
        │
        ├── [Step 5] MarketRegimeDetector.detect()         # 8 种市场状态检测
        │           → bull / sideways_up / sideways_down / neutral / bear / crisis / ...
        │           → suggested_position_pct (仓位建议)
        │           → effective_top_n (根据 regime 调整持仓数)
        │
        ├── [Step 6] 策略发现与注册 (ADR-031 快速通道)
        │   │   StrategyRegistry 三级回退:
        │   │   1. APPROVED 策略 (已冻结上线)
        │   │   2. RESEARCH 策略 (有权重 + 回测 IC)
        │   │   3. Fallback: momentum_vol_full
        │   │
        │   │   对每个策略:
        │   └── compute_today_signals()                    # 快速通道: 仅计算今日分数 O(stocks)
        │       MultiFactorStrategy.from_today_scores()    # (非全历史 O(stocks × dates))
        │
        ├── [Step 7] 每日验证 (轻量级)
        │           → 不做完整 Gate, 策略质量在实验阶段验证
        │
        ├── [Step 7.5] Quality Gate (regime 门禁)
        │           → bear/crisis + confidence > 70% → BLOCKED, 跳过今日交易
        │
        ├── [Step 8] 策略执行
        │   │   strategy.generate_signals(today) → 每个策略产出一批信号
        │   │
        │   ├── [Step 8.5] StrategyHealthLogger.record_and_check()
        │   │   → 健康分 (0-100), 信号一致性, 换手率, 当前回撤
        │   │   → StrategyHealthReport.from_health()
        │   │
        │   └── [Step 8.5b] StrategyHealthReport 生成
        │       → 历史趋势分析 + 当前健康评估
        │
        ├── [Step 9] EnsembleEngine.fuse()                 # 多策略信号融合
        │           → UniversePolicy.FILL_ZERO
        │           → WeightEngine(WeightMethod.EQUAL)
        │           → combined_signals (融合后的统一信号)
        │
        ├── [Step 10] PortfolioRiskManager.apply_risk_limits_with_prices()
        │           → 风控过滤: 单票上限, 行业上限, 相关性检查
        │           → RiskAudit: violations + dropped_symbols + sector_exposure
        │
        ├── [Step 10.5] OnlineSignalMonitor.check()       # 在线信号监控 (ADR-031)
        │           → 实时信号质量检查 + 告警
        │
        ├── [Step 11] CostModel.estimate_trade()          # 成本估算
        │           → MarketImpactModel.compute_adv() → 市场冲击成本
        │
        ├── [Step 12] CapitalAllocator.run()              # 🔑 仅调仓日 (today.day ≤ 5)
        │           → 等权 / 风险平价 / 凯利公式
        │           → TargetPortfolio → Order[] (BUY)
        │
        ├── [Step 12.5] Exit Engine (V2.1)                # 三类退出信号
        │   │
        │   ├── 第二类 Risk Exit (每日必检):
        │   │   RiskExitManager.evaluate_daily()
        │   │   → 止损, ST, 退市, 停牌, 流动性枯竭
        │   │
        │   ├── 第一类 Rank Exit (仅调仓日):
        │   │   → Top10 买入, 11-20 缓冲持有, >20 卖出
        │   │
        │   ├── 第三类 Sector Overconcentration (仅调仓日):
        │   │   → 单一行业 > 40% → 标记超配
        │   │
        │   ├── 第三类 Fundamental Deterioration (仅调仓日):
        │   │   FundamentalExitDetector.check()
        │   │   → ROE 恶化, 营收下滑, 现金流恶化
        │   │
        │   └── V2.1 Merge: 每 symbol 合并为单条 SELL + 所有 reason tags
        │       → 按 Priority (CRITICAL > HIGH > MEDIUM > LOW) 排序
        │
        ├── [Step 12.8] ShadowLedger.run_daily()          # 影子组合 (模拟实盘)
        │
        ├── [Step 12.9] NAVLedger.record_daily()          # NAV 历史记录 (KPI 追踪)
        │
        └── [Step 13] DecisionPackage 构建与持久化
            │
            ├── DecisionEngine.generate()                  # BUY 建议 (仅调仓日)
            │   → signals + prices + risk_report + regime
            │   → TradeRecommendation[] (BUY)
            │
            ├── + SELL recommendations (来自 Exit Engine)
            │
            ├── package.to_json()
            │   → data/decisions/dp-{date}-{run_id}.json
            │
            ├── package.to_markdown()
            │   → data/decisions/{date}.md
            │
            └── package.update_index()
                → data/decisions/index.json
```

### 4.2 关键决策点

| 决策点 | 调仓日 (day ≤ 5) | 非调仓日 (day > 5) |
|--------|-------------------|---------------------|
| BUY 信号 | ✅ 生成 | ❌ 跳过 |
| Rank Exit | ✅ 检查 | ❌ 跳过 |
| Risk Exit | ✅ 检查 | ✅ 检查 |
| Sector Exit | ✅ 检查 | ❌ 跳过 |
| Fundamental Exit | ✅ 检查 | ❌ 跳过 |
| Capital Allocation | ✅ 执行 | ❌ 跳过 |
| Regime Gate | ✅ 检查 | ✅ 检查 |
| Strategy Health | ✅ 记录 | ✅ 记录 |
| Shadow Production | ✅ 运行 | ✅ 运行 |
| NAV Recording | ✅ 记录 | ✅ 记录 |

### 4.3 数据流

```
DataPipeline ──→ FeaturePipeline ──→ Price Data ──→ Today Signals
                                                        │
                                          ┌─────────────┴─────────────┐
                                          ▼                           ▼
                                    Strategy Discovery          Market Regime
                                          │                           │
                                          ▼                           ▼
                                    Strategy Signals            Regime Gating
                                          │                           │
                                          └───────────┬───────────────┘
                                                      ▼
                                              EnsembleEngine.fuse()
                                                      │
                                          ┌───────────┴───────────┐
                                          ▼                       ▼
                                   Risk Management          Online Monitor
                                          │                       │
                                          ▼                       ▼
                                   Cost Estimation         Health Report
                                          │
                                          ▼
                                   Capital Allocator ──→ Orders (BUY)
                                          │
                                          ▼
                                   Exit Engine ──→ TradeRecommendations (SELL)
                                          │
                                          ▼
                                   DecisionEngine ──→ DecisionPackage
                                          │
                                          ▼
                                   ┌──────┴──────┐
                                   ▼              ▼
                              dp-*.json      dp-*.md
                                   │
                                   ▼
                              index.json
```

### 4.4 涉及的核心模块（按调用顺序）

| 步骤 | 模块 | 文件 |
|------|------|------|
| 入口 | CLI | `qp/platform/cli/commands/ingest.py` |
| 0 | SystemState | `qp/monitoring/system_state.py` |
| 1 | DataPipeline | `qp/data/pipeline.py` |
| 2 | FeaturePipeline | `qp/research/pipeline/feature_pipeline.py` |
| 3 | Price/Fundamental loader | `qp/pipeline/daily_pipeline.py:_load_price_data` |
| 4 | LineageSnapshot | `qp/pipeline/daily_pipeline.py:_build_lineage_snapshot` |
| 5 | MarketRegimeDetector | `qp/strategy/market_regime.py` |
| 6 | StrategyRegistry + compute_today_signals | `qp/strategy/registry.py` + `qp/strategy/multifactor.py` |
| 7 | Validation (lightweight) | 内联 in daily_pipeline.py |
| 8 | Strategy.generate_signals | `qp/strategy/strategies/` |
| 8.5 | StrategyHealthLogger | `qp/monitoring/strategy_health_logger.py` |
| 9 | EnsembleEngine | `qp/strategy/ensemble/` |
| 10 | PortfolioRiskManager | `qp/portfolio/risk_manager.py` |
| 10.5 | OnlineSignalMonitor | `qp/monitoring/online_monitor.py` |
| 11 | CostModel | `qp/portfolio/cost_model.py` |
| 12 | CapitalAllocator | `qp/portfolio/capital_allocator.py` |
| 12.5 | RiskExitManager + FundamentalExitDetector | `qp/portfolio/risk_exit.py` + `qp/portfolio/exit_signals.py` |
| 12.8 | ShadowLedger | `qp/simulation/shadow_ledger.py` |
| 12.9 | NAVLedger | `qp/portfolio/nav_ledger.py` |
| 13 | DecisionEngine + DecisionPackage | `qp/decision/engine.py` + `qp/decision/decision_package.py` |

---

## Phase 5: 操作指南 [已完成]

- [x] `user_guide.md` — 融合 `使用指南.md` + `量化投资买卖规则说明书.md`（17 章）

---

## Phase 6: 架构文档 [已完成]

### 6.1 已完成的文档

| 目标文件 | 状态 |
|----------|------|
| `developer_guide.md` | ✅ 已创建（8 章） |
| `user_guide.md` | ✅ Phase 5 完成 |
| `architecture/DP-001 ~ DP-010` | ✅ 11 个 DP 文件已填充 |
| `architecture/reference/twelve-layer-overview.md` | ✅ 架构总览 |
| `archive/` | ✅ 32 份历史文档已归档 |

### 6.2 可选（信息已在其他文档中）

| 目标文件 | 说明 |
|----------|------|
| `architecture.md` | 内容已被 `twelve-layer-overview.md` + ADR 覆盖 |
| `module_overview.md` | 内容已在 Phase 2 模块地图中 |
| `workflow.md` | 内容已在 Phase 4 调用链中 |

---

## 全部完成 ✅

| # | 事项 | 状态 |
|---|------|------|
| 1 | **`api.md`** | ✅ 刚完成 |

**文档重建 100% 完成。**

---

## 执行记录

| 日期 | 阶段 | 做了什么 |
|------|------|----------|
| 2026-08-01 | Phase 0 | 创建本文档，完成现状摸底 |
| 2026-08-01 | Phase 0 | 完成文档清单与状态判定（70+ 文件 → 5 类） |
| 2026-08-01 | Phase 1 | 完成代码入口分析、核心类地图 |
| 2026-08-01 | Phase 1 | 完成 CLI 命令地图（20+ 命令） |
| 2026-08-01 | 归档 | 20 份过期文档归档 → `docs/archive/` |
| 2026-08-01 | 归档 | docs 根目录从 70+ 降到 15 个 .md 文件 |
| 2026-08-01 | Phase 2 | **完成 12 层 + Pipeline + Web + Shared 共 15 个模块地图** |
| 2026-08-01 | Phase 3 | `使用指南.md` → ✅已修复 |
| 2026-08-01 | Phase 3 | `gap_analysis.md` → 已归档 |
| 2026-08-01 | Phase 3 | `4_Registry_LineageLayer.md` → 已归档 |
| 2026-08-01 | Phase 4 | **`qp run daily` 13 步调用链完整追踪**（CLI → DecisionPackage），含关键决策点 + 数据流图 + 20 个核心模块映射 |
| 2026-08-01 | Phase 5 | **融合完成 `user_guide.md`**（`使用指南.md` + `量化投资买卖规则说明书.md`）：新增第4章「投资策略规则」+ 17 章结构统一 + 旧文件归档 |
| 2026-08-01 | 归档 | **7 份对话体设计文档归档**（`5_`~`8_`、`11_12`、`data_layer`、`research_layer`） |
| 2026-08-01 | 文档 | **docs 根目录: 70+ → 5 个 .md 文件** |
| 2026-08-01 | Phase 6 | **`developer_guide.md` 完成**（8 章） |
| 2026-08-01 | Phase 6 | **11 个 DP 文件填充完成**（DP-001 ~ DP-010 + twelve-layer-overview），从 0 字节空壳 → 30-84 行实质内容 |

---

## 全部完成 ✅

### 文档重建完成清单

| # | 阶段 | 内容 | 状态 |
|---|------|------|------|
| 1 | Phase 0 | 现状摸底（70+ → 5） | ✅ |
| 2 | Phase 1 | 代码地图 + CLI 地图 | ✅ |
| 3 | Phase 2 | 15 模块地图 | ✅ |
| 4 | Phase 3 | 文档可信度验证 | ✅ |
| 5 | Phase 4 | `qp run daily` 13 步调用链 | ✅ |
| 6 | Phase 5 | `user_guide.md` | ✅ |
| 7 | Phase 6 | `developer_guide.md` + 11 DP + 10 TDR + 3 impl + constitution | ✅ |
| 8 | — | `api.md` | ✅ |
| 9 | — | 归档 63 份过期/空壳文档 | ✅ |
| 10 | — | 修复 pyright + 6 test failures | ✅ |
| 11 | — | WebUI 健康记录去重 | ✅ |

### 实验管道调用链（追加）

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
