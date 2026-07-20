# QP (Quant Platform) 详细开发计划 v1.0

> 综合《项目宪法 v4.2》(rule.md)、《设计文档体系》(dp.md)、《落地执行计划》(plan.md) 三份文档，结合当前仓库实际状态制定的详细执行计划。
>
> 最后更新：2026-07-20

---

## 目录

1. [项目当前状态](#1-项目当前状态)
2. [架构总览](#2-架构总览)
3. [总体时间线](#3-总体时间线)
4. [Phase 0：Sprint 0 Bootstrap — 平台骨架](#4-phase-0sprint-0-bootstrap--平台骨架)
5. [Phase 1：Walking Skeleton — 端到端最小闭环](#5-phase-1walking-skeleton--端到端最小闭环)
6. [Phase 2：Validation Gate + Kill Switch 最小版](#6-phase-2validation-gate--kill-switch-最小版)
7. [Phase 3：Portfolio Risk + Capital Allocation](#7-phase-3portfolio-risk--capital-allocation)
8. [Phase 4：Registry & Lineage + Simulation 正式版](#8-phase-4registry--lineage--simulation-正式版)
9. [Phase 5：监控、熔断、知识沉淀](#9-phase-5监控熔断知识沉淀)
10. [Phase 6：缓冲与复盘](#10-phase-6缓冲与复盘)
11. [质量门禁 (Definition of Done)](#11-质量门禁-definition-of-done)
12. [风险管理](#12-风险管理)
13. [附录：完整里程碑检查清单](#13-附录完整里程碑检查清单)

---

## 1. 项目当前状态

### 1.1 已完成

| 项目 | 状态 | 说明 |
|---|---|---|
| Git 仓库初始化 | ✅ 完成 | 仅一个 commit `29d6c06 first version, start coding` |
| 目录骨架 | ✅ 完成 | 10 层目录 + shared + tests 全部创建 |
| ADR 文档 (30 篇) | ✅ 完成 | `docs/adr/ADR-001` ~ `ADR-030` |
| TDR 文档 (10 篇) | ✅ 完成 | `docs/tdr/TDR-001` ~ `TDR-010` |
| DP 设计文档 (10 篇) | ✅ 完成 | `docs/architecture/{layer}/DP-00X-*.md` |
| 工程规范文档 | ✅ 完成 | coding-style, naming, testing |
| CLAUDE.md | ✅ 完成 | 项目指引文件 |
| 项目宪法 v4.2 | ✅ 完成 | `docs/constitution/constitution-v4.2.md` |

### 1.2 待完成（所有 `__init__.py` 仍为空占位）

| 模块 | 状态 | 说明 |
|---|---|---|
| `pyproject.toml` | ❌ 未创建 | Phase 0 Milestone 0 |
| Platform 全部子模块 | ❌ 空文件 | config/logging/runtime/pipeline/cli/storage/scheduler/metadata |
| Data Layer | ❌ 空目录 | 10 个子模块全部为空 |
| Research Layer | ❌ 空目录 | 9 个子模块全部为空 |
| Validation Layer | ❌ 空目录 | — |
| Strategy Layer | ❌ 空目录 | — |
| Portfolio Layer | ❌ 空目录 | — |
| Simulation Layer | ❌ 空目录 | — |
| Decision Layer | ❌ 空目录 | — |
| Monitoring Layer | ❌ 空目录 | — |
| Knowledge Layer | ❌ 空目录 | — |
| Shared 模块 | ❌ 空目录 | protocols/types/constants/exceptions |
| 测试 | ❌ 空目录 | unit/integration/e2e |

---

## 2. 架构总览

### 2.1 十层架构（dp.md 最终版，合并 Portfolio+Risk+Capital）

```
Layer 1:  platform/      — 运行时基础设施（配置、日志、调度、存储、CLI、Pipeline 引擎）
Layer 2:  data/          — 可信、可版本化的数据产品（Data Products）
Layer 3:  research/      — 可复现实验（特征、标签、模型、Purged CV）
Layer 4:  validation/    — 研究到策略的守门人（Rule Engine）
Layer 5:  strategy/      — 投资政策，输出 Decision（非 Order）
Layer 6:  portfolio/     — 组合构建 + 风险控制 + 资金分配（ADR-029/030 合并）
Layer 7:  simulation/    — 纸面交易、影子交易、回测
Layer 8:  decision/      — 可解释、可审计的决策
Layer 9:  monitoring/    — 仅观察，不决策（漂移检测、熔断）
Layer 10: knowledge/     — 长期记忆（事后分析、实验总结、失败归档）
```

### 2.2 关键设计决策速查

| ADR | 决策 | 影响 |
|---|---|---|
| ADR-001 | 混合架构：DataFrame Pipeline + Domain Model | 数据/研究用列式，组合/订单用对象 |
| ADR-002 | CLI 名称 `qp`，唯一入口 | 所有操作通过 `qp` CLI |
| ADR-003 | 无 DI 框架，显式 Composition Root | `builder.py` 手动组装 |
| ADR-005 | Phase 0 无 Event Bus | Layer 间直接调用 |
| ADR-006 | Everything Is Pipeline | `BasePipeline.run(context) -> PipelineResult` |
| ADR-012 | Runtime 拥有所有基础设施 | Pipeline 通过 `runtime.logger` 获取 |
| ADR-013 | Data Product Architecture | 消费者依赖 Dataset，不依赖数据源 |
| ADR-021 | Purged CV 强制 | 禁止普通 KFold |
| ADR-029 | Portfolio 合并 Risk + Capital Allocation | `portfolio/` 一个目录三个职责 |

### 2.3 技术栈

| 技术 | 用途 | TDR |
|---|---|---|
| Python 3.12+ | 语言 | — |
| uv | 包管理 | — |
| Pydantic | 配置与数据模型 | TDR-007 |
| Loguru | 日志 | TDR-008 |
| APScheduler | 调度 | TDR-009 |
| DuckDB | 分析数据库 | TDR-002 |
| Parquet | 列式存储 | TDR-003 |
| Polars | DataFrame（可选替代 Pandas） | TDR-010 |
| LightGBM | 默认 ML 模型 | TDR-004 |
| AkShare | 当前数据源 | TDR-001 |
| Optuna | 超参优化（未来） | TDR-005 |
| SHAP | 模型可解释性 | TDR-006 |

---

## 3. 总体时间线

```
Phase 0: 第 1–4 周     Sprint 0 Bootstrap — 平台骨架 + Walking Skeleton
Phase 1: 第 5–8 周     Validation Gate + Kill Switch 最小版 + LightGBM 建模
Phase 2: 第 9–12 周    Portfolio Risk 最小版 + 多策略并行
Phase 3: 第 13–16 周   Capital Allocation 升级
Phase 4: 第 17–22 周   Registry & Lineage + Simulation 正式版
Phase 5: 第 23–26 周   监控、熔断、知识沉淀
Phase 6: 第 27–28 周   缓冲 + 复盘
```

**总计：约 24–28 周（6–7 个月）到"10 层可用水平"**

---

## 4. Phase 0：Sprint 0 Bootstrap — 平台骨架

> **周期**：第 1–4 周
> **目标**：建立 Platform Layer 全部基础设施 + 端到端 Walking Skeleton 跑通
> **原则**：先搭舞台，再请演员。不接触任何数据源之前，先把 Platform 骨架立起来。
> **对应**：dp.md §18 + plan.md 第 1–4 周 + rule.md §8

### Milestone 0.0：项目工程化（第 1 周，1–2 天）

**目标**：项目可安装、CLI 可运行

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.0.1 | 创建 `pyproject.toml` | 定义 `qp` 包、Python 3.12+、依赖（pydantic、loguru、duckdb、apscheduler、pyarrow、polars、lightgbm）、dev 依赖（pytest、ruff、pyright） | `pyproject.toml` |
| 0.0.2 | 创建 `.python-version` | 锁定 Python 3.12 | `.python-version` |
| 0.0.3 | 创建 `.editorconfig` | 统一编辑器配置 | `.editorconfig` |
| 0.0.4 | 创建 `.pre-commit-config.yaml` | ruff format + ruff check + pyright 检查 | `.pre-commit-config.yaml` |
| 0.0.5 | 更新 `.gitignore` | Python 项目标准忽略项 | `.gitignore` |
| 0.0.6 | 创建 `README.md` | 项目介绍、快速开始、架构图、开发指南 | `README.md` |
| 0.0.7 | 实现 `qp/platform/metadata/version.py` | 版本号定义 `__version__ = "0.0.1"` | 可 import 的版本号 |
| 0.0.8 | 实现 `qp version` CLI 命令 | 打印版本号的最小 CLI | CLI 可运行 |

**验收标准**：
```bash
uv sync                # 成功
uv run qp version      # 输出 "qp 0.0.1"
ruff format            # 通过
ruff check             # 零错误
pyright                # 零错误
pytest                 # 全部通过
```

---

### Milestone 0.1：Shared 模块（第 1 周，1 天）

**目标**：建立跨层共享的基础类型和接口

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.1.1 | `shared/constants/` | `DEFAULT_TIMEZONE`、`DEFAULT_CURRENCY`、`TRADING_DAYS_PER_YEAR` 等常量 | `constants/__init__.py` |
| 0.1.2 | `shared/types/` | `PositionState` 枚举（IDEA→CANDIDATE→APPROVED→HOLDING→REDUCING→CLOSED→ARCHIVED）、`OrderSide`、`MarketRegime` 等 | `types/__init__.py` |
| 0.1.3 | `shared/exceptions/` | `QPError`(基类)、`ConfigError`、`DataValidationError`、`PipelineError`、`LayerViolationError` | `exceptions/__init__.py` |
| 0.1.4 | `shared/protocols/` | 9 个核心抽象接口的桩（空实现或 `NotImplementedError`） | `protocols/__init__.py` |

**验收标准**：所有类型可 import，`PositionState.HOLDING.value == 4`

---

### Milestone 0.2：Configuration System（第 1 周，2 天）

**目标**：实现四层优先级配置系统

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.2.1 | `config/defaults.py` | 所有配置项的默认值：project、storage、logging、scheduler、data、feature、model、backtest、broker、monitoring、runtime | `defaults.py` |
| 0.2.2 | `config/models.py` | Pydantic 配置模型：`ProjectConfig`、`StorageConfig`、`LoggingConfig`、`SchedulerConfig`、`DataConfig`、`RuntimeConfig` 等 | `models.py` |
| 0.2.3 | `config/loader.py` | 四层优先级加载：CLI Args > Env Vars > config.toml > Defaults；加载后 freeze | `loader.py` |
| 0.2.4 | `config/validator.py` | 配置合法性校验：路径是否存在、必要字段是否缺失、类型是否正确 | `validator.py` |
| 0.2.5 | 创建 `config.toml.example` | 模板配置文件，供新用户复制 | 项目根目录 |

**关键约束**：
- Secrets 永远来自环境变量
- `os.getenv()` 只能出现在 `config/loader.py`
- 加载后 Config 对象 freeze（只读），任何模块不能修改

**验收标准**：
```python
from qp.platform.config import load_config
config = load_config()
print(config.project.name)  # "qp"
config.project.name = "x"   # 抛出 FrozenInstanceError
```

---

### Milestone 0.3：Logging System（第 1 周，1 天）

**目标**：统一日志基础设施，禁止 `print()`

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.3.1 | `logging/logger.py` | 基于 Loguru 的 `QPLogger` 封装：支持结构化日志、上下文绑定、级别控制 | `logger.py` |
| 0.3.2 | `logging/formatter.py` | 统一格式：时间戳 + 级别 + 模块名 + 消息，支持 JSON 格式（生产）和彩色格式（开发） | `formatter.py` |
| 0.3.3 | `logging/context.py` | `LogContext`：绑定 run_id、pipeline_name、实验 ID 等上下文 | `context.py` |

**验收标准**：
```python
logger.info("Platform initialized", run_id="run-001")
# 2026-07-20 10:00:00 | INFO | platform | Platform initialized | run_id=run-001
```

---

### Milestone 0.4：Runtime & Lifecycle（第 2 周，2–3 天）

**目标**：实现 Runtime 状态机和 Composition Root

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.4.1 | `runtime/state.py` | 状态枚举 `CREATED → INITIALIZING → READY → RUNNING → STOPPING → TERMINATED` (+ `FAILED`) | `state.py` |
| 0.4.2 | `runtime/context.py` | `RuntimeContext`：持有 Config、Logger、StorageFactory、Scheduler、Clock、Metadata、Environment 引用 | `context.py` |
| 0.4.3 | `runtime/lifecycle.py` | `LifecycleManager`：状态转换、启动顺序、关闭顺序、Fail Fast 逻辑 | `lifecycle.py` |
| 0.4.4 | `runtime/builder.py` | `build_runtime()` 显式 Composition Root：config → logger → scheduler → storage → runtime | `builder.py` |
| 0.4.5 | `runtime/application.py` | `Application` 类：聚合 RuntimeContext + LifecycleManager，提供 `start()` / `stop()` | `application.py` |

**Fail Fast 原则**：
- Config Invalid → 立即退出
- Logger 初始化失败 → 立即退出
- Storage 初始化失败 → 立即退出

**验收标准**：
```python
from qp.platform.runtime import build_runtime
runtime = build_runtime()
runtime.start()
assert runtime.state == RuntimeState.READY
runtime.logger.info("hello")  # 通过 runtime 获取 logger
runtime.stop()
```

---

### Milestone 0.5：Pipeline Engine（第 2 周，2 天）

**目标**：统一 Pipeline 抽象

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.5.1 | `pipeline/base.py` | `BasePipeline` 抽象类：`run(context: PipelineContext) -> PipelineResult` | `base.py` |
| 0.5.2 | `pipeline/context.py` | `PipelineContext`：包含 runtime 引用、pipeline 名称、run_id、start_time、parameters | `context.py` |
| 0.5.3 | `pipeline/result.py` | `PipelineResult`：status (SUCCESS/FAILED/PARTIAL)、metrics、artifacts、errors、duration | `result.py` |
| 0.5.4 | `pipeline/runner.py` | `PipelineRunner`：执行 Pipeline、记录上下文、处理异常、记录审计日志 | `runner.py` |

**验收标准**：
```python
class MyPipeline(BasePipeline):
    def run(self, context):
        context.logger.info("running")
        return PipelineResult(status=PipelineStatus.SUCCESS)

runner = PipelineRunner(runtime)
result = runner.run(MyPipeline())
assert result.status == PipelineStatus.SUCCESS
```

---

### Milestone 0.6：Storage Factory（第 3 周，2 天）

**目标**：统一存储后端访问

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.6.1 | `storage/factory.py` | `StorageFactory`：根据配置返回对应后端实例 | `factory.py` |
| 0.6.2 | `storage/duckdb.py` | DuckDB 连接管理、数据库初始化 | `duckdb.py` |
| 0.6.3 | `storage/sqlite.py` | SQLite 连接管理（轻量场景） | `sqlite.py` |
| 0.6.4 | `storage/parquet.py` | Parquet 读写封装 | `parquet.py` |

**关键约束**：
- Platform 只提供 Storage Factory，不提供 Repository
- Repository 属于各业务 Layer（如 `ExperimentRepository` 在 research/）

**验收标准**：
```python
storage = runtime.storage_factory.get_storage("duckdb")
assert storage.is_connected()
```

---

### Milestone 0.7：Scheduler（第 3 周，2 天）

**目标**：可编程的 Job 调度

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.7.1 | `scheduler/scheduler.py` | 基于 APScheduler 的 `QPScheduler`：启动/停止/添加 Job/移除 Job | `scheduler.py` |
| 0.7.2 | `scheduler/job.py` | `Job` 定义：名称、触发器、任务、重试策略、锁（防重复执行）、幂等 | `job.py` |
| 0.7.3 | `scheduler/trigger.py` | Trigger 定义：Cron、Interval、Date | `trigger.py` |
| 0.7.4 | `scheduler/registry.py` | `JobRegistry`：管理已注册的 Job、查询、启停 | `registry.py` |

**验收标准**：
```python
scheduler = runtime.scheduler
scheduler.add_job(Job(name="daily_ingest", trigger=CronTrigger(hour=17, minute=30), task=ingest_task))
scheduler.start()
```

---

### Milestone 0.8：CLI System（第 3–4 周，2 天）

**目标**：完整的 `qp` CLI 入口

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.8.1 | `cli/main.py` | `qp` 主入口：参数解析、命令分发 | `main.py` |
| 0.8.2 | `cli/parser.py` | 子命令注册：`version`、`doctor`、`ingest`、`feature`、`train`、`validate`、`backtest`、`report`、`run`、`scheduler`、`pipeline` | `parser.py` |
| 0.8.3 | 实现 `qp version` | 打印版本号 | 可运行 |
| 0.8.4 | 实现 `qp doctor` | 环境检查：Python 版本、依赖、数据库连接、磁盘空间 | 可运行 |
| 0.8.5 | 实现 `qp pipeline list` | 列出已注册的 Pipeline | 可运行 |

**验收标准**：
```bash
qp version     # qp 0.0.1
qp doctor      # 所有检查通过
qp pipeline list  # 输出 Pipeline 列表
qp --help      # 输出帮助
```

---

### Milestone 0.9：Metadata（第 4 周，1 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 0.9.1 | `metadata/runtime.py` | 运行时元数据：启动时间、Python 版本、平台信息 | `runtime.py` |
| 0.9.2 | `metadata/environment.py` | 环境信息：OS、CPU、内存、磁盘 | `environment.py` |

---

### Milestone 0.10：协议接口实现（第 4 周，贯穿前面 Milestone）

**目标**：将 rule.md §7 的全部核心抽象接口落盘到 `shared/protocols/`

| # | 接口 | 来源 | 关键方法 |
|---|---|---|---|
| 0.10.1 | `BaseDataSource` | rule.md §7.1 | `dataset_name`, `fetch_raw()`, `validate_schema()` |
| 0.10.2 | `BaseFeature` | rule.md §7.2 | `feature_name`, `required_data`, `compute()` |
| 0.10.3 | `BaseModel` | rule.md §7.3 | `fit()`, `predict()`, `save_model()`, `load_model()` |
| 0.10.4 | `BaseStrategy` | rule.md §7.4 | `strategy_id`, `generate_signals()` |
| 0.10.5 | `BasePortfolioRiskManager` | rule.md §7.5 | `apply_risk_limits()` |
| 0.10.6 | `BaseCapitalAllocator` | rule.md §7.5 | `allocate_capital()` |
| 0.10.7 | `BaseExperimentTracker` | rule.md §7.6 | `log_experiment()` |
| 0.10.8 | `BaseBroker` | rule.md §7.7 | `submit_order()`, `cancel_order()`, `get_positions()`, `get_cash()` |
| 0.10.9 | `CorporateActionEngine` | rule.md §7.7 | `adjust_portfolio()` |
| 0.10.10 | `BaseRiskModel` | rule.md §7.8 | `decompose_risk()` |

---

### Milestone 0.11：Platform Layer 集成测试（第 4 周，1 天）

| # | 任务 | 详细说明 |
|---|---|---|
| 0.11.1 | Runtime 启动流程集成测试 | config → logger → scheduler → storage → runtime 全链路 |
| 0.11.2 | CLI 命令集成测试 | 每个 CLI 命令的端到端测试 |
| 0.11.3 | Pipeline 执行流程测试 | BasePipeline → PipelineRunner → PipelineResult |
| 0.11.4 | 异常路径测试 | Config 无效 → Fail Fast、Storage 不可用 → 正确报错 |

**Phase 0 总验收（Platform Layer 完成）**：
```bash
uv sync                    # ✅
ruff format                # ✅
ruff check                 # ✅ 零错误
pyright                    # ✅ 零错误
pytest                     # ✅ 全部通过
qp version                 # ✅ 输出版本号
qp doctor                  # ✅ 环境检查通过
qp pipeline list           # ✅
```

---

## 5. Phase 1：Walking Skeleton — 端到端最小闭环

> **周期**：第 5–8 周（Phase 0 延伸，与 plan.md 第 1–4 周对应）
> **目标**：数据 → 因子 → 选股 → 回测 → 报告 全流程跑通
> **原则**：不追求规范，追求连通。Rule 28 — Walking Skeleton 优先。
> **对应**：rule.md §8 + plan.md 第 1–4 周

### Milestone 1.1：Data Layer — 数据接入（第 5 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 1.1.1 | `data/adapter/akshare_adapter.py` | 实现 `BaseDataSource`，接入 AkShare 日线行情（`stock_zh_a_hist`） | `AKShareAdapter` |
| 1.1.2 | `data/cleaning/` | 停牌（volume=0）、涨跌停（无法成交）、除权除息（复权因子）、ST/退市处理 | `CleaningEngine` |
| 1.1.3 | `data/validation/` | 基本 Schema 校验：列名、类型、非空、日期范围 | `DataValidator` |
| 1.1.4 | `data/contract/` | Data Contract 定义：`DailyPriceContract`（列定义、频率、主键、时区） | `contract/` |
| 1.1.5 | `data/dataset/` | `DatasetRegistry` 最简版：按名称+版本定位数据 | `DatasetRegistry` |
| 1.1.6 | `data/loader/` | `DatasetLoader`：`load_dataset("daily_price", version="2026-07-20")` | `DatasetLoader` |
| 1.1.7 | `data/calendar/` | 交易日历：A 股交易日获取 | `TradingCalendar` |

**产出物**：`daily_price.parquet` 可稳定生成

**验收标准**：
```python
from qp.data.loader import load_dataset
ds = load_dataset("daily_price", version="2026-07-20")
assert len(ds) > 0
assert "close" in ds.columns
```

---

### Milestone 1.2：Data Layer — 数据清洗深化（第 5–6 周，3 天）

> ⚠️ **计划中特别提醒**：数据清洗是最容易低估的部分，如果超时直接借时间。

| # | 任务 | 详细说明 |
|---|---|---|
| 1.2.1 | 停牌处理 | volume=0 的交易日标记为停牌 |
| 1.2.2 | 涨跌停处理 | 涨跌停价无法成交的标记 |
| 1.2.3 | 复权处理 | 前复权/后复权因子计算 |
| 1.2.4 | ST/退市标记 | ST 股票、退市整理期标记 |
| 1.2.5 | PIT 财务数据 | as-first-reported + as-restated 双版本 |
| 1.2.6 | 数据流水线 | `Bronze → Silver → Gold` 三级数据加工 |

---

### Milestone 1.3：Research Layer — 因子计算（第 6 周，2 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 1.3.1 | `research/feature/momentum.py` | 实现 `BaseFeature`，计算 20 日动量因子 | `Momentum20dFeature` |
| 1.3.2 | `research/feature/` | Feature Registry 最简版（字典注册） | Feature 注册机制 |
| 1.3.3 | `research/feature/` | 截面中性化（行业、市值）基础实现 | 中性化函数 |

**产出物**：`momentum_20d` 因子值

**验收标准**：
```python
feature = Momentum20dFeature()
result = feature.compute(data_map={"daily_price": df})
assert "feature_value" in result.columns
```

---

### Milestone 1.4：Strategy Layer — 简单策略（第 6 周，2 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 1.4.1 | `strategy/simple_rank.py` | 实现 `BaseStrategy`，Top 10 排序选股 | `SimpleRankStrategy` |
| 1.4.2 | 信号生成 | 基于动量因子排名，选取 Top 10 | Signal DataFrame |
| 1.4.3 | Decision 对象 | `Decision`：symbol、action (BUY/SELL/HOLD)、target_weight、reason | `Decision` dataclass |

**验收标准**：
```python
strategy = SimpleRankStrategy(top_n=10)
signals = strategy.generate_signals(as_of_date=date.today())
assert len(signals) == 10
```

---

### Milestone 1.5：Portfolio Layer — 简单组合（第 7 周，2 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 1.5.1 | `portfolio/single_portfolio.py` | `SinglePortfolio`：等权配置，固定调仓日 | `SinglePortfolio` |
| 1.5.2 | 资金分配 | Equal Weight（等权重） | 目标权重 |
| 1.5.3 | Order 生成 | 根据目标权重和当前持仓生成 Order 列表 | `Order` dataclass |

**验收标准**：
```python
portfolio = SinglePortfolio(total_capital=1000000)
orders = portfolio.generate_orders(signals, current_positions)
assert all(o.action in ("BUY", "SELL", "HOLD") for o in orders)
```

---

### Milestone 1.6：Simulation Layer — 简化回测（第 7–8 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 1.6.1 | `simulation/backtest.py` | `SimpleVectorBacktest`：向量化回测引擎 | `SimpleVectorBacktest` |
| 1.6.2 | 滑点模拟 | 固定滑点模型（默认 0.1%） | Slippage |
| 1.6.3 | 交易成本 | 印花税 0.05%、佣金 0.025% | Cost |
| 1.6.4 | 绩效报告 | 生成 Markdown 绩效报告：累计收益、Sharpe、最大回撤、年化波动 | Report |

**产出物**：端到端回测报告

**验收标准**：
```bash
qp backtest simple_rank  # 一行命令输出回测报告
```

---

### Milestone 1.7：Walking Skeleton 集成（第 8 周，2 天）

| # | 任务 | 详细说明 |
|---|---|---|
| 1.7.1 | 全流程 Pipeline | `DataPipeline → FeaturePipeline → StrategyPipeline → PortfolioPipeline → BacktestPipeline` |
| 1.7.2 | `qp run daily` 命令 | 一条命令执行全流程 |
| 1.7.3 | 集成测试 | 端到端测试：数据 → 因子 → 策略 → 组合 → 回测 → 报告 |
| 1.7.4 | 修复所有 ruff/pyright 问题 | 零错误 |

**Phase 1 总验收（Walking Skeleton 跑通）**：
```bash
qp run daily                              # ✅ 一条命令完成全流程
# 输出：daily_price.parquet → momentum_20d → signals → orders → backtest_report.md
```

---

## 6. Phase 2：Validation Gate + Kill Switch 最小版

> **周期**：第 9–12 周
> **目标**：建立策略质量门禁和熔断机制，用 LightGBM 替代简单排序策略
> **对应**：plan.md 第 5–8 周 + rule.md §7.9 + §10.1–10.3

### Milestone 2.1：Validation Layer — 因子检验（第 9 周，3 天）

| # | 任务 | 详细说明 | 阈值 | 产出 |
|---|---|---|---|---|
| 2.1.1 | Rank IC 计算 | 截面 Rank IC 均值 | ≥ 0.02 | `RankICCheck` |
| 2.1.2 | IC_IR 计算 | IC 均值 / IC 标准差 | ≥ 0.3 | `ICIRCheck` |
| 2.1.3 | IC t-stat | 显著性检验 | ≥ 2.0 | `TStatCheck` |
| 2.1.4 | 分层测试 | Top 与 Bottom 分层收益差单调性 | t-stat ≥ 2.0 | `StratificationCheck` |
| 2.1.5 | Rule Engine 框架 | `BaseRule` + `RuleEngine`：全部规则配置化 | `RuleEngine` |

---

### Milestone 2.2：Research Layer — Purged CV（第 9–10 周，3 天）

> ⚠️ **优先级最高**：切分错误会导致过拟合判断失去意义

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 2.2.1 | `research/split/purged_cv.py` | Walk-Forward 时间序列切分，默认 5 折，禁止 shuffle | `PurgedKFold` |
| 2.2.2 | Purge 逻辑 | 训练集与验证集标签计算窗口重叠的样本从训练集剔除 | `purge()` |
| 2.2.3 | Embargo 逻辑 | 验证集结束后额外禁运期，防止特征信息泄漏 | `embargo()` |
| 2.2.4 | 最小训练窗口 | ≥ 2 年（约 500 个交易日） | 参数校验 |
| 2.2.5 | Purged CV 测试 | 验证 Purge/Embargo 正确性 | 单元测试 |

---

### Milestone 2.3：LightGBM 建模流水线（第 10 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 2.3.1 | `research/trainer/lgb_rank.py` | 实现 `BaseModel`：`LightGBMRankModel`，LambdaRank 目标 | `LightGBMRankModel` |
| 2.3.2 | 特征截面标准化 | 单日截面 z-score 标准化 | `Standardizer` |
| 2.3.3 | 训练 Pipeline | `TrainingPipeline`：特征标准化 → 切分 → 训练 → 评估 | `TrainingPipeline` |
| 2.3.4 | 默认超参数 | 按 rule.md §7.9.4 表格配置 | 配置文件 |

**超参数默认起点**：

| 参数 | 默认值 |
|---|---|
| `objective` | `lambdarank` |
| `num_leaves` | 31 |
| `max_depth` | 6 |
| `learning_rate` | 0.05 |
| `n_estimators` | 1000（early stopping） |
| `min_data_in_leaf` | 100 |
| `feature_fraction` | 0.8 |
| `bagging_fraction` | 0.8 |
| `lambda_l1` | 0.5 |
| `lambda_l2` | 0.5 |
| `early_stopping_rounds` | 50 |

---

### Milestone 2.4：过拟合检查（第 10–11 周，2 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 2.4.1 | 样本内/外 IC 比值 | 样本外 IC 低于样本内 IC 50% → 过拟合，禁止上线 | `OverfitCheck` |
| 2.4.2 | 单调约束 | 对有经济学方向的特征使用 `monotone_constraints` | 配置化 |
| 2.4.3 | Feature Importance 输出 | 每次重训后输出 Gain-based Feature Importance 排名 | 可审计输出 |

---

### Milestone 2.5：Backtest Validation（第 11 周，2 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 2.5.1 | `validation/backtest_check.py` | 年化 Sharpe ≥ 1.0、最大回撤 ≤ 25%、换手率在预设区间 | `BacktestCheck` |
| 2.5.2 | 行业/市值中性化检验 | Rule 9：Alpha 必须通过中性化检验 | `NeutralizationCheck` |
| 2.5.3 | `ValidationResult` 模型 | status (PASS/FAIL)、score、confidence、metrics、failed_rules、recommendation | `ValidationResult` |

---

### Milestone 2.6：Kill Switch 最小版（第 11–12 周，2 天）

| # | 任务 | 详细说明 | 阈值 | 产出 |
|---|---|---|---|---|
| 2.6.1 | `monitoring/kill_switch.py` | `KillSwitch` 检查引擎 | — | `KillSwitch` |
| 2.6.2 | 最大回撤检查 | 策略回撤超历史最大回撤 1.5× | — | 暂停信号 |
| 2.6.3 | 组合回撤检查 | 单月 ≥ 15% 或滚动 60 日 ≥ 20% | — | 全组合减仓 |
| 2.6.4 | PSI 漂移检测 | PSI ≥ 0.25 | — | 暂停排产 |

---

### Milestone 2.7：第一策略完整验证（第 12 周，2 天）

| # | 任务 | 详细说明 |
|---|---|---|
| 2.7.1 | LightGBM 策略跑通全部检查 | IC → Purged CV → 过拟合检查 → Backtest → Validation Gate |
| 2.7.2 | Paper Trading 启动 | 30 天 Paper Trading 开始（此后在后台挂钟计时） |
| 2.7.3 | 每日 5–10 分钟检查 Paper Trading | 信号生成是否正常、是否有异常中断 |

**Phase 2 总验收**：
- ✅ Purged CV 框架可用
- ✅ LightGBM 训练流水线可运行
- ✅ Validation Gate 检查可自动化
- ✅ Kill Switch 最小版可用
- ✅ 第一策略进入 Paper Trading

---

## 7. Phase 3：Portfolio Risk + Capital Allocation

> **周期**：第 13–16 周
> **目标**：策略数量扩展到 2+，建设组合层风控和资金分配
> **对应**：plan.md 第 9–16 周

### Milestone 3.1：第二策略研发（第 13 周，贯穿）

| # | 任务 | 详细说明 |
|---|---|---|
| 3.1.1 | 第二策略因子研发 | 新的 Alpha 因子（非动量类） |
| 3.1.2 | IC 检验 + Purged CV | 走完整研究流程 |
| 3.1.3 | Validation Gate | 通过全部检查 |

> 🔄 **并行提示**：第一策略 Paper Trading 在后台计时（第 12 周已启动），不占用开发工时，务必并行推进第二策略。

---

### Milestone 3.2：Portfolio Risk Manager（第 14 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 3.2.1 | `portfolio/risk_manager.py` | 实现 `BasePortfolioRiskManager` | `PortfolioRiskManager` |
| 3.2.2 | 单一持仓上限 | ≤ 组合总资金 8% | 约束检查 |
| 3.2.3 | 单一行业上限 | ≤ 组合总资金 25% | 行业暴露控制 |
| 3.2.4 | 相关性分析 | 持仓间相关性监控 | 风险报告 |
| 3.2.5 | 风险预算 | 总风险预算框架 | 预算分配 |

---

### Milestone 3.3：Paper Trading 判定（第 15 周，1 天）

| # | 任务 | 详细说明 |
|---|---|---|
| 3.3.1 | 30 天 Paper Trading 满期判定 | 实盘信号与回测相关性 ≥ 0.8？滑点偏差 ≤ 50%？ |
| 3.3.2 | Shadow Production 升级 | 通过 → 进入 Shadow Production 观察期 |

---

### Milestone 3.4：Capital Allocation 升级（第 15–16 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 3.4.1 | Risk Parity 实现 | `BaseCapitalAllocator` → `RiskParityAllocator` | Risk Parity |
| 3.4.2 | Fractional Kelly 实现 | 系数 0.25×–0.5×，含敏感性测试 | `KellyAllocator` |
| 3.4.3 | 现金缓冲 | 正常保留 ≥ 5% 现金 | Buffer |

---

### Milestone 3.5：组合层 KPI 看板（第 16 周，2 天）

| # | 指标 | 目标值 |
|---|---|---|
| 3.5.1 | 年化 Sharpe | ≥ 1.2 |
| 3.5.2 | 最大回撤 | ≤ 20% |
| 3.5.3 | Alpha/Beta 收益占比 | Alpha ≥ 60% |
| 3.5.4 | 季度复盘报告 | 书面记录 → Knowledge Layer |

**Phase 3 里程碑检查**：至少 1 策略在 Shadow/Production，1–2 个在 Paper Trading。

---

## 8. Phase 4：Registry & Lineage + Simulation 正式版

> **周期**：第 17–22 周
> **目标**：策略/实验数量增多后的正式管理能力
> **对应**：plan.md 第 17–22 周

### Milestone 4.1：Experiment Tracker 正式版（第 17–18 周，4 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 4.1.1 | `research/experiment/tracker.py` | 实现 `BaseExperimentTracker`：JSON/Parquet 存储实验配置、指标、血缘 | `ExperimentTracker` |
| 4.1.2 | 实验血缘图 | Dataset → Feature → Label → Model → Strategy 全链路版本绑定 | `LineageGraph` |
| 4.1.3 | 实验状态机 | CREATED→RUNNING→COMPLETED→REGISTERED→VALIDATED→ARCHIVED（+FAILED） | State Machine |
| 4.1.4 | 模型版本管理 | 训练窗口、超参数、特征列表版本、模型文件哈希、Git commit | `ModelVersion` |

**模型版本命名规则**：`{algo}_{objective}_v{major}.{minor}`，如 `lgb_lambdarank_v3.1`

---

### Milestone 4.2：Registry 正式版（第 19–20 周，4 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 4.2.1 | Dataset Registry | 数据集注册、版本、Schema、Owner、Source | `DatasetRegistry` |
| 4.2.2 | Feature Registry | 特征注册、依赖、参数、版本 | `FeatureRegistry` |
| 4.2.3 | Model Registry | 模型注册、超参数、训练窗口、文件哈希 | `ModelRegistry` |
| 4.2.4 | Strategy Registry | 策略注册、Feature+Model 绑定、生命周期状态 | `StrategyRegistry` |
| 4.2.5 | 数据库表设计 | DuckDB 表结构（先简单，不引入专门系统） | SQL Schema |

---

### Milestone 4.3：自动化重训（第 19–20 周，并行）

| # | 任务 | 详细说明 |
|---|---|---|
| 4.3.1 | 月度滚动重训 Pipeline | 定时触发，Walk-Forward 训练窗口滚动 |
| 4.3.2 | 重训后自动写入 Registry | 模型版本 + 特征重要性 + 验证指标 |
| 4.3.3 | Feature Importance 变更检测 | Top 5 特征剧烈变化 → 人工复核，暂缓上线 |

---

### Milestone 4.4：Simulation 正式版（第 21 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 4.4.1 | `BaseBroker` 接口实现 | `SimulatedBroker`：完整模拟撮合 | `SimulatedBroker` |
| 4.4.2 | Paper Trading 升级 | 从简化滑点 → 逐笔冲击成本模型 | 真实模拟 |
| 4.4.3 | ADV 限制 | 单笔交易不超过日成交量 10% | 流动性约束 |
| 4.4.4 | 滑点模型 | `SlippageModel`：线性/平方根/非线性 | 可配置 |

---

### Milestone 4.5：Corporate Action Engine（第 22 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 4.5.1 | `data/corporate_action/engine.py` | 分红/送股/拆股/配股 持仓调整 | `CorporateActionEngine` |
| 4.5.2 | 复权因子自动应用 | 前复权/后复权 | 自动化 |
| 4.5.3 | 持仓成本调整 | 分红除权后成本调整 | `CostAdjuster` |

**Phase 4 总验收**：
- ✅ ExperimentTracker 正式版可用
- ✅ 全链路血缘可追溯
- ✅ 4 个 Registry 可用
- ✅ 自动化月度重训
- ✅ Paper Trading 升级为真实模拟

---

## 9. Phase 5：监控、熔断、知识沉淀

> **周期**：第 23–26 周
> **目标**：生产级监控和知识体系建立
> **对应**：plan.md 第 23–26 周

### Milestone 5.1：Risk Model — 多因子归因（第 23 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 5.1.1 | `portfolio/risk_model.py` | 实现 `BaseRiskModel` | `RiskModel` |
| 5.1.2 | Market Risk 拆解 | 市场 Beta 归因 | 归因报告 |
| 5.1.3 | Style Risk 拆解 | 风格因子暴露 | 归因报告 |
| 5.1.4 | Sector Risk 拆解 | 行业暴露归因 | 归因报告 |
| 5.1.5 | Idiosyncratic Risk | 特异性风险 | 归因报告 |

**公式**：`Total Risk = Market Risk + Style Risk + Sector Risk + Idiosyncratic Risk`

---

### Milestone 5.2：Monitoring Layer 完整版（第 24 周，3 天）

| # | 任务 | 详细说明 | 阈值 |
|---|---|---|---|
| 5.2.1 | PSI 漂移检测 | 特征分布漂移（Population Stability Index） | ≥ 0.25 → Drift |
| 5.2.2 | 预测分布漂移 | 模型输出分布变化 | ≥ 0.25 → Drift |
| 5.2.3 | Model Decay 判定 | 滚动 20 日样本外 IC < 训练验证集 IC 30% | → 降级 Shadow |
| 5.2.4 | Market Regime Engine | 市场状态感知：趋势/震荡/高波动/低波动 | Regime 分类 |
| 5.2.5 | 策略状态监控 | 信号生成频率、持仓变化、换手率 | Dashboard |

---

### Milestone 5.3：告警通道（第 25 周，2 天）

| # | 任务 | 详细说明 |
|---|---|---|
| 5.3.1 | Terminal 告警 | 彩色日志 + 关键事件高亮 |
| 5.3.2 | Log 告警 | 结构化日志 + 触发条件记录 |
| 5.3.3 | Telegram 告警 | Telegram Bot 推送（API Key 来自环境变量） |

---

### Milestone 5.4：Kill Switch 全量接入（第 25 周，2 天）

| # | 任务 | 详细说明 |
|---|---|---|
| 5.4.1 | Kill Switch 全量接入实盘流程 | 触发 → 暂停买入 → 降级 → 人工决策 → 复盘 |
| 5.4.2 | 独立的 Kill Switch 检查 Pipeline | `KillSwitchPipeline`：每日自动运行 |
| 5.4.3 | Model Decay 与 Kill Switch 联动 | 两者独立触发，不互相替代 |

**Model Decay vs Kill Switch 关系**：
- **Model Decay**：模型层面早期预警 → 降级 Shadow 观察
- **Kill Switch**：组合/策略层面最终防线 → 停止信号 + 减仓

---

### Milestone 5.5：Knowledge Layer 规范化（第 26 周，3 天）

| # | 任务 | 详细说明 | 产出 |
|---|---|---|---|
| 5.5.1 | Research Debt Archive | 失败假设与验证的归档分类 | `knowledge/research_debt/` |
| 5.5.2 | Decision Audit Log | 人的决策审计日志：接受/拒绝/改单 + 理由 | `knowledge/decision_audit/` |
| 5.5.3 | Experiment Summary | 实验总结模板（Background → Hypothesis → Method → Result → Lesson） | `knowledge/experiment_summary/` |
| 5.5.4 | Failure Analysis | 失败案例分析分类（过拟合、数据泄漏、市场状态变化等） | `knowledge/failure_analysis/` |
| 5.5.5 | Post Mortem | 重大事件复盘模板 | `knowledge/post_mortem/` |

> **从第一天就开始**：Knowledge Layer 以「一个 Markdown 文件夹」的形式存在即可，不需要工程化。重要的是"有没有养成记录习惯"，而不是"有没有专门的系统"。

**Phase 5 总验收**：
- ✅ 多因子归因可运行
- ✅ PSI + Model Decay 监控可用
- ✅ 告警通道三端打通
- ✅ Kill Switch 全量接入
- ✅ Knowledge Layer 有结构化的内容积累

---

## 10. Phase 6：缓冲与复盘

> **周期**：第 27–28 周
> **目标**：修复之前延期的问题、系统性复盘
> **对应**：plan.md 第 27–28 周
>
> ⚠️ **设计决策（2026-07-20）**：QP 是**决策辅助系统**，非自动交易系统。
> 系统产出买卖建议 → 用户手动下单。因此移除券商 API 联调，改为实现 Decision Layer（可解释、可审计的交易建议输出）。

### Milestone 6.1：延期缓冲（第 27 周）

| # | 任务 | 详细说明 |
|---|---|---|
| 6.1.1 | Decision Layer 实现 | 可解释、可审计的交易建议输出（替代券商 API 联调），每笔建议附带理由、风险提示、成本估算 |
| 6.1.2 | 数据源问题修复 | AkShare API 变化、数据缺失处理 |
| 6.1.3 | Bug 排查与修复 | 26 周积累的已知问题 |
| 6.1.4 | 性能优化 | 大数据量下的查询、回测性能 |

---

### Milestone 6.2：系统性复盘（第 28 周）

| # | 任务 | 详细说明 |
|---|---|---|
| 6.2.1 | 架构完整性自查 | 按 rule.md §9 七类可信性逐项检查 |
| 6.2.2 | 阈值校准 | 根据实际运行数据校准第 10 节量化判定标准 |
| 6.2.3 | 宪法修订 | 按 rule.md §12 流程录入实际调整 |
| 6.2.4 | 文档同步 | 全部 README、ADRs、DPs 与代码同步 |
| 6.2.5 | 下一阶段规划 | 基于 28 周经验的后续路线图 |

**七类可信性自查表**：

| 可信性维度 | 对应机制 | 检查结果 |
|---|---|---|
| 数据可信性 | PIT、Data Contract、Cleaning、Lineage | ☐ |
| 研究可信性 | IC、Neutralization、Purged CV、Experiment Tracking | ☐ |
| 策略可信性 | Validation Gate、Paper Trading、Lifecycle | ☐ |
| 交易可信性 | Execution Simulator、ADV、Slippage | ☐ |
| 组合可信性 | Portfolio Risk、Capital Allocation | ☐ |
| 长期演进能力 | Registry、Knowledge、Research Debt | ☐ |
| 生产安全性 | Monitoring、Decay、Kill Switch | ☐ |

---

## 11. 质量门禁 (Definition of Done)

### 11.1 每个 Milestone 的 DoD

```bash
uv sync                    # ✅ 依赖安装成功
ruff format                # ✅ 格式化通过
ruff check                 # ✅ 零错误
pyright                    # ✅ 零类型错误
pytest                     # ✅ 全部通过
```

### 11.2 每个 Phase 额外检查

| Phase | 额外检查 |
|---|---|
| Phase 0 | `qp version` + `qp doctor` 可运行 |
| Phase 1 | `qp run daily` 端到端可执行 |
| Phase 2 | `qp validate <strategy>` 可运行 |
| Phase 3 | 组合层 KPI 看板可查看 |
| Phase 4 | `qp pipeline list` 显示全部已注册 Pipeline |
| Phase 5 | 告警三通道测试通过 |
| Phase 6 | 七类可信性全部通过 |

### 11.3 始终要求

- ✅ main 分支可安装、可启动、可运行、可测试（Rule 32）
- ✅ README 同步更新
- ✅ 涉及设计变化时新增 ADR
- ✅ 无 `print()`，全部使用 Logger
- ✅ 无裸 `except:`，全部指定异常类型
- ✅ 无 `utils/`、`helpers/`、`misc/` 等禁止目录
- ✅ 无跨层 Import

---

## 12. 风险管理

### 12.1 关键风险

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|---|
| R1 | 数据清洗超时（最容易超时） | 高 | 高 | Phase 1 Milestone 1.2 预留额外缓冲；超时从后续阶段借时间 |
| R2 | Purged CV 切分逻辑 Bug | 中 | 极高 | 大量单元测试验证 Purge/Embargo 正确性；优先保证正确性 |
| R3 | AkShare API 变化/限流 | 中 | 高 | Adapter 模式隔离；数据缓存 |
| R4 | LightGBM 过拟合 | 中 | 高 | Purged CV + 样本内/外 IC 比值强制检查 |
| R5 | 策略 Paper Trading 结果不理想 | 高 | 中 | 允许失败；记录到 Knowledge Layer；回到 Research 迭代 |
| R6 | Kill Switch 过于敏感/迟钝 | 低 | 中 | 阈值可配置；Phase 6 复盘时根据实际数据校准 |
| R7 | 券商 API 联调复杂 | 低 | 中 | BaseBroker 接口已定义；SimulatedBroker 先行测试 |

### 12.2 关键提醒（来自 plan.md）

1. **不要等第一个策略 Paper Trading 完成再开始第二个策略的研发** —— 30 天空档务必并行推进。
2. **第 2 周的数据清洗大概率会超时** —— 如果超了，直接从后面阶段"借"时间，不要压缩它。
3. **目标是"12 层可用"，不是"12 层完美"** —— 真正的打磨会持续到项目生命周期结束。
4. **Purged CV 或过拟合检查跑不通时** —— 优先从后续阶段借时间，不要跳过检查直接上线模型。

---

## 13. 附录：完整里程碑检查清单

### Phase 0: Sprint 0 Bootstrap（第 1–4 周）

- [ ] M0.0 — 项目工程化（pyproject.toml、uv、CLI）
- [ ] M0.1 — Shared 模块（protocols/types/constants/exceptions）
- [ ] M0.2 — Configuration System（四层优先级、Pydantic、Freeze）
- [ ] M0.3 — Logging System（Loguru、结构化日志、无 print()）
- [ ] M0.4 — Runtime & Lifecycle（状态机、Composition Root）
- [ ] M0.5 — Pipeline Engine（BasePipeline、PipelineContext、PipelineResult）
- [ ] M0.6 — Storage Factory（DuckDB、SQLite、Parquet）
- [ ] M0.7 — Scheduler（APScheduler、Job Registry）
- [ ] M0.8 — CLI System（qp version/doctor/pipeline list）
- [ ] M0.9 — Metadata（Runtime、Environment 信息）
- [ ] M0.10 — 协议接口实现（10 个抽象接口落盘）
- [ ] M0.11 — Platform Layer 集成测试
- [ ] **Gate: Platform Layer 完成**

### Phase 1: Walking Skeleton（第 5–8 周）

- [ ] M1.1 — Data Layer 数据接入（AkShare → daily_price.parquet）
- [ ] M1.2 — Data Layer 数据清洗深化（停牌/涨跌停/复权/ST/PIT）
- [ ] M1.3 — Research Layer 因子计算（momentum_20d）
- [ ] M1.4 — Strategy Layer 简单策略（SimpleRankStrategy Top 10）
- [ ] M1.5 — Portfolio Layer 简单组合（SinglePortfolio Equal Weight）
- [ ] M1.6 — Simulation Layer 简化回测（向量化回测 + 报告）
- [ ] M1.7 — Walking Skeleton 集成（qp run daily）
- [ ] **Gate: 端到端最小闭环跑通**

### Phase 2: Validation Gate + Kill Switch（第 9–12 周）

- [ ] M2.1 — Validation Layer 因子检验（Rank IC/IC_IR/t-stat/分层测试/Rule Engine）
- [ ] M2.2 — Research Layer Purged CV（Purge+Embargo）
- [ ] M2.3 — LightGBM 建模流水线（LambdaRank + 截面标准化）
- [ ] M2.4 — 过拟合检查（样本内/外 IC 比 + 单调约束）
- [ ] M2.5 — Backtest Validation（Sharpe/回撤/中性化）
- [ ] M2.6 — Kill Switch 最小版（回撤/PSI/连续亏损）
- [ ] M2.7 — 第一策略完整验证 + Paper Trading 启动
- [ ] **Gate: 第一策略进入 Paper Trading**

### Phase 3: Portfolio Risk + Capital Allocation（第 13–16 周）

- [ ] M3.1 — 第二策略研发
- [ ] M3.2 — Portfolio Risk Manager（行业/集中度/相关性）
- [ ] M3.3 — Paper Trading 30 天判定（→ Shadow Production）
- [ ] M3.4 — Capital Allocation 升级（Risk Parity + Fractional Kelly）
- [ ] M3.5 — 组合层 KPI 看板
- [ ] **Gate: 1 策略 Shadow + 1–2 策略 Paper**

### Phase 4: Registry & Lineage + Simulation（第 17–22 周）

- [ ] M4.1 — Experiment Tracker 正式版
- [ ] M4.2 — 4 个 Registry 正式版
- [ ] M4.3 — 自动化月度重训
- [ ] M4.4 — Simulation 正式版（逐笔冲击成本）
- [ ] M4.5 — Corporate Action Engine
- [ ] **Gate: 全链路血缘可追溯**

### Phase 5: 监控、熔断、知识沉淀（第 23–26 周）

- [ ] M5.1 — Risk Model 多因子归因
- [ ] M5.2 — Monitoring Layer 完整版（PSI + Model Decay + Regime）
- [ ] M5.3 — 告警通道（Terminal/Log/Telegram）
- [ ] M5.4 — Kill Switch 全量接入实盘
- [ ] M5.5 — Knowledge Layer 规范化
- [ ] **Gate: 生产级监控体系就绪**

### Phase 6: 缓冲与复盘（第 27–28 周）

- [ ] M6.1 — 延期缓冲（Bug 修复/性能优化/券商联调）
- [ ] M6.2 — 系统性复盘（架构自查/阈值校准/宪法修订/文档同步）
- [ ] **Gate: 七类可信性全部通过**

---

*本计划综合了《量化投资平台项目宪法 v4.2》、《QP 设计文档体系》和《落地执行计划》三份文档，以及当前仓库的实际状态。执行过程中如发现与实际情况不符，请按宪法 §12 修订流程记录并调整。*

*建议每月做一次进度复盘，对照此计划更新各 Milestone 的完成状态。*
