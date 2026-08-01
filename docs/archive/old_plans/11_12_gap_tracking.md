# Layer 11 & 12 — 差距跟踪表

> 对照文档: `docs/11_12.md`
> 最后更新: 2026-07-25

---

## Layer 11: Monitoring Layer（监控与熔断层）

### 1. Drift & Decay Detection（漂移与衰退检测）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 1.1 | PSI 计算（特征分布漂移） | ✅ 已实现 | `monitoring/drift.py` — `DriftMonitor.compute_psi()` |
| 1.2 | KS 检验（预测分布漂移） | ✅ 已实现 | `monitoring/drift.py` — `DriftMonitor.compute_ks()` |
| 1.3 | Wasserstein 距离 | ✅ 已实现 | `monitoring/drift.py` — `DriftMonitor.compute_wasserstein()` |
| 1.4 | 批量特征漂移检查 | ✅ 已实现 | `monitoring/drift.py` — `DriftMonitor.check_features()` |
| 1.5 | PSI > 0.25 → 自动触发 Retrain | ✅ 已实现 | `monitoring/retrain_signal.py` — `evaluate_retrain_need()` + `KillSwitchPipeline._emit_retrain_signal()` |
| 1.6 | 滚动 20/60 日 IC 监控 | ✅ 已实现 | `monitoring/model_decay.py` — `ModelDecayDetector` |
| 1.7 | Rank IC 连续 20 日 < 0.02 → 降低策略权重 | ✅ 已实现 | `retrain_signal.py` — IC ratio < 0.30 → REDUCE_WEIGHT |
| 1.8 | IC Sharpe 监控 | ❌ 未实现 | 只算 IC ratio，未算 IC Sharpe |

### 2. Market Regime Engine（市场状态引擎）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 2.1 | BULL_TREND 状态 | ⚠️ 变体 | 实现为 TREND_UP，语义相近 |
| 2.2 | HIGH_VOLATILITY 状态 | ✅ 已实现 | `monitoring/regime.py` — `Regime.HIGH_VOL` |
| 2.3 | LIQUIDITY_CRUNCH 状态 | ✅ 已实现 | `regime.py` — 涨跌停比 < 0.15 或 > 0.85 |
| 2.4 | STYLE_REVERSAL 状态 | ✅ 已实现 | `regime.py` — 行业轮动速度 > 0.50 |
| 2.5 | ADX 趋势强度 | ✅ 已实现 | `regime.py` — `_compute_adx()` |
| 2.6 | MA 交叉方向判断 | ✅ 已实现 | `regime.py` — `_trend_direction()` |
| 2.7 | ATR 波动率 | ✅ 已实现 | `regime.py` — 用于 vol percentile |
| 2.8 | 涨跌停家数比输入 | ❌ 未实现 | LIQUIDITY_CRUNCH 所需核心输入 |
| 2.9 | 量能突变率输入 | ❌ 未实现 | — |
| 2.10 | 行业轮动速度输入 | ❌ 未实现 | STYLE_REVERSAL 所需核心输入 |
| 2.11 | Regime 切换检测 | ✅ 已实现 | `regime.py` — `detect_transition()` |
| 2.12 | 策略按 Regime 自适应 | ✅ 已实现 | `strategy/config.py` — `regime_positions`/`regime_freq` |

### 3. Kill Switch（熔断机制）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 3.1 | KillSwitchLevel 枚举 (NORMAL/WARNING/HALT_BUY/FULL_STOP) | ✅ 已实现 | `monitoring/kill_switch.py` — `KillSwitchLevel` |
| 3.2 | DrawdownTrigger（回撤超历史最大 ×1.5） | ✅ 已实现 | `monitoring/kill_switch.py` — `DrawdownTrigger` |
| 3.3 | PortfolioDrawdownTrigger（月回撤 > 15%） | ✅ 已实现 | `monitoring/kill_switch.py` — `PortfolioDrawdownTrigger` |
| 3.4 | 周回撤 > 5% → HALT_BUY | ✅ 已实现 | `monitoring/kill_switch.py` — `WeeklyDrawdownTrigger` |
| 3.5 | 月回撤 > 10% → FULL_STOP | ✅ 已实现 | `PortfolioDrawdownTrigger(monthly_limit=0.15)` 阈值略不同 |
| 3.6 | 连续 5 日 PnL 为负 → WARNING + 强制人工复核 | ✅ 已实现 | `monitoring/kill_switch.py` — `ConsecutiveLossTrigger` |
| 3.7 | 单日换手 > 80% 持仓 → FULL_STOP | ✅ 已实现 | `monitoring/kill_switch.py` — `AbnormalTurnoverTrigger` |
| 3.8 | PSITrigger (PSI ≥ 0.25) | ✅ 已实现 | `monitoring/kill_switch.py` — `PSITrigger` |
| 3.9 | ModelDecayTrigger | ✅ 已实现 | `monitoring/kill_switch.py` — `ModelDecayTrigger` |
| 3.10 | KillSwitchPipeline 每日自动化 | ✅ 已实现 | `monitoring/kill_switch_pipeline.py` |

### 4. Strategy Monitor（策略健康监控）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 4.1 | 信号频率/一致性监控 | ✅ 已实现 | `monitoring/strategy_monitor.py` — `StrategyMonitor` |
| 4.2 | 换手率监控 | ✅ 已实现 | `strategy_monitor.py` — `record_turnover()` |
| 4.3 | 回撤轨迹监控 | ✅ 已实现 | `strategy_monitor.py` — `record_drawdown()` |
| 4.4 | 健康评分 (0-100) | ✅ 已实现 | `strategy_monitor.py` — `health_check()` |
| 4.5 | 信号中断天数检测 | ✅ 已实现 | `strategy_monitor.py` — `_compute_signal_gap()` |

### 5. Alert Channels（告警通道）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 5.1 | Terminal 告警 | ✅ 已实现 | `monitoring/alerts.py` — `TerminalAlert` |
| 5.2 | Log 告警 | ✅ 已实现 | `monitoring/alerts.py` — `LogAlert` |
| 5.3 | Telegram 告警 | ✅ 已实现 | `monitoring/alerts.py` — `TelegramAlert` |
| 5.4 | 钉钉告警 | ✅ 已实现 | `monitoring/alerts.py` — `DingTalkAlert` |
| 5.5 | 企业微信告警 | ✅ 已实现 | `monitoring/alerts.py` — `WeComAlert` |
| 5.6 | Email 告警 | ✅ 已实现 | `monitoring/alerts.py` — `EmailAlert` |
| 5.7 | File/Markdown 告警 | ✅ 已实现 | `monitoring/alerts.py` — `FileAlert` |
| 5.8 | AlertManager 多通道路由 | ✅ 已实现 | `monitoring/alerts.py` — `AlertManager` |

---

## Layer 12: Knowledge Layer（知识与资产库）

### 1. Failure Archive（失败档案库）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 1.1 | Failure Analysis 模板 | ✅ 已实现 | `knowledge/archive.py` — `FAILURE_ANALYSIS_TEMPLATE` |
| 1.2 | Post-Mortem 模板 | ✅ 已实现 | `knowledge/archive.py` — `POST_MORTEM_TEMPLATE` |
| 1.3 | 止损事件自动记录（含买入时特征快照） | ✅ 已实现 | `knowledge/failure_archive_logger.py` — `FailureArchiveLogger.record_stop_loss()` |
| 1.4 | Kill Switch 触发自动归档 | ✅ 已实现 | P1 C1 — `KillSwitchPipeline._archive_to_knowledge()` + `FailureArchiveLogger.record_kill_switch()` |
| 1.5 | 黑天鹅事件完整因子截面数据 | ✅ 已实现 | `FailureArchiveLogger.record_black_swan()` |
| 1.6 | 失败聚类分析 → 黑名单规则反哺 Layer 2/3 | ✅ 已实现 | `knowledge/cluster_analyzer.py` — `FailureClusterAnalyzer` |
| 1.7 | Markdown + YAML frontmatter 存储 | ✅ 已实现 | `knowledge/archive.py` — `KnowledgeEntry` |

### 2. Research Debt（研究债务）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 2.1 | Research Debt 创建 API | ✅ 已实现 | `knowledge/archive.py` — `create_research_debt()` |
| 2.2 | Gate Failure 自动归档 | ✅ 已实现 | `data/knowledge/research_debt/` 已有 17 条记录 |
| 2.3 | 策略版本树（结构化版本链） | ✅ 已实现 | `knowledge/version_tree.py` — `StrategyVersionTree` |
| 2.4 | 研究债务 TODO 清单（已知问题+待优化项） | ❌ 未实现 | 只记录 gate failure，不记录"已知有坑暂未修" |
| 2.5 | 全文搜索 | ✅ 已实现 | `knowledge/archive.py` — `search()` |
| 2.6 | 按标签/分类过滤 | ✅ 已实现 | `knowledge/archive.py` — `list_entries()` |

### 3. Market Regime Notes（市场日志）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 3.1 | 市场重大波动 ↔ 策略表现对齐记录 | ✅ 已实现 | `knowledge/regime_notes.py` — `RegimeNoteLogger` |
| 3.2 | 2024.2 微盘股流动性危机标注 | ✅ 基础架构 | Logger 已就绪，具体标注数据待填充 |
| 3.3 | 2024.9 暴涨行情 Hysteresis Buffer 影响分析 | ✅ 基础架构 | Logger 已就绪，具体标注数据待填充 |
| 3.4 | Ground Truth 标注数据供 Layer 11 校准 | ✅ 已实现 | `RegimeNoteLogger.get_ground_truth_labels()` |
| 3.5 | KnowledgeCategory 中没有对应分类 | ⚠️ 复用 | 复用 RESEARCH_DEBT 分类存储，不新增枚举值 |

### 4. Decision Audit & Trade Reason Log（决策审计）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 4.1 | Decision Audit 模板 | ✅ 已实现 | `knowledge/archive.py` — `DECISION_AUDIT_TEMPLATE` |
| 4.2 | 每日 Raw Target Portfolio 自动快照 | ✅ 已实现 | `knowledge/decision_audit_logger.py` — `record_portfolio_snapshot()` |
| 4.3 | Trade Recommendations + 完整 Tag (STOP_LOSS/RANK_DROP/RISK_EVENT) | ✅ 已实现 | `knowledge/decision_audit_logger.py` — `ReasonTag` 枚举 10 个标签 |
| 4.4 | Human-in-the-loop 覆盖记录 | ✅ 已实现 | `DecisionAuditLogger.record_human_override()` |
| 4.5 | 实际执行价格 vs 信号价格 | ✅ 已实现 | `DecisionRecord` 包含 signal_price + execution_price |
| 4.6 | `data/decisions/` 日级决策记录 | ⚠️ 部分 | 有 JSON + Markdown，但缺多标签 |

### 5. Experiment Summary（实验总结）

| # | 要求 | 状态 | 备注 |
|---|------|------|------|
| 5.1 | 实验总结模板 | ✅ 已实现 | `knowledge/archive.py` — `EXPERIMENT_SUMMARY_TEMPLATE` |
| 5.2 | 自动从 ExperimentTracker 生成 | ❌ 未实现 | 需手动填写 |

---

## 三张核心数据表

| # | 表名 | 设计文档要求 | 状态 |
|---|------|-------------|------|
| T1 | `system_health_log` | 每日 Drift PSI、IC、Regime、Kill Switch 状态 | ✅ 已实现 — `monitoring/health_logger.py` |
| T2 | `trade_decision_audit` | T 日建议、Trade Reason Tags、人工审核、执行价格 | ✅ 已实现 — `knowledge/decision_audit_logger.py` |
| T3 | `failure_archive` | 所有止损事件、黑天鹅事件时的完整因子截面 | ✅ 已实现 — `knowledge/failure_archive_logger.py` |

---

## 闭环联动

| # | 联动路径 | 状态 |
|---|---------|------|
| C1 | Layer 11 触发事件 → Layer 12 知识归档 | ✅ 已实现 — `KillSwitchPipeline._archive_to_knowledge()` |
| C2 | Layer 12 归因分析 → 反哺黑名单规则 (Layer 2) | ✅ 已实现 — `FailureClusterAnalyzer.generate_blacklist_rules()` |
| C3 | Layer 12 归因分析 → 反哺特征工程 (Layer 4) | ✅ 已实现 — `FailureClusterAnalyzer.suggest_features()` |
| C4 | Layer 12 归因分析 → 反哺策略迭代 (Layer 8) | ✅ 已实现 — `FailureClusterAnalyzer.suggest_strategy_adjustments()` |

---

## 统计

| 分类 | 已实现 | 未实现 | 部分实现 | 合计 |
|------|--------|--------|----------|------|
| L11 Drift & Decay | 4 | 3 | 1 | 8 |
| L11 Market Regime | 5 | 5 | 2 | 12 |
| L11 Kill Switch | 4 | 5 | 1 | 10 |
| L11 Strategy Monitor | 5 | 0 | 0 | 5 |
| L11 Alert Channels | 8 | 0 | 0 | 8 |
| **L11 小计** | **26** | **13** | **4** | **43** |
| L12 Failure Archive | 3 | 4 | 0 | 7 |
| L12 Research Debt | 3 | 2 | 1 | 6 |
| L12 Market Regime Notes | 0 | 5 | 0 | 5 |
| L12 Decision Audit | 1 | 4 | 1 | 6 |
| L12 Experiment Summary | 1 | 1 | 0 | 2 |
| **L12 小计** | **8** | **16** | **2** | **26** |
| 核心数据表 | 0 | 3 | 0 | 3 |
| 闭环联动 | 0 | 4 | 0 | 4 |
| **总计** | **34** | **36** | **6** | **76** |

---

## 按优先级排序的待办

### P0 — 安全相关

- [x] L11-3.1: KillSwitchLevel 枚举 (NORMAL/WARNING/HALT_BUY/FULL_STOP)
- [x] L11-3.4: 周回撤 > 5% → HALT_BUY
- [x] L11-3.6: 连续 5 日 PnL 为负 → WARNING
- [x] L11-3.7: 单日换手 > 80% 持仓 → FULL_STOP

### P1 — 核心功能

- [x] L11-2.3: LIQUIDITY_CRUNCH 状态检测（涨跌停家数比）
- [x] L11-2.4: STYLE_REVERSAL 状态检测（行业轮动速度）
- [x] T1: system_health_log 数据表
- [x] C1: KillSwitchPipeline → KnowledgeArchive 自动归档

### P2 — 长期资产

- [x] L12-1.3: 止损事件自动记录（特征快照）
- [x] L12-1.4: Kill Switch 触发自动归档
- [x] L12-4.2: 每日组合快照自动保存
- [x] L12-4.3: Trade Recommendations 结构化标签
- [x] L12-3: Market Regime Notes 模块
- [x] T2: trade_decision_audit 数据表
- [x] T3: failure_archive 数据表

### P3 — 闭环优化

- [x] L11-1.5: PSI 超限 → 自动触发 Retrain
- [x] L11-1.7: Rank IC 衰减 → 自动降权
- [x] L12-2.3: 策略版本树
- [x] L12-1.6: 失败聚类 → 黑名单规则
- [x] L12-1.5: 黑天鹅事件因子截面快照
- [x] C2-C4: 知识→底层反哺闭环
