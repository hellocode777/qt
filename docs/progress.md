# QP 开发进度与使用指南

> 最后更新：2026-07-20

---

## 一、当前进度

### ✅ Phase 0 — Sprint 0 Bootstrap（已完成）

**目标**：建立 Platform Layer 全部基础设施，不涉及业务逻辑。

| Milestone | 状态 | 说明 |
|---|---|---|
| M0.0 | ✅ | 项目工程化：`pyproject.toml`、`.python-version`、`.editorconfig`、`.pre-commit-config.yaml`、`.gitignore`、`README.md` |
| M0.1 | ✅ | Shared 模块：4 个常量、10 个枚举类型、20 个异常类、11 个抽象协议接口 |
| M0.2 | ✅ | 配置系统：4 层优先级(CLI > 环境变量 > config.toml > 默认值)、Pydantic 11 段配置、递归冻结 |
| M0.3 | ✅ | 日志系统：Loguru 封装、结构化输出、控制台+文件双通道 |
| M0.4 | ✅ | 运行时：状态机(CREATED→INITIALIZING→READY→RUNNING→STOPPING→TERMINATED)、显式 Composition Root |
| M0.5 | ✅ | Pipeline 引擎：BasePipeline、PipelineContext、PipelineResult、PipelineRunner |
| M0.6 | ✅ | 存储工厂：DuckDB、SQLite、Parquet 后端 |
| M0.7 | ✅ | 调度器：APScheduler 封装、Job/JobRegistry、Cron/Interval 触发器 |
| M0.8 | ✅ | CLI 系统：`qp version`、`qp doctor`、`qp pipeline list` |
| M0.9 | ✅ | 元数据：运行时信息、环境信息 |
| M0.11 | ✅ | 测试：34 个单元测试，全部通过 |

### ✅ Phase 1 — Walking Skeleton（已完成）

数据接入 → 因子 → 策略 → 组合 → 回测 → 报告，端到端最小闭环已跑通。

| Milestone | 状态 | 说明 |
|---|---|---|
| M1.1 | ✅ | Data Layer：Tencent 适配器（主力）+ AKShare + Demo、清洗引擎、Data Contract、DatasetRegistry、DatasetLoader、交易日历 |
| M1.3 | ✅ | Research Layer：Momentum20dFeature (BaseFeature)、FeatureRegistry、FeaturePipeline |
| M1.4 | ✅ | Strategy Layer：SimpleRankStrategy (Top 10)、Decision dataclass |
| M1.5 | ✅ | Portfolio Layer：SinglePortfolio (Equal Weight)、Order dataclass |
| M1.6 | ✅ | Simulation Layer：SimpleVectorBacktest (向量化回测)、绩效指标 |
| M1.7 | ✅ | Walking Skeleton 集成：真实数据端到端跑通（Sharpe 0.88，总收益 40.62%，最大回撤 -14.02%） |

### ✅ Phase 2 — Validation Gate + Kill Switch（已完成）

**目标**：建立策略质量门禁和熔断机制。

| Milestone | 状态 | 说明 |
|---|---|---|
| M2.1 | ✅ | Validation Layer：RankIC / IC_IR / t-stat / 分层检验 + Rule Engine（BaseRule + RuleEngine） |
| M2.2 | ✅ | Purged CV：PurgedKFold（walk-forward + Purge + Embargo），最少 500 天训练窗口 |
| M2.3 | ✅ | LightGBM：LightGBMRankModel (LambdaRank) + CrossSectionalStandardizer |
| M2.4 | ✅ | 过拟合检查：样本内/外 IC 比值 + 特征重要性集中度检测 |
| M2.5 | ✅ | Backtest Validation：Sharpe ≥ 1.0、最大回撤 ≤ 25%、换手率检查 |
| M2.6 | ✅ | Kill Switch：DrawdownTrigger + PortfolioDrawdownTrigger + PSITrigger |
| M2.7 | ✅ | 集成：`qp validate` 命令 + 全量质量检查通过 |

**Phase 2 实测**：

```
qp validate → simple_rank_v1.0:
  ❌ rank_ic         0.0178 < 0.02
  ❌ ic_ir           0.053 < 0.3
  ❌ ic_t_stat       1.30 < 2.0
  ❌ stratification  1.73 < 2.0
  ❌ sharpe_ratio    0.88 < 1.0
  ✅ max_drawdown    14.02% ≤ 25%
  Overall: FAIL (Score 33/100, 5/6 failed)
```

### ✅ Phase 3 — Portfolio Risk + Capital Allocation（已完成）

**目标**：多策略并行、组合风控、资金分配、交易成本、仓位优化。

| Milestone | 状态 | 说明 |
|---|---|---|
| M3.1 | ✅ | Strategy Registry + Signal Aggregator + Volatility20d 因子 |
| M3.2 | ✅ | Portfolio Risk Manager：单仓 ≤ 8%、单行业 ≤ 25%、相关性过滤（>0.7）、风险预算 |
| M3.3 | ✅ | Transaction Cost Model：印花税 0.05% + 佣金 0.025% + 滑点 0.1% + sqrt 冲击成本 |
| M3.4 | ✅ | Capital Allocation：EqualWeight + RiskParity（逆波动率）+ FractionalKelly（0.25×）+ 现金缓冲 ≥ 5% |
| M3.5 | ✅ | MeanVarianceOptimizer（最大夏普、SLSQP、Ledoit-Wolf 协方差收缩）+ 分析回退 |
| M3.6 | ✅ | 集成：DailyPipeline 升级为完整 Portfolio 流程 + `qp portfolio report/risk` 命令 |

### ✅ Phase 4 — Registry & Lineage + Simulation 正式版（已完成）

**目标**：实验追踪、模型注册、SimulatedBroker、公司事件处理。

| Milestone | 状态 | 说明 |
|---|---|---|
| M4.1 | ✅ | Experiment Tracker：ExperimentTracker + ExperimentRunner + LineageGraph + JSON 存储 |
| M4.2 | ✅ | Model Registry：ModelRegistry + ModelMetadata + SHA256 哈希 + 文件管理 |
| M4.3 | ✅ | Simulation 升级：SimulatedBroker (BaseBroker) + SlippageModel + ADV 限制 + SimulationResult |
| M4.4 | ✅ | Corporate Action Engine：现金分红/送股/拆股/配股/转增 + CorporateActionLoader |
| M4.5 | ✅ | 集成：`qp experiment list/show` + `qp model list/show` + `qp backtest run` 命令 |

### ✅ Phase 5 — 监控、熔断、知识沉淀（已完成）

**目标**：生产级监控体系和知识沉淀机制。

| Milestone | 状态 | 说明 |
|---|---|---|
| M5.1 | ✅ | Risk Model：RiskModel (BaseRiskModel) + 多因子归因（Market/Style/Sector/Idiosyncratic）+ RiskDecomposition + AttributionReport |
| M5.2 | ✅ | Monitoring Layer：DriftMonitor (PSI/KS/Wasserstein) + ModelDecayDetector (滚动IC衰减) + MarketRegimeEngine (趋势/震荡/高低波动) + StrategyMonitor (信号/换手率/回撤健康度) |
| M5.3 | ✅ | Alert Channels：AlertManager + TerminalAlert (彩色) + LogAlert (结构化) + TelegramAlert (Bot推送) + AlertSeverity 三级 |
| M5.4 | ✅ | Kill Switch Pipeline：KillSwitchPipeline (BasePipeline) + MonitorReport + 每日自动检查 + Model Decay与Kill Switch联动 + MonitorAction 五级 |
| M5.5 | ✅ | Knowledge Layer：KnowledgeArchive + KnowledgeEntry（YAML frontmatter + Markdown）+ 5类模板（实验总结/失败分析/事后复盘/决策审计/研究债务）+ 全文搜索 |
| M5.6 | ✅ | 集成：`qp monitor check/regime/alert-test` + `qp knowledge stats/search` CLI 命令 |

---

## 二、可用命令

### 2.1 安装与运行

```bash
uv sync                                    # 安装依赖
uv run qp version                          # 查看版本
uv run qp doctor                           # 环境诊断
uv run qp --help                           # 帮助
uv run qp pipeline list                    # 已注册 Pipeline
uv run qp ingest --demo                    # 数据摄入（模拟数据）
uv run qp ingest 2024-01-01 2024-12-31     # 数据摄入（日期范围）
uv run qp run daily --demo                 # 端到端流程（模拟数据）
uv run qp run daily                        # 端到端流程（真实数据）
uv run qp validate                         # 策略验证（全部 Gate 检查）
uv run qp portfolio report                 # 组合 KPI 看板
uv run qp portfolio risk                   # 风控分析 + 相关性扫描
uv run qp experiment list                  # 实验列表
uv run qp experiment show <id>             # 实验详情 + 血缘
uv run qp model list                       # 模型列表
uv run qp model show <id>                  # 模型详情 + 指标
uv run qp backtest run [strategy]          # Broker 回测（含成本）
uv run qp monitor check                    # 每日安全检查（KS + 漂移 + 衰减）
uv run qp monitor regime                   # 市场状态检测
uv run qp monitor alert-test               # 告警通道测试
uv run qp knowledge stats                  # 知识库统计
uv run qp knowledge search <query>         # 知识库搜索
```

### 2.2 代码检查

```bash
uv run ruff format       # 自动格式化
uv run ruff check        # 代码检查
uv run ruff check --fix  # 自动修复
uv run pyright           # 类型检查
uv run pytest            # 运行全部测试
uv run pytest --cov=qp   # 带覆盖率
```

### 2.3 一键全量检查（Definition of Done）

```bash
uv sync && uv run ruff format && uv run ruff check && uv run pyright && uv run pytest
```

---

## 三、项目结构速查

```
qp/
├── platform/          # Layer 1: 运行时基础设施 ✅
│   ├── cli/           #   CLI 入口 (qp)
│   ├── config/        #   配置系统
│   ├── logging/       #   日志系统
│   ├── metadata/      #   元数据
│   ├── pipeline/      #   Pipeline 引擎
│   ├── runtime/       #   运行时 + Composition Root
│   ├── scheduler/     #   调度器
│   └── storage/       #   存储工厂
├── shared/            # 跨层共享 ✅
│   ├── protocols/     #   抽象接口 (11 个)
│   ├── types/         #   枚举类型 (10 个)
│   ├── constants/     #   常量
│   └── exceptions/    #   异常类 (20 个)
├── data/              # Layer 2: ✅
│   ├── adapter/       #   Tencent(主力) + AKShare + Demo
│   ├── cleaning/      #   数据清洗引擎
│   ├── contract/      #   DailyPriceContract
│   ├── loader/        #   DatasetLoader
│   └── calendar/      #   TradingCalendar
├── research/          # Layer 3: ✅ Phase 4
│   ├── feature/       #   Momentum20d + Volatility20d + FeatureRegistry
│   ├── split/         #   PurgedKFold (walk-forward + Purge + Embargo)
│   ├── trainer/       #   LightGBMRankModel + ModelRegistry
│   └── experiment/    #   ExperimentTracker + ExperimentRunner
├── validation/        # Layer 4: ✅ Phase 2
│   ├── engine.py      #   BaseRule + RuleEngine + ValidationContext
│   ├── result.py      #   RuleResult + ValidationResult
│   └── checks/        #   factor_checks + overfit_checks + backtest_checks
├── strategy/          # Layer 5: ✅ Phase 3
│   ├── simple_rank.py #   SimpleRankStrategy (Top 10)
│   ├── registry.py    #   StrategyRegistry (多策略管理)
│   └── aggregator.py  #   SignalAggregator (rank_blend/equal_weight/vote)
├── portfolio/         # Layer 6: ✅ Phase 3 重点
│   ├── single_portfolio.py  # SinglePortfolio (legacy)
│   ├── risk_manager.py #  PortfolioRiskManager (仓位/行业/相关性限制)
│   ├── industry.py    #   IndustryMapper (申万行业分类)
│   ├── correlation.py #   CorrelationAnalyzer (>0.7 冗余检测)
│   ├── cost_model.py  #   CostModel + MarketImpactModel (sqrt)
│   ├── optimizer.py   #   MeanVarianceOptimizer (最大夏普, SLSQP, Ledoit-Wolf)
│   └── allocator/     #   资金分配器
│       ├── equal_weight.py  # EqualWeightAllocator (1/N)
│       ├── risk_parity.py   # RiskParityAllocator (逆波动率)
│       ├── kelly.py         # KellyAllocator (Fractional Kelly)
│       └── factory.py       # AllocationFactory
├── simulation/        # Layer 7: ✅ Phase 4
│   ├── backtest.py    #   SimpleVectorBacktest (legacy)
│   ├── broker.py      #   SimulatedBroker (BaseBroker)
│   ├── slippage.py    #   SlippageModel (fixed/volatility/sqrt)
│   └── result.py      #   SimulationResult
├── monitoring/        # Layer 9: ✅ Phase 5
│   ├── kill_switch.py #   KillSwitch + 3 triggers (Phase 2)
│   ├── kill_switch_pipeline.py # KillSwitchPipeline (Phase 5)
│   ├── drift.py       #   DriftMonitor (PSI/KS/Wasserstein)
│   ├── model_decay.py #   ModelDecayDetector
│   ├── regime.py      #   MarketRegimeEngine
│   ├── strategy_monitor.py # StrategyMonitor
│   └── alerts.py      #   AlertManager + Terminal/Log/Telegram
├── decision/          # Layer 8: ⏳ 空
└── knowledge/         # Layer 10: ✅ Phase 5
    └── archive.py     #   KnowledgeArchive + 5类模板
tests/
├── unit/              # 单元测试 (34 个) ✅
├── integration/       # 集成测试 ⏳
└── e2e/               # 端到端测试 ⏳
```

---

## 四、Phase 3 数据流

```
FeaturePipeline (momentum_20d + volatility_20d)
          ↓
StrategyRegistry.get_backtest_ready() → 2 策略
          ↓
SignalAggregator (rank_blend)
          ↓
PortfolioRiskManager.apply_risk_limits_with_prices()
  ├── 单仓上限 8%
  ├── 单行业上限 25%
  └── 相关性过滤 (>0.7)
          ↓
CostModel.estimate()
  ├── 印花税 0.05% (卖)
  ├── 佣金 0.025%
  └── sqrt 冲击成本
          ↓
AllocationFactory.create("risk_parity")
  └── 现金缓冲 5%
          ↓
MeanVarianceOptimizer.optimize()
  ├── Ledoit-Wolf 协方差收缩
  └── SLSQP 最大夏普
          ↓
订单生成 + SimpleVectorBacktest
```

---

## 五、Phase 5 数据流

```
MarketRegimeEngine (趋势/震荡/高低波动)
          ↓
DriftMonitor (PSI / KS / Wasserstein)
          ↓
ModelDecayDetector (滚动 IC 衰减检测)
          ↓
StrategyMonitor (信号频率 / 换手率 / 回撤)
          ↓
KillSwitchPipeline (每日自动检查)
          ↓
AlertManager → TerminalAlert / LogAlert / TelegramAlert
          ↓
KnowledgeArchive (实验总结 / 失败分析 / 决策审计 / 事后复盘)
```

## 六、下一步：Phase 6 缓冲与复盘

按 `docs/plan_v1.md` 继续推进：

1. 数据源问题修复 — AkShare API 变化、数据缺失
2. 券商 API 联调 — 真实券商连接、认证、下单
3. Bug 排查与修复 — 26 周积累的已知问题
4. 性能优化 — 大数据量查询、回测性能
5. 架构完整性自查 — 七类可信性逐项检查
6. 阈值校准 — 根据实际运行数据校准判定标准
