# PROJECT_MAP — QP 项目地图（AI 导航第一站）

> 用途：**给 AI 看的项目地图**。回答任何 QP 问题前，先读本文件定位问题所属的层/模块/入口，
> 再按 MODULE_MAP.md / COMMAND_MAP.md 拿到最小必要 Context。
> 人与 AI 的详细文档见 `docs/user_guide.md`、`docs/developer_guide.md`、`docs/architecture/`。

## System Purpose

量化投资研究与投资决策操作系统（Personal Quant Research & Investment Decision Platform）。

- **人执行交易，系统不出自动订单**（决策输出 Decisions，不是 Orders）
- 12 层架构，359 源文件 / ~77K 行，1488 测试函数（2026-08-11 实测）
- CLI 唯一入口：`qp`（`.venv/bin/qp`）
- 宪法治理：`docs/constitution/rule.md`（28 条宪法）+ `docs/constitution/constitution-v4.2.md`（精简版）
- 依赖安装：`uv sync --extra dev`；Python 3.12（`.venv`）

## 架构（12 层，严格单向依赖：上层可依赖下层，反之禁止）

| 层 | 目录 | 一句话职责 |
|---|---|---|
| 1 | `qp/platform/` | 运行框架：CLI、配置、日志、调度器、存储、Pipeline 引擎 |
| 2 | `qp/data/` | 可信 Data Products（数据集），消费方永远不知道数据源 |
| 3 | `qp/research/` | 可复现实验：因子、标签、模型、Purged CV |
| 4 | `qp/validation/` | 研究与策略之间的 Gate（规则引擎） |
| 5 | `qp/strategy/` | 投资策略；输出 Decisions，不是 Orders |
| 6 | `qp/portfolio/` | 组合构建、风控、资金分配 |
| 7 | `qp/simulation/` | 回测 / 影子交易 / Paper Trading |
| 8 | `qp/decision/` | 可解释、可审计的决策 |
| 9 | `qp/monitoring/` | 只观察、不决策；漂移检测、熔断 |
| 10 | `qp/knowledge/` | 长期记忆：post-mortem、实验摘要、失败分析 |

**关键边界**：
- `data/` 对外只暴露 Data Products（Dataset）；research/strategy 等消费方不碰腾讯/AkShare 等原始源
- `research/` 禁止直接调腾讯 kline 或 `ak.stock_zh_a_hist(...)`（数据源封装在 data 层，TDR-001）
- 跨层捷径禁止（ADR-009）；没有 utils/helpers/common（shared/ 只放 protocols/types/constants/exceptions）

## 辅助目录（非 12 层主体）

| 目录 | 职责 |
|---|---|
| `qp/shared/` | protocols（BaseStrategy 等）、types、constants、exceptions |
| `qp/pipeline/` | 长任务 Pipeline：daily、factor_calc、multifactor、fundamental |
| `qp/lineage/` | 血缘图（Rule 7）：LineageRegistry DAG → `data/metadata/lineage_graph.json` |
| `qp/web/` | Web UI（FastAPI 前端）：Jinja 旧页 `templates/` + JSON 端点 `routers/api_v1.py` + SPA `spa_src/`（源码入库，构建产物 `static/spa/` 不入库，`scripts/spa_deploy.sh` 部署到 `/proto/`） |
| `scripts/` | 运维/研究脚本（`maintenance/` 一次性数据修正、`research/` 研究、`spa_deploy.sh` 部署） |
| `tests/` | 1488 测试函数 |
| `docs/` | 人读文档；`docs/ai/` 是 AI 导航层（本目录） |
| `data/` | 所有数据与运行时产物（见 DATA_FLOW.md） |

## 主入口点

| 入口 | 位置 | 说明 |
|---|---|---|
| CLI | `qp/platform/cli/main.py` + `commands/*.py` | 唯一入口，20+ 命令（见 COMMAND_MAP.md） |
| Daily Pipeline | `qp/pipeline/daily_pipeline.py` | 每日 18:00 跑，出买卖信号 |
| 调度器 | `qp/platform/cli/commands/scheduler.py` | systemd `qp-scheduler.service`，5 个工作日 job |
| Web UI | `qp/web/` | `qp web start` |
| 实验 | `qp/research/experiment/` | `qp experiment run multifactor` |

## 三个执行系统（策略验证 → 每日决策验证 → 真实账户）

容易混淆的三个"执行层"，全部消费**同一个 DecisionPackage（data/decisions/）**，但目的、资金、审核完全不同：

```
策略生命周期（验证"策略能不能上线"）
  Paper Trading（qp paper start，Rule 11，30 天验证）
      │  策略信号，纸面持仓，数据/paper_trading/
      ▼
每日决策验证（验证"跟着系统建议做会怎样"）
  Shadow Production（影子运行，daily_pipeline Step 13.1 自动跑）
      │  决策包全自动执行，独立假钱 10 万，数据/simulation/
      ▼
真实账户（人工把关的账户账本）
  Portfolio（投资组合，WebUI approve 后建仓）
      │  人工审核状态机，真实现金账本，data/positions/
      ▼
  人工执行交易（系统出建议，人下单）
```

| | Paper Trading | Shadow 影子运行 | Portfolio 投资组合 |
|---|---|---|---|
| 目的 | 策略上线前验证 | 每日决策无脑执行对照 | 真实账户记账 |
| 触发 | `qp paper start` | daily_pipeline 自动 | WebUI 人工 approve |
| 资金 | 纸面（独立） | 假钱 10 万（独立） | 真实账户现金（ADR-032） |
| 审核 | 无 | 无 | 有状态机 + 驳回 |
| 存储 | `data/paper_trading/` | `data/simulation/` | `data/positions/`（含 account.json） |
| 代码 | `qp/simulation/paper_trading.py` | `qp/simulation/shadow_ledger.py` | `qp/decision/position_ledger.py` |
| WebUI | `/paper`（模拟交易页，权益曲线+门槛状态） | `/simulation`（影子盘页） | `/portfolio`（组合页） |

⚠️ 现金账本（ADR-032）只属于 Portfolio；Shadow/Paper 各有独立假钱，互不干扰。

## 数据流（总览，详见 DATA_FLOW.md）

```
腾讯 kline（唯一行情源，TDR-001；复权因子用 AkShare qfq-factor）
  → data/raw（原始，不可变，只追加）
  → data/bronze → data/silver（清洗/标准化）
  → data/dataset/*.parquet（Gold Data Product：daily_price_latest 等）
  → qp/research（因子/特征/模型）
  → qp/validation（Gate，只允许 APPROVED 策略进产线，ADR-031）
  → qp/strategy（信号）
  → qp/portfolio（组合/风控）
  → qp/decision（DecisionPackage → data/decisions/）
  → qp/monitoring（观察 + 熔断 + 重训信号）
```

## 运行时产物位置（查状态先看这些）

| 路径 | 内容 |
|---|---|
| `data/strategy_registry.json` | 策略注册表（会被 WebUI/实验自动改写！）；APPROVED 冻结快照在 `strategies.<id>.approved` 字段内（ADR-031） |
| `data/decisions/` | DecisionPackage（每日决策，三个执行系统的共同输入） |
| `data/positions/` | Portfolio 真实账户：positions.parquet + account.json（现金账本，ADR-032） |
| `data/simulation/` | Shadow 影子盘：shadow_positions.parquet + shadow_daily.parquet |
| `data/paper_trading/` | Paper Trading 状态（`{strategy_id}_paper.json`） |
| `data/experiments/` | 实验产物 |
| `data/metadata/lineage_graph.json` | 血缘图（`qp lineage snapshot` 生成） |
| `data/monitoring/` | 监控产物：健康日志、`retrain_signals.parquet`（信号→策略权重，见 Step 9）、`retrain_notify_state.json`（告警去重） |
| `logs/{日期}/{job}.log` | 调度任务日志（7 天清理） |

## 证据等级（回答 QP 问题时的强制分层）

见 AGENTS.md §13（FACT / INFERENCE / HYPOTHESIS）+ §3 证据优先级。
速记：FACT=代码/运行/测试直接支持 > INFERENCE=推断 > HYPOTHESIS=未验证假设。
**禁止把猜测当结论**——先定位代码/数据，再解释。AGENTS.md 是行为规范（如何调查），本文件只是导航（从哪找）。
