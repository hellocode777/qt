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
| M1.1 | ✅ | Data Layer：Tencent 适配器（主力）+ AKShare 适配器 + Demo 适配器、数据清洗引擎、Data Contract、DatasetRegistry、DatasetLoader、交易日历 |
| M1.3 | ✅ | Research Layer：Momentum20dFeature (BaseFeature)、FeatureRegistry、FeaturePipeline |
| M1.4 | ✅ | Strategy Layer：SimpleRankStrategy (Top 10)、Decision dataclass |
| M1.5 | ✅ | Portfolio Layer：SinglePortfolio (Equal Weight)、Order dataclass |
| M1.6 | ✅ | Simulation Layer：SimpleVectorBacktest (向量化回测)、绩效指标 |
| M1.7 | ✅ | Walking Skeleton 集成：`qp ingest`（腾讯API真实数据）+ `qp run daily` 端到端跑通（Sharpe 0.88，总收益 40.62%，最大回撤 -14.02%） |

---

## 二、可用命令

### 2.1 安装与运行

```bash
# 安装依赖（首次或依赖变更时执行）
uv sync

# 查看版本
uv run qp version

# 环境诊断
uv run qp doctor

# 查看帮助
uv run qp --help

# 查看已注册的 Pipeline
uv run qp pipeline list

# 数据摄入（使用模拟数据）
uv run qp ingest --demo

# 数据摄入（指定日期范围）
uv run qp ingest 2024-01-01 2024-12-31

# 端到端每日流程（数据 → 特征 → 策略 → 组合 → 回测）
uv run qp run daily --demo
```

### 2.2 代码检查

```bash
# 自动格式化
uv run ruff format

# 代码检查（零错误）
uv run ruff check

# 自动修复可修复的问题
uv run ruff check --fix

# 类型检查（零错误）
uv run pyright
```

### 2.3 测试

```bash
# 运行全部测试
uv run pytest

# 详细输出
uv run pytest -v

# 运行单个测试文件
uv run pytest tests/unit/test_config.py

# 运行单个测试方法
uv run pytest tests/unit/test_config.py::TestConfigFreeze::test_cannot_modify_frozen_config

# 带覆盖率
uv run pytest --cov=qp
```

### 2.4 一键全量检查（每个 Milestone 的 Definition of Done）

```bash
uv sync && uv run ruff format && uv run ruff check && uv run pyright && uv run pytest
```

---

## 三、项目结构速查

```
qp/
├── platform/          # Layer 1: 运行时基础设施 ✅
│   ├── cli/           #   CLI 入口 (qp)
│   ├── config/        #   配置系统 (4层优先级)
│   ├── logging/       #   日志系统 (Loguru)
│   ├── metadata/      #   元数据 (版本/环境)
│   ├── pipeline/      #   Pipeline 引擎
│   ├── runtime/       #   运行时 (状态机/Composition Root)
│   ├── scheduler/     #   调度器 (APScheduler)
│   └── storage/       #   存储工厂 (DuckDB/SQLite/Parquet)
├── shared/            # 跨层共享 ✅
│   ├── protocols/     #   抽象接口 (11 个 ABCs)
│   ├── types/         #   枚举类型 (10 个)
│   ├── constants/     #   常量
│   └── exceptions/    #   异常类 (20 个)
├── data/              # Layer 2: ✅ Walking Skeleton
│   ├── adapter/       #   Tencent(主力) + AKShare + Demo 适配器
│   ├── cleaning/      #   数据清洗引擎
│   ├── contract/      #   DailyPriceContract
│   ├── dataset/       #   DatasetRegistry
│   ├── loader/        #   DatasetLoader
│   └── calendar/      #   TradingCalendar
├── research/          # Layer 3: ✅ Walking Skeleton
│   └── feature/       #   Momentum20dFeature + FeatureRegistry
├── validation/        # Layer 4: ⏳ 空
├── strategy/          # Layer 5: ✅ Walking Skeleton
│   └── simple_rank.py #   SimpleRankStrategy (Top 10)
├── portfolio/         # Layer 6: ✅ Walking Skeleton
│   └── single_portfolio.py  # SinglePortfolio (Equal Weight)
├── simulation/        # Layer 7: ✅ Walking Skeleton
│   └── backtest.py    #   SimpleVectorBacktest
├── decision/          # Layer 8: ⏳ 空
├── monitoring/        # Layer 9: ⏳ 空
└── knowledge/         # Layer 10: ⏳ 空
tests/
├── unit/              # 单元测试 (34 个) ✅
├── integration/       # 集成测试 ⏳
└── e2e/               # 端到端测试 ⏳
```

---

## 四、Phase 1 真实数据跑分

| 指标 | 真实数据（腾讯 API） | 模拟数据（Demo） |
|---|---|---|
| 数据量 | 11,066 行 | 9,690 行 |
| 股票数 | 18 只 | 15 只 |
| 夏普比率 | **0.88** | 1.65 |
| 年化收益 | 16.67% | - |
| 总收益 | 40.62% | 55.75% |
| 最大回撤 | -14.02% | -14.94% |

> 模拟数据 GBM 随机游走高估了策略表现，真实数据更可靠。

---

## 五、下一步：Phase 2 Validation Gate + Kill Switch

按 `docs/plan_v1.md` 的计划表继续推进：

1. Validation Layer — 因子检验（Rank IC、IC_IR、t-stat）、Rule Engine 框架
2. Research Layer — Purged CV（Purge + Embargo）
3. LightGBM 建模流水线（LambdaRank、截面标准化、过拟合检查）
4. Backtest Validation（Sharpe ≥1.0、最大回撤 ≤25%）
5. Kill Switch 最小版（回撤熔断、PSI 漂移检测）
