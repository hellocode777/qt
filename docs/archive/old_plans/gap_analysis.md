# 差距分析：当前实现 vs rule.md

> 生成日期：2026-07-23 | 基准文档：`docs/rule.md` v4.2

## 状态说明

- 🔴 **待修复** — 与规范矛盾或违反宪法条文
- 🟡 **待补齐** — 已部分实现但未集成或功能不完整
- 🟢 **待规划** — 锦上添花，不影响核心闭环

---

## 🔴 关键差距

### ~~G-001: LightGBM 使用二分类，而非 LambdaRank~~ ✅ 已修复 (2026-07-23)

- **违反条款**: §7.9.1, §7.9.9
- **文件**: `qp/research/model_trainer.py`
- **修复**: `WalkForwardScorer` 使用 `LightGBMRankModel`（`objective: "lambdarank"`, `metric: "ndcg"`），标签改为截面 rank 百分位（连续值），group 参数按日期截面分组
- **关联修复**: G-006, G-007, G-008, G-009, G-013 一并修复

### G-002: 缺少 `platform/alert/` 目录

- **违反条款**: §8 阶段一（Week 1 交付物）
- **现状**: 告警通道（Terminal/Log/Telegram/DingTalk/WeCom/Email）存在于 `qp/monitoring/alerts.py`，但 Walking Skeleton 规定的 `platform/alert/` 目录不存在
- **影响**: 目录结构与设计文档不一致
- **修复方向**: 将 alerts.py 移动到 `platform/alert/` 或建立重导出桥接

### G-003: `platform/cli/parser.py` 为空

- **违反条款**: §1 Platform Layer（CLI 子系统）
- **文件**: `qp/platform/cli/parser.py`（0 行）
- **现状**: CLI 参数定义（约 130 行 argparse）内联在 `main.py` 中
- **影响**: parser 模块零实现，违反"每个子系统独立模块"的原则
- **修复方向**: 将 argparse 定义提取到 parser.py，main.py 仅做命令路由

### G-004: 无 Shadow Trading 追踪器

- **违反条款**: §5.1 策略生命周期, §10.2（Shadow Production → Production 条件）
- **现状**: `StrategyLifecycle.SHADOW_PRODUCTION` 枚举已定义，但无对应追踪器（ShadowTradingTracker 不存在）
- **要求**: §10.2 规定 Shadow → Production 需 ≥1 次市场波动期间无异常
- **影响**: 策略无法通过生命周期自动流转到 Production
- **修复方向**: 创建 `qp/strategy/shadow_trading.py`，类比 PaperTradingTracker 但专门做观察模式

### G-005: e2e 测试为空

- **违反条款**: Walking Skeleton 验收标准, ADR-006
- **目录**: `tests/e2e/`（仅 `__init__.py`）
- **影响**: 无从 Data → Feature → Strategy → Backtest → Report 的自动化端到端验证
- **修复方向**: 添加至少 1 条端到端测试，用少量股票（如 5 只）跑完整管道

### ~~G-006: ML 管道未使用 Purged CV~~ ✅ 已修复 (2026-07-23)

- **违反条款**: §7.9.3
- **文件**: `qp/research/model_trainer.py:267`
- **现状**: 简单 `split = int(len(y) * 0.8)` 80/20 按行切分
- **要求**:
  1. Walk-Forward 时间序列切分（非随机）
  2. Purge：标签计算窗口重叠的样本从训练集中剔除
  3. Embargo：验证集后额外禁运期
  4. 最小训练窗口 ≥ 2 年
- **影响**: 标签未来信息泄漏，样本内 IC 虚高
- **修复方向**: 使用已有的 `qp/research/split/purged_cv.py` 替代手动切分

---

## 🟡 重要差距

### ~~G-007: LightGBM 缺少单调约束~~ ✅ 已修复 (2026-07-23)

- **违反条款**: §7.9.5
- **文件**: `qp/research/model_trainer.py:276-293`
- **现状**: params 字典中无 `monotone_constraints`
- **要求**: 对估值因子（PE_TTM、PB）强制负向约束，防止模型学到反直觉噪声
- **修复方向**: 添加 `monotone_constraints` 列表（-1=负向, 0=无约束, 1=正向）

### ~~G-008: 无特征重要性稳定性检查~~ ✅ 已修复 (2026-07-23)

- **违反条款**: §7.9.7
- **文件**: `qp/research/importance/feature_importance.py` 存在但未集成
- **要求**: 若 Top 5 特征排名与上一版剧烈变化 → 触发人工复核，暂缓上线
- **修复方向**: 在 `model_trainer.py` 训练后调用重要性对比，超过阈值记录 WARNING

### ~~G-009: 模型版本命名未执行~~ ✅ 已修复 (2026-07-23)

- **违反条款**: §7.9.6
- **要求**: `{algo}_{objective}_v{major}.{minor}`（如 `lgb_lambdarank_v3.1`）
- **现状**: 模型无版本号，无模型文件哈希记录，无 Git commit 绑定
- **修复方向**: 在 `ExperimentTracker.log_experiment` 中强制要求 `model_id` 符合命名规范

### G-010: 财务数据未追踪 as-first-reported vs as-restated

- **违反条款**: §10.6
- **文件**: `qp/data/universe/restatement.py`
- **现状**: RestatementTracker 追踪版本号，但未存储首次报告值与重述值的双重数据
- **要求**: 每条财务记录存两份 — `as_first_reported` + `as_restated`，回测默认只用前者
- **修复方向**: 扩展 RestatementTracker schema，增加 `value_first` / `value_restated` 字段

### G-011: 无策略提案流程

- **违反条款**: §5.1（Research Proposal → Validation Gate）, §10.2
- **现状**: 策略通过 `StrategyRegistry.register()` 直接注册，无提案、无审查
- **要求**: Validation Gate 应在注册前阻止未达标的策略
- **修复方向**: 创建 `StrategyProposal` 数据模型 + `ValidationGate.check_strategy()` 阻止未达标注册

### G-012: 无自动化投资组合 KPI 报告

- **违反条款**: §10.5
- **要求**: 季度自动报告 — Sharpe ≥ 1.2, MaxDD ≤ 20%, Alpha/Beta 归因
- **现状**: 无定时报告生成器，无归因报告
- **修复方向**: 创建 `qp/monitoring/portfolio_report.py`，可由 scheduler 按季度触发

### ~~G-013: LightGBM 缺少 group 参数~~ ✅ 已修复 (2026-07-23)

- **违反条款**: §7.9.9 示例代码
- **文件**: `qp/research/model_trainer.py:296-297`
- **现状**: `lgb.Dataset(X_tr, label=y_tr)` — 未传 `group` 参数
- **要求**: LambdaRank 要求 `group` 参数指定每个 query（日期）的样本数
- **影响**: 切换到 LambdaRank 目标函数的先决条件
- **修复方向**: 按日期计算各截面样本数，作为 `group` 传入

### G-014: ModelDecay → Shadow 降级未连接

- **违反条款**: §7.9.8
- **文件**: `qp/monitoring/model_decay_lifecycle.py`（249 行）存在但未集成
- **现状**: `ModelDecayTrigger` 触发 WARNING 但不会自动将策略生命周期降级为 SHADOW_PRODUCTION
- **要求**: "降级到 Shadow 观察，而非直接 Kill Switch"
- **修复方向**: 在管道中连接 `ModelDecayLifecycle.downgrade_if_needed()`

---

## 🟢 小差距

| # | 差距 | 说明 |
|---|---|---|
| G-015 | SimpleVectorBacktest 是遗留代码 | 实际回测在 `multifactor_pipeline.py` 中内联实现，`SimpleVectorBacktest` 未被使用 |
| G-016 | DailyPipeline 使用合成估值数据 | `_build_valuation_data()` 硬编码 PE=15+偏移，而非从 quant.db 加载真实基本面 |
| G-017 | 指数代理构建方式粗糙 | `_build_index_df()` 从股票均价构建代理，而非使用真实 000001 数据 |
| G-018 | 缺少 experiment CLI 命令 | 无 `qp experiment list/show/compare` |
| G-019 | 缺少 `--dry-run` 标志 | 无法在不获取数据/执行交易的情况下模拟完整管道 |
| G-020 | CorporateActionEngine 签名使用 object | ABC 的 `adjust_portfolio(self, portfolio: object, ...)` 应为 `pd.DataFrame` |
| G-021 | Scheduler 从未运行 | `platform/scheduler/` 完全实现，但没有 cron 任务或系统定时器实际调度它 |
| G-022 | 无 Markdown 报告生成器 | Walking Skeleton §8 第三阶段提到 "QuantStats / Markdown Report" |

---

## 完成度统计

| 类别 | 数量 |
|---|---|
| 🔴 关键 | 5 (-1) |
| 🟡 重要 | 3 (-5) |
| 🟢 小 | 8 |
| ✅ 已修复 | 6 |
| **合计** | **22** |

---

## 修复建议顺序（基于 §11 优先级）

1. **G-001 + G-013 + G-006**: LightGBM 切换为 LambdaRank + Purged CV + group 参数 — 影响模型质量
2. **G-003 + G-002**: parser.py + alert/ 目录 — 目录结构合规
3. **G-011**: 策略提案流程 — Validation Gate 准入控制
4. **G-004 + G-014**: Shadow Trading + 降级流程 — 生产安全
5. **G-007 + G-008 + G-009**: 单调约束 + 特征重要性稳定性 + 模型版本 — 防过拟合
6. **G-010**: 首次报告值 vs 重述值 — PIT 合规
7. **G-005 + G-012**: e2e 测试 + KPI 报告
8. **G-015 ~ G-022**: 小差距 — 按需

---

*关联文档: [[rule.md]], [[CLAUDE.md]]*
