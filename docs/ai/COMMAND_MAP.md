# COMMAND_MAP — QP CLI 命令地图（命令 → 代码入口 → 流程）

> 用途：给 AI 定位"某个命令做了什么"。先查本表拿到命令组入口文件，
> 再只读相关 handler 和 service。
> CLI 唯一入口：`qp`（`.venv/bin/qp`，勿用 `uv run qp`——Python 3.12 下载会超时）。
> 入口统一在 `qp/platform/cli/commands/<组>.py`。

## 命令总表（`qp --help` 实测 2026-08-11）

| 命令组 | 入口文件 | 主要子命令 |
|---|---|---|
| data | `commands/data_cmd.py` | fetch（拉取行情） |
| decide | `commands/decide.py` | 生成/审阅投资决策 |
| doctor | `commands/meta.py`（cmd_doctor） | 环境自检 |
| experiment | `commands/experiment.py` | list, show, run, compare, validate, clean |
| factor | `commands/factor_cmd.py` | catalog, compute, health, list, report, update-health, validate |
| fundamental | main | 拉取基本面数据 |
| ingest | `commands/ingest.py` | 从配置源导入数据 |
| knowledge | `commands/knowledge.py` | stats, search |
| lineage | `commands/lineage.py` | snapshot（同步注册表→血缘 DAG→lineage_graph.json） |
| model | `commands/model.py` | list, show |
| monitor | `commands/monitor.py` | check, regime, alert-test |
| paper | `commands/paper.py` | start, status |
| pipeline | main/`commands/` | Pipeline 子命令 |
| portfolio | `commands/portfolio.py` | report, risk |
| position | `commands/position.py` | list, show, close, pnl, history |
| proposal | `commands/proposal.py` | list, show, create, approve, reject, withdraw |
| retrain | `commands/retrain.py` | 触发模型重训 |
| run | `commands/ingest.py`（cmd_run，parser.py 转发） | 运行 Pipeline（daily 等） |
| scheduler | `commands/scheduler.py` | 调度器（systemd 管理，勿手动起第二实例） |
| simulation | `commands/shadow.py` | 影子/纸面交易模拟 |
| strategy | `commands/strategy.py` | list, approve, deactivate, approved |
| validate | `commands/validate.py` | 对策略/实验跑验证 Gate |
| web | `commands/web.py` | Web UI 服务器 |

## 高频命令详解

### qp run daily
- 入口：`qp/pipeline/daily_pipeline.py`（`run daily` 由 main 转发）
- 流程：Step 6 选策略 → **只选 lifecycle==APPROVED**（ADR-031，无 APPROVED 则跳过+警告）→ compute_today_signals → Step 8 逐策略 generate_signals(today) → Step 8.5 StrategyHealthLogger → Step 9 Ensemble 融合 → Step 10.5 存信号快照到 `data/monitoring/online_signal_history.parquet` → DecisionPackage → `data/decisions/`
- ⚠️ 生产读冻结快照 `registry.get_approved(id)`，不读可变 meta（410dd8a）

### qp factor update-health / health / report
- 入口：`commands/factor_cmd.py` → `qp/monitoring/factor_health_logger.py`（FactorHealthLogger）+ `factor_health*.py`
- 流程：load factor dataset → 算 IC → 算 IC_IR → 分类 health（production/weakening/degraded/retired 等 stage）→ 写 registry → 生成 report
- 判定逻辑在 `qp/monitoring/factor_health_logger.py`（stage 排序见 cmd_factor_list）；因子计算在 `qp/research/factor_calculator.py`

### qp strategy approve <id> --by <名字>
- 入口：`commands/strategy.py` → `qp/strategy/registry.py` + `approved.py`
- 流程：校验有权重 → 冻结不可变快照（ApprovedStrategy）→ lifecycle→APPROVED → 快照带 validation_report
- 配套：`deactivate` → lifecycle→BACKTEST_PASSED；判断"跑不跑"以 lifecycle 为准，别信 approved dict

### qp monitor check / regime
- 入口：`commands/monitor.py` → `qp/monitoring/kill_switch_pipeline.py`（full/fast）+ `online_monitor.py`
- 输出：MonitorReport（含 rolling_ic / rolling_ic_available）；IC_DECAY 报警语义：available=False=没数据不报，True+ic≈0=真衰减才报
- 产物：`data/monitoring/retrain_signals.parquet`

### qp experiment run multifactor
- 入口：`commands/experiment.py` → `qp/research/experiment/run_multifactor_experiment.py`
- 示例：`qp experiment run multifactor --strategy momentum_vol_full --start 2024-01-01 --end 2026-07-23 --top-n 10 --rebalance 20`（加 `--skip-gate` 跳过门禁）
- ⚠️ 需要 Gold 数据集；数据缺失先 `qp data fetch`

### qp lineage snapshot
- 入口：`commands/lineage.py` → `qp/lineage/engine.py`
- 流程：sync DatasetRegistry(12)/FeatureRegistry(0)/ModelRegistry(0)/StrategyRegistry(6) → DAG → `data/metadata/lineage_graph.json`（Rule 7）

### qp paper start <strategy_id>
- 入口：`commands/paper.py` → `qp/strategy/paper_trading.py` + `qp/simulation/broker.py`
- ⚠️ CLI 只校验已注册策略，不自动注册（否则污染 strategy_registry.json）
- 状态文件固定 `data/paper_trading/{strategy_id}_paper.json`——回放验证会覆盖真实 run，验证完记得重启

### qp scheduler（systemd 管理）
- 服务：`qp-scheduler.service`，ExecStart=`python -m qp.platform.cli.main scheduler start`，Restart=always RestartSec=30
- 5 个工作日 job：monitor_check 09:07 / retrain_notify 09:17 / pre_close_check 16:53 / daily_pipeline 18:00 / email_report 18:30
- 重启：sudo 或 `kill -TERM <MainPID>` 等 30s 自动拉起；**勿绕过 systemd 起第二实例**

## 查命令细节的方法
1. `.venv/bin/qp <组> --help` 看子命令
2. `read_file qp/platform/cli/commands/<组>.py` 看 handler
3. handler 里跟 service 调用链（如 factor_health → monitoring/factor_health.py）
4. 只看这条链上的文件，不要读整个目录
