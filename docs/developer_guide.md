# QP 开发者指南 / Developer Guide

> 面向 QP 平台的开发者。如果你只是想使用平台，请阅读 [`user_guide.md`](user_guide.md)。
>
> 更新日期：2026-08-01

---

## 目录

1. [环境搭建](#1-环境搭建)
2. [架构全景](#2-架构全景)
3. [开发工作流](#3-开发工作流)
4. [操作指南 (How-To)](#4-操作指南-how-to)
   - [添加新的 CLI 命令](#41-添加新的-cli-命令)
   - [添加新的策略](#42-添加新的策略)
   - [添加新的 Pipeline](#43-添加新的-pipeline)
   - [添加新的验证检查](#44-添加新的验证检查)
5. [核心模式与约定](#5-核心模式与约定)
6. [测试](#6-测试)
7. [常见陷阱](#7-常见陷阱)
8. [参考](#8-参考)

---

## 1. 环境搭建

### 1.1 前置条件

- Python **3.12**（`.python-version` 锁定，NumPy/LightGBM 尚未与 3.14 ABI 兼容）
- `uv` 包管理器

### 1.2 首次安装

```bash
git clone <repo-url> && cd qt
uv sync --extra dev        # 安装运行时 + 开发依赖
uv run qp version          # 验证 CLI 可用
uv run qp doctor           # 环境自检
```

### 1.3 质量门禁

每次提交前必须全部通过：

```bash
uv run ruff format         # 自动格式化
uv run ruff check          # Lint（零错误）
uv run pyright             # 类型检查（零错误）
uv run pytest              # 全部测试
```

安装 pre-commit 钩子：

```bash
uv run pre-commit install  # 提交时自动 ruff-format + ruff-check
```

### 1.4 Definition of Done

- `uv sync` 成功
- `ruff check` 零错误
- `pyright` 零错误
- `pytest` 全部通过
- 至少一个 CLI 命令可运行
- README 已更新
- 设计变更需新增 ADR

---

## 2. 架构全景

### 2.1 十二层架构

```
Layer 1:  platform/      — 运行时基础（配置、日志、CLI、调度、存储、管道引擎）
Layer 2:  data/          — 可信数据产品（消费者不知道原始数据源）
Layer 3:  research/      — 可复现实验（特征、标签、模型、Purged CV）
Layer 4:  validation/    — 门控（16 项检查，4 阶段）
Layer 5:  strategy/      — 投资策略（输出 Decisions，不输出 Orders）
Layer 6:  portfolio/     — 组合构建、风控、资金分配
Layer 7:  simulation/    — 纸交易、影子交易
Layer 8:  decision/      — 可审计决策（非 AI/LLM）
Layer 9:  monitoring/    — 只观察不决策（漂移、熔断、健康检查）
Layer 10: knowledge/     — 长期记忆（复盘、实验总结、失败分析）
```

**铁律**: **不允许向上导入**。Layer 5 可以 import Layer 2，Layer 2 绝不可以 import Layer 5。

### 2.2 关键边界

| 边界 | 规则 |
|------|------|
| `data/` → 上层 | Data Products（Dataset），绝不暴露原始数据源 |
| `research/` | **禁止**直接调用 `ak.stock_zh_a_hist(...)` |
| `shared/` | 只有 4 样东西：protocols, types, constants, exceptions |
| 禁止目录 | `utils/`, `helpers/`, `misc/`, `scripts/`, `common_utils/` |

### 2.3 模块速查

| 要做什么 | 去哪里 |
|----------|--------|
| 加 CLI 命令 | `qp/platform/cli/commands/` + `qp/platform/cli/parser.py` |
| 加策略 | `qp/strategy/strategies/` + `qp/strategy/config.py` |
| 加 Pipeline | `qp/pipeline/` → 继承 `BasePipeline` |
| 加验证检查 | `qp/validation/checks/` |
| 加数据源适配器 | `qp/data/adapter/` → 实现 `BaseDataSource` |
| 加因子/特征 | `qp/research/feature/` → 实现 `BaseFeature` |
| 加模型 | `qp/research/trainer/` → 实现 `BaseModel` |
| 加告警通道 | `qp/monitoring/alerts.py` |

---

## 3. 开发工作流

### 3.1 日常循环

```
编辑代码 → ruff format → ruff check → pyright → pytest → git commit
```

### 3.2 快速验证

```bash
# 最快验证：跑 demo 管道
uv run qp run daily --demo

# 只跑相关测试
uv run pytest tests/unit/path/to/test_file.py -x -q

# 只检查类型
uv run pyright qp/path/to/changed_file.py
```

### 3.3 提交信息格式

```
<type>: <简短描述>

<详细说明>

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## 4. 操作指南 (How-To)

### 4.1 添加新的 CLI 命令

**Step 1**: 在 `qp/platform/cli/commands/` 创建 handler 函数。

```python
# qp/platform/cli/commands/my_feature.py

def cmd_my_feature_list() -> int:
    """List all my-feature items."""
    # 业务逻辑
    return 0
```

**Step 2**: 在 `qp/platform/cli/parser.py` 注册 Click 命令。

```python
# 顶级命令
@cli.command()
def my_feature() -> None:
    """My feature description."""
    from qp.platform.cli.commands.my_feature import cmd_my_feature_list
    raise SystemExit(cmd_my_feature_list())

# 或带子命令的 group
@cli.group()
def my_feature() -> None:
    """My feature group."""

@my_feature.command("list")
def my_feature_list() -> None:
    """List items."""
    from qp.platform.cli.commands.my_feature import cmd_my_feature_list
    raise SystemExit(cmd_my_feature_list())
```

**关键点**:
- 所有 import 在函数内部（lazy import，加快 CLI 启动）
- handler 返回 `int`（0 = 成功），通过 `raise SystemExit(code)` 传播
- 使用 `click.option()` 声明参数，自动获得 `--help`

### 4.2 添加新的策略

**Step 1**: 在 `qp/strategy/config.py` 注册策略配置。

```python
# 在 STRATEGY_CONFIGS 字典中添加
"my_strategy_v1": StrategyConfig(
    name="my_strategy_v1",
    factors={
        "Momentum_3M": 0.25,
        "Volatility_60D": 0.25,
        # ...
    },
    top_n=10,
    rebalance_frequency="monthly",
    industry_neutral=True,
),
```

**Step 2**: 在 `qp/strategy/strategies/` 创建策略类（如需要自定义逻辑）。

```python
# qp/strategy/strategies/my_strategy.py
from qp.strategy.models import AlphaSignal
from qp.shared.protocols.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    @property
    def strategy_id(self) -> str:
        return "my_strategy_v1"

    def generate_signals(self, date) -> ...:
        # 自定义信号生成逻辑
        ...
```

**Step 3**: 运行实验验证。

```bash
uv run qp experiment run multifactor --strategy my_strategy_v1 --start 2024-01-01
```

### 4.3 添加新的 Pipeline

```python
# qp/pipeline/my_pipeline.py
from qp.platform.pipeline.context import PipelineContext
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.platform.pipeline.runner import PipelineResult, PipelineStatus

class MyPipeline(BasePipeline):
    @property
    def name(self) -> str:
        return "my_pipeline"

    def run(self, context: PipelineContext) -> PipelineResult:
        logger = context.logger  # 使用 Runtime logger（ADR-012）

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        try:
            # Step 1: ...
            # Step 2: ...

            result.metrics["key"] = value
            result.artifacts.append("path/to/output.parquet")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.errors.append(f"{type(e).__name__}: {e}")

        return result
```

Pipeline 通过 CLI 的 `qp run` 或 scheduler 触发。所有长运行任务必须是 Pipeline（ADR-006）。

### 4.4 添加新的验证检查

```python
# qp/validation/checks/my_check.py
from qp.validation.result import CheckResult

class MyCheck:
    """检查描述。"""

    def run(self, experiment_data) -> CheckResult:
        passed = ...  # 判断逻辑
        return CheckResult(
            name="MyCheck",
            passed=passed,
            score=...,
            detail="...",
        )
```

然后在 `qp/validation/__init__.py` 中注册导出。

---

## 5. 核心模式与约定

### 5.1 命名

| 类型 | 规则 | 示例 |
|------|------|------|
| 文件 | `snake_case.py` | `feature_pipeline.py` |
| 类 | `PascalCase` | `FeaturePipeline` |
| 函数/方法 | `snake_case` | `build_feature()` |
| 常量 | `UPPER_CASE` | `DEFAULT_TIMEZONE` |
| 抽象类 | `BaseXxxx` | `BaseStorage`, `BaseBroker` |
| 私有成员 | `_leading_underscore` | `_load_price_data()` |

### 5.2 术语（统一语言）

| 术语 | 含义 | 不要用 |
|------|------|--------|
| **Pipeline** | 管道 | Workflow, Flow, Process |
| **Job** | 调度计划 | — |
| **Task** | Job 中的一个动作 | — |
| **Run** | 一次 Pipeline 执行 | — |
| **Signal** | 可交易信号 | Prediction |
| **Order** | 订单（可能被拒） | Trade |
| **Trade** | 已确认成交 | Order |
| **Experiment** | 实验容器 | — |
| **Dataset** | 可信数据产品 | Data Source |
| **Data Source** | 原始数据提供商 | Dataset |

### 5.3 配置优先级

```
CLI 参数 > 环境变量 > config.toml > 默认值
```

配置启动后冻结，运行时不可修改。密钥（API Key）只能通过环境变量提供。

### 5.4 日志

```python
# 正确：使用 Logger
logger.info("处理 {} 条记录", len(data))

# 错误：禁止
print("处理完了")
```

### 5.5 异常处理

```python
# 正确：指定异常类型
try:
    data = load_data()
except FileNotFoundError as e:
    logger.warning("数据文件不存在: {}", e)

# 错误：裸 except
try:
    ...
except:  # ❌
    pass
```

### 5.6 导入规则

```python
# 正确：从上层导入下层
from qp.data.dataset import load_dataset  # L5 → L2 ✅

# 错误：从下层导入上层
from qp.strategy.registry import StrategyRegistry  # L2 → L5 ❌

# 正确：跨层通过 shared/
from qp.shared.protocols.base_strategy import BaseStrategy  # ✅
```

### 5.7 关键 ADR（必读）

| ADR | 内容 | 影响 |
|-----|------|------|
| 001 | 混合架构：DataFrame 管道 + Domain Model | 数据层用 Polars，组合层用 Pydantic |
| 006 | 一切皆 Pipeline | 所有长运行任务继承 `BasePipeline` |
| 012 | Runtime 拥有一切 | 用 `context.logger`，不要自己创建 Logger |
| 013 | Data Product 架构 | 消费者依赖 Dataset，不依赖 Data Source |
| 021 | Purged KFold 强制 | 所有模型必须用 Purged Walk-Forward CV |
| 022 | Notebook 仅供探索 | 绝不进入生产 |

---

## 6. 测试

### 6.1 测试结构

```
tests/
├── unit/           # 单元测试（镜像 qp/ 目录结构）
│   ├── platform/
│   ├── data/
│   ├── research/
│   └── ...
└── e2e/            # 端到端测试
```

### 6.2 编写测试

```python
# tests/unit/strategy/test_my_strategy.py
import pytest
from qp.strategy.strategies.my_strategy import MyStrategy

def test_my_strategy_generates_signals():
    strategy = MyStrategy()
    signals = strategy.generate_signals(date=...)
    assert signals is not None
```

### 6.3 运行测试

```bash
uv run pytest                              # 全部
uv run pytest tests/unit/strategy/         # 某个模块
uv run pytest -x -q                        # 快速模式（遇错即停）
uv run pytest --cov=qp --cov-report=html   # 覆盖率
```

---

## 7. 常见陷阱

### 7.1 未来函数（Lookahead Bias）

```python
# ❌ 错误：用全量数据做标准化
from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)  # 泄漏了测试集信息

# ✅ 正确：只在训练集 fit
scaler.fit(X_train)
X_train_scaled = scaler.transform(X_train)
X_test_scaled = scaler.transform(X_test)
```

### 7.2 数据源泄漏

```python
# ❌ 错误：research 层直接调数据源
from qp.data.adapter import ak  # research/ 不应知道 AkShare 存在

# ✅ 正确：通过 Dataset
from qp.data.dataset import load_dataset
data = load_dataset("daily_price_main")
```

### 7.3 循环导入

```python
# ❌ 错误：A import B，B import A
# 解决：提取共同依赖到 shared/ 或使用延迟导入
```

### 7.4 可变默认参数

```python
# ❌ 错误
def process(symbols: list = []) -> list:  # 所有调用共享同一个 list
    ...

# ✅ 正确
def process(symbols: list | None = None) -> list:
    if symbols is None:
        symbols = []
    ...
```

---

## 8. 参考

### 8.1 公开协议（`qp/shared/protocols/`）

| 协议 | 用途 |
|------|------|
| `BasePipeline` | 所有 Pipeline 的抽象基类 |
| `BaseStrategy` | 所有策略的抽象基类 |
| `BaseModel` | 所有 ML 模型的抽象基类 |
| `BaseFeature` | 所有因子/特征的抽象基类 |
| `BaseDataSource` | 所有数据源适配器的抽象基类 |
| `BaseExperimentTracker` | 实验追踪的抽象基类 |
| `BaseBroker` | 券商接口的抽象基类 |
| `BasePortfolioRiskManager` | 组合风控的抽象基类 |
| `BaseRiskModel` | 风险模型的抽象基类 |
| `BaseCapitalAllocator` | 资金分配的抽象基类 |
| `BaseCorporateAction` | 公司行为调整的抽象基类 |

### 8.2 技术栈

| 技术 | 用途 |
|------|------|
| DuckDB | 分析数据库 |
| Parquet | 列式存储 |
| LightGBM | 默认 ML 模型（LambdaRank） |
| Pydantic | 配置和数据模型 |
| Loguru | 日志 |
| APScheduler | 任务调度 |
| Polars | DataFrame（数据/研究层） |
| Pandas | DataFrame（组合/决策层） |
| Click | CLI 框架 |
| FastAPI | Web UI |

### 8.3 文档导航

| 文档 | 内容 |
|------|------|
| [`CLAUDE.md`](../CLAUDE.md) | AI 辅助开发指南 |
| [`user_guide.md`](user_guide.md) | 用户操作指南 |
| [`doc_rebuild_tracker.md`](doc_rebuild_tracker.md) | 文档重建进度 |
| [`constitution/constitution-v4.2.md`](constitution/constitution-v4.2.md) | 项目宪法 |
| `adr/ADR-*.md` | 架构决策记录（31 份） |
| `tdr/TDR-*.md` | 技术决策记录（10 份） |
| `architecture/DP-*.md` | 分层设计提案（10 份） |
