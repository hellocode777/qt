# MODULE_MAP — QP 模块地图（问题 → 相关文件）

> 用途：给 AI 定位代码用。问"X 模块/行为为什么这样"时，先查本表拿到**相关文件清单**，
> 只读这些文件，不要读整个项目。
> 映射以 2026-08-11 源码为准；改了代码后若文件结构变化，顺手更新本文件。

## 1. qp/platform/ — 运行框架（Layer 1）

| 子目录 | 职责 | 关键文件 |
|---|---|---|
| cli | CLI 唯一入口 | `main.py`、`parser.py`、`commands/*.py`（每个命令组一个文件） |
| runtime | 生命周期状态机、composition root | `runtime/` |
| config | 4 层优先级配置，启动后冻结 | `config/` |
| logging | Loguru 统一日志，禁 print | `logging/` |
| scheduler | 任务调度 | `scheduler.py`（在 cli/commands/）、`scheduler/` |
| storage | StorageFactory（DuckDB/SQLite/Parquet） | `storage/` |
| pipeline | BasePipeline 抽象 | `pipeline/` |
| metadata | 版本/环境信息 | `metadata/` |

**诊断顺序**：问题 → 命令 → `qp/platform/cli/commands/<组>.py` 的 handler → 对应 service。

## 2. qp/data/ — 数据层（Layer 2，对外只出 Data Product）

| 子目录 | 职责 | 关键文件 |
|---|---|---|
| adapter | 外部源适配（AkShare、QuantTrading DB） | `quant_trading_db_adapter.py` |
| dataset | Dataset 注册表与解析 | `dataset/registry.py` |
| pipeline.py | 数据 Pipeline | `pipeline.py` |
| cleaning / loader / universe / calendar | 清洗/加载/股票池/交易日历 | 各子目录 |
| fundamental / capital_flow / corporate_action / industry / knowledge | 基本面/资金流/事件/行业/另类数据 | 各子目录 |

**规则**：消费方只依赖 Dataset；`data/dataset/` 是唯一公开接口（ADR-013/015/017）。

## 3. qp/research/ — 研究层（Layer 3）

| 子目录 | 职责 | 关键文件 |
|---|---|---|
| factor_calculator.py / factor_processor.py | 因子计算与处理 | 顶层两文件 |
| experiment | 实验系统（CLI 入口 → pipeline） | `pipeline/`、`models.py`、`tracker.py` |
| model_trainer.py / trainer | LightGBM 训练 | 顶层 + trainer/ |
| feature / label / split / evaluation | 特征/标签/数据集划分/评估 | 各子目录 |
| pipeline | 研究 Pipeline | `pipeline/` |

**规则**：Purged KFold 强制（ADR-021）；实验≠生产（ADR-018）。

## 4. qp/validation/ — 验证门（Layer 4，Gate）

| 文件 | 职责 |
|---|---|
| engine.py | 规则引擎 |
| checks/ | 验证规则集 |
| pipeline.py | 验证 Pipeline |
| result.py | 验证结果模型 |
| gate_registry_bridge.py | Gate ↔ 注册表桥接 |

## 5. qp/strategy/ — 策略层（Layer 5，输出 Decisions）

| 文件/目录 | 职责 |
|---|---|
| registry.py | 策略注册表（register/get_meta/get_approved） |
| approved.py | ApprovedStrategy 冻结快照（ADR-031） |
| multifactor.py | 多因子策略 |
| generator.py / loader.py | 信号生成/加载 |
| quality_filter.py / market_filter.py / market_regime.py | 质量/市场过滤、regime |
| factor_composite.py / factor_layers.py / regime_ensemble.py / aggregator.py | 因子合成/分层/集成 |
| ensemble/ | 策略融合（Step 9） |
| paper_trading.py | Paper Trading（Rule 11） |
| models/ / signal/ / runner/ | 模型/信号/运行器 |

## 6. qp/portfolio/ — 组合层（Layer 6）

| 文件/目录 | 职责 |
|---|---|
| capital_allocator.py / allocator/ / budget/ / cash/ | 资金分配 |
| portfolio_risk_engine.py / risk* | 风控 |
| optimizer.py / optimization/ | 组合优化 |
| correlation.py / clustering.py / exposure/ / constraints/ | 相关性/聚类/暴露/约束 |
| alpha_decay.py / exit_signals.py | 衰减/退出信号 |
| cost_model.py / slippage（simulation） | 成本 |
| nav_ledger.py / models/ | NAV 记账 |

## 7. qp/simulation/ — 模拟层（Layer 7）

| 文件 | 职责 |
|---|---|
| broker.py | SimulatedBroker（成交/持仓） |
| result.py | 回测结果 |
| shadow_ledger.py | 影子交易台账（⚠️ 宪法 5 处违规待整改：应归 decision） |
| slippage.py | 滑点模型 |

## 8. qp/decision/ — 决策层（Layer 8）

| 文件 | 职责 |
|---|---|
| decision_package.py | DecisionPackage |
| engine.py | 决策引擎 |
| position_ledger.py | 持仓台账 |
| state_machine.py | 决策状态机 |
| models.py | 决策数据模型 |

## 9. qp/monitoring/ — 监控层（Layer 9，只观察不决策）

| 文件 | 职责 |
|---|---|
| kill_switch.py / kill_switch_pipeline.py | 熔断（09:07 全量 / 16:53 fast） |
| factor_health.py / factor_health_logger.py / factor_health_pipeline.py / factor_report.py | 因子健康度（IC/IC_IR 分类） |
| online_monitor.py | 在线信号健康（rolling_ic，无数据返回 None） |
| model_decay.py / model_decay_lifecycle.py | 模型衰减与生命周期降级 |
| retrain_signal.py | 重训信号（时间戳必须 Asia/Shanghai） |
| strategy_health_logger.py / strategy_health_report.py / strategy_monitor.py | 策略健康度 |
| regime.py / drift.py / alerts.py / system_state.py | regime/漂移/告警/系统状态 |

## 10. qp/knowledge/ — 知识层（Layer 10）

| 文件 | 职责 |
|---|---|
| archive.py / failure_archive_logger.py | 失败归档 |
| decision_audit_logger.py | 决策审计 |
| regime_notes.py / cluster_analyzer.py / version_tree.py | 笔记/聚类/版本树 |

## 11. 辅助模块

| 路径 | 职责 |
|---|---|
| `qp/shared/` | protocols（BaseStrategy/BaseModel）、types、constants、exceptions |
| `qp/pipeline/daily_pipeline.py` | **每日管道**（Step 6 选 APPROVED 策略，ADR-031） |
| `qp/pipeline/factor_calc_pipeline.py` / `multifactor_pipeline.py` / `fundamental_pipeline.py` | 各专项 Pipeline |
| `qp/lineage/engine.py` | LineageRegistry（Rule 7） |
| `qp/web/` | Web UI |

## 依赖速查（改代码前先看这条线）

```
daily_pipeline → strategy/registry(approved 快照) → multifactor → factor_composite → factor_values(dataset)
kill_switch_pipeline → monitoring/* + strategy health → retrain_signals.parquet
experiment run multifactor → research/experiment → model_trainer → validation gate → registry.register
```
