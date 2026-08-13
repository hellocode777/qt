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
- [ ] 补全 ADR-001~030 空文档（0 字节占位，后续项）

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

## 方向性探索（不在清单但值得想）

### A. 策略池扩容
- 现状: mvF 5因子 APPROVED 是唯一生产策略（ADR-031）；研究侧已有 10因子 + LightGBM
- 目标: 把第二个策略推过 validation gate
- 价值: ⭐⭐⭐⭐⭐（直接决定系统产出）

### B. 实盘闭环验证
- 现状: Portfolio 真实账户状态机 + 现金账本（ADR-032）已建成
- 目标: 跑通一个完整「人工审核 → 建仓 → 平仓 → 记账」周期
- 价值: 系统从「玩具」变「工具」的最后一步

---

## 关联

- 架构导航: `docs/ai/PROJECT_MAP.md`
- 镜像笔记: Obsidian `1-Projects/qt项目待办.md`
- 相关整改: Obsidian `1-Projects/qt宪法合规整改.md` / `docs/constitution/rule.md`
