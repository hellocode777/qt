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

---

## 关联

- 架构导航: `docs/ai/PROJECT_MAP.md`
- 镜像笔记: Obsidian `1-Projects/qt项目待办.md`
- 相关整改: Obsidian `1-Projects/qt宪法合规整改.md` / `docs/constitution/rule.md`
