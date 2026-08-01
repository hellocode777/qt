# QP 项目宪法 v4.2

> Personal Quant Research & Investment Decision Platform
> 最后更新：2026-08-01

---

## 一、项目定位

QP (Quant Platform) 是一个**个人量化研究与投资决策操作系统**。

它是**决策辅助系统**，不是自动交易系统。平台产出可解释、可审计的交易建议，最终执行由人完成。

## 二、十二层架构

```
Layer 1:  platform/     — 运行时内核（配置、日志、CLI、调度、存储、管道引擎）
Layer 2:  data/         — 可信数据产品（消费者不知道原始数据源）
Layer 3:  research/     — 可复现实验（特征、标签、模型、Purged CV）
Layer 4:  validation/   — 门控（16 项检查，4 阶段）
Layer 5:  strategy/     — 投资策略（输出 Decisions，不输出 Orders）
Layer 6:  portfolio/    — 组合构建、风险控制、资金分配
Layer 7:  simulation/   — 纸交易、影子交易
Layer 8:  decision/     — 可审计决策（非 AI/LLM）
Layer 9:  monitoring/   — 只观察不决策（漂移检测、熔断开关）
Layer 10: knowledge/    — 长期记忆（复盘、实验总结、失败分析）
```

**铁律一：不允许向上导入。** Layer 5 可以 import Layer 2，Layer 2 绝不可以 import Layer 5。

**铁律二：跨层共享只通过 `shared/`**，且只允许四样东西：protocols、types、constants、exceptions。

## 三、核心设计原则

### 3.1 混合架构
DataFrame 管道（Polars）用于数据和研究层；Domain Model（Pydantic）用于组合和决策层（ADR-001）。

### 3.2 一切皆管道
所有长运行任务继承 `BasePipeline`，不是脚本（ADR-006）。

### 3.3 Data Product 架构
消费者依赖 Dataset，永远不知道数据源是 AkShare 还是 Tushare（ADR-013）。

### 3.4 Purged KFold 强制
所有模型必须使用 Purged Walk-Forward 交叉验证，不允许普通 KFold（ADR-021）。

### 3.5 配置冻结
配置优先级：CLI 参数 > 环境变量 > config.toml > 默认值。启动后冻结，不可修改（ADR-011）。

### 3.6 单入口 CLI
所有操作通过 `qp` 命令，不创建第二个入口点（ADR-002）。

### 3.7 无 DI 框架
显式组合根在 `builder.py`，不引入依赖注入框架（ADR-003）。

## 四、投资哲学（V2.1 Final）

### 四大原则

| 原则 | 含义 |
|------|------|
| **Model Driven** | 一切投资决策由模型驱动。Alpha 来自截面排序而非价格走势 |
| **Risk First** | 风险控制优先于 Alpha。策略负责机会，风控负责生存 |
| **Stateless Decision** | 每次调仓都是全新评估。历史持仓、历史止损不影响当前决策 |
| **Human in the Loop** | 平台生成建议，最终交易由投资者确认执行 |

### 交易规则

- **仅调仓日买入**（每月前 5 个自然日），选 Top 10
- **每日风险退出**：止损（-10%）、ST、退市、停牌
- **调仓日 Rank 退出**：Buy Top 10，Buffer 11-20，Sell >20
- **退出信号优先级**：CRITICAL > HIGH > MEDIUM > LOW
- **同 symbol 多信号合并**为一条卖出指令，保留所有 reason tag

## 五、硬规则

### 5.1 代码
- `print()` 禁止 — 使用 Logger
- 裸 `except:` 禁止 — 指定异常类型
- 循环导入禁止
- `utils/`, `helpers/`, `misc/`, `scripts/`, `common_utils/` 目录禁止 — 每个模块归属一个层

### 5.2 数据
- 原始数据不可变 — 从不修改，只追加（ADR-014）
- 数据集发布前必须验证（ADR-016）
- 密钥（API Key）只能通过环境变量提供

### 5.3 分支
- `main` 分支必须始终可安装、可启动、可运行、可测试

### 5.4 质量
- `ruff check` 零错误
- `pyright` 零错误
- `pytest` 全部通过

## 六、技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12 | 运行时 |
| DuckDB | 分析数据库 |
| Parquet | 列式存储 |
| LightGBM (LambdaRank) | 默认 ML 模型 |
| Pydantic | 配置与数据模型 |
| Loguru | 日志 |
| APScheduler | 任务调度 |
| Polars | DataFrame（数据/研究层） |
| Pandas | DataFrame（组合/决策层） |
| Click | CLI 框架 |
| FastAPI | Web UI |
| AkShare | 数据源（通过适配器隔离） |

## 七、统一术语

| 术语 | 含义 | 禁止用 |
|------|------|--------|
| Pipeline | 管道 | Workflow, Flow |
| Job | 调度计划 | Cron |
| Run | 一次执行实例 | Execution |
| Signal | 可交易信号 | Prediction |
| Order | 订单（可能被拒） | Trade |
| DecisionPackage | 每日决策包 | Report |
| Dataset | 可信数据产品 | Data Source |
| Experiment | 实验容器 | Trial |

## 八、文档体系

```
docs/
├── constitution/constitution-v4.2.md    ← 本文档（最高准则）
├── user_guide.md                        ← 用户操作指南
├── developer_guide.md                   ← 开发者指南
├── api.md                               ← 公开 API 参考
├── architecture/                        ← 分层设计提案（DP-001 ~ DP-010）
└── tdr/                                 ← 技术决策记录（TDR-001 ~ TDR-010）
```

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v4.2 | 2026-08-01 | 文档重建完成，V2.1 Final 交易宪法纳入，ADRs 归档（信息已整合至本文档 + DP） |
| v4.1 | 2026-07-20 | 原始版本 |
