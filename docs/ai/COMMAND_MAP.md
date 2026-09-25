# COMMAND_MAP — QP CLI 命令地图（命令 → 代码入口 → 流程）

> 用途：给 AI 定位"某个命令做了什么"。先查本表拿到命令组入口文件，
> 再只读相关 handler 和 service。
> CLI 唯一入口：`qp`（`.venv/bin/qp`，勿用 `uv run qp`——Python 3.12 下载会超时）。
> 入口统一在 `qp/platform/cli/commands/<组>.py`。

## 命令总表（`qp --help` 实测 2026-08-11；industry 于 2026-09-25 补录）

| 命令组 | 入口文件 | 主要子命令 |
|---|---|---|
| data | `commands/data_cmd.py` | fetch（拉取行情）, index（基准指数 CSI300/上证，打印最新交易日 + OK/STALE，支持 `--symbol=`） |
| decide | `commands/decide.py` | 生成/审阅投资决策 |
| doctor | `commands/meta.py`（cmd_doctor） | 环境自检 |
| experiment | `commands/experiment.py` | list, show, run, compare, validate, clean, optuna |
| factor | `commands/factor_cmd.py` | catalog, compute, health, list, report, update-health, validate |
| fundamental | `commands/ingest.py`（cmd_fundamental） | 拉取基本面数据 |
| industry | `commands/industry.py` | heat（行业热度榜：行情口径 涨幅/成交额/上涨占比；资金流口径 主力净流入；`--granularity csrc\|subsector\|sector`、`--window`、`--date`、`--top`、`--save`） |
| ingest | `commands/ingest.py` | 从配置源导入数据（cmd_ingest） |
| knowledge | `commands/knowledge.py` | stats, search |
| lineage | `commands/lineage.py` | snapshot（同步注册表→血缘 DAG→lineage_graph.json） |
| model | `commands/model.py` | list, show |
| monitor | `commands/monitor.py` | check, regime, alert-test |
| paper | `commands/paper.py` | start, status |
| pipeline | `commands/ingest.py`（cmd_pipeline_list） | list（data_ingest / fundamental_ingest / feature_compute / daily） |
| portfolio | `commands/portfolio.py` | report, risk |
| position | `commands/position.py` | list, show, close, pnl, history |
| proposal | `commands/proposal.py` | list, show, create, approve, reject, withdraw |
| retrain | `commands/retrain.py` | `qp retrain [strategy_id] [--dry-run]`；不传策略 = registry 里唯一 APPROVED（解析失败即报错，不猜） |
| run | `commands/ingest.py`（cmd_run，parser.py 转发） | 运行 Pipeline（daily 等） |
| scheduler | `commands/scheduler.py` | 调度器（systemd 管理，勿手动起第二实例） |
| simulation | `commands/shadow.py` | 影子/纸面交易模拟 |
| strategy | `commands/strategy.py` | list, approve, deactivate, approved |
| validate | `commands/validate.py` | 对策略/实验跑验证 Gate；默认策略 = registry 唯一 APPROVED；指标取自实验记录（`--experiment` 可指定），缺失的指标列在「未评估」而非塞占位值 |
| web | `commands/web.py` | Web UI 服务器 |

## 高频命令详解

### qp run daily
- 入口：`qp/pipeline/daily_pipeline.py`（`run daily` 由 main 转发，cmd_run 在 ingest.py）
- 完整步骤（2026-08-11 实测）：
  1. Step 0 系统状态检查 → Step 1 抓数据（增量合并到 `data/dataset/daily_price_latest.parquet`）→ Step 1.5 因子计算（→ `factor_values_daily.parquet`）
  2. Step 5 regime 检测 → 决定 `effective_top_n`
  3. **Step 6 选策略（ADR-031 Policy A）**：只选 `lifecycle == APPROVED`（registry.get_lifecycle）；无 APPROVED → 跳过+警告，**不回退 research**；权重读 `registry.get_approved(id)` 冻结快照（不读 meta）；调 `compute_today_signals()` 只算今日分数（O(stocks)）
  4. **Step 8 出信号**：逐策略 `strategy.generate_signals(today)` → 返回 `[symbol, raw_score, rank]`（已 top-N 过滤）→ Step 8.5 StrategyHealthLogger 记健康度
  5. **Step 9 融合**：EnsembleEngine 等权融合 Step 6 选出的全部 APPROVED 策略信号（FILL_ZERO 宇宙）；策略集大小 = 当时 APPROVED 数量（N=1 时等效直通，N≥2 时等权合成）
  6. Step 10 风控/退出（止损 -7% / 止盈 / 回撤 20% / 行业超配 / 基本面恶化）→ Step 10.5 存信号快照到 `data/monitoring/online_signal_history.parquet` → Step 11 成本 → Step 12 资金分配（仅调仓日）
  7. **Step 13** DecisionPackage → `data/decisions/` → **Step 13.1 ShadowLedger.run_daily(today)** 模拟盘（假钱按决策包数量建仓，无 SELL 即持有，当日市值 mark-to-market）
- ⚠️ 生产读冻结快照 `registry.get_approved(id)`，不读可变 meta（410dd8a）
- ⚠️ 信号是截面排名选股（今日因子加权分 top-N），不是涨跌择时；top_n 受 regime 调节
- ⚠️ Shadow 的 mark-to-market 用 `daily_price_latest.parquet` 最新收盘价（补跑历史日期有前视偏差）

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
- 输出：MonitorReport（含 rolling_ic / rolling_ic_available / psi_available）；IC_DECAY 报警语义：available=False=没数据不报，True+ic≈0=真衰减才报
- 显示铁律：`psi_available=False`（或 `rolling_ic_available=False`）时，CLI/日志/邮件/模板必须显示「不可测」，不得打印默认值 `0.000`
- 产物：`data/monitoring/retrain_signals.parquet`

### qp experiment run multifactor
- 入口：`commands/experiment.py` → `qp/pipeline/multifactor_pipeline.py`（MultiFactorPipeline）
- 示例：`qp experiment run multifactor --strategy momentum_vol_full --start 2024-01-01 --end 2026-07-23 --top-n 10 --rebalance 20`（加 `--skip-gate` 跳过门禁）
- ⚠️ 需要 Gold 数据集；数据缺失先 `qp data fetch`
- 历史脚本 `run_multifactor_experiment.py` 已于 2026-08-12 删除（被 CLI 取代，跨层违规）

### qp lineage snapshot
- 入口：`commands/lineage.py` → `qp/lineage/engine.py`
- 流程：sync DatasetRegistry(12)/FeatureRegistry(0)/ModelRegistry(0)/StrategyRegistry(6) → DAG → `data/metadata/lineage_graph.json`（Rule 7）

### qp paper start <strategy_id>
- 入口：`commands/paper.py` → `qp/strategy/paper_trading.py` + `qp/simulation/broker.py`
- 机制：30 天周期验证**策略本身**（跟策略自选信号走，不经决策包/风控）；首日建仓 top-N，之后**月度调仓日**（每月首个交易日，对齐 shadow 侧 daily_pipeline BUY 门）按最新信号等权重构，持仓跨日持久化
- 自动推进：scheduler job `paper_trading`（工作日 18:32，等 daily_pipeline 拉价完成后）对每个未完成 run 调 `run_day()`；30 天满自动 evaluate（Sharpe≥0.5 / MaxDD≤20% / 信号数 3-30）→ PASS=SHADOW_PRODUCTION / FAIL=RESEARCH
- ⚠️ CLI 只校验已注册策略，不自动注册（否则污染 strategy_registry.json）
- ⚠️ 状态文件固定 `data/paper_trading/{strategy_id}_paper.json`——回放验证会覆盖真实 run，验证完记得重启

### qp scheduler（systemd 管理）
- 服务：`qp-scheduler.service`，ExecStart=`python -m qp.platform.cli.main scheduler start`，Restart=always RestartSec=30
- 6 个工作日 job：monitor_check 09:07 / retrain_notify 09:17 / pre_close_check 16:53 / daily_pipeline 18:00 / paper_trading 18:32 / email_report 18:30
- 重启：sudo 或 `kill -TERM <MainPID>` 等 30s 自动拉起；**勿绕过 systemd 起第二实例**
- `retrain_notify` 去重：同一批信号只通知一次（状态文件 `data/monitoring/retrain_notify_state.json` 记 `last_notified_at`），无新信号只打日志；信号→策略权重在 `daily_pipeline` Step 9（`load_weight_scales`）

## 查命令细节的方法
1. `.venv/bin/qp <组> --help` 看子命令
2. `read_file qp/platform/cli/commands/<组>.py` 看 handler
3. handler 里跟 service 调用链（如 factor_health → monitoring/factor_health.py）
4. 只看这条链上的文件，不要读整个目录
