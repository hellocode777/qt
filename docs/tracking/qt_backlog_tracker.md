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

- [x] 读 lgb_rank.py + TDR-005，出集成方案 → ✅ 2026-08-13 完成（tracker 过时）
- [x] 接入 Optuna 搜索（num_leaves / learning_rate 等）→ ✅ 已实现：`qp/research/trainer/optuna_search.py`（329 行）+ CLI `qp experiment optuna`（参数由函数内手工解析，故 `--help` 只显示 `--help`，非缺陷）
- [x] walk-forward + Purged CV 验证 → ✅ **2026-09-19 完成**：Purged CV 本已实现（目标函数即 PurgedKFold），本轮补齐**时间序 walk-forward**验证 → **best 参数无稳定优势，`DEFAULT_LGB_PARAMS` 不动**（详见下方 §#1-a）
- [x] 与固定参数基线对比，记录结果 → ✅ 内置 ΔIC 对比：8/13 结果见 `data/optuna/lgb_optuna_20260813_011526.json`（30 trials，best −0.0444 vs baseline −0.0572，改善约 22%）

> 📌 **2026-09-19 复核**：模块 / CLI / 结果文件 / 测试（`tests/unit/research/test_optuna_search.py`）均在位，本节 4 项中 3 项早已完成（tracker 过时）。**只剩「最优参数的完整 walk-forward 验证」**——这一步会决定是否调整生产模型参数（production-sensitive，需批准）。

#### #1-a 时间序验证（2026-09-19 进行中/已建能力）

- **核实发现**：`WalkForwardScorer` 内部**硬编码** `DEFAULT_LGB_PARAMS` → 8/13 搜出的 best 参数**没有任何入口可验证**，也从未进过生产；`qp experiment optuna` 用的是 **PurgedKFold（随机折）**，不是时间序外推（TDR-005 要求后者）
- **已补能力**（commit `91b0340`，默认行为不变）：
  - `WalkForwardScorer(lgb_params: dict | None = None)` —— 两处训练点改为
    `{**DEFAULT_LGB_PARAMS, **(lgb_params or {})}`；+4 项测试
  - `scripts/research/optuna_params_walkforward_validate_20260919.py` —— 复用
    `qp experiment optuna` 的数据组装（同样本同标签），做 expanding-window
    时间序验证（train ≤ N 年 → test N+1 年），baseline 与 best 各训一次
  - **评估口径用 |IC|**：A 股价量因子 IC 为负属正常（`direction=-1`），带符号比较
    会把「变差」读成「改善」（与 §#14 的 |IC| 是同一类陷阱，当天第二次遇到）
- **抽样预跑结论（200 股）**：均值 |OOS IC| baseline **0.0428** vs best **0.0426**
  （Δ ≈ 0），best 胜出 **2/4** 年；而 best 的样本内 IC 明显更高（+0.0976 vs +0.0380）
  → **典型过拟合特征**，8/13 PurgedKFold 的「改善 22%」是随机折偏乐观
- **全量结果（1500 股 / 2,153,113 行 / 4 个测试年）**：

  year | base \|OOS\| | best \|OOS\| | Δ\|OOS\| | best IS
  ---|---|---|---|---
  2022 | 0.0421 | 0.0500 | **+0.0079** | −0.0242
  2023 | 0.1130 | 0.0996 | **−0.0134** | −0.0258
  2024 | 0.0204 | 0.0291 | **+0.0087** | −0.0385
  2025 | 0.0409 | 0.0370 | **−0.0039** | −0.0254

  均值 \|OOS IC\|：baseline **0.0541** vs best **0.0539**（Δ **−0.0002**），best 胜出 **2/4** 年

- **结论：best 参数在时间序外推下无稳定优势 → `DEFAULT_LGB_PARAMS` 不动**。
  8/13 PurgedKFold 报的「改善 22%」是随机折偏乐观（与全量时间序结论矛盾），
  这正是 TDR-005 要求「完整 walk-forward 才能进生产」的意义
- **附带发现（影响面已核实）**：所有测试年的 OOS IC **均为负**（−0.02 ~ −0.11）→ 该
  ML 打分在时间序外推下与实现收益**反向**。`factor_processor` 把 `ml_scores` 直接写入
  `score`（**未取反**，见 `factor_processor.py:953-960`），但 `model_mode` **默认 False**
  （`multifactor_pipeline.py:135`、`experiment/models.py:62`）→ 仅影响
  `qp experiment run --model` 实验路径，**生产不受影响**（生产走因子加权 momentum_vol_full）
- 产物：`scripts/research/optuna_params_walkforward_validate_20260919.py`
  + `data/optuna/walkforward_validation_*.json`

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
- 回归测试（`tests/unit/test_factor_health_significance_gate.py`：计数不再等于全历史 / |IC| 上升不判衰减 / 弱因子仍 degraded / 渐进衰减端到端）

### #15 因子健康判定的归因口径与展示精度 ⭐⭐⭐（2026-09-19 完成分析 + 展示层修复）

**起因**: `Volatility_20D` 全历史 t=19.5、2026YTD t=+3.4，却因 60 日斜率显著被建议「降权 50%」——怀疑判定过激。

**结论（实测三层证据，原怀疑被否）**:
1. **不是过激判定**: `|ic_30d|` 的历史分位（ic_series 样本 2024-12 起）——`Volatility_20D` **12%** / `Volatility_60D` **12%** / `Volume_Price_Trend` **5%** → 当前水平已在历史底部，斜率显著为负是真实衰减
2. **「多窗口一致」判据被数据排除**: 120 日与 252 日 |IC| 斜率对 19 个因子**几乎全为正**（+0.0001~+0.0017）——长窗口斜率反映「全样本水平漂移」，不是近期衰减 → 原方案 B 撤销
3. **真问题是归因混杂**: 三类条件（IC_IR 低 / 60 日斜率越线 / |ic30|<0.02）任一触发即降级；`Implied_Net_Flow`（|ic30| 分位 91%、IC_IR=0.21）与 `MaxDD_60D`（分位 76%、IC_IR=0.13）被判 degraded 的原因是**历史一致性差**，不是当前衰减

**本次已修（展示层精度，判定逻辑未动）**:
- `weakening` 文案不再显示无意义的「持续 0 天」，改显示近 60 日 decay 与门禁阈值
- `degraded(IC_IR)` 文案改为 `IC_IR=0.297 < 0.3`（3 位小数），消除「0.30 < 0.3」的自相矛盾，去掉「持续 N 天」
- `degraded(decay)` 文案门禁阈值格式化（原为 `-0.00221909071710342`）

**已实施（2026-09-19，用户拍板「两个全做」）**:
- [x] **分层口径**: 主条件（60 日斜率越门禁 / IC_IR 偏低）1 条 → WEAKENING，≥2 条 → DEGRADED；「当前 |IC_30d| < 0.02」是**加重项**（单独出现不算，仍走 RESEARCH —— 那是「新因子评估中」不是衰退）
- [x] **策略级口径**: 降权幅度按因子在生产策略**冻结权重中的 |w| 占比**分档 —— 0 暴露 → 不建议降权（仅标记复核）；<10% → 幅度减半；≥10% → 全档。暴露由 `load_production_factor_exposure()` 从 `StrategyRegistry.load_active()` 的 approved weights 计算（多个生产策略取平均；registry 不可读 → 显示 **N/A**，不用 0 冒充）
  - 实测暴露（momentum_vol_full v20260811）: Amplitude_5D 25% / Volatility_20D 22% / Momentum_3M 20% / Volume_Concentration 19% / Volume_Trend_10D 14%
- **实测清单变化（19 因子）**: degraded 7 → **5**、weakening 7 → **9**、validated 5（不变）
  - `Implied_Net_Flow` / `MaxDD_60D` / `Short_Term_Reversal_5D`: degraded → weakening（仅 IC_IR 单条件）
  - `Momentum_6M`: weakening → degraded（decay + IC_IR 两项同时成立）
  - `Volatility_20D`（暴露 22%）→ degraded + 降权 50%；`Amplitude_5D`（25%）→ weakening + 降权 25%；非生产因子（暴露 0%）→ 「未进入生产策略，无需降权，仅标记复核」
- 测试: `tests/unit/test_factor_health_significance_gate.py` 20 项（新增分层 4 项 + 暴露分档 5 项）
- [x] 展示层归因与精度修复

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
  - [x] 1.4 SPA 卡片 → ✅ **2026-09-19 完成**：`GET /api/v1/industry-heat`（只读，如实标注 as_of/滞后天数）+ `IndustryHeat.vue` 页面（源切换 / 表格 / 价格源资金流列显示 — 而非 0）+ `/industry` 路由与 nav；headless DOM 验证过（真实行业名 26 行）
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
  - [x] 未计佣金/印花税/滑点 → ✅ **已解决**：`position_service.py` 三口径含 `est_buy_fee` /
        `est_sell_fee` / `est_round_trip_fee` / `unrealized_pnl_net(_pct)`；2026-09-19 又给
        `CostModel` 补了最低佣金（¥5/笔）与过户费开关（默认关闭，见 §#12-2）
  - [x] `/api/v1/account` 的 `active_value` 与页面不同源 → ✅ **已解决**：该端点已返回
        `valuation`（成本 / 最新收盘 / 费用后三口径），前端一律消费 `valuation`；
        `active_value` 现在**有意**保留为成本口径并在 docstring 写明
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
  - [x] 券商最低佣金与过户费 → ✅ **2026-09-19 实现**：`CostModel` 新增 `min_commission`（默认 **0 = 不启用**）与 `transfer_fee_rate`（默认 0），`CostBreakdown` 增 `transfer_fee` 字段并计入 `total_cost`，`DecisionEngine` 透传；常量 `MIN_COMMISSION_CNY = 5.0` / `TRANSFER_FEE_RATE = 0.00001`（2022-04-29 起沪深统一 0.001%，双向）。
        **默认 0 的取舍**：保持与历史回测结果可比；实盘/纸面要精确需显式传参启用（¥450 的单：¥0.11 → ¥5，**45 倍**）。
        测试：`tests/unit/portfolio/test_cost_model.py`（9 项，含「默认行为不变」守卫与真实小额单对比）
  - [x] `MarketImpactModel.compute_adv()` 的 volume 单位 → ✅ **2026-09-19 已修**（commit `c8d8124`
        「fix(portfolio): ADV 计算补 手→股 换算」）。原问题：日线 `volume` 单位是**手**，
        而 `compute_adv` 用 `close*volume` 当成交额 → ADV 低估 100× → 冲击成本估算**高估 10×**
        （实测 1 万元单：600207 ¥5.47 vs 修正后 ¥0.55；600930 ¥2.54 vs ¥0.25），
        并让 10%-ADV 流动性惩罚提前 100× 触发。影响 `daily_pipeline` Step 11 的
        `estimated_cost_pct`（进决策包 markdown / portfolio_snapshot）

---

## 统一接口候选（2026-08-27 扫描，仅记录未实施）

> 背景：时间接口已统一（`qp/shared/time.py`，commit fb8d00b）。以下 4 处为同类"散落多点、值得收编"的横切关注点。

### C-1 路径常量 ✅ 已完成（2026-09-19）
- 原状（2026-08-27 扫描）：`data/` 字符串硬编码 **153 处 / 87 文件**
- **2026-09-19 复核 + 收尾**：AST 审计（区分代码字面量 vs 注释/docstring）显示
  扫描后已消掉大半（qp/ 剩 79 处），本轮全部补齐：
  - `paths.py` 常量 41 → **62**（新增 bronze/silver/factor_store/feature_store_data/
    fundamental_cache/valuation_cache/market_regime_notes/proposals/cache_research
    + 12 个具名文件常量 + __all__ 同步）
  - **批次 1**：21 文件 / 22 处「路径使用」→ 常量（commit `f64a589`）
  - **批次 2**：11 处（4 处真实路径 + 7 处用户可见文本，f-string 逐字等价）（commit `78856eb`）
  - **最终：`qp/` + `scripts/` + `tests/` 内 `data/` 代码字面量清零**，仅剩
    `qp/shared/paths.py` 自身的常量定义（定义源豁免）
- 验证：ruff format --check / ruff check 全过；pyright **0 errors**；
  tests/unit/data + test_lineage_registry（61 项）+ test_feature_registry 全过；
  实测 `qp doctor` 通过、`qp knowledge stats` 输出与替换前逐字一致
- 过程中修掉 2 类自动替换陷阱（已记入 skill）：① 替换脚本必须排除定义源文件
  （否则 paths.py 自我引用）② 补 import 必须用 AST 定位（正则会把新 import
  插进多行括号 import 内部，破坏 `from qp.lineage.types import (...)`）

### C-2 JSON 读写封装 ✅ 已完成（2026-09-19）
- 原状（2026-08-27 扫描）：`json.dump` 58 处 + `json.load` 60 处 / 50 文件
- **2026-09-19 复核 + 收尾**：`qp/` 生产代码**早已清零**（仅 `json_io.py` 自身的
  实现，定义源豁免）；本轮清掉 `scripts/` + `tests/` 的 6 处（commit `4d8d751`）：
  orthogonalize_sameuniverse / orthogonalize_walkforward / retrain_monthly /
  test_feature_registry
- 统一走 `qp.shared.json_io`（utf-8 / indent=2 / ensure_ascii=False / 自动建父目录）

### C-3 strftime 格式收编 ✅ 已完成（2026-09-19）
- 原状（2026-08-27 扫描）：56 处 / 10 种格式
- **2026-09-19 核实**：AST 审计实际 **23 处 / 10 种**（原扫描口径含数据框层的 `.dt.strftime`，
  与 Python datetime 混在一起统计）
- 本轮收编 **9 处** Python datetime 调用（格式全部映射到既有函数）：
  - `'%Y-%m-%d'` → `fmt_date()`：retrain_monthly ×2（**顺带修掉裸 `datetime.now()` 的时区隐患**）、
    test_retrain_signal_weights ×2（改为 `now_cn()` 基准，与 `load_weight_scales` 的 CN cutoff 同源）、
    exit_signals
  - `'%Y%m%d'` → `fmt_compact()`；`'v%Y%m%d'` → `f"v{fmt_compact()}"`（multifactor_pipeline 策略版本号）
  - `'%Y%m%dT%H%M%S'` → `fmt_ts(now_utc(), sep="T")`；`datetime.now(UTC).isoformat()` → `utc_iso()`（lineage_tracker）
  - 新增 `fmt_short()`（`'MM-DD HH:MM'`）收编 data_quality_service 的最后一处
- **剩余 14 处明确不收编**（理由记录在案，避免以后反复「清理」）：
  1. **数据框层（6 处）**：`records[col].dt.strftime` / `pd.to_datetime(...).dt.strftime` /
     `pl.col(...).dt.strftime` —— polars/pandas 的**列级**格式化，与 `qp/shared/time.py`
     （Python datetime）不同层，强行收编会破坏类型与语义
  2. **`qp/shared/time.py` 自身实现（8 处）** —— 定义源豁免
- 验证：ruff format --check / ruff check 全过；pyright **0 errors**；
  tests/unit/web + test_retrain_signal_weights + test_lineage_registry 全过；
  `scripts/retrain_monthly.py` 编译通过

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

### #14 门禁指标生产者 + 行业中性化失效（2026-09-25）

#### #14-1 门禁 5 项「未评估」指标补齐生产者 ✅ 已完成

- **背景**: `qp validate` 的 `cost_adjusted` / `turnover` / `neutralization` / `overfit_ic_ratio` /
  `feature_importance` 长期显示「未评估」——实验记录里根本没有这些指标的生产者。
- **已做**（`qp/research/experiment/models.py` + `tracker.py` + `qp/pipeline/multifactor_pipeline.py`）:

  | 新增字段 | 口径 | 落盘位置 |
  |---|---|---|
  | `sharpe_ratio_net` / `max_drawdown_pct_net` | 权益曲线本身含成本（`SimulatedBroker.get_equity = _cash + 市值`，成交即扣佣金/印花税/滑点）→ 直接记实测值，不再用"gross 减成本"外推 | `_compute_backtest` → `result.metrics` |
  | `total_cost_pct` | 总成本 / 平均权益（新增 `avg_equity` 返回值） | 同上 |
  | `daily_turnover_pct` | 累计换手（总卖出 / 平均权益）÷ 交易日数 = 日均**单边**换手 | 同上 |
  | `pre/post_neutralization_ic` | legacy 因子管线路径：同管线关掉 neutralize 再算一次组合分，两次 IC 对照 | Stage 3 |
  | `feature_importance` | 线性策略 = 归一化 `|权重|`（**不是** tree gain，仅用于集中度判断） | `_record_experiment` |
  | `in/out_of_sample_ic`（validate 侧映射） | 全期 `ic_mean` vs Purged-CV OOS `cv_oos_ic_mean` | `validate._build_context` |

- **实测验证**（`qp experiment run multifactor --strategy momentum_vol_full --start=2025-09-05
  --end=2026-08-31 --top-n=10 --rebalance=20 --skip-gate --freeze-weights=…`）:
  `total_cost_pct=3.6439` / `daily_turnover_pct=3.6695` / `sharpe_ratio_net=1.65` /
  `max_drawdown_pct_net=17.49` / `feature_importance` 5 项和为 1.0 → `qp validate` 输出
  `cost_adjusted ✅`、`overfit_ic_ratio ✅ (IS=0.0773, OOS=0.0622, ratio 0.805)`、
  `feature_importance ✅ (Top-1 25%)`；「未评估」从 5 项降到 1 项。
- **⚠️ 新暴露的真结果**: `turnover ❌ 3.7% < 5% 下限`（检查项阈值区间 [5%, 200%] 按**日**，
  即要求 ≥100%/月单边）。这是真实评估结果，不是 bug；是否调整阈值属策略/风控决策，**未动**。
- **剩余缺口**: `neutralization` 在**策略模式**（`momentum_vol_full` 等白名单）仍为「未评估」
  ——组合分由策略内部（`qp/strategy/multifactor.py`）产出，管线看不到中性化前后的中间量。
  要闭合需让策略层把"中性化前组合分"回传（改动点在 `run_multifactor_strategy` 的 diagnostics）。

#### #14-2 ⚠️ 未修：行业映射拿不到 → 中性化实际未生效（production-sensitive，待批准）

- **FACT 证据**:
  1. 真实行业映射存在：`data/stock_industry.json`（`qp/portfolio/industry.py` 消费）、
     `data/stock_industry_csrc.json`（`qp/data/industry/csrc.py` 生成）
  2. 因子中性化取行业映射的唯一入口是 `_build_industry_map(price_data)`
     （`qp/pipeline/multifactor_pipeline.py:3060`、`qp/strategy/multifactor.py:1111`），
     它要求 `price_data` 的 DataFrame **含 `industry` 列**
  3. 全仓库无任何代码往 `price_data` 加 `industry` 列（grep 全 `qp/` 无创建点）；价格
     parquet 列里也没有该列
  4. 实测（legacy 路径）：关掉 neutralize 再算的组合分与中性化后**逐位相同**（IC 均 0.1084，
     full precision 相等）→ 中性化没改变任何分数
- **INFERENCE（待验证）**: 策略路径大概率同样失效（同一 `_build_industry_map` 模式 + 无列来源），
  但**未实测验证**策略路径的中性化效果 —— 需在 `run_multifactor_strategy` 内插桩确认。
- **本轮已加防护**（不是修复）: 管线检测到行业映射缺失 → 打 warning 且 **不落盘**
  pre/post IC，避免门禁"前后相同"造成**假通过**。
- [ ] 决定修法：把 `data/stock_industry.json` 接进 `_build_industry_map`（或在数据加载层
      补 `industry` 列）→ 属 production 路径改动，需先确认对现有 IC/回测的影响

#### #14-3 DailyPipeline Step 1.6（FactorHealthPipeline.run_incremental）实测 4-5 分钟，不是"几个小时" ⚠️ 未修（待批准）

- **起因**: 全量 pytest 看起来"卡在" `test_pipeline_critical_path.py`（改任何东西后套件都跑不完），先怀疑是新改动回归。
- **归因（有效对照）**: 父提交 `fa788b07` + **同一份数据**跑同一用例同样超时（240s、38 CPU-分钟）
  → 与改动无关；用 faulthandler 抓栈定位到 `daily_pipeline.py:335 → factor_health_pipeline.py:322/447`。
- **实测成本（逐段计时，非推测）**:

  | 环节 | 实测 | 说明 |
  |---|---|---|
  | `_build_fundamental_score_frames` | **0.6s** | 9 个基本面因子，PIT join_asof 不慢 |
  | 单个价量因子 `compute_daily_ic_series` | **1.5s** | 内部对**全量价格帧**排序+算前向收益 |
  | 单个价量因子 `compute_ic_decay` | **7.5s** | = 5 个 horizon **各重算一遍** `evaluate_factor_ic`（1/3/5/10/20） |
  | 单因子合计 | **9.0s** | 19 个价量因子 ≈ 2.8 分钟；+9 个基本面因子 ≈ 1.35 分钟 |
  | 每次 run 总计 | **≈4-5 分钟** | 与观测（4-8 分钟）一致；docstring 却写"runs in seconds" |

- **机制（代码位置）**: `qp/research/evaluation/rank_ic.py`
  - `compute_daily_ic_series()` 无条件 `price_df.sort(["symbol","trade_date"])` 并给**全部 730 万行**算
    `shift(-forward).over("symbol")`，之后再 join 得分日期 → 每次调用 1.11s，与"需要几天 IC"无关
  - `compute_ic_decay()` 对 5 个 horizon 逐次调用 `evaluate_factor_ic` → 每因子 6 次全量价格 pass
  - `run_incremental()` 串行跑 28 个因子 → 168 次全量 pass ≈ 3.1 分钟（占总耗时约 7 成）
- **优化空间（已实测）**: 把价格帧先按"得分日期 ± forward 尾巴"裁剪再排序 → 1.11s → **0.15s**（7.4×）。
  ⚠️ 坑：不能只留得分日期本身，必须保留末日期之后 `forward_days`（decay 到 20 天）的交易日，否则最新日期的前向收益会变 NaN。
- **数据侧异常**: `data/dataset/factor_values_daily.parquet` 现有 **50 个日期**（2016-10-31 … 2026-09-24，每日约 3000 行，个别日期只有 1 行），
  而 docstring 假设"normally the latest trading day" → IC 循环多做 30+ 天的横截面。写入方是 `qp/pipeline/factor_calc_pipeline.py`（`qp factor compute`）与 `qp-daily` 定时任务，需查为何累积历史日期。
- **影响面**: `qp-daily.timer`（Mon..Fri 17:57）每周 5 次付这份成本；**任何跑 DailyPipeline 的测试也各付一次** → 这解释了全量套件 ~13 分钟的基线，以及"单文件超时 120s/240s/420s 全部误判为卡死"。
- [x] **方案 1 已落地（fe69d189）**: `compute_daily_ic_series` 排序前只保留"得分日可达"的价格行
      窗口 = `[score_date, score_date + forward_days + 10 交易日缓冲]`（缓冲覆盖停牌使 `shift(-n).over(symbol)` 越过 horizon 的情况）
      - 证据 1（数值等价，真实数据）: 28 因子 × 5 horizon **全部逐位相同**（参考实现 vs 优化后），
        140 次调用 **359.9s → 186.4s（1.9×）**
      - 证据 2（单测）: 新增 `tests/unit/research/test_rank_ic_window.py` **17 项**（含改造前参考实现作 oracle、
        停牌洞、末日期、空得分帧、日期不可对齐、字符串日期）；`tests/unit/research` + 因子健康/监控测试全绿
      - 证据 3（质量门禁）: `uvx ruff format --check .` 483 files already formatted、`uvx ruff check .` All checks passed、
        `uv run pyright` 0 errors
      - 未达预期说明: 实测 1.9× 而非预估 7× —— 裁剪本身有成本（`unique()` 0.094s + semi join + 子帧排序），
        且基本面因子得分帧有 ~420 个日期（窗口更宽）
- [x] **方案 2 + 方案 3 已落地**: 新增 `prepare_forward_returns` / `compute_daily_ic_series_from_forward` /
      `compute_ic_decay_from_forward` —— **每个 horizon 只准备一次前向收益，28 个因子复用**；
      同时把"逐日对 merged 全帧 filter"改成单趟 `partition_by`（fund 因子 420 天、100 万行时 0.75s → ~0.2s，
      这是方案 3 能否真正见效的关键：准备只占每次调用成本的 ~25%）。
      方案 2（decay 单次 pass 出多 horizon）**未单独实现**——准备层抽出后，decay 的 5 个 horizon 只剩
      join+分组，不再有全量价格 pass，其收益已被方案 3 覆盖。
      - 证据 1（数值等价，真实数据）: 28 因子 × 5 horizon **逐位相同**；旧路径 240.4s →
        新路径 13.9s（准备 1.7s + IC 12.2s）= **17.3×**
      - 证据 2（端到端集成）: 真实 `run_incremental`、同一份 monitoring 种子数据跑两次对比：
        **before 113.4s → after 17.9s（6.3×）**，两边 status=SUCCESS / 28 因子，
        产出 `factor_ic_series.parquet`（57069 行）与 `factor_health.parquet`（870 行）**逐列逐行完全相同**
      - 证据 3（单测）: `test_rank_ic_window.py` 扩到 **27 项**（新增 prepare/from_forward/decay 等价、
        缺 horizon 抛 KeyError、窗口边界），research + factor_health + monitoring 全绿
      - 证据 4（质量门禁）: `uvx ruff format --check .` → 483 files already formatted；`uvx ruff check .` → All checks passed；
        `uv run pyright` → 0 errors
      - 证据 5（全量回归）: `7d7a8c0f` 全量 pytest **WALL=148.63s / 100% / exit 0 / 1 skip**（skip 与改动无关）
        —— 对比方案 1 时的 345.96s，套件再提速 **2.3×**；原始实现下套件需 ~13 分钟且单文件常见超时误判
      - **总账**: 原始实现 ~4-5 分钟/次 → 现在 **17.9s**；`test_pipeline_critical_path.py` 由"420s 超时被杀"变为 325s 跑完
        （该数字含多个 DailyPipeline 用例，非单次 run_incremental）

### factor_values_daily.parquet 的两个异常（2026-09-26 查清，只诊断未改码）
- [x] **写入方**：唯一生产者 = `qp/pipeline/factor_calc_pipeline.py`（`_DATASET_NAME="factor_values_daily"`，全仓无第二个 writer）
      - 增量模式（默认）：`FactorCalculator.compute(price_df, date=None)` → target_date 取价格最大日 → 逐股计算 →
        **每行 trade_date 取该股自己最后一行**（`factor_calculator.py:117-120`：`last = factors_df.tail(1)` + `_trade_date_value(last["trade_date"])`）
        → `merge_with_existing()` 按 (trade_date, symbol) 去重、append-only、**从不清理** → `write_atomic()`
      - 正常触发：DailyPipeline Step 1.5（`qp-daily` 工作日 17:57）；证据 `logs/scheduler.log` 2026-09-25 18:21 "Incremental write: 111668 rows"
      - **测试触发（污染）**：`tests/unit/test_pipeline_critical_path.py` 两个用例 patch 了 `DataPipeline` / `FeaturePipeline` /
        `_load_price_data`，但**没 patch `FactorCalcPipeline`**，context 也没传 `output_dir` → 走默认生产路径写盘。逐用例实测确认为：
        `TestDailyPipelineCriticalPath::test_system_state_normal_allows_execution_fails_on_missing_data` 与
        `TestDailyPipelineCriticalPath::test_state_check_is_advisory`（全量套件跑一次 → mtime 被改 2 次，与两个用例一一对应）
- [x] **50 个日期的构成**：37 个 2026-08-05→2026-09-24 连续交易日（每工作日一次增量，各 ~3015-3037 行）
      + 13 个散落日期各 1-4 行 = **已停止交易个股**，其 trade_date 被写成该股自己最后一个交易日
      （实测对应：000748 价格止于 2016-10-31 ↔ 因子行 2016-10-31；600068→2021-09-01；000004→2026-07-13；600421→2026-06-22）
- [x] **影响评估**：IC 无影响（散落日期横截面 1-4 只 < `min_stocks_per_day=10` → 跳过）；
      策略快路径无影响（`_compute_today_from_parquet` 先按 `trade_date == today` 过滤，multifactor.py:1474-1480）；
      写盘原子 + merge 去重 → 内容稳定（套件跑完 md5 不变）
- [x] **建议 A（测试隔离）已落地**：两个用例新增 stub —— 注意 Step 1.5/1.6 都是**函数内 import**，
      必须 patch 源模块 `qp.pipeline.factor_calc_pipeline.FactorCalcPipeline` /
      `qp.monitoring.factor_health_pipeline.FactorHealthPipeline`（patch `qp.pipeline.daily_pipeline.X` 会 AttributeError）
      - 空跑实测：该文件跑完 `factor_values_daily.parquet` + `data/monitoring/*.parquet` md5 **全部不变**
      - 顺带提速：该文件 38.25s（只 stub 1.5 时）→ **1.50s**；全量套件 148.63s → **13.41-13.59s**（两次复现，exit 0）
      - 门禁：`uvx ruff format --check .` 483 files / `uvx ruff check .` passed / `uv run pyright` 0 errors
- [ ] **建议 B（日期语义，行为变更）**：`compute(date=...)` 只保留"在 target_date 当天有价格"的 symbol，
      不再把停止交易股写成它们自己的陈旧日期；配套对存量文件做一次显式清理或 full_history 重建
- [ ] 可选加固：给 tests/conftest.py 加自动 fixture，快照生产产物 md5，测试改动了就 fail（防止同类污染回归）
- INFERENCE（未验证）：19 只停止交易股另有 2026-08-05 一行，推测来自更早的价格快照（同期"三源复权混入"事故），merge 保留至今

### 质量门禁（2026-09-19）
- [x] `uvx ruff format --check .` → 473 files already formatted；`uvx ruff check .` → All checks passed
- [x] `uv run pyright` → 0 errors, 0 warnings, 0 informations（注意：`uvx pyright` 找不到 .venv，会假报 ~692 个 reportMissingImports）
- [x] 全量 `pytest -q` → exit 0（基线 1768 passed；本次新增/更新 9 项测试）

---

## 关联

- 架构导航: `docs/ai/PROJECT_MAP.md`
- 镜像笔记: Obsidian `1-Projects/qt项目待办.md`
- 相关整改: Obsidian `1-Projects/qt宪法合规整改.md` / `docs/constitution/rule.md`
