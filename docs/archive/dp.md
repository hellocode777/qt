# QP 设计文档体系（Design Proposal & Architecture Decision Records）

> 本文档整理自《量化投资平台项目宪法 v4.2》与《落地执行计划 全职节奏》配套的设计讨论，将原对话中的架构设计、ADR、TDR、术语定义、工程规范等内容按主题重组，作为项目宪法之下的第二层文档——**Reference Architecture & Design Proposals**。

---

## 目录

1. [文档体系定位](#1-文档体系定位)
2. [QP 设计哲学（12 条）](#2-qp-设计哲学12-条)
3. [统一术语（Ubiquitous Language）](#3-统一术语ubiquitous-language)
4. [架构决策记录（ADR）](#4-架构决策记录adr)
5. [技术决策记录（TDR）](#5-技术决策记录tdr)
6. [DP-001：Platform Layer](#6-dp-001platform-layer)
7. [DP-002：Data Layer](#7-dp-002data-layer)
8. [DP-003：Research Layer](#8-dp-003research-layer)
9. [DP-004：Validation Layer](#9-dp-004validation-layer)
10. [DP-005：Strategy Layer](#10-dp-005strategy-layer)
11. [DP-006：Portfolio Layer](#11-dp-006portfolio-layer)
12. [DP-007：Simulation Layer](#12-dp-007simulation-layer)
13. [DP-008：Decision Layer](#13-dp-008decision-layer)
14. [DP-009：Monitoring Layer](#14-dp-009monitoring-layer)
15. [DP-010：Knowledge Layer](#15-dp-010knowledge-layer)
16. [Pipeline Engine（横切能力）](#16-pipeline-engine横切能力)
17. [工程规范（Engineering Handbook）](#17-工程规范engineering-handbook)
18. [Sprint 0：Bootstrap 计划](#18-sprint-0bootstrap-计划)
19. [文档目录结构建议](#19-文档目录结构建议)
20. [建议新增宪法条文](#20-建议新增宪法条文)

---

## 1. 文档体系定位

整个项目的文档分为四层，各司其职：

```
项目宪法（Constitution）
        │
        ▼
Reference Architecture（十二层参考架构）
        │
        ▼
Design Proposal（每层详细设计，即本文档体系）
        │
        ▼
ADR / TDR（重大设计决策与技术选型记录）
        │
        ▼
Implementation Guide（开发指南 / Engineering Handbook）
```

- **Constitution**：定义价值观、原则和不可违反的规则（即《量化投资平台项目宪法》）
- **Reference Architecture**：定义系统整体结构、层次关系和职责边界
- **Design Proposal**：定义每一层如何设计和实现（DP-001 ~ DP-010）
- **ADR**：记录每一个关键技术决策及其理由
- **TDR**：记录技术选型决策（与 ADR 分离，因为技术生命周期 2–5 年，架构生命周期 10 年）

**核心原则**：
- 每一层采用统一的 RFC 风格模板：Background → Goals/Non-goals → Architecture → Component Design → Public Interface → Data Model → State Machine → Failure Handling → ADR/TDR → Directory Layout → Future Evolution
- 设计文档不仅回答"怎么实现"，更回答"为什么这么实现"
- 12 份独立的 Design Proposal（每层一份），每份控制在 20–40 页

---

## 2. QP 设计哲学（12 条）

### Philosophy 1：Architecture over Framework
框架可以替换，架构必须稳定。

### Philosophy 2：Data Products, Not Data Sources
整个系统消费的是 Data Product，而不是 AkShare、Tushare 或任何具体数据源。

### Philosophy 3：Pipelines Everywhere
所有长期运行的业务都以 Pipeline 为统一抽象。

### Philosophy 4：Everything Is Versioned
数据、特征、标签、模型、实验、策略、配置，都必须可版本化、可复现。

### Philosophy 5：Validation Before Trust
任何研究成果都必须经过验证，验证先于信任。

### Philosophy 6：Policy Before Execution
策略负责制定投资政策，执行负责落实政策，两者严格分离。

### Philosophy 7：Platform Owns Infrastructure
配置、日志、调度、存储、运行时都属于 Platform，业务层不得自行创建基础设施。

### Philosophy 8：Layers Own Responsibilities
每个 Layer 只拥有自己的职责，不跨层，不越权，不绕过边界。

### Philosophy 9：Fail Fast, Recover Safely
尽早失败，安全恢复；宁可拒绝执行，也不要带病运行。

### Philosophy 10：Everything Is Auditable
任何结果都必须能够追溯到数据、代码、配置、模型和设计决策。

### Philosophy 11：Evolution over Perfection
追求持续演进，而不是一次性完美；保持架构稳定，实现持续优化。

### Philosophy 12：The Platform Is a Long-Term Asset
这个平台不是为了写完一个项目，而是为了陪伴未来十年以上的投资研究与决策。

---

## 3. 统一术语（Ubiquitous Language）

整个项目（Design Proposal、ADR、README、Code、Docstring、注释）统一使用以下词汇。

### 3.1 系统层级

| Term | 定义 |
|---|---|
| QP | 整个项目（Quant Platform） |
| QP Runtime | 系统运行时，由 Platform Layer 提供 |
| QP Kernel | Runtime 的核心组件，负责生命周期管理 |
| Layer | 十二层架构中的一个层 |
| Component | Layer 内的功能模块 |
| Service | 一个具有明确职责的运行单元 |
| Pipeline | 一条可执行的数据或业务流程 |

> Runtime ≠ Kernel。Kernel 是 Runtime 的一部分。

### 3.2 调度

| Term | 定义 |
|---|---|
| Job | 一个调度计划（例如每天 17:30） |
| Task | Job 中执行的一个动作 |
| Pipeline | 多个 Task 组成的完整流程 |
| Run | Pipeline 的一次执行实例 |
| Schedule | Job 的时间计划 |

### 3.3 数据

| Term | 定义 |
|---|---|
| Data Source | 数据来源（AkShare 等） |
| Dataset | 一份数据集 |
| Snapshot | 某一时刻的数据快照 |
| Feature | 一个模型输入特征 |
| Label | 一个监督学习目标 |
| Factor | 一个研究因子 |
| Signal | 模型输出（可交易） |
| Prediction | 模型预测值（不可直接交易） |

> **Signal ≠ Prediction**。Prediction 只是模型输出，Signal 已经可以交易。这是两个不同的层。

### 3.4 策略与投资组合

```
Research → Model → Signal → Strategy → Decision → Order
```

```
Portfolio → Position → Order → Trade → Execution
```

> **Order ≠ Trade**。Order 可能被 Rejected；Trade 一定已成交。

### 3.5 实验

```
Experiment → Run → Artifact → Metric → Result
```

> Experiment 和 Run 严格区分，不可混用。

---

## 4. 架构决策记录（ADR）

> ADR 记录影响系统结构的架构决策，生命周期约 10 年。

### ADR-001：Hybrid Architecture（混合架构）

**Decision**：采用 **Data Pipeline + Domain Model** 混合架构。

- **Data Layer、Research Layer**：保持 DataFrame Pipeline（Pandas / Polars / DuckDB），以研究效率优先。
- **Domain Layer（Portfolio、Position、Order、Decision 等）**：采用 Repository + 强类型 Domain Object，保证业务一致性与可维护性。

**Why**：项目本质上有两种完全不同的数据——分析数据（行情、财务、因子、标签、特征）天然适合列式处理；业务对象（Position、Order、Decision、Experiment、Strategy Metadata）天然适合对象模型。把两者统一成一种模式反而会增加复杂度。

---

### ADR-002：CLI 名称确定为 `qp`

**Decision**：统一采用 `qp` 作为所有命令入口。未来禁止新增第二套入口。

```bash
qp ingest daily-price
qp feature momentum20
qp train lgb-rank
qp validate strategy
qp backtest momentum_v1
qp report latest
qp run daily
qp scheduler start
```

**Why**：CLI First 原则。即使未来接 GUI、Web API、Telegram Bot，本质也都是调用 CLI。

---

### ADR-003：Explicit Composition Root（不引入 DI Framework）

**Decision**：不引入 Dependency Injection Framework。所有对象在应用启动时显式构造。

```python
config = Config.load()
logger = Logger(config)
scheduler = Scheduler(logger)
storage = DuckDBStorage(config)
experiment = ExperimentTracker(storage)
app = Application(
    config=config,
    logger=logger,
    scheduler=scheduler,
    experiment=experiment,
)
```

**Why**：符合 Research First、Walking Skeleton First 原则，避免隐藏依赖。

---

### ADR-004：Platform 提供 Storage Factory，不提供 Repository

**Decision**：Platform Layer 提供 StorageFactory、Connection Lifecycle、Config、Database Initialization。Platform 不提供 Repository，Repository 属于各业务 Layer。

**Why**：Repository 已经开始表达业务语义（如 ExperimentRepository 知道 Experiment 是什么），Platform 不应该知道业务。否则 Platform 最终会变成 Business Platform，造成 Layer Corruption。

---

### ADR-005：Phase 0 不引入 Event Bus

**Decision**：Layer 之间采用 Direct Call，不引入 Event Bus。

**Why**：Event Bus 最大的问题不是"写"，而是"隐藏流程"——到后来没人知道为什么会执行，Debug 极其困难。Direct Call 让执行顺序清晰可见。符合 Rule 28（不要为了未来可能发生的需求而增加抽象）。

---

### ADR-006：Everything Is Pipeline

**Decision**：系统所有长期任务全部表示为 Pipeline，而不是 Script。

如 `TrainingPipeline`、`FeaturePipeline`、`BacktestPipeline`（而非 `train.py`、`feature.py`、`backtest.py`）。

**Why**：Pipeline 天然具有 Input → Transform → Output，与量化平台的数据流完全一致。Scheduler 调度 Pipeline，CLI 执行 Pipeline，Experiment 记录 Pipeline。

---

### ADR-007：One Concept, One Name

一个概念只能有一个名字。如只能叫 `Pipeline`，绝不能 Workflow、Flow、Process、Task Chain 混着出现。

---

### ADR-008：One Responsibility, One Layer

如 Feature 只能属于 Research Layer。不能 Data、Research、Strategy 三层都有 Feature。

---

### ADR-009：No Cross-Layer Shortcuts

永远不能跳层调用。如 Research 不能直接访问 Portfolio，必须通过 Strategy。

---

### ADR-010：Stable Public Interface

每个 Layer 只允许暴露 `public/` 或 `__init__.py` 中的接口。内部目录以后可以随便改，外部不能依赖。

---

### ADR-011：Configuration Is Runtime State

Configuration 不是普通文件，而是 Runtime State Definition。整个 Runtime 只能拥有一个 Config，不能 reload，不能 dynamic update。否则实验、日志、Scheduler 都会失去一致性。

---

### ADR-012：Runtime Owns Everything

任何基础设施（Logger、Storage、Clock、Scheduler、Configuration、Metadata、Environment）都属于 Runtime。Pipeline 不能 `new Logger()`，只能 `runtime.logger`。

---

### ADR-013：Data Product Architecture

Data Layer 管理的是 Data Product（数据产品），而不是 Data Source（数据源）。Research Layer 永远不碰 AkShare、CSV、Parquet，只知道 Dataset。

```python
dataset = data.load_dataset("daily_price", version="2026-07-20")
```

Research 不知道数据来自 AkShare 还是 Tushare。这是整个十二层架构最重要的一条边界——依赖倒置。

---

### ADR-014：Immutable Raw Data

Raw Data 永远不能修改。只能新增，不可覆盖。

---

### ADR-015：Dataset Is The Only Public Interface

Data Layer 对外只暴露 Dataset，不暴露内部实现。

---

### ADR-016：Validation Before Publication

任何 Dataset 必须通过 Validation 才能发布。

---

### ADR-017：Consumer Never Knows Data Source

消费者永远不知道数据来源。换数据源时 Research 一行代码不用改。

---

### ADR-018：Everything Is Experiment

任何训练都是 Experiment，不能直接 `train.py`，必须用 `ExperimentRunner`。

---

### ADR-019：Feature Is First-Class Asset

Feature 拥有 Version、Owner、Metadata、Importance。Model 可以换，Feature 才是 Alpha。

---

### ADR-020：Label Is Dataset

Label 不是临时生成，而是独立管理的 Dataset。Label 拥有 Registry 和独立版本。

---

### ADR-021：Purged CV Mandatory

任何 Model 不得使用普通 KFold。必须使用 Purged KFold（Purge + Embargo），这是硬规则。

---

### ADR-022：Notebook Never In Production

Notebook 只能探索，不能生产。最终必须 Pipeline。

---

### ADR-023：Validation Is Gate

Validation 永远不能被跳过。整个系统唯一允许进入 Strategy 的入口就是 Validation。

---

### ADR-024：Everything Is Rule

验证规则全部配置化，采用 Rule Engine 而非硬编码 `if` 判断。

---

### ADR-025：Only Validation Can Promote Strategy

只有 Validation Layer 才能将策略提升到下一阶段。

---

### ADR-026：Strategy Produces Decision

Strategy 输出的是 Decision，不是 Order。

---

### ADR-027：Model Ends Before Strategy

Model 在 Research Layer 结束，Strategy 从 Policy 开始。两者不重叠。

---

### ADR-028：Policy Over Algorithm

策略是投资政策（Policy），不是算法（Algorithm）。

---

### ADR-029：Portfolio Owns Risk

Risk 不是独立的 Layer，而是 Portfolio 的能力。Portfolio、Risk、Capital Allocation 三个在代码层面合并为 `portfolio/`。

---

### ADR-030：Capital Allocation Is Portfolio Responsibility

资金分配是 Portfolio 层的职责。

---

## 5. 技术决策记录（TDR）

> TDR 记录技术选型决策，生命周期约 2–5 年。与 ADR 分离，换技术时只改 TDR 不改 ADR。

| 编号 | 决策 | 说明 |
|---|---|---|
| TDR-001 | AkShare | 当前数据源 |
| TDR-002 | DuckDB | 分析型数据库 |
| TDR-003 | Parquet | 列式存储格式 |
| TDR-004 | LightGBM | 默认模型算法 |
| TDR-005 | Optuna | 超参数优化（未来） |
| TDR-006 | SHAP | 模型可解释性 |
| TDR-007 | Pydantic | 配置与数据模型 |
| TDR-008 | Loguru | 日志库 |
| TDR-009 | APScheduler | 调度器 |
| TDR-010 | Polars | DataFrame（可选替代 Pandas） |

---

## 6. DP-001：Platform Layer

### 6.1 Background

Platform Layer 是整个系统的运行时基础设施（Runtime Foundation）。如果没有统一平台层，会出现：配置散落各处、日志各自初始化、调度入口混乱、Experiment Metadata 无法统一、CLI 越来越混乱——最终形成 Big Ball of Mud。

**Kernel Architecture**：Platform Layer 不是传统的 Utilities，而是 Kernel（内核）。整个系统只有一个 Runtime，所有 Layer 运行在同一个 Runtime 之上。

### 6.2 Goals / Non-goals

**Goals**：
- G1. Single Runtime：整个系统只有一个 Runtime
- G2. Single Entry：所有操作通过 `qp` CLI 进入
- G3. Unified Lifecycle：统一的 Application Startup → Bootstrap → Run → Shutdown
- G4. Unified Infrastructure：统一提供 Config、Logger、Scheduler、Metadata、Storage Factory
- G5. Keep Runtime Lightweight：Platform 不允许演变成企业级中间件

**Non-goals**：
- NG-1. 不做业务计算（Feature、Factor、Model、Portfolio 禁止进入 Platform）
- NG-2. 不管理业务状态（Position、Order、Strategy、Portfolio 属于 Domain）
- NG-3. 不做数据处理（ETL、Cleaning、Validation 属于 Data Layer）
- NG-4. 不实现业务 Registry（Feature/Model/Strategy Registry 只提供接口）

### 6.3 Design Philosophy

| 原则 | 说明 |
|---|---|
| Runtime over Framework | 平台提供运行环境，不是开发框架 |
| CLI First | CLI 是唯一入口，GUI/API/Telegram 全部调用 CLI |
| Composition over Inheritance | 优先组合，避免深层继承 |
| Configuration over Hardcode | 路径、参数、数据源、目录全部来自 Config |
| Everything Observable | 任何任务可记录、可追踪、可重放、可审计 |
| Deterministic Runtime | 同样输入 + 同样 Config + 同样 Seed = 相同结果 |
| Walking Skeleton First | Platform 只实现 Walking Skeleton 当前需要的能力 |

### 6.4 Architecture

```
                         qp CLI
                            │
                            ▼
                  ┌─────────────────┐
                  │ Application      │
                  │     Kernel       │
                  └─────────────────┘
                            │
     ┌──────────────┬───────────────┬───────────────┐
     │              │               │               │
 Config        Logging        Scheduler      Metadata
     │              │               │               │
     └──────────────┴───────────────┴───────────────┘
                            │
                     Service Container
                            │
        ┌──────────┬──────────┬──────────┬──────────┐
        │          │          │          │
      Data     Research   Strategy   Portfolio ...
```

### 6.5 Runtime State Machine

```
CREATED → INITIALIZING → READY → RUNNING → STOPPING → TERMINATED
                                  │
                                  ▼
                               FAILED → STOPPING → TERMINATED
```

原则：Fail Fast。Config Invalid → 立即退出；Logger 初始化失败 → 立即退出；Storage 初始化失败 → 立即退出。不要带病运行。

### 6.6 Runtime Context

```
Configuration / Logger / StorageFactory / Scheduler / Clock / Metadata / Environment
```

任何 Pipeline 只能通过 Runtime 获取组件（`runtime.logger`），不能自己创建。

### 6.7 Configuration System

**四层优先级**：CLI Arguments > Environment Variables > config.toml > Defaults

**Config Tree**（按 Capability 组织，非按 Layer）：

```text
Config
├── project
├── storage
├── logging
├── scheduler
├── data
├── feature
├── model
├── backtest
├── broker
├── monitoring
└── runtime
```

**关键约束**：
- Config 在 Runtime 启动后 Freeze（只读），任何模块不能修改
- Secrets（API Key 等）永远来自 Environment Variables，禁止写入 config.toml
- `os.getenv()` 只能出现在 Platform，业务 Layer 禁止直接读取环境变量
- 每个 Config Section 有明确 Owner，其他 Layer 不能偷偷增加配置

### 6.8 Scheduler Design

```
systemd timer → CLI → APScheduler → Job Registry → Task
```

**技术选型理由**：
- 不用 Airflow：太重，个人项目不需要 DAG 调度平台
- 不用 Celery：需要 Broker（Redis/RabbitMQ），增加运维复杂度
- 不用 cron：无法程序化管理 Job 生命周期
- 选择 systemd timer + CLI + APScheduler：轻量、可控、可编程管理

Job 生命周期：支持 Retry Policy、Lock（防止重复执行）、Idempotency（幂等）、失败恢复。

### 6.9 CLI Design

```bash
qp version
qp doctor
qp ingest <source>
qp feature <name>
qp train <model>
qp validate <strategy>
qp backtest <strategy>
qp report <run_id>
qp run daily
qp scheduler start
qp pipeline list
```

### 6.10 Pipeline Engine（归属 Platform）

所有业务 Pipeline 继承统一的 `BasePipeline`：

```python
class BasePipeline:
    def run(self, context: PipelineContext) -> PipelineResult: ...
```

Platform 提供 `PipelineRunner`、`PipelineContext`、`PipelineResult`。业务 Layer 只需要实现 Pipeline 的具体逻辑。

### 6.11 Directory Layout

```text
qp/
├── platform/
│   ├── runtime/
│   │   ├── application.py
│   │   ├── builder.py
│   │   ├── context.py
│   │   ├── lifecycle.py
│   │   └── state.py
│   ├── config/
│   │   ├── loader.py
│   │   ├── models.py
│   │   ├── validator.py
│   │   └── defaults.py
│   ├── logging/
│   │   ├── logger.py
│   │   ├── formatter.py
│   │   └── context.py
│   ├── scheduler/
│   │   ├── scheduler.py
│   │   ├── job.py
│   │   ├── trigger.py
│   │   └── registry.py
│   ├── storage/
│   │   ├── factory.py
│   │   ├── duckdb.py
│   │   ├── sqlite.py
│   │   └── parquet.py
│   ├── cli/
│   │   ├── main.py
│   │   ├── commands/
│   │   └── parser.py
│   ├── pipeline/
│   │   ├── base.py
│   │   ├── context.py
│   │   ├── result.py
│   │   └── runner.py
│   └── metadata/
│       ├── runtime.py
│       ├── version.py
│       └── environment.py
├── shared/
│   ├── protocols/
│   ├── types/
│   ├── constants/
│   └── exceptions/
├── data/
├── research/
├── validation/
├── strategy/
├── portfolio/
├── simulation/
├── decision/
├── monitoring/
└── knowledge/
```

### 6.12 Project Root 布局决策

**采用方案 B**：`qp/` 作为根 Package（而非 `src/qp/`）。

理由：这是一个 Application，不是 Library。`qp` 既是 CLI 名称、Package 名称、Runtime 名称、Project 名称，全部统一。

### 6.13 Shared Module 约束

`shared/` 只允许四种东西，禁止增加任何目录：

```text
shared/
├── protocols/   # BaseStrategy, BaseModel 等抽象接口
├── types/       # PositionState 等枚举与类型
├── constants/   # DEFAULT_TIMEZONE 等常量
└── exceptions/  # DataValidationError 等异常
```

### 6.14 禁止出现的目录

`utils/`、`helpers/`、`misc/`、`common_utils/`、`temp/`、`scripts/`、`test2/`、`new/`、`backup/` —— 这些都是 Architecture Smell。任何代码必须属于某个 Layer。

---

## 7. DP-002：Data Layer

### 7.1 Mission

> Data Layer exists to produce trusted, versioned, reproducible Data Products for the entire platform.

Data Layer 的职责不是下载数据，而是生产可信、可版本化、可复现的数据产品。

### 7.2 Layer Boundary

```text
                External World
────────────────────────────────────────
        AkShare / Tushare / CSV / API
────────────────────────────────────────
               Data Layer
────────────────────────────────────────
Source Adapter → Raw Dataset → Cleaning → Normalization
→ Validation → Corporate Action → Dataset Builder
→ Data Product → Dataset Registry
────────────────────────────────────────
            Consumer Layers
────────────────────────────────────────
Research / Validation / Strategy / Simulation / Monitoring
```

Research 永远不能 `ak.stock_zh_a_hist(...)`，这是违反架构的。

### 7.3 Responsibilities

**负责**：数据获取、清洗、标准化、PIT 修正、企业行为调整、Dataset Version、Dataset Metadata、Dataset Contract

**不负责**：Feature、Alpha、Label、Signal、Model

### 7.4 Data Philosophy

| 原则 | 说明 |
|---|---|
| Immutable Raw Data | Raw 永远不能修改，只能新增 |
| Deterministic Cleaning | 同一份 Raw，任何时候 Cleaning 结果必须一致 |
| Everything Versioned | Dataset、Metadata、Contract、Validation 全版本化 |
| Trust Through Validation | 数据必须经过 Validation 才可信 |
| Producer / Consumer | Data Layer 是 Producer，Research 是 Consumer |

### 7.5 Component Design

```
Source Adapter → Raw Storage → Cleaning Engine → Validation Engine
→ Corporate Action Engine → Dataset Builder → Dataset Registry → Dataset Loader
```

### 7.6 Data Flow

```
Raw (immutable)
  ↓
Bronze (cleaned, deterministic)
  ↓
Silver (validated, schema-enforced)
  ↓
Gold (PIT-corrected, dataset-ready)
  ↓
Feature Store
```

### 7.7 Dataset Contract

每个 Dataset 必须具备：Name、Owner、Source、Schema、Frequency、Primary Key、Timezone、Coverage、PIT Confidence、Update Policy、Validation Rules、Version。没有 Contract 的 Dataset 禁止发布。

### 7.8 Storage Layout

```text
storage/
├── raw/        # 原始数据，不可修改
├── clean/      # 清洗后数据
├── dataset/    # 发布的数据产品
├── feature/    # 特征存储
├── registry/   # 注册信息
├── metadata/   # 元数据
├── cache/      # 缓存
└── artifact/   # 产物
```

### 7.9 Public Interface

```python
register_source()
build_dataset()
load_dataset()
list_dataset()
validate_dataset()
```

### 7.10 Failure Handling

Pipeline 失败时，Dataset 不能覆盖旧版本——昨天成功的 Dataset 仍然 Available。这是金融系统的基本原则。

### 7.11 Directory Layout

```text
qp/data/
├── adapter/
├── cleaning/
├── validation/
├── builder/
├── loader/
├── contract/
├── dataset/
├── calendar/
├── corporate_action/
└── metadata/
```

---

## 8. DP-003：Research Layer

### 8.1 Mission

> Research Layer exists to transform trusted Data Products into reproducible Investment Knowledge.

研究的目标不是训练模型，而是发现规律、沉淀可复现的投资知识。模型只是知识的载体。

### 8.2 Layer Position

```
Data Layer → Research Layer → Validation Layer → Strategy Layer
```

### 8.3 Responsibilities

**负责**：Feature Engineering、Label Engineering、Dataset Split、Purged CV、Model Training、Model Evaluation、Feature Importance、Experiment、Hyperparameter Search、Artifact Generation

**不负责**：Portfolio、Position、Risk、Execution

### 8.4 Research Philosophy

| 原则 | 说明 |
|---|---|
| Research Produces Knowledge | 不是 Model，Model 只是 Knowledge 的表达 |
| Everything Is Experiment | 任何训练都是 Experiment |
| Feature First | Model 可以换，Feature 才是 Alpha |
| Label Is Product | Label 是独立 Dataset，拥有 Registry |
| Reproducibility | 一年后必须 100% 重新跑出来 |
| No Notebook Dependency | Notebook 只能探索，最终必须 Pipeline |

### 8.5 Architecture

```
Dataset Loader → Feature Pipeline → Label Pipeline
→ Training Dataset → Experiment Runner → Model Trainer
→ Model Evaluator → Artifact Builder → Experiment Tracker
```

### 8.6 Component Design

```text
feature/     # 特征工程
label/       # 标签工程
dataset/     # 训练数据集管理
split/       # 数据集切分（Purged CV）
trainer/     # 模型训练（Plugin 模式：LightGBM/XGBoost/...）
evaluator/   # 模型评估（IC、Rank IC、Sharpe 等量化指标）
experiment/  # 实验管理
artifact/    # 产物管理（Model、SHAP、Metrics、Report）
importance/  # 特征重要性分析
pipeline/    # 研究 Pipeline 编排
```

### 8.7 Purged CV

整个系统统一 Purged KFold。任何 Model 不得使用普通 KFold——这是硬规则。

- 严格按时间顺序切分（Walk-Forward），默认 5 折
- Purge：训练集与验证集之间，标签计算窗口存在重叠的样本从训练集剔除
- Embargo：验证集结束后额外留出禁运期
- 最小训练窗口：不少于 2 年（约 500 个交易日）

### 8.8 Experiment

一个 Experiment 必须包含：

```
Dataset Version → Feature Version → Label Version
→ Model Version → Parameters → Metrics → Artifacts
```

缺一不可。

### 8.9 Experiment State Machine

```
CREATED → RUNNING → COMPLETED → REGISTERED → VALIDATED → ARCHIVED
              │
              ▼
           FAILED → ARCHIVED
```

### 8.10 Public Interface

```python
run_experiment()
train_model()
evaluate_model()
build_feature()
build_label()
```

### 8.11 Directory Layout

```text
qp/research/
├── feature/
├── label/
├── dataset/
├── split/
├── trainer/
├── evaluation/
├── experiment/
├── artifact/
├── importance/
└── pipeline/
```

---

## 9. DP-004：Validation Layer

### 9.1 Mission

> Validation Layer exists to decide whether a research result is trustworthy enough to become an investment strategy.

Research 输出 Knowledge，Validation 输出 Confidence，Strategy 消费 Confidence。

### 9.2 Layer Position

```
Research → Validation → Strategy
```

Validation 永远不能被跳过。整个系统唯一允许进入 Strategy 的入口就是 Validation。这是一个 Gate，不是一个工具。

### 9.3 Validation Pipeline

```
Experiment
  ↓
Statistical Validation（IC、Rank IC、IC_IR、t-stat）
  ↓
Walk Forward Validation
  ↓
Backtest Validation
  ↓
Stress Test
  ↓
Risk Check
  ↓
Production Assessment
  ↓
Validation Report
```

任何一步失败 → 全部失败。

### 9.4 Validation Object

```python
ValidationResult:
    status          # PASS / FAIL
    score           # 综合评分
    confidence      # 置信度
    metrics         # 各项指标
    failed_rules    # 失败的规则
    recommendation  # Paper Trading / Shadow / Reject
```

Strategy 只能接收 ValidationResult，不能直接读取 Experiment。

### 9.5 Rule Engine

所有验证规则配置化，采用 Rule Engine：

```
Rule 1: Rank IC > 0.03  → PASS/FAIL
Rule 2: IC_IR > 0.5     → PASS/FAIL
Rule 3: Sharpe > 1.0    → PASS/FAIL
Rule 4: Max Drawdown < 25% → PASS/FAIL
Rule 5: Turnover in range → PASS/FAIL
→ Ready
```

---

## 10. DP-005：Strategy Layer

### 10.1 Mission

> Strategy Layer converts validated predictions into executable investment policies.

策略不是预测，不是交易，而是 Policy（投资政策）。

### 10.2 Pipeline

```
Prediction → Signal → Universe → Ranking → Filter → Entry → Exit → Decision
```

输出是 Decision，不是 Order。

### 10.3 Decision Object

```python
Decision:
    symbol
    action          # BUY / SELL / HOLD
    target_weight
    reason
    confidence
    strategy_version
```

Portfolio 消费 Decision。

---

## 11. DP-006：Portfolio Layer

### 11.1 Mission

> Transform investment decisions into feasible portfolios.

### 11.2 合并说明

Portfolio、Risk、Capital Allocation 三个在代码层面合并为 `portfolio/`，因为 Risk 和 Capital 本质都是 Portfolio 的能力，而不是三个平级 Layer。逻辑层面保持十二层，代码层面不过度拆分。

### 11.3 Pipeline

```
Decision → Risk Control → Capital Allocation → Constraint Check → Portfolio → Order Request
```

### 11.4 核心对象

Portfolio、Position、Allocation、Exposure。

---

## 12. DP-007：Simulation Layer

### 12.1 Mission

> Simulate reality before entering reality.

### 12.2 范围

Paper Trading、Shadow Trading、Backtest、Execution Simulation 全部统一在 Simulation Layer。Broker 只是 Plugin。

---

## 13. DP-008：Decision Layer

### 13.1 Mission

> Make every investment decision explainable and auditable.

### 13.2 核心职责

Decision Layer 不是 AI，不是 LLM，而是 Audit。所有买入、卖出、不买、不卖的决定都必须可解释（Explainable）。

---

## 14. DP-009：Monitoring Layer

### 14.1 Mission

> Observe. Never Decide.

### 14.2 核心职责

Monitoring 只有 Observation，没有 Decision。避免自动化风险。包括：漂移检测（PSI）、市场状态感知（Market Regime Engine）、Kill Switch 熔断机制。

---

## 15. DP-010：Knowledge Layer

### 15.1 Mission

> Preserve every lesson learned.

### 15.2 核心职责

Knowledge 不是 Wiki，不是 Markdown，而是整个系统的长期记忆。

纳入范围：Research Debt、Decision Audit、Experiment Summary、Failure Analysis、Post Mortem。

---

## 16. Pipeline Engine（横切能力）

Pipeline Engine 不是独立的第十三层，而是 **Platform Layer 的核心能力**。

```
Platform Layer
├── Runtime
├── Scheduler
├── CLI
├── Storage
└── Pipeline Engine   ← 归属 Platform
```

所有业务 Pipeline 统一继承：

```python
class BasePipeline:
    def run(self, context: PipelineContext) -> PipelineResult: ...
```

系统 Pipeline 全景：

- `DataPipeline` — 数据采集与清洗
- `FeaturePipeline` — 特征计算
- `TrainingPipeline` — 模型训练
- `BacktestPipeline` — 回测
- `DailyPipeline` — 每日调度
- `MonitoringPipeline` — 监控

---

## 17. 工程规范（Engineering Handbook）

### 17.1 Naming

| 类型 | 规范 | 示例 |
|---|---|---|
| 文件 | `snake_case.py` | `feature_pipeline.py` |
| 类 | `PascalCase` | `FeaturePipeline` |
| 函数 | `snake_case` | `build_feature()` |
| 常量 | `UPPER_CASE` | `DEFAULT_TIMEZONE` |
| 抽象类 | `BaseXXXX` | `BaseStorage`、`BaseBroker` |

### 17.2 Code Rules

- **禁止 Magic Number**：全部来自 Config
- **禁止 `print()`**：全部使用 Logger
- **禁止裸 `except:`**：必须明确异常类型
- **禁止 Circular Import**
- **禁止跨 Layer Import**

### 17.3 Test Structure

```
tests/
├── unit/
├── integration/
└── e2e/
```

### 17.4 Definition of Done（每个 Milestone）

- ✅ `uv sync` 成功
- ✅ `ruff format` 通过
- ✅ `ruff check` 零错误
- ✅ `pyright` 零错误
- ✅ `pytest` 全部通过
- ✅ 至少一个 CLI 命令可运行
- ✅ README 同步更新
- ✅ 涉及设计变化时新增 ADR

### 17.5 版本管理

- Git Tag 每个 Milestone：`v0.0.1-bootstrap` → `v0.0.7-platform`
- Rule 32：Never Leave the Main Branch Broken——任何时候 main 分支必须可安装、可启动、可运行、可测试

---

## 18. Sprint 0：Bootstrap 计划

> 目标：在接触任何数据源之前，先把 Platform Layer 的骨架立起来。遵循"先搭舞台，再请演员"的原则。

### Milestone 0：Project Bootstrap（半天）

建立项目骨架：`pyproject.toml`、`README.md`、`.gitignore`、`.editorconfig`、`.pre-commit-config.yaml`、`.python-version`

交付：`uv sync && uv run qp version` 成功。

### Milestone 1：Project Layout

建立全部 Layer 目录（空目录，不写业务）。

### Milestone 2：Configuration

实现 `platform/config/`：defaults、loader、validator、models。

交付：`config = load_config()` 可打印 `config.project.name`。

### Milestone 3：Logging

实现 `platform/logging/`：logger、formatter、context。

交付：`runtime.logger.info(...)`。

### Milestone 4：Runtime

实现 Runtime、Builder、Context、State Machine、Lifecycle。

交付：`runtime = build_runtime(); runtime.start(); runtime.stop()`。

### Milestone 5：Pipeline Engine

实现 `BasePipeline`、`PipelineContext`、`PipelineResult`、`PipelineRunner`。

### Milestone 6：CLI

实现 `qp version`、`qp doctor`、`qp pipeline list`。

### Milestone 7：Storage Factory

实现 DuckDB、SQLite、Parquet 的 Factory。

交付：Platform Layer 完成。

---

## 19. 文档目录结构建议

```text
docs/
├── constitution/           # 项目宪法
│   └── constitution-v4.2.md
├── architecture/           # 参考架构
│   ├── reference/          # 十二层架构总览
│   ├── platform/           # DP-001
│   ├── data/               # DP-002
│   ├── research/           # DP-003
│   ├── validation/         # DP-004
│   ├── strategy/           # DP-005
│   ├── portfolio/          # DP-006
│   ├── simulation/         # DP-007
│   ├── decision/           # DP-008
│   ├── monitoring/         # DP-009
│   └── knowledge/          # DP-010
├── adr/                    # 架构决策记录
│   ├── ADR-001-hybrid-architecture.md
│   ├── ADR-002-cli-name.md
│   └── ...
├── tdr/                    # 技术决策记录
│   ├── TDR-001-akshare.md
│   ├── TDR-002-duckdb.md
│   └── ...
└── implementation/         # 工程规范
    ├── coding-style.md
    ├── naming.md
    └── testing.md
```

---

## 20. 建议新增宪法条文

以下是在设计过程中识别出的、建议补充进《项目宪法》的规则：

### Rule 29：No Orphan Code

任何代码必须属于某一个 Layer、某一个 Domain 或某一个 Platform Component。禁止出现没有明确归属的代码。直接约束 utils/helper/common/script 的泛滥。

### Rule 30：Architecture Before Code

任何新增的重要功能，都必须先完成 Design Proposal，再开始编码。具体要求：
1. 影响公共接口的功能，必须先完成设计评审
2. 引入新的核心组件（Broker、Risk Model、Registry 等）时，必须先完成对应的 DP
3. 新增重大技术选型时，必须新增对应的 TDR
4. 代码实现必须能够追溯到相应的 Design Proposal、ADR 或 TDR

### Rule 32：Never Leave the Main Branch Broken

任何时候 main 分支必须可安装、可启动、可运行、可测试。即使功能只有 5%，也不能出现编译不过的情况。

---

*本文档整理自原始设计讨论，与《量化投资平台项目宪法 v4.2》和《落地执行计划 全职节奏》配套使用。后续任何修改请遵循宪法第 12 节修订流程并留痕。*
