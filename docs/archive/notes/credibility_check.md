# QP 架构可信性自查报告 / Architecture Credibility Self-Check

> 按 rule.md §9 七类可信性逐项检查，最后更新：2026-07-20

---

## 1. 数据可信性 / Data Credibility

| 机制 | 状态 | 实现 | 评估 |
|---|---|---|---|
| Data Contract | ✅ | `qp/data/contract/` — `DailyPriceContract` 定义列名、类型、频率、主键 | 有定义，但 Pipeline 各阶段未强制执行 Schema 校验 |
| Data Cleaning | ✅ | `qp/data/cleaning/` — 停牌(volume=0)、涨跌停过滤 | 仅基础清洗，缺异常值检测(mad-based)、PIT 双版本 |
| Lineage | ✅ | `qp/research/experiment/models.py` — `LineageGraph` (dataset→feature→model→strategy) | Experiment 级别有血缘，但日常 Pipeline 运行不记录数据版本 |
| Trading Calendar | ✅ | `qp/data/calendar/` — A 股交易日历 | 有实现，但非交易日处理逻辑分散在各模块 |
| Data Source Isolation | ✅ | Adapter 模式 — Tencent/AKShare/Demo，消费者只接触 Dataset | 符合 ADR-013，但 Demo 数据覆盖度有限 |

**综合评估**: ⚠️ **数据可信性基本满足**。差距：缺少 PIT 财务数据、Pipeline 运行时缺少自动 Schema 校验、Demo 数据不够真实。

**建议**:
1. 在 Pipeline 各阶段入口加 Schema 校验
2. 给 Demo 数据加上真实股票代码和合理价格范围

---

## 2. 研究可信性 / Research Credibility

| 机制 | 状态 | 实现 | 评估 |
|---|---|---|---|
| Rank IC | ✅ | `qp/validation/checks/factor_checks.py` — `RankICCheck(≥0.02)` | 有实现，但仅用于 Phase 2 验证，未被日常 Pipeline 调用 |
| IC IR | ✅ | `ICIRCheck(≥0.3)` | 同上 |
| t-stat | ✅ | `TStatCheck(≥2.0)` | 同上 |
| 分层检验 | ✅ | `StratificationCheck(n_quantiles=5)` | 同上 |
| Purged CV | ✅ | `qp/research/split/` — `PurgedKFold` + `purge_train_set` + `embargo_test_set` | 完整实现，但未被任何训练 Pipeline 实际使用 |
| Experiment Tracking | ✅ | `qp/research/experiment/` — `ExperimentTracker` + `ExperimentRunner` + JSON 存储 | 完整，但缺少自动超参搜索 |
| 截面中性化 | ❌ | 未实现 | 没有行业/市值中性化模块 |

**综合评估**: ⚠️ **框架齐全但未集成**。Purged CV 和 IC 检验都有实现，但没有串联成自动化训练→验证→注册流程。

**建议**:
1. 实现截面中性化（行业 + 市值）
2. 将 Purged CV 接入 LightGBM 训练
3. 训练完成后自动写入 Experiment Tracker

---

## 3. 策略可信性 / Strategy Credibility

| 机制 | 状态 | 实现 | 评估 |
|---|---|---|---|
| Validation Gate | ✅ | `qp/validation/engine.py` — `RuleEngine` + 6 条规则 + PASS/FAIL 判定 | 完整，`qp validate` 可运行 |
| Strategy Lifecycle | ✅ | `StrategyLifecycle` 枚举（RESEARCH→…→PRODUCTION→KILL_SWITCH） + `StrategyRegistry` | 有状态定义和 Registry，但生命周期转换无自动化 |
| Paper Trading | ⚠️ | `SimulatedBroker` 实现，但无独立 Paper Trading Pipeline | Broker 有，但缺少 30 天持续运行的 Paper Trading 跟踪 |
| Kill Switch | ✅ | `qp/monitoring/kill_switch.py` + `KillSwitchPipeline` | 完整，3 个 trigger + 每日自动检查 |
| Decision ≠ Order | ✅ | `qp/decision/` — `TradeRecommendation` + `DecisionReport` | 刚完成，符合 ADR-026 |

**综合评估**: ✅ **策略可信性框架完整**。差距：Paper Trading 30 天自动跟踪未实现、生命周期状态转换需手动触发。

---

## 4. 交易可信性 / Trading Credibility

| 机制 | 状态 | 实现 | 评估 |
|---|---|---|---|
| Cost Model | ✅ | `qp/portfolio/cost_model.py` — 印花税(0.05%)+佣金(0.025%)+滑点(10bps)+sqrt冲击成本 | 完整，A 股实际费率 |
| ADV 限制 | ✅ | `SimulatedBroker` — 单笔 ≤ 10% ADV，超额自动裁剪 | 完整 |
| Slippage Model | ✅ | `qp/simulation/slippage.py` — FixedSlippage / VolatilitySlippage / SqrtImpactModel | 3 种模型可选 |
| Corporate Action | ✅ | `qp/data/corporate_action/engine.py` — 现金分红/送股/拆股/配股/转增 | 完整，但实际触发依赖外部数据 |
| Trade Log | ✅ | `SimulatedBroker` — 完整 trade log (timestamp/symbol/side/shares/price/cost) | 可审计 |

**综合评估**: ✅ **交易可信性完整**。回测的成本估算和流动性约束独立于任何特定券商，符合「决策辅助系统」定位。

---

## 5. 组合可信性 / Portfolio Credibility

| 机制 | 状态 | 实现 | 评估 |
|---|---|---|---|
| Position Limit | ✅ | `PortfolioRiskManager` — 单仓 ≤ 8% | 完整 |
| Sector Limit | ✅ | 单行业 ≤ 25% + `IndustryMapper` (申万分类) | 完整 |
| Correlation Filter | ✅ | `CorrelationAnalyzer` — >0.7 冗余检测 | 完整 |
| Capital Allocation | ✅ | EqualWeight + RiskParity + FractionalKelly + 现金缓冲 ≥ 5% | 3 种方法 |
| Position Optimization | ✅ | `MeanVarianceOptimizer` — SLSQP + Ledoit-Wolf + 等权回退 | 完整 |
| Risk Decomposition | ✅ | `RiskModel` — Market/Style/Sector/Idiosyncratic | 有框架，但硬编码近似值而非真实因子模型 |

**综合评估**: ✅ **组合可信性基本完整**。差距：RiskModel 的 `decompose_risk` 用硬编码近似（beta=1.0），需要真实收益数据才能启用 `attribute()` 做精确归因。

---

## 6. 长期演进能力 / Long-term Evolution

| 机制 | 状态 | 实现 | 评估 |
|---|---|---|---|
| Strategy Registry | ✅ | `qp/strategy/registry.py` — dict-backed，支持生命周期过滤 | 完整，但 dict 非持久化 |
| Feature Registry | ✅ | `qp/research/feature/` | 完整 |
| Dataset Registry | ✅ | `qp/data/loader/` — `DatasetRegistry` | 完整 |
| Model Registry | ✅ | `qp/research/trainer/registry.py` — SHA256 哈希 + 文件管理 | 完整 |
| Experiment Tracker | ✅ | JSON 文件存储 + LineageGraph | 完整 |
| Knowledge Archive | ✅ | `qp/knowledge/archive.py` — 5 类模板 + 全文搜索 | 完整 |
| Research Debt | ✅ | `KnowledgeArchive.create_research_debt()` | 完整，但内容依赖人工填写 |

**综合评估**: ✅ **长期演进能力完整**。5 个 Registry + Experiment Tracker + Knowledge Archive 构成了完整的可追溯体系。

---

## 7. 生产安全性 / Production Safety

| 机制 | 状态 | 实现 | 评估 |
|---|---|---|---|
| Monitoring | ✅ | `qp/monitoring/` — 7 个模块（KillSwitch, Drift, Decay, Regime, StrategyMonitor, Alerts, Pipeline） | 完整 |
| Drift Detection | ✅ | PSI/KS/Wasserstein 三种方法 | 完整 |
| Model Decay | ✅ | 滚动 IC < 30% 训练 IC → 降级 Shadow | 完整 |
| Market Regime | ✅ | TREND/RANGING/HIGH_VOL/LOW_VOL + ADX | 完整 |
| Alert Channels | ✅ | Terminal + Log + Telegram 三通道 | Terminal/Log 可用，Telegram 需 Token |
| Kill Switch | ✅ | 3 个 trigger + 5 级动作 + 每日自动 Pipeline | 完整 |

**综合评估**: ✅ **生产安全性完整**。监控、衰减检测、熔断三套独立机制覆盖了从早期预警到紧急停止的全链路。

---

## 总结 / Summary

| 维度 | 评级 | 关键差距 |
|---|---|---|
| 1. 数据可信性 | ⚠️ 基本满足 | 缺 PIT、Pipeline Schema 校验 |
| 2. 研究可信性 | ⚠️ 基本满足 | 缺截面中性化、Purged CV 未接入训练 |
| 3. 策略可信性 | ✅ 完整 | Paper Trading 30 天未自动化 |
| 4. 交易可信性 | ✅ 完整 | — |
| 5. 组合可信性 | ✅ 基本完整 | RiskModel 精确度待提升 |
| 6. 长期演进能力 | ✅ 完整 | — |
| 7. 生产安全性 | ✅ 完整 | — |

**全 7 类可信性：5 通过 / 2 基本满足 / 0 不通过**

### 后续行动计划

1. **短期**（Phase 6 内）: 实现截面中性化、在 Pipeline 入口加 Schema 校验
2. **中期**: 将 Purged CV 接入 LightGBM 训练流程、自动化 Paper Trading 跟踪
3. **长期**: 引入 PIT 财务数据、实现真实因子协方差 RiskModel
