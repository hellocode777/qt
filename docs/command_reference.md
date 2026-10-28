# QP CLI 命令手册（全量）

> **本文件由脚本生成，请勿手改**：`.venv/bin/python scripts/maintenance/gen_command_reference.py`
> 权威来源：`qp/platform/cli/parser.py`（Click 定义）；可执行命令 **60** 条（Click 命令 59 + 手动分派 1），命令节点 75 个（命令组 16 个，含嵌套组 1 个）。
> CLI 入口：`.venv/bin/qp`（等价 `python -m qp.platform.cli.main`；**勿用 `uv run qp`**，Python 3.12 下载会超时）。
> 相关：`docs/ai/COMMAND_MAP.md`（AI 定位：命令 → 代码入口 → 流程）、`docs/user_guide.md`（使用指南）。


## 0. 读法与约定

- 每条命令给出：**作用**、**参数表**、**代码入口**。
- 标 **透传参数** 的命令由 handler 直接读 `sys.argv`：Click 层不知道它支持哪些 flag，因此 `qp <cmd> --help` 只打印一行简介；下表来自 handler 源码扫描，说明列是**源码注释/用法文本的原文摘录**（可能不完整），语义以源码为准。
- 退出码：`0` = 成功，非 0 = 失败（`qp run` / `qp validate` 等会把 pipeline 状态映射成退出码）。
- 触及生产的命令（`run`、`retrain`、`proposal approve`、`strategy approve` 等）先读 `docs/constitution/rule.md`。
- `<xxx_id>` 是占位符，不是字面量；执行前用对应的 `list` 命令拿真实 ID。


## 1. 速查表（全部可执行命令）

| 命令 | 作用 |
|---|---|
| `qp capital-flow` | Fetch capital flow data (主力净流入/北向持股) for all stocks. |
| `qp data fetch` | Fetch market data. All extra args passed through to handler. |
| `qp data index` | Fetch CSI300 index daily data for market filter + regime detection. |
| `qp decide` | Generate and review investment decisions. |
| `qp doctor` | Run environment self-check. |
| `qp experiment clean` | Clean old experiment files. |
| `qp experiment compare` | Compare experiments. |
| `qp experiment list` | List experiments. |
| `qp experiment optuna` | Run Optuna hyperparameter search for LambdaRank model (TDR-005). |
| `qp experiment run` | Run a multifactor experiment. All args passed through to handler. |
| `qp experiment show` | Show experiment details. |
| `qp experiment validate` | Validate an experiment against quality gates. |
| `qp factor catalog` | Show factor catalog grouped by category. |
| `qp factor compute` | Compute daily factor values → factor_values_daily.parquet (Factor Execution Plane). |
| `qp factor health` | Show factor health: overview (no args) or detail for a specific factor. |
| `qp factor list` | List all tracked factors with lifecycle status. |
| `qp factor register` | Register all BaseFeature classes into the persisted FeatureRegistry. |
| `qp factor report` | Generate factor research report (markdown). |
| `qp factor update-health` | Recompute full-history health for ALL factors → factor_health.parquet. |
| `qp factor validate` | Run validation gate on a single factor against FULL price history. |
| `qp fundamental` | Fetch fundamental data for all stocks (options parsed by the handler: --quick). |
| `qp industry heat` | 行业热度榜 (行情口径: 涨幅/成交额/上涨占比; 资金流口径: 主力净流入). |
| `qp ingest` | Ingest market data from configured sources. All args pass through. |
| `qp knowledge search` | Search knowledge base. |
| `qp knowledge stats` | Show knowledge base statistics. |
| `qp lineage snapshot` | Build and persist the full lineage graph from registries. |
| `qp model list` | List registered models. |
| `qp model show` | Show model details. |
| `qp monitor alert-test` | Send test alerts to configured channels. |
| `qp monitor check` | Run all monitoring checks. |
| `qp monitor regime` | Detect current market regime. |
| `qp paper start` | Start paper trading for a strategy. |
| `qp paper status` | Show paper trading status. |
| `qp pipeline` | Pipeline subcommands. Try: qp pipeline list |
| `qp portfolio report` | Print portfolio-level KPI dashboard. |
| `qp portfolio risk` | Run risk analysis on current holdings. |
| `qp position close` | Close a position. |
| `qp position history` | Show closed position history. |
| `qp position list` | List all positions. |
| `qp position pnl` | Show P&L summary. |
| `qp position show` | Show details for a position. |
| `qp proposal approve` | Approve a proposal. |
| `qp proposal create` | Create a new strategy promotion proposal. |
| `qp proposal list` | List proposals. |
| `qp proposal reject` | Reject a proposal. |
| `qp proposal show` | Show proposal details. |
| `qp proposal withdraw` | Withdraw a proposal. |
| `qp retrain` | Trigger model retraining (default: the single APPROVED strategy). |
| `qp run` | Run a pipeline. All args pass through to handler. |
| `qp scheduler` | Job scheduler (long-running). Try: qp scheduler start |
| `qp simulation shadow` | Run or view shadow production. |
| `qp strategy approve` | Freeze a strategy as an ApprovedStrategy snapshot. |
| `qp strategy approved list` | List all approved (frozen) strategy snapshots. |
| `qp strategy approved show` | Show details of an approved strategy snapshot. |
| `qp strategy deactivate` | Deactivate an approved strategy. |
| `qp strategy list` | List all registered strategies with lifecycle. |
| `qp validate` | Run validation gate on strategies or experiments. |
| `qp version` | Print QP version info. |
| `qp web start` | Start the QP web dashboard. |
| `qp pipeline list` | 手动分派子命令（`qp pipeline` 内按 `sys.argv[2]` 分派） |

## 2. 顶层命令与命令组

> 命令组只列子命令；参数细节在其子命令小节里。


### `qp capital-flow`

**作用**：Fetch capital flow data (主力净流入/北向持股) for all stocks.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--quick` | — |
| `--northbound` | — |
| `--incremental` | 复用已有缓存，只拉缺失尾部(适合日常更新; 全量重建不要加此参数) |

**代码入口**：`qp.platform.cli.commands.ingest.cmd_capital_flow`


### `qp data`

**作用**：Data operations.

**子命令**：`qp data fetch`、`qp data index`


#### `qp data fetch`

**作用**：Fetch market data. All extra args passed through to handler.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--batch` | — |
| `--skip-etl` | — |
| `--start` | — |
| `--end` | — |

**代码入口**：`qp.platform.cli.commands.data_cmd.cmd_data_fetch`


#### `qp data index`

**作用**：Fetch CSI300 index daily data for market filter + regime detection.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--force` | — |
| `--symbol` | — |

**代码入口**：`qp.platform.cli.commands.data_cmd.cmd_data_index`


### `qp decide`

**作用**：Generate and review investment decisions.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `--force` | 选项 | 可选 | `False（开关）` | Re-run daily pipeline to generate a fresh DecisionPackage |
| `--review` | 选项 | 可选 | `False（开关）` | Open today's DecisionPackage for human review |
| `--history` | 选项 | 可选 | `False（开关）` | List all past decision packages |
| `--show` | 选项 | 可选 | `` | Display a specific DecisionPackage (ID or suffix) |
| `--capital` | 选项 | 可选 | `0.0` | Total capital (default 100000) |
| `--action` | 选项 | 可选 | `` | Review action: approve/reject/modify |
| `--notes` | 选项 | 可选 | `` | Review notes |
| `--strategy` | 选项 | 可选 | `simple_rank_v1.0` | Legacy strategy_id |

**代码入口**：`qp.platform.cli.commands.decide.cmd_decide`


### `qp doctor`

**作用**：Run environment self-check.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.meta.cmd_doctor`


### `qp experiment`

**作用**：Experiment management (list, show, run, compare, validate, clean).

**子命令**：`qp experiment clean`、`qp experiment compare`、`qp experiment list`、`qp experiment optuna`、`qp experiment run`、`qp experiment show`、`qp experiment validate`


#### `qp experiment clean`

**作用**：Clean old experiment files.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--keep` | — |
| `--dry-run` | \n[] 以上 {len(to_delete)} 个文件将被删除（未实际执行） |

**代码入口**：`qp.platform.cli.commands.experiment.cmd_experiment_clean`


#### `qp experiment compare`

**作用**：Compare experiments.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.experiment.cmd_experiment_compare`


#### `qp experiment list`

**作用**：List experiments.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--strategy` | — |
| `--min-sharpe` | — |
| `--min-ic` | — |
| `--min-return` | — |

**代码入口**：`qp.platform.cli.commands.experiment.cmd_experiment_list`


#### `qp experiment optuna`

**作用**：Run Optuna hyperparameter search for LambdaRank model (TDR-005).

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--trials` | N Number of Optuna trials (default 30) |
| `--start` | YYYY-MM-DD Start date (default 2019-01-01) |
| `--end` | YYYY-MM-DD End date (default today) |
| `--symbols` | 000001,000002 Stock codes (default: all) |
| `--dataset` | NAME Gold dataset name (default daily_price_latest) |
| `--snapshot` | PATH Experiment snapshot parquet |
| `--train-window` | N Training window days (default 252) |
| `--timeout` | SECONDS Search timeout (default: no timeout) |
| `--seed` | N Random seed (default 42) |
| `--max-stocks` | N Random sample N stocks (memory guard, default all) |

**代码入口**：`qp.platform.cli.commands.experiment.cmd_experiment_optuna`


#### `qp experiment run`

**作用**：Run a multifactor experiment. All args passed through to handler.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--strategy` | momentum_vol_full Strategy name. Use ',' for batch: v1,v2 |
| `--compare` | Force comparison mode |
| `--symbols` | 000001,000002,... Stock codes |
| `--start` | 2024-01-01 Start date |
| `--end` | 2026-07-20 End date |
| `--top-n` | 10 Top N stocks |
| `--quality-filter` | =true/false Enable/disable quality filter |
| `--quality-min-roe` | =0.05 Minimum ROE for quality filter |
| `--rebalance` | 20 Rebalance frequency (days) |
| `--industry-neutral` | Enable industry neutralization |
| `--orthogonalize` | Enable factor orthogonalization |
| `--score-band` | 60-80 Score percentile band (Q4 sweet spot) |
| `--debug` | Enable DEBUG-level logging |
| `--resume` | <experiment_id> Reproduce experiment from snapshot |
| `--rebalance-offset` | 2026-08-16: align windowed runs with full-range rebalance |
| `--skip-gate` | — |
| `--model` | — |
| `--optimize-weights` | 提示: 想跑 IC 权重优化请显式加 |
| `--freeze-weights` | ⚠ 需要 JSON 对象，忽略 |
| `--max-stocks` | — |

**代码入口**：`qp.platform.cli.commands.experiment.cmd_experiment_run`


#### `qp experiment show`

**作用**：Show experiment details.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `experiment_id` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.experiment.cmd_experiment_show`


#### `qp experiment validate`

**作用**：Validate an experiment against quality gates.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `experiment_id` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.experiment.cmd_experiment_validate`


### `qp factor`

**作用**：Factor research & health (list, health, report, validate, catalog).

**子命令**：`qp factor catalog`、`qp factor compute`、`qp factor health`、`qp factor list`、`qp factor register`、`qp factor report`、`qp factor update-health`、`qp factor validate`


#### `qp factor catalog`

**作用**：Show factor catalog grouped by category.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_catalog`


#### `qp factor compute`

**作用**：Compute daily factor values → factor_values_daily.parquet (Factor Execution Plane).

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `--date` | 选项 | 可选 | `` | Target trade date (default: latest in dataset) |
| `--full` | 选项 | 可选 | `False（开关）` | Recompute full history (all dates) |
| `--subset` | 选项 | 可选 | `` | Comma-separated factor names (default: all 19) |
| `--output-dir` | 选项 | 可选 | `data/dataset` | Output directory |

**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_compute`


#### `qp factor health`

**作用**：Show factor health: overview (no args) or detail for a specific factor.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `factor_name` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_health`


#### `qp factor list`

**作用**：List all tracked factors with lifecycle status.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--skip-gate` | qp experiment run multifactor |

**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_list`


#### `qp factor register`

**作用**：Register all BaseFeature classes into the persisted FeatureRegistry.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `--force` | 选项 | 可选 | `False（开关）` | Re-register even if registry exists. |

**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_register`


#### `qp factor report`

**作用**：Generate factor research report (markdown).

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `factor_name` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_report`


#### `qp factor update-health`

**作用**：Recompute full-history health for ALL factors → factor_health.parquet.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_update_health`


#### `qp factor validate`

**作用**：Run validation gate on a single factor against FULL price history.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `factor_name` | 位置参数 | 可选 | `STRING` |  |
| `--persist` | 选项 | 可选 | `False（开关）` | Save results to factor_health.parquet |

**代码入口**：`qp.platform.cli.commands.factor_cmd.cmd_factor_validate`


### `qp fundamental`

**作用**：Fetch fundamental data for all stocks (options parsed by the handler: --quick).

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--quick` | — |

**代码入口**：`qp.platform.cli.commands.ingest.cmd_fundamental`


### `qp industry`

**作用**：Industry heat operations (行业资金流热度).

**子命令**：`qp industry heat`


#### `qp industry heat`

**作用**：行业热度榜 (行情口径: 涨幅/成交额/上涨占比; 资金流口径: 主力净流入).

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `--date` | 选项 | 可选 | `` | 基准日 YYYY-MM-DD (默认: 数据最新日) |
| `--window` | 选项 | 可选 | `1` | 累计窗口(交易日数), 如 1/5/20 |
| `--granularity` | 选项 | 可选 | `csrc` | 行业粒度: csrc=证监会行业(84类,默认) / subsector,sector=名称关键词 |
| `--source` | 选项 | 可选 | `price` | 数据口径: price=行情(涨幅/成交额, 最新) / capital_flow=主力净流入 |
| `--top` | 选项 | 可选 | `15` | 显示前 N 个行业 |
| `--save` | 选项 | 可选 | `True（开关）` | 是否落盘 JSON 快照 |

**代码入口**：`qp.platform.cli.commands.industry.cmd_industry_heat`


### `qp ingest`

**作用**：Ingest market data from configured sources. All args pass through.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--demo` | — |
| `--quick` | — |
| `--source` | — |

**代码入口**：`qp.platform.cli.commands.ingest.cmd_ingest`


### `qp knowledge`

**作用**：Knowledge base (stats, search).

**子命令**：`qp knowledge search`、`qp knowledge stats`


#### `qp knowledge search`

**作用**：Search knowledge base.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `query` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.knowledge.cmd_knowledge_search`


#### `qp knowledge stats`

**作用**：Show knowledge base statistics.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.knowledge.cmd_knowledge_stats`


### `qp lineage`

**作用**：Lineage graph operations (Rule 7: Full Data Lineage).

**子命令**：`qp lineage snapshot`


#### `qp lineage snapshot`

**作用**：Build and persist the full lineage graph from registries.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.lineage.cmd_lineage_snapshot`


### `qp model`

**作用**：Model management (list, show).

**子命令**：`qp model list`、`qp model show`


#### `qp model list`

**作用**：List registered models.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.model.cmd_model_list`


#### `qp model show`

**作用**：Show model details.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `model_id` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.model.cmd_model_show`


### `qp monitor`

**作用**：System monitoring (check, regime, alert-test).

**子命令**：`qp monitor alert-test`、`qp monitor check`、`qp monitor regime`


#### `qp monitor alert-test`

**作用**：Send test alerts to configured channels.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.monitor.cmd_monitor_alert_test`


#### `qp monitor check`

**作用**：Run all monitoring checks.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.monitor.cmd_monitor_check`


#### `qp monitor regime`

**作用**：Detect current market regime.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.monitor.cmd_monitor_regime`


### `qp paper`

**作用**：Paper trading operations.

**子命令**：`qp paper start`、`qp paper status`


#### `qp paper start`

**作用**：Start paper trading for a strategy.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_id` | 位置参数 | 可选 | `STRING` |  |
| `--capital` | 选项 | 可选 | `100000` | 初始资金 (CNY) |

**代码入口**：`qp.platform.cli.commands.paper.cmd_paper_start`


#### `qp paper status`

**作用**：Show paper trading status.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_id` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.paper.cmd_paper_status`


### `qp pipeline`

**作用**：Pipeline subcommands. Try: qp pipeline list

**手动分派子命令**（wrapper 里按 `sys.argv[2]` 分派，不是 Click 子命令）：`qp pipeline list`

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.ingest.cmd_pipeline_list`


### `qp portfolio`

**作用**：Portfolio operations (report, risk analysis).

**子命令**：`qp portfolio report`、`qp portfolio risk`


#### `qp portfolio report`

**作用**：Print portfolio-level KPI dashboard.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.portfolio.cmd_portfolio_report`


#### `qp portfolio risk`

**作用**：Run risk analysis on current holdings.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.portfolio.cmd_portfolio_risk`


### `qp position`

**作用**：Position tracking (list, show, close, pnl, history).

**子命令**：`qp position close`、`qp position history`、`qp position list`、`qp position pnl`、`qp position show`


#### `qp position close`

**作用**：Close a position.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `position_id` | 位置参数 | 必填 | `STRING` |  |
| `--price` | 选项 | 可选 | `0.0` | Exit price |
| `--reason` | 选项 | 可选 | `` | Exit reason |

**代码入口**：`qp.platform.cli.commands.position.cmd_position_close`


#### `qp position history`

**作用**：Show closed position history.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | 位置参数 | 可选 | `INT` |  |

**代码入口**：`qp.platform.cli.commands.position.cmd_position_history`


#### `qp position list`

**作用**：List all positions.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.position.cmd_position_list`


#### `qp position pnl`

**作用**：Show P&L summary.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.position.cmd_position_pnl`


#### `qp position show`

**作用**：Show details for a position.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `position_id` | 位置参数 | 必填 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.position.cmd_position_show`


### `qp proposal`

**作用**：Strategy proposal workflow (list, show, create, approve, reject, withdraw).

**子命令**：`qp proposal approve`、`qp proposal create`、`qp proposal list`、`qp proposal reject`、`qp proposal show`、`qp proposal withdraw`


#### `qp proposal approve`

**作用**：Approve a proposal.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `proposal_id` | 位置参数 | 必填 | `STRING` |  |
| `--reviewer` | 选项 | 可选 | `` | Reviewer name |
| `--notes` | 选项 | 可选 | `` | Review notes |

**代码入口**：`qp.platform.cli.commands.proposal.cmd_proposal_approve`


#### `qp proposal create`

**作用**：Create a new strategy promotion proposal.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `--strategy` | 选项 | 必填 | `Sentinel.UNSET` | Strategy ID |
| `--target` | 选项 | 必填 | `Sentinel.UNSET` | Target lifecycle state |
| `--justification` | 选项 | 可选 | `` | Rationale |
| `--by` | 选项 | 可选 | `cli` | Proposer name |

**代码入口**：`qp.platform.cli.commands.proposal.cmd_proposal_create`


#### `qp proposal list`

**作用**：List proposals.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `--status` | 选项 | 可选 | `` | Filter by status |

**代码入口**：`qp.platform.cli.commands.proposal.cmd_proposal_list`


#### `qp proposal reject`

**作用**：Reject a proposal.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `proposal_id` | 位置参数 | 必填 | `STRING` |  |
| `--reviewer` | 选项 | 可选 | `` | Reviewer name |
| `--notes` | 选项 | 可选 | `` | Rejection reason |

**代码入口**：`qp.platform.cli.commands.proposal.cmd_proposal_reject`


#### `qp proposal show`

**作用**：Show proposal details.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `proposal_id` | 位置参数 | 必填 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.proposal.cmd_proposal_show`


#### `qp proposal withdraw`

**作用**：Withdraw a proposal.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `proposal_id` | 位置参数 | 必填 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.proposal.cmd_proposal_withdraw`


### `qp retrain`

**作用**：Trigger model retraining (default: the single APPROVED strategy).

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_id` | 位置参数 | 可选 | `STRING` |  |
| `--dry-run` | 选项 | 可选 | `False（开关）` | 演习模式：不落盘、不注册模型 |

**代码入口**：`qp.platform.cli.commands.retrain.cmd_retrain`


### `qp run`

**作用**：Run a pipeline. All args pass through to handler.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--demo` | — |
| `--skip-fetch` | — |
| `--skip-factor-calc` | — |
| `--force-rebalance` | Default: fetch last 5 days (Sina, fast with progress). |

**代码入口**：`qp.platform.cli.commands.ingest.cmd_run`


### `qp scheduler`

**作用**：Job scheduler (long-running). Try: qp scheduler start

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `subcommand` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.scheduler.cmd_scheduler_start`


### `qp simulation`

**作用**：Shadow / paper trading simulation.

**子命令**：`qp simulation shadow`


#### `qp simulation shadow`

**作用**：Run or view shadow production.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `date` | 位置参数 | 可选 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.shadow.cmd_shadow_summary`


### `qp strategy`

**作用**：Strategy management (list, approve, deactivate).

**子命令**：`qp strategy approve`、`qp strategy approved`、`qp strategy deactivate`、`qp strategy list`


#### `qp strategy approve`

**作用**：Freeze a strategy as an ApprovedStrategy snapshot.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_id` | 位置参数 | 必填 | `STRING` |  |
| `--by` | 选项 | 可选 | `` | Approver name |
| `--version` | 选项 | 可选 | `` | Freeze version string |
| `--from-experiment` | 选项 | 可选 | `` | Load weights & metrics from this experiment_id |
| `--force` | 选项 | 可选 | `False（开关）` | Bypass approval guard (missing approver / failed quality gate); logged as WARNING |

**代码入口**：`qp.platform.cli.commands.strategy.cmd_strategy_approve`


#### `qp strategy approved`

**作用**：Approved strategy snapshots (ADR-031).

**子命令**：`qp strategy approved list`、`qp strategy approved show`


##### `qp strategy approved list`

**作用**：List all approved (frozen) strategy snapshots.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.strategy.cmd_strategy_approved_list`


##### `qp strategy approved show`

**作用**：Show details of an approved strategy snapshot.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_id` | 位置参数 | 必填 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.strategy.cmd_strategy_approved_show`


#### `qp strategy deactivate`

**作用**：Deactivate an approved strategy.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `strategy_id` | 位置参数 | 必填 | `STRING` |  |

**代码入口**：`qp.platform.cli.commands.strategy.cmd_strategy_deactivate`


#### `qp strategy list`

**作用**：List all registered strategies with lifecycle.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.strategy.cmd_strategy_list`


### `qp validate`

**作用**：Run validation gate on strategies or experiments.

**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：

| flag | 说明（原文摘录） |
|---|---|
| `--stage` | — |
| `--strategy-id` | — |
| `--experiment` | — |
| `--json` | — |

**代码入口**：`qp.platform.cli.commands.validate.cmd_validate`


### `qp version`

**作用**：Print QP version info.

_无参数（或由 handler 自行解析，见代码入口）。_


**代码入口**：`qp.platform.cli.commands.meta.cmd_version`


### `qp web`

**作用**：Web UI server.

**子命令**：`qp web start`


#### `qp web start`

**作用**：Start the QP web dashboard.

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `--host` | 选项 | 可选 | `0.0.0.0` | Bind address |
| `--port` | 选项 | 可选 | `8080` | Port number |
| `--reload` | 选项 | 可选 | `False（开关）` | Enable auto-reload for development |

**代码入口**：`qp.platform.cli.commands.web.cmd_web_start`


## 3. 典型工作流（示例）

> 示例只做形状说明：`<xxx_id>` 换成真实 ID；flag 见对应命令的参数表。


**每日完整链路（调度器工作日 18:00 自动跑；人工补跑用这条）** — 抓数据 → 因子计算 → 因子健康 → regime → 策略信号 → 风控 → 决策包 → 影子盘

```bash
qp run daily
qp run daily --skip-fetch
qp run daily --skip-factor-calc
```

**数据准备** — 行情 / 基准指数 / 基本面 / 资金流

```bash
qp data fetch
qp data index
qp fundamental
qp fundamental --quick
qp capital-flow --quick
qp ingest 2015-01-01
```

**因子研究与健康** — 算因子 → 看因子目录 → 全历史健康重算 → 查健康/生命周期 → 出报告

```bash
qp factor compute
qp factor compute --date 2026-09-24
qp factor catalog
qp factor update-health
qp factor health
qp factor list
qp factor report
```

**策略回测实验** — 多因子实验（--skip-gate 跳过门禁）→ 列表 / 详情 / 对比 / 单实验验证

```bash
qp experiment run multifactor --strategy momentum_vol_full --start 2025-09-05 --end 2026-08-31 --top-n 10 --rebalance 20
qp experiment list
qp experiment show <experiment_id>
qp experiment compare
qp experiment validate <experiment_id>
```

**策略生命周期（研究 → 生产）** — 列策略 → 跑验证门禁 → 审批冻结快照 → 生成决策包 → 人工确认提案

```bash
qp strategy list
qp strategy approved list
qp validate
qp strategy approve <strategy_id> --by <名字>
qp decide
qp decide --force
qp decide --review
qp proposal list
qp proposal show <proposal_id>
qp proposal approve <proposal_id>
qp strategy deactivate <strategy_id>
```

**持仓与组合** — 持仓明细/盈亏 → 组合报告与风险

```bash
qp position list
qp position show <position_id>
qp position pnl
qp position history 20
qp portfolio report
qp portfolio risk
```

**监控与告警** — 系统检查 → 市场 regime → 告警通道自测

```bash
qp monitor check
qp monitor regime
qp monitor alert-test
```

**模拟盘 / 影子盘** — 按决策包假钱建仓并逐日 mark-to-market；paper 是 30 天策略验证

```bash
qp simulation shadow
qp paper start <strategy_id>
qp paper status
```

**模型与血缘** — 模型列表/详情、重训触发、血缘快照

```bash
qp model list
qp model show <model_id>
qp retrain
qp retrain <strategy_id> --dry-run
qp lineage snapshot
```

**运维** — 环境自检、调度器（systemd 管理）、Web UI

```bash
qp doctor
qp version
qp scheduler
qp web start
```

## 4. 维护

- 命令增删改后重跑生成器即可（`parser.py` 才是权威；本文件不建议手改）。
- **忘了重跑不会静默腐化**：`tests/unit/test_docs_command_reference.py` 会跑 `gen_command_reference.py --check`，文档与 CLI 不一致即测试失败。
- 生成器不联网、不写数据，只读 `parser.py` 与 handler 源码；两次运行结果字节一致（**刻意不写生成日期**：`--check` 是字节比对，任何随时间变化的字段都会让守卫在第二天必然失败）。文档新鲜度看 `git log -1 -- docs/command_reference.md`。
- 想补充示例，改生成器顶部的 `WORKFLOWS`（带存在性断言，写错命令会直接报错退出）。

