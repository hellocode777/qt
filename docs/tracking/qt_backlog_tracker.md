# QP 项目待办追踪 / QP Backlog Tracker

> 创建: 2026-08-13 | 来源: Hermes 讨论「qt 项目还有什么可做」+ Obsidian `1-Projects/qt项目待办.md`
> 项目现状: 12 层架构已完整（359 源文件 / ~77K 行 / 1488 测试），框架层饱和；剩余为「已规划未落地」项

---

## 总体判断

架构层基本完成。可做的事集中在 **4 个已规划未落地项 + 2 个方向性探索**。
每项标注证据来源（TDR/tracking/TODO 注释），勾选状态与 Obsidian 待办同步。

---

## 待办清单

### #1 Optuna 超参优化落地 ⭐ 推荐先做

- **证据**: `docs/tdr/TDR-005-optuna.md` — 「已规划但非默认，常规实验用固定参数 + Purged CV」
- **价值**: 直接提升模型质量；walk-forward/OOS/regime 验证的地基
- **成本**: 中
- **涉及**: `qp/research/trainer/lgb_rank.py`, `docs/tdr/TDR-005-optuna.md`

- [ ] 读 lgb_rank.py + TDR-005，出集成方案
- [ ] 接入 Optuna 搜索（num_leaves / learning_rate 等）
- [ ] walk-forward + Purged CV 验证
- [ ] 与固定参数基线对比，记录结果

### #2 文档重建收尾

- **证据**: `docs/doc_rebuild_tracker.md` 停在 Phase 1；architecture.md / module_overview.md / workflow.md / developer_guide.md / api.md 全缺失
- **价值**: 工程完整度（不改变策略结果）
- **成本**: 低

- [x] 从 ADR + DP 合成 architecture.md → ✅ 2026-08-13（docs/architecture.md，含 12 层 + 铁律 + ADR 索引）
- [x] 生成 module_overview.md / workflow.md → ✅ 2026-08-13（docs/module_overview.md + docs/workflow.md）
- [x] 生成 developer_guide.md / api.md → ✅ 已存在（8/1，511 行 / 435 行，tracker 过时）
- [x] 补全 ADR-001~030 空文档 → ✅ 2026-08-13 已全部补全（每份含上下文/决策/实现状态/验证，tracker 过时）

### #3 WebUI 图表系统重构

- **证据**: `docs/tracking/chart_system_implementation.md`「规划中」，Step 1 未完成——daily_nav.parquet 缺 benchmark 曲线、日收益率、回撤序列
- **价值**: 可视化体验
- **成本**: 中

- [x] Step 1: `qp/pipeline/multifactor_pipeline.py` `_compute_backtest()` 加 benchmark/drawdown 列 → ✅ 2026-08-13 复核：已实现
- [x] Step 2: Service 层封装（router 不直接读 parquet）→ ✅ 2026-08-13 复核：experiment_service.py 已有全部方法
- [x] Step 3: cockpit.js 图表模块化 → ✅ 2026-08-13 复核：QPCharts 导出 EquityCurve/DrawdownChart
- [x] Step 4: 修复实验页面图表 bug → ✅ 2026-08-13 复核：Canvas + equity_json 注入已落地

> 📌 2026-08-13 复核：规划文档（8/4）过时，4 个 Step 在后续开发中已全部实现。

### #4 策略自动发现

- **证据**: `qp/pipeline/daily_pipeline.py:375` TODO — 「auto-discover validated strategies from ExperimentTracker」，当前策略手动注册
- **价值**: 架构一致性
- **成本**: 低

- [x] 从 ExperimentTracker 自动发现 APPROVED 策略 → ✅ 2026-08-13 复核：已实现（Registry 自动发现链路）
- [x] 替换手动注册逻辑 → ✅ 已实现（multifactor_pipeline:792-839 Gate 通过自动注册 + qp strategy approve 人工批准）

> 📌 2026-08-13 复核：TODO 注释过时——实验 Gate 通过 → 自动写 Registry（RESEARCH）→ `qp strategy approve` → APPROVED → daily_pipeline 自动发现执行，完整闭环已工作（当前 momentum_vol_full 为唯一 APPROVED）。本次仅清理过时注释。

---

## 待办清单（2026-08-13 更新 — 已规划项全部清零）

### #5 因子失效应对 ⭐⭐⭐⭐⭐
- **证据**: `qp factor health`（2026-09-18 快照）— 28 因子中 **17 DEGRADED** + 1 WEAKENING；8/13 首轮曾显示 12 DEGRADED + 11 WEAKENING
- **价值**: 决定生产策略（mvF）是否逆风；策略池扩容前提
- [x] mvF 生产策略 5 因子滚动 IC 健康度 → ✅ 2026-08-13 首轮 + **2026-09-19 复检**（多窗口 + 4 分窗表）
- [x] 关键失效因子 OOS 验证（`qp factor validate`），区分真失效 vs 窗口噪音 → ✅ **2026-09-19**：全历史 t=17.2–35.3；分窗 2019-2021/2022-2023/2024-2025/2026YTD **5 因子全部同符号显著**；近 30 日弱值落在自身噪声带内
- [x] 因子失效诊断报告入 Obsidian → ✅ 2026-08-13 [[技术深挖/因子失效诊断报告-20260813]] + **2026-09-19 [[技术深挖/因子失效诊断报告-20260919]]**
- [x] 决策：调方向 / 降权 / 换池 / 等 regime → ✅ **维持原版不动**（8/13 决定，9/19 二次确认；替换实验负结果原版超额 +15.82% 最高）

> 📌 **2026-09-19 复检结论**（本次）：
> - 全历史 `qp factor validate`：Amplitude_5D t=23.12 / Volatility_20D t=19.53 / Momentum_3M t=17.66 / Volume_Concentration t=35.30 / Volume_Trend_10D t=17.17 → 全部 ≥4/5 过（唯一未过项 `IC>0%≥50%` 对 direction=-1 因子结构性不适，见 §#14）
> - 分窗稳定性：5 因子在 4 个窗口全部同符号且显著（|t| ≥ 3.4），无方向反转 → **无因子真失效**
> - 近 30 日弱值（Volatility_20D +0.0162、Amplitude_5D −0.0282）**落在自身 30 日噪声带 ±0.056~0.063 内**（日 IC σ≈0.16，SE=σ/√30）
> - Volume_Trend_10D 近 30 日 ic_30d=−0.074（t=−4.4）反而是 5 因子中最强之一 → 8/13 的 ic_30d=0 属窗口噪音
> - 生产影响澄清：`factor_health.recommended_action`（含"建议降权 50%"）**只有展示层消费**，不自动改权重；自动降权走策略级 retrain signal（2026-09-19 已修，见 §#13-3）
> - 复现：`scripts/research/factor_decay_window_diagnosis_20260919.py`

### #14 因子健康判定规则修正 ⭐⭐⭐⭐（2026-09-19 完成，含一处被实测推翻的初始假设）

- **初始假设（部分被实测推翻，如实记录）**: 判定阈值 `decay_slope=-0.001/day` 与 60 日斜率的噪声同量级（σ≈0.0011–0.0013/day）→ 曾怀疑 degraded 泛滥用是噪声误判
- **实测（用真实日 IC 序列，28 因子）**:
  - 只加 1σ 门禁时 **stage 零变化** → 越线者的斜率通常 3σ+（Volatility_20D −0.00526±0.00235，t=−2.24），**不是噪声**；门禁保留（对齐 P1-3 策略级口径，无害）
  - **真 bug ①（计数语义）**: `_count_consecutive_degraded` 把当前标量（60 日斜率 / 全历史 IC_IR）当逐日条件 → 实测计数 = **2822/2822 天**，「连续 30 天」保护形同虚设 → 改按 trailing 30 日均值序列计数（实测降到 0–43）
  - **真 bug ②（方向语义，本次最实质）**: 衰减用**带符号 IC** 计算 → 对 40% 的 direction=−1 因子「IC 更负 = 信号增强」被误判为衰减（实例：Implied_Net_Flow ic_30d=−0.059 强于 ic_90d=−0.016，却因斜率 −0.00267 被判 DEGRADED）→ 改为按 **|IC|** 计算衰减
  - **口径改进（已原型化，最终未采用）**: 曾加「显著衰减 + 90 日 IC 仍显著 → WEAKENING（25%）」的中期对照；实测它无法只凭 IC 序列与真衰减区分，且与既有语义冲突（`tests/unit/test_factor_health.py` 的 `test_degraded_low_ic_ratio` / `test_decay_trend_degraded` 期望「IC 大幅下滑 → 降级」）→ **撤销**，留作待评估建议
  - **连带修正**: WEAKENING 的旧前置 `consecutive_degraded >= 15` 在计数修好后会整体压制 weakening（旧计数恒真才显得可用）→ 改由斜率显著性承担
  - **validate 门禁修正**: `IC>0% ≥ 50%` → 「同向占比 ≥ 50%」（按 expected_direction 换算）；实测 Amplitude_5D 31.3% → 同向 68.7%，**4/5 → 5/5**
- **实测效果（28 因子，最终规则）**: degraded 15→**15**、weakening 10→8、validated 3→5 —— 判定**稳定不震荡**；真正改变的是语义正确性（连续计数 2822 → 0–43；消除「信号增强被判衰减」的误判；validate 由 4/5 → 5/5）
- **已知局限（未改）**: 衰减只看 trailing 60 日窗口 → 对「台阶式下跌」（衰减发生在窗口之外）不敏感，只对渐进衰减有效
- **对照脚本**: `scripts/research/factor_health_significance_gate_compare_20260919.py`
- [x] 因子级 decay 判定加显著性门禁（1σ，可关闭）
- [x] `validate` 的 IC>0% 判定改方向调整口径
- [x] 回归测试 10 项（`tests/unit/test_factor_health_significance_gate.py`：计数不再等于全历史 / |IC| 上升不判衰减 / 弱因子仍 degraded / 中期显著→25% vs 50%）

### #6 策略池扩容 ⭐⭐⭐⭐（依赖 #5，已解除）
- **证据**: mvF 唯一 APPROVED；lvr_vol_mom1m（research）、lvr_vol_only（backtest_passed）待提升
- **候选（2026-08-13）**: lvr_vol_only — IC=0.054, Sharpe=1.52, MaxDD=9.7；8/8 曾被批准 fa42821，backtest_passed 是 8/11 bug 残留
- [x] 选定候选 lvr_vol_only（低波单因子，与 mvF 真分散化）
- [x] Paper Trading 启动 `pt-8b63c05c`（0/30 天，与 mvF pt-bb27fc9d 并行）
- [ ] 30 天后 evaluate() → APPROVED → 记录第二个生产策略

### #7 实盘闭环验证 ⭐⭐⭐
- **证据**: ADR-032 现金账本已建，无证据走通完整周期
- [x] ✅ 2026-08-13 验证完成：闭环实际走通（8/8 建仓 6 只 → 8/12 人工审核执行 3 SELL → 现金回流）
- [x] get_account_summary 核对：cash 51,186 + 持仓 49,371 = 100,557；realized 557.00 与平仓盈亏一致；决策包 human_review 状态 closed

### ⏳ 进行中
- Paper Trading 30 天验证 `pt-bb27fc9d`（0/30 天，8/11 启动，每天 `qp paper status`）

### #8 跌停博弈微观结构研究 ⭐⭐⭐⭐⭐（2026-08-13 完成）
- **背景**: R1-R5 定位反转 Alpha 衰减根因 = 跌停样本腰斩 + 修复变薄，本文回答「为什么」
- **结论**: **跌停从「情绪性错杀」变成「信息性下跌」**——同样恐慌环境下跌停频率 -72%（627→178/千股）；跌停后 1 日 +3.97%→-1.65%；20 日 P99 +468%→+81%；跌停日量比 0.96→1.41（放量博弈）+ 次日打开 79%→86% 但打开后不修复；非恐慌月个股跌停修复 +69.7%→+7.8%
- **脚本**: `scripts/research/limit_down_microstructure_s1~s3.py`
- **报告**: Obsidian `技术深挖/跌停博弈微观结构研究-20260813.md` + skill reference `alpha-decay-r1-r5-study.md` R6 节
- **生产含义**: mvF 维持原版；交互项 w≈0.05 仍最有希望；反转 Alpha 容量结构性收缩
- [x] 全部完成（s1/s2/s3 + 报告 + skill 沉淀）
- [x] Future Work: join fundamentals 验证「跌停股更多基本面差/退市风险」 → ✅ 2026-08-13：相对恶化扩大但全市场同期也恶化（confounder），部分支持

### #9 行业热度 × AI 能力 ✅ 阶段 1 完成（2026-09-10）

- **证据/详情**: `docs/tracking/industry_heat_ai_feasibility.md`（含 §7 五项避坑发现）
- **结论**: 已落地。热度 = 行业聚合（纯统计，**不需要 AI**）；AI 解读层不做（对选股无直接作用 + 不进因子）
- **完成情况**:
  - [x] 决策：「热度」用**双口径** —— 行情（涨幅/成交额/上涨占比，数据最新）+ 资金流（主力净流入，数据滞后，如实标注）
  - [x] 决策：只做对选股有影响的部分；AI 层不做
  - [x] 1.1 行业分类 → ⚠️**换方案**：东财不可达，改用 **baostock 证监会行业**（5216 只 / 84 类 / 覆盖 ~94%，替换掉覆盖仅 ~39% 的名称关键词分类）
  - [x] 1.2 热度聚合 → `qp/research/industry_heat.py`（双口径 + N 日窗口 + min_members 小样本过滤）
  - [x] 1.3 CLI → `qp industry heat [--source price|capital_flow] [--granularity csrc|subsector|sector] [--window N]`
  - [x] **接入选股**：`~/.hermes/scripts/stock_morning_report.py` 输出带「行业 + 当日热度 + 排名」，行业逆势时显式警示
  - [ ] 1.4 SPA 卡片
- **关键发现**（详见文档 §7）: `volume` 单位是「手」(×100 才是股)；parquet 的 `turnover` 列语义不明（已排除出聚合）；新浪限流严格（已加 0.3s 间隔 + 退避重试 + 熔断）；**`--quick` 会覆盖整个 parquet**（事故，已从缓存重建恢复）；东财本机不可达
- **遗留**: 资金流数据停在 2026-08-14（抓取停了一个月），全量更新受限流阻塞 → 需分批慢跑；无「半导体/CPO」等**主题粒度**（证监会行业是国民经济大类）

### #10 实时 IC 假 STALE → 平台误停 ✅ 根因已修（2026-09-11）

- **证据/详情**: `docs/tracking/rolling_ic_false_stale.md`
- **现象**: 9/10 起系统状态 PAUSED；9/11 18:00 daily_pipeline 被 Step 0 拦住，连续两日无 DecisionPackage（邮件只发占位符）
- **根因**: `rolling_ic()` 实际只用 ~5 只股票算 Spearman（单日 SE≈0.45），得到 0.0023 → 撞上 `absolute_min_ic=0.005` → STALE → PAUSED；同口径全横截面 IC = **+0.077（t=+5.3）**，模型并未衰减。随机打分有 97.3% 概率被判 STALE
- **连带**: PAUSED 挡住唯一写信号历史的 Step 10.5 → 指标冻结 → **不会自愈**（死锁）
- **完成**:
  - [x] 复现 + 样本量/噪声验伪 + 全横截面金标准交叉验证
  - [x] `rolling_ic()` 加数据充分性门槛（≥10 贡献日、每日中位 ≥300 只），不足返回 `None`（不可测）
  - [x] 回归测试 3 项 + ruff/pyright 全仓 0 + monitoring 163 测试全过
  - [x] 端到端验证 action `pause_buy → watch`；commit `b507576` 已 push；scheduler 已重启
- **遗留**:
  - [x] P1-1 ✅ 2026-09-11 落地：信号历史改落全横截面抽样（头 200 + 中段 100 + 尾 200 = 500/日）；真机验证 rolling_ic(20) 由 -0.0023（不可测）→ **+0.0502（可测）**，贡献日 19 / 中位样本 500。见 §5.1
  - [x] P2-1 ✅ 随 P1-1 修掉：`_save_signal_snapshot` 改为按 `(strategy_id, date)` 覆盖写（幂等）
  - [x] P1-2 ✅ 2026-09-11 修复：PAUSED 改为「只跑记录链路」到 Step 10.5 才早退（沙盒 e2e：记录跑通 + data/decisions 零变动）
  - [x] P1-3 ✅ 2026-09-11 修复：IC 衰减判定加标准误门禁（点估计 + 1σ 仍低于边界才判 STALE/DECAYING，否则 NOT_MEASURED）
  - [x] P1-4 ✅ 2026-09-11 修复：状态机 fail-open → fail-safe（数据读不到时 OK 不再降级状态）；沙盒复刻验证通过
  - [x] P1-5 ✅ 2026-09-11 修复：conftest 把监控路径重定向到 tmp + session 级守卫；4 个 logger/状态类默认目录改为调用期解析；验证后生产 data/monitoring 13 文件 md5 未变
  - [x] P2-2 ✅ 2026-09-11 修复：PSI epsilon 尺度错误（实测 15.529 → 5.395）+ 样本充分性门禁 + 只在 universe 抽样上计算；重复实现删除，委托 DriftMonitor
  - [x] P2-3 ✅ 2026-09-11 修复：新增 DecayStage.NOT_MEASURED；默认值不再自称 healthy；WebUI decay_stage_label（缺失/未知 → 不可测）

---

## 待办清单（2026-09-14 更新）

### #11 WebUI 持仓页「盈亏」恒为 0 —— 字段口径错配 ✅ 根因已修（2026-09-14）

- **现象**: `/proto/positions` 活跃持仓「盈亏 / 盈亏%」两列恒显示 `0.00 / 0.00%`；Dashboard「浮动盈亏」列同（column title 写的是"浮动"，数据却是已实现）
- **根因**: 前端绑定 `positions.parquet` 的 `pnl`/`pnl_pct`，而这两个字段是 **已实现盈亏** —— `Position.realized_pnl` 仅在 `status == CLOSED and exit_price > 0` 时非零，`pnl_pct` 仅 `close()` 时赋值；HOLDING 行永远是建仓默认值 0，被当作测量值展示（违反 WebUI 铁律：默认值不得伪装成测量值）
- **二级 bug**: `pnl_pct` 语义是**小数**（0.0211 = +2.11%，见 `Position.close()` 与 `Simulation.vue` 的 `*100`），`Positions.vue` 直接 `toFixed(2) + '%'` → 历史行少 100 倍（0.02%）
- **修复**:
  - [x] `qp/web/routers/api_v1.py` `/api/v1/positions` 增加标记到市价字段：`latest_price / quote_date / latest_suspended / market_value_latest / unrealized_pnl / unrealized_pnl_pct`（数据源 `daily_price_latest.parquet` 最后一个 trade_date 收盘价；`_latest_quotes_cached` 缓存键含 `mtime_ns`，数据更新自动失效；无行情/停牌 → `None`，不回落为 0）
  - [x] SPA `Positions.vue` / `Dashboard.vue`（源码 `qp/web/spa_src/`，2026-09-14 从 `~/workspace/quant-ui-research/qp-proto/web` 移入入库）：活跃行用标记值、历史行用已实现值，`pnl_pct` 统一 ×100；新增「最新价 / 平仓价」列与口径脚注
  - [x] 验证：`curl /api/v1/positions?active_only=true`（600207→5.10/510.00/+60.00/+13.33%）+ headless Chrome 真实 DOM 渲染两视图（活跃视图同上；历史视图 P-00006 → +2.11%）；ruff format --check / ruff check / pyright 全 0
  - [x] `bash scripts/spa_deploy.sh` 重建并部署（`/proto/` 已引用新 bundle）
- **遗留**:
  - [ ] 未计佣金/印花税/滑点（与老 UI `/portfolio` 同口径）；要精确持仓收益需接交易成本模型
  - [ ] `/api/v1/account` 的 `index.json.active_value` 仍为成本市值（`PositionLedger.total_active_value()`），与页面标记值不同源
  - [x] SPA 源码已入库：2026-09-14 从无版本控制的 `~/workspace/quant-ui-research/qp-proto/web` 移入 `qp/web/spa_src/`（`node_modules`/`dist` 与构建产物 `qp/web/static/spa/` 仍 .gitignore），`scripts/spa_deploy.sh` 默认路径随之改为仓库内

---

## 待办清单（2026-09-14 第二轮）

### #12 持仓盈亏计费用 + 账户口径同源 ✅ 已完成（2026-09-14）

- **背景**: #11 的两条遗留 —— (a) 盈亏未计佣金/印花税/滑点；(b) `/api/v1/account` 的
  `index.json.active_value` 是成本市值，与页面按最新收盘标记的市值不同源（同一页面两个"总权益"）
- **完成**:
  - [x] 新增 `qp/web/services/position_service.py`：**唯一**估值实现，三套显式口径 ——
        `cost`（entry×shares，= `PositionLedger.total_active_value` / `index.json.active_value`）、
        `mark`（最新收盘×shares）、`fees`/`net`（`CostModel` 估算：买入=佣金+滑点；卖出=佣金+印花税+滑点）；
        行情缓存键含 `mtime_ns`（数据更新自动失效）；无行情 → `None`（显示 —，不回落 0）；
        账户视图标 `n_fallback_cost` / `fallback_symbols`（无行情行回落成本，显式计数）
  - [x] `/api/v1/positions` 增 `est_buy_fee`/`est_sell_fee`/`est_round_trip_fee`/
        `unrealized_pnl_net(_pct)`（活跃）/`realized_pnl_net(_pct)`（已平仓）+ `meta.fees` 费率元数据
  - [x] `/api/v1/account` 增 `valuation`（cost/mark/realized/fees 三口径），前端不再本地重算
  - [x] 老 UI 同源：`routers/portfolio.py`（市值/盈亏/费后列 + 账户卡标注成本口径）、
        `routers/dashboard.py`（账户卡加"账户总资产（最新收盘）/成本口径/浮动盈亏 毛·费后"）
  - [x] SPA：持仓页加「净盈亏(费后)」列（tooltip 拆费用、页脚列费率与未计项）、总览页 KPI 卡改用服务端口径
  - [x] 顺带修同类缺陷：`api_v1` 的 `json_load(account.json / index.json / 两个 registry / stock_names)`
        文件缺失时直接 500 → 新增 `_json_or_empty()` 降级为空 dict（运行产物在新机器上本就不存在）
  - [x] 验证：新增/更新 9 项测试（`tests/unit/web` 20 项全过）；ruff format --check / ruff check / pyright 全 0；
        真机 curl + headless Chrome DOM：持仓页 600207 毛 +60.00/+13.33% → 净 +58.55/+12.99%（费 ¥1.45）、
        总览页 总资产 ¥100,408（= 现金 99,504 + 最新市值 904；成本口径 839）、浮盈 ¥65.00 → 费后 ¥62.37、
        已实现 ¥343.00 → 费后 ¥−33.38；老 UI `/` 与 `/portfolio` 同步显示
- **数据结论（用户可见）**: 小额持仓被费用吃掉 —— 13 笔平仓毛 +¥343、估算费用 ¥376 → 费后 **−¥33**；
  两只在持仓位毛 +¥65（+7.75%）→ 费后 +¥62.37（+7.42%）
- **遗留（待用户决定）**:
  - [ ] 记账回滚行（`exit_reason=rollback_wrong_size`，entry=exit 且 pnl=0，共 5 笔）实际未成交，
        但费用估算按"都成交"计 → 汇总费后被高估约 ¥289：是否按原因串排除？
  - [ ] 券商最低佣金（常见 ¥5/笔）与过户费未建模 —— 小额单（¥450 级）真实费用远高于估算，是否加可配置项？
  - [ ] `MarketImpactModel.compute_adv()` 的 volume 单位：日线 `volume` 单位是**手**，
        而 `compute_adv` 用 `close*volume` 当成交额 → ADV 低估 100× → 冲击成本估算**高估 10×**
        （实测 1 万元单：600207 ¥5.47 vs 修正后 ¥0.55；600930 ¥2.54 vs ¥0.25），
        并让 10%-ADV 流动性惩罚提前 100× 触发。影响 `daily_pipeline` Step 11 的
        `estimated_cost_pct`（进决策包 markdown / portfolio_snapshot）—— 生产路径，待批准后修（一行 ×100）

---

## 统一接口候选（2026-08-27 扫描，仅记录未实施）

> 背景：时间接口已统一（`qp/shared/time.py`，commit fb8d00b）。以下 4 处为同类"散落多点、值得收编"的横切关注点。

### C-1 路径常量 ⭐ 推荐先做
- 现状：`data/` 字符串硬编码 **153 处 / 87 文件**（data/dataset、data/experiments、data/decisions、data/paper_trading、data/monitoring、data/knowledge 等）
- 方案：`qp/shared/paths.py` 统一常量 → 改目录位置只动一处
- 成本：中（机械替换为主）

### C-2 JSON 读写封装
- 现状：`json.dump` 58 处 + `json.load` 60 处 / 50 文件
- 方案：`json_save()/json_load()`（统一 ensure_ascii=False + indent=2 + 自动建目录）
- 成本：低-中

### C-3 strftime 格式收编
- 现状：56 处 / **10 种格式**（%Y-%m-%d 29、%Y%m%d 10、%Y%m%d_%H%M%S 5...）
- 方案：并入 `qp/shared/time.py`（format_cn / format_ts_file 等）
- 成本：低，价值低-中（格式各有用途）

### C-4 print() 残留甄别 ✅ 已完成（2026-08-27，0 处违规）
- 现状：print( 调用 1048 处 / 59 文件
- **甄别结论**：896 处 CLI 命令（用户输出，合理）+ 116 处 research 诊断（工具输出，合理）+ 36 处核心库 = **30 处 docstring 示例 + 4 处豁免注释（alerts 兜底/tencent 进度条）+ 2 处 __main__ smoke test → 实际违规 0 处**
- rule.md No print 硬规则已被 P0 清理执行到位，核心库无违规
- 处置：无需代码改动；新增 print 时保持规则（CLI/诊断/豁免注释外一律 logger）

**已统一无需动**：seed（DEFAULT_SEED 引用 17 处）、mkdir（exist_ok=True 78 处）、env（仅 9 处）

---

## 待办清单（2026-09-19 更新 — 项目巡检四项修复）

> 来源：2026-09-19 项目巡检（`qp doctor` / `qp monitor check` / 数据新鲜度实测 / git 状态）。
> 架构与运行时整体健康（Action=OK、Regime=RANGING、Health 84、数据到最新交易日），
> 以下 4 项为巡检发现的「静默错误」，均已修复并验证。

### #13-1 指数数据静默过时 ⚠️ 已修（2026-09-19）

- **现象**: `data/dataset/index_csi300.parquet` 最新交易日停在 **2026-08-20**，缺 8/21–9/18 共 20 个交易日；`index_sh000001.parquet` 同
- **根因**: `qp/data/dataset/index_provider.py:fetch_index_data()` 的逻辑是「本地文件存在就直接 return」→ 首次落盘后再不会被更新（不是网络问题）
- **影响面（区分清楚，避免误判）**:
  - `multifactor_pipeline._load_index_data()` → 策略侧 **market filter（MA20/MA60 大盘过滤）/regime 检测**实际消费的是滞后 20 个交易日的指数
  - daily_pipeline 决策包里的 regime **不受影响**：它用 `_build_index_df(price_data)`（全市场收盘均值合成代理指数，随行情每日更新）
- **修复**:
  - [x] `fetch_index_data()` 增加新鲜度判定：本地最新 `trade_date` 距今天 ≤ `DEFAULT_MAX_AGE_DAYS`(7) 才复用，否则重抓；新增 `latest_local_date()` 辅助函数
  - [x] 抓取失败但本地有旧数据 → **raise 明确错误**（含旧数据日期），不覆盖、不假装成功
  - [x] `_load_index_data()` 消费侧：过时先刷新；刷新失败回退旧数据并 WARNING 携带滞后天数（不静默）
  - [x] `qp data index` CLI 打印 `latest trade_date` + 两个指数文件的新鲜度（OK/STALE），并支持 `--symbol=`
  - [x] 实测补拉：两个指数 2026-01-05 → **2026-09-18**（260 天滚动窗口，174 个交易日，gap 仅春节/五一）
- **遗留观察**: 滚动窗口只有 ~174 个交易日 < `MarketRegimeDetector.min_history=200` → 该指数**不能**独立支撑 regime 检测（detect() 会返回「数据不足」默认值）；这是窗口设计，不是 bug

### #13-2 PSI 不可测却显示 `0.000` ⚠️ 已修（2026-09-19）

- **现象**: `qp monitor check` 打印 `PSI: 0.000`，实际日志明确 `psi_available=False`（样本不足）→ 不可测被渲染成「测量值 0」，绿色读作「无漂移」（违反 WebUI/监控铁律：默认值不得伪装成测量值；同类问题 P2-3 修过 decay，PSI 漏了）
- **修复**:
  - [x] `qp/platform/cli/commands/monitor.py`：`psi_available=False` → 打印「不可测 / not measured (样本不足，非 0)」
  - [x] `qp/platform/cli/commands/scheduler.py`：日志行 `psi=n/a`（原 `psi=0.000`）
  - [x] `qp/monitoring/kill_switch_pipeline.py`：归档/邮件摘要 `**PSI**: 不可测 (n/a)`
  - [x] `qp/web/templates/components/strategy_health.html`：PSI/rolling_ic 均按 `*_available` 分支，不可测显示「不可测」（`health.html`/`dashboard.html` 原本已正确）

### #13-3 retrain signal：行数上限冒充日期窗口 + 每日重复告警 + 假 PSI 驱动降权 ⚠️ 已修（2026-09-19）

- **现象**: scheduler 每天打印 `retrain_signals: 70 actionable`，条目重复（momentum_vol_full×2 + unknown×3，全 `[PSI_DRIFT]`）
- **根因（三层，逐层实证）**:
  1. `RetrainSignalLogger.load_history(days)` 实现是 `head(days * 10)` —— **行数上限，不是日期窗口**。7 天窗口 = "最新 70 行"，`70` 正是该上限被当成 actionable 计数上报
  2. 告警无「已通知」状态 → 同一批未处理信号在滚出窗口前**每天重复发邮件**（9/12–9/18 重复同一批 9/11 信号）
  3. **更严重**：`retrain_signals.parquet` 里 66 行 `PSI_DRIFT` 的 `psi_value` 为 **4.22–22.32**（P2-2 已确认修复前 PSI 实现产出假值 15.529），被 `daily_pipeline` Step 9 的 `load_weight_scales` 消费 → momentum_vol_full **9/2–9/11 被降权至 0.85**，并把 `strategy_exposure_scale`（组合总敞口）一并压到 0.85
- **修复**:
  - [x] `load_history(days, limit=None)` 改为**按信号日期过滤**（`date >= today - days`），行数上限只作为可选 `limit`
  - [x] `scheduler.job_retrain_notify`：只对「比上次通知时间更新」的信号发信（状态文件 `data/monitoring/retrain_notify_state.json`），无新信号时打日志不发邮件；`job_monitor_check` 打印带上窗口最新日期
  - [x] `load_weight_scales` 增加防御：`trigger=PSI_DRIFT` 且 `psi_value >= 1.0`（阈值体系 0.10/0.25）判为不可信 → 跳过并 WARNING，不据此降权
  - [x] 数据修正：`scripts/maintenance/purge_implausible_psi_signals_20260919.py` —— 全量备份 `retrain_signals_archive_20260919.parquet`，移除 66 行假 PSI（198 → 132 行；剩余 132 行是 8/02–8/11 的 `IC_DECAY` 空名信号，早已出窗且代码本就忽略空 strategy_name）
  - [x] 实测：`load_weight_scales(['momentum_vol_full'])` → **1.0**（降权已解除）
- **遗留**: `strategy_name="unknown"` 的信号无语义（来自 report 无策略上下文的运行）；生成侧 P2-2 修复后已不再产生，未额外改动

### #13-4 ADV 单位错（volume 是「手」）影响 3 处实现 ⚠️ 已修（2026-09-19）

- **现象/证据**: 日线 `volume` 单位是**手**（1 手 = 100 股）。实测 600519 @2026-09-18 `close=1257.12, volume=24891`：按股算成交额 ¥3,129 万（不合理），按手算 ¥31.3 亿（符合茅台量级）
- **影响面（原 tracker #12 只记了第 1 处，本次审计发现 3 处同源）**:
  1. `qp/portfolio/cost_model.py:MarketImpactModel.compute_adv()` → ADV 低估 100× → 冲击成本高估 10×（`sqrt(100)`），且 10%-ADV 流动性惩罚提前 100× 触发 → 进 `daily_pipeline` Step 11 `estimated_cost_pct`
  2. `qp/portfolio/exposure/liquidity_exposure.py:_compute_adv()` → ADV 低估 100× → `liquidity_score` 被系统性压低（`log10(adv)/10` ⇒ −0.2），阈值 50M/200M 判级同样失真
  3. `qp/portfolio/portfolio_risk_engine.py:_compute_advs()` → 同上，影响 Layer 7 风控候选
- **修复**:
  - [x] `qp/shared/constants/__init__.py` 新增单一来源 `SHARES_PER_LOT = 100.0`（附单位说明），三处统一引用
  - [x] 三处公式改为 `close × volume × SHARES_PER_LOT`，docstring 标注「手 → 股」
  - [x] 测试：`compute_adv` 值断言、`sqrt_impact` 小额单不再触发流动性惩罚、两处 ADV 单位断言
- **遗留（待决定，与 #12 同源）**: 券商最低佣金 ¥5/笔、过户费未建模；回滚行（`exit_reason=rollback_wrong_size`，实际未成交）费用被高估约 ¥289

### 质量门禁（2026-09-19）
- [x] `uvx ruff format --check .` → 473 files already formatted；`uvx ruff check .` → All checks passed
- [x] `uv run pyright` → 0 errors, 0 warnings, 0 informations（注意：`uvx pyright` 找不到 .venv，会假报 ~692 个 reportMissingImports）
- [x] 全量 `pytest -q` → exit 0（基线 1768 passed；本次新增/更新 9 项测试）

---

## 关联

- 架构导航: `docs/ai/PROJECT_MAP.md`
- 镜像笔记: Obsidian `1-Projects/qt项目待办.md`
- 相关整改: Obsidian `1-Projects/qt宪法合规整改.md` / `docs/constitution/rule.md`
