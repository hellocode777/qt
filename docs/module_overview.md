# QP 模块总览 / Module Overview

> 人读版模块地图。对 AI：更细的「问题 → 文件」映射见 `ai/MODULE_MAP.md`。
> 最后更新：2026-08-13

---

## 1. platform/ — 运行框架（L1）

| 子模块 | 职责 | 关键类/文件 |
|--------|------|------------|
| `cli/` | CLI 唯一入口（20+ 命令） | `main.py`、`parser.py`、`commands/*.py` |
| `runtime/` | 生命周期状态机 + 组合根 | `Application`、`RuntimeContext`、`LifecycleManager`、`build_runtime()` |
| `config/` | 4 层优先级配置，启动后冻结 | `Config`（FreezableBaseModel） |
| `logging/` | Loguru 统一日志，禁 print | `QPLogger` |
| `scheduler/` | 任务调度（5 个工作日 job） | `JobRegistry`、`QPScheduler` |
| `storage/` | 多后端存储工厂 | `StorageFactory`（DuckDB/SQLite/Parquet） |
| `pipeline/` | 管道引擎 | `PipelineRunner`、`PipelineContext`、`BasePipeline` |
| `metadata/` | 版本/环境信息 | `RuntimeMeta` |
| `proposals/` | 策略提案审批 | `StrategyProposal`、`ProposalStore` |

## 2. data/ — 数据层（L2）

对外只出 **Data Product（Dataset）**，消费方永远不知道数据源（ADR-013/015/017）。

| 子模块 | 职责 |
|--------|------|
| `adapter/` | 外部源适配（AkShare、QuantTrading DB） |
| `dataset/` | Dataset 注册表与解析（唯一公开接口） |
| `loader/` | 从 Parquet/DuckDB 加载 |
| `cleaning/` | 数据清洗（5 个管道） |
| `validation/` | 数据质量验证（7 个检查） |
| `universe/` | 股票池定义与筛选 |
| `calendar/` | A 股交易日历 |
| `fundamental/` | 基本面数据（ROE、毛利率等） |
| `valuation/` | PE/PB 估值（PIT 对齐） |
| `capital_flow/` | 资金流向 |
| `corporate_action/` | 公司行为（分红/拆股/复权） |
| `industry/` | 行业分类映射 |
| `metadata/` | 血缘与元信息 |

## 3. research/ — 研究层（L3）

可复现实验：**Purged KFold 强制**（ADR-021），实验 ≠ 生产（ADR-018）。

| 子模块 | 职责 | 关键类 |
|--------|------|--------|
| `feature/` | 特征工程（动量/波动/量价/资金流） | `compute_all_factors`、`FeatureRegistry` |
| `label/` | 标签构建（forward return rank） | — |
| `trainer/` | LightGBM LambdaRank 训练 | `LightGBMRankModel`、`OptunaSearch`（TDR-005） |
| `model_trainer.py` | Walk-forward 滚动训练 | `WalkForwardScorer` |
| `split/` | 数据集划分 | `PurgedKFold` |
| `evaluation/` | 分层测试（Rank IC / ICIR / 分层收益） | `LayeredTest`、`quintile_diag` |
| `experiment/` | 实验追踪 | `ExperimentTracker`、`ExperimentRunner` |
| `importance/` | 特征重要性（SHAP） | — |

## 4. validation/ — 验证门（L4）

| 文件 | 职责 |
|------|------|
| `engine.py` | 规则引擎（16 项检查，4 阶段） |
| `checks/` | 验证规则集 |
| `pipeline.py` | 验证管道 |
| `result.py` | GateResult（pass/fail + 详情） |

## 5. strategy/ — 策略层（L5）

输出 **Decisions**，不是 Orders（ADR-026）。

| 文件/目录 | 职责 |
|----------|------|
| `registry.py` | 策略注册表 |
| `approved.py` | ApprovedStrategy 冻结快照（ADR-031） |
| `multifactor.py` | 多因子策略 |
| `factor_composite.py` / `factor_layers.py` / `regime_ensemble.py` | 因子合成/分层/regime 集成 |
| `quality_filter.py` / `market_filter.py` / `market_regime.py` | 质量/市场过滤 |
| `paper_trading.py` | Paper Trading（Rule 11） |
| `strategies/momentum_vol_full.py` | 生产策略 mvF（5 因子） |

## 6. portfolio/ — 组合层（L6）

风险归 portfolio（ADR-029），资金分配也是 portfolio 责任（ADR-030）。

| 文件/目录 | 职责 |
|----------|------|
| `capital_allocator.py` / `allocator/` | 资金分配（等权/Kelly/RiskParity/VolTarget） |
| `portfolio_risk_engine.py` / `risk*` | 风控引擎 |
| `budget/` | 风险预算（VaR/CVaR/Volatility） |
| `cash/` | 现金管理 |
| `nav_ledger.py` | NAV 记账 |
| `cost_model.py` / `correlation.py` / `clustering.py` | 成本/相关性/聚类 |

## 7. simulation/ — 模拟层（L7）

| 文件 | 职责 |
|------|------|
| `broker.py` | SimulatedBroker（成交/持仓/订单拒绝） |
| `slippage.py` | 滑点模型 |
| `shadow_ledger.py` | 影子交易台账（⚠️ 宪法 5 处违规待整改） |
| `paper_trading.py` | 纸交易 |

## 8. decision/ — 决策层（L8）

| 文件 | 职责 |
|------|------|
| `decision_package.py` | DecisionPackage（每日输出，三个执行系统共同输入） |
| `engine.py` | 决策引擎 |
| `position_ledger.py` | 持仓账本（Portfolio 现金账本 ADR-032） |
| `state_machine.py` | 决策状态机 |

## 9. monitoring/ — 监控层（L9，只观察不决策）

| 文件 | 职责 |
|------|------|
| `kill_switch.py` / `kill_switch_pipeline.py` | 熔断（09:07 全量 / 16:53 fast） |
| `factor_health.py` / `factor_health_pipeline.py` / `factor_report.py` | 因子健康度（IC/IC_IR 分类） |
| `online_monitor.py` | 在线信号健康（rolling_ic） |
| `model_decay.py` / `model_decay_lifecycle.py` | 模型衰减与生命周期降级 |
| `retrain_signal.py` | 重训信号（Asia/Shanghai 时间戳） |
| `strategy_monitor.py` / `strategy_health_report.py` | 策略健康度 |
| `regime.py` / `drift.py` / `alerts.py` | regime/漂移/告警 |

## 10. knowledge/ — 知识层（L10）

| 文件 | 职责 |
|------|------|
| `archive.py` / `failure_archive_logger.py` | 失败归档 |
| `decision_audit_logger.py` | 决策审计 |
| `regime_notes.py` / `cluster_analyzer.py` / `version_tree.py` | 笔记/聚类/版本树 |

## 11. 辅助模块

| 路径 | 职责 |
|------|------|
| `qp/shared/` | protocols（11 个 Base*）、types、constants、exceptions |
| `qp/pipeline/daily_pipeline.py` | **每日管道**（Step 6 选 APPROVED 策略） |
| `qp/pipeline/multifactor_pipeline.py` | 多因子实验管道 |
| `qp/lineage/engine.py` | LineageRegistry（Rule 7） |
| `qp/web/` | Web UI（FastAPI + Jinja2 + HTMX） |

## 依赖速查（改代码前先看这条线）

```
daily_pipeline → strategy/registry(approved 快照) → multifactor → factor_composite → factor_values(dataset)
kill_switch_pipeline → monitoring/* + strategy health → retrain_signals.parquet
experiment run multifactor → research/experiment → model_trainer → validation gate → registry.register
```
