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

### ⏳ Phase 1 — Walking Skeleton（待开始）

数据接入 → 因子 → 策略 → 组合 → 回测 → 报告，端到端最小闭环。

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
├── data/              # Layer 2: ⏳ 空
├── research/          # Layer 3: ⏳ 空
├── validation/        # Layer 4: ⏳ 空
├── strategy/          # Layer 5: ⏳ 空
├── portfolio/         # Layer 6: ⏳ 空
├── simulation/        # Layer 7: ⏳ 空
├── decision/          # Layer 8: ⏳ 空
├── monitoring/        # Layer 9: ⏳ 空
└── knowledge/         # Layer 10: ⏳ 空
tests/
├── unit/              # 单元测试 (34 个) ✅
├── integration/       # 集成测试 ⏳
└── e2e/               # 端到端测试 ⏳
```

---

## 四、下一步：Phase 1 Walking Skeleton

按 `docs/plan_v1.md` 的计划表继续推进：

1. Data Layer — AkShare 数据接入，生成 `daily_price.parquet`
2. Research Layer — 20 日动量因子计算
3. Strategy Layer — SimpleRankStrategy (Top 10)
4. Portfolio Layer — SinglePortfolio (Equal Weight)
5. Simulation Layer — 简化向量回测 + Markdown 报告
6. `qp run daily` 一条命令跑通全流程
