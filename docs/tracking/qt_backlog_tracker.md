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

### #5 因子失效应对 ⭐⭐⭐⭐⭐ 最紧迫
- **证据**: `qp factor health` — 28 因子中 12 DEGRADED + 11 WEAKENING；10 因子模型 9 个近期反向（Momentum_3M ic_30d=-0.21、Amplitude_5D=-0.25），仅 Volatility_20D 健康（+0.25）；Optuna OOS IC 负（-0.0444）
- **价值**: 决定生产策略（mvF）是否逆风；策略池扩容前提
- [ ] mvF 生产策略 5 因子滚动 IC 健康度
- [ ] 关键失效因子 OOS 验证（qp factor validate），区分真失效 vs 窗口噪音
- [ ] 因子失效诊断报告入 Obsidian
- [ ] 决策：调方向 / 降权 / 换池 / 等 regime

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

## 关联

- 架构导航: `docs/ai/PROJECT_MAP.md`
- 镜像笔记: Obsidian `1-Projects/qt项目待办.md`
- 相关整改: Obsidian `1-Projects/qt宪法合规整改.md` / `docs/constitution/rule.md`
