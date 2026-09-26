# QT AI Project Context

> 用途：**Hermes 接手 QT 项目时的第一份导航**。只回答「QT 是什么、往哪找」。
> 不含实现细节——那是 Agent 自己 Locate → Trace → Verify 的事（见 AGENTS.md）。
> 本文件是导航，不是权威；权威 = 当前代码 + 运行结果 + 测试 + 配置。

## 1. Project Identity

QT（仓库 `~/workspace/qt`，CLI 名 `qp`）是一个个人量化研究
与投资决策支持平台，面向中国 A 股市场。

- 系统提供：研究、验证、组合、风控、决策支持
- **人执行交易；QT 不自动下单**（输出 Decisions，不是 Orders）
- 宪法治理：`docs/constitution/rule.md`（28 条）+ 精简版 `constitution-v4.2.md`

## 2. Architecture

QT 采用 12 层架构（严格单向依赖，上层可依赖下层，反之禁止）：

```
1 Platform    运行框架（CLI/配置/日志/调度器/存储）
2 Data        可信 Data Products（消费方永远不知道数据源）
3 Research    可复现实验（因子/标签/模型/Purged CV）
4 Validation  研究↔策略之间的 Gate
5 Strategy    投资策略（输出 Decisions）
6 Portfolio   组合构建/风控/资金分配
7 Simulation  回测/影子交易/Paper Trading
8 Decision    可解释可审计的决策包
9 Monitoring  只观察不决策（漂移/熔断/重训信号）
10 Knowledge  长期记忆（post-mortem/实验摘要/失败分析）
```

辅助目录：`qp/shared/`（protocols/types/constants）、`qp/pipeline/`（长任务编排）、
`qp/lineage/`（血缘 DAG）、`qp/web/`（Web UI）。

详情：`docs/ai/PROJECT_MAP.md`

## 3. Primary Runtime Flow

```
数据 → 因子计算 → 策略 → 验证 → 组合/风控 → 决策 → 监控
```

每日生产流程（scheduler，工作日）：
`data_fetch → monitor_check → pre_close_check → daily_pipeline`

详情：`docs/ai/DATA_FLOW.md` + `docs/ai/COMMAND_MAP.md`

## 4. Research Flow

```
Research → Experiment → Backtest → Validation Gate → Paper Trading → Shadow Production → Production
```

- 只有通过 Validation Gate 的 APPROVED 策略进入产线（ADR-031）
- Paper Trading 30 天验证（Rule 11），Shadow 影子盘每日自动跑（Step 13.1）
- 详情：`docs/ai/COMMAND_MAP.md` + `docs/workflow.md`

## 5. Factor System

```
Factor Library → Factor Calculation → Factor Health Monitor → Strategy Selection
```

- 因子定义在 `qp/research/feature/`（方向定义随代码，勿凭名称猜测）
- 因子健康度：`qp factor health`，判定在 `qp/monitoring/factor_health_logger.py`
- ⚠️ 裸 IC 负 ≠ 因子失效——先查该因子 direction（A 股量价/动量因子天然负 IC）
- 详情：`docs/research/factor-health.md`（如存在）或 COMMAND_MAP

## 6. Important Systems

| 系统 | 位置/命令 |
|---|---|
| CLI 入口 | `.venv/bin/qp`（唯一入口，命令组见 COMMAND_MAP） |
| Daily Pipeline | `qp/pipeline/daily_pipeline.py`（每日 18:00） |
| 调度器 | `qp/platform/cli/commands/scheduler.py` + systemd `qp-scheduler.service` |
| 策略注册表 | `data/strategy_registry.json`（APPROVED 冻结快照在 `strategies.<id>.approved`） |
| Web UI | `qp/web/`（`qp web start`） |
| 实验 | `qp experiment run multifactor` / `qp experiment optuna` |
| 三执行系统 | Paper（`data/paper_trading/`）/ Shadow（`data/simulation/`）/ Portfolio（`data/positions/`） |

## 7. Engineering Rules

- 行为规范（Agent 怎么工作）：`AGENTS.md`（本仓库最高协议）
- 宪法（28 条硬规则）：`docs/constitution/rule.md`
- 分层铁律：见 PROJECT_MAP 关键边界 + `docs/implementation/coding-style.md`
- 质量门禁：`uvx ruff format --check .` + `uv run pyright` + pytest

## 8. Current Project State

当前阶段与活跃工作**不在本文件维护**（状态会变，本文件会过时）：

- 版本化追踪：`docs/tracking/qt_backlog_tracker.md`
- 用户侧待办：Obsidian `1-Projects/qt项目待办.md`（双镜像）
- 近期决策：`docs/archive/adr/`（ADR-xxx）+ `docs/tdr/`（TDR-xxx）
- 项目记忆（发现/失败/工作流）：`.hermes/memory/`

## 9. Navigation

| 想找 | 去哪 |
|---|---|
| 项目地图（子系统） | `docs/ai/PROJECT_MAP.md` |
| 模块地图（功能→文件） | `docs/ai/MODULE_MAP.md` |
| 命令地图（命令→入口→流程） | `docs/ai/COMMAND_MAP.md` |
| 命令手册（全量命令 + 参数表，自动生成） | `docs/command_reference.md` |
| 数据流（Raw→Gold→下游） | `docs/ai/DATA_FLOW.md` |
| 量化改动 11 项检查 | `docs/ai/QUANT_VERIFICATION_CHECKLIST.md` |
| 任务留痕模板 | `docs/templates/TASK_RECORD.md` |
| 人读文档 | `docs/user_guide.md` / `docs/developer_guide.md` / `docs/architecture.md` |

> 原则：**Context ≠ 知识库**。本文件只导航，具体实现让 Agent 自己
> Locate → Trace → Verify → Explain（AGENTS.md §2）。
