# Validation Gate Layer 差距追踪文档

> 对照 `rule.md` §5、§10.1、§10.2 与 `docs/5_Validation_Gate_Research_Review_Process.md`，逐项追踪 Layer 5（Validation Gate）的待实现项。
> 最后更新：2026-07-22

---

## 状态说明

- ⬜ `[ ]` 待实现
- 🟡 `[~]` 部分实现，有缺陷
- ✅ `[x]` 已完成

---

## 一、框架基础

### 0.1 RuleEngine + BaseRule 框架

- **状态**: `[x]` ✅ 已完成
- **已实现**: `engine.py`（`RuleEngine` + `BaseRule` + `ValidationContext`）+ `result.py`（`RuleResult` + `ValidationResult`）
- **涉及文件**: `qp/validation/engine.py`, `qp/validation/result.py`

### 0.2 因子检查

- **状态**: `[x]` ✅ 已完成
- **已实现**: `RankICCheck`、`ICIRCheck`、`TStatCheck`、`StratificationCheck`
- **涉及文件**: `qp/validation/checks/factor_checks.py`

### 0.3 回测检查

- **状态**: `[x]` ✅ 已完成
- **已实现**: `SharpeCheck`、`MaxDrawdownCheck`、`TurnoverCheck`
- **涉及文件**: `qp/validation/checks/backtest_checks.py`

### 0.4 过拟合检查

- **状态**: `[x]` ✅ 已完成
- **已实现**: `OverfitCheck`（OOS/IS IC ratio）、`FeatureImportanceCheck`（集中度）
- **涉及文件**: `qp/validation/checks/overfit_checks.py`

---

## 二、P1 — 核心检查缺失（Validation Gate 阶段）

### 1.1 NeutralizationCheck — 行业/市值中性化检验

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "通过行业/市值中性化检验（Rule 9）"；Rule 9 "Alpha Must Survive Neutralization"
- **已实现**: `NeutralizationCheck(min_ratio=0.5)` — 计算中性化前后 IC 比值，衰减超 50% 则 FAIL
- **涉及文件**: `qp/validation/checks/factor_checks.py`

---

### 1.2 MinSamplePeriodCheck — 最小样本区间检查

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.1 "最小样本区间 ≥ 3 年（覆盖至少 1 轮牛熊）"
- **已实现**: `MinSamplePeriodCheck(min_years=3.0)` — 从 `metadata["train_start"]` / `["train_end"]` 计算年跨度
- **涉及文件**: `qp/validation/checks/factor_checks.py`

---

### 1.3 CostAdjustedCheck — 交易成本后验证

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "剔除交易成本后仍满足以上条件"
- **已实现**: `CostAdjustedCheck(min_sharpe=1.0, max_drawdown_pct=25.0)` — 对比 net/gross 指标，支持 `total_cost_pct` 估算 fallback
- **涉及文件**: `qp/validation/checks/backtest_checks.py`

---

## 三、P2 — Paper Trading 阶段检查

### 2.1 SignalCorrelationCheck — 实盘 vs 回测信号相关性

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "实盘信号与回测信号相关性 ≥ 0.8"
- **已实现**: `SignalCorrelationCheck(min_correlation=0.8)` — 每日截面 Spearman 相关性
- **涉及文件**: `qp/validation/checks/paper_trading_checks.py`

---

### 2.2 SlippageDeviationCheck — 滑点偏差检查

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "实际滑点与假设滑点偏差 ≤ 50%"
- **已实现**: `SlippageDeviationCheck(max_deviation_pct=0.50)` — 对比 bps 偏差
- **涉及文件**: `qp/validation/checks/paper_trading_checks.py`

---

### 2.3 SignalInterruptionCheck — 信号中断检查

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "无因数据缺失/异常导致的信号中断"
- **已实现**: `SignalInterruptionCheck(max_consecutive_missing=2, max_missing_ratio=0.05)` — 连续缺失 + 总缺失比例双阈值
- **涉及文件**: `qp/validation/checks/paper_trading_checks.py`

---

## 四、P2 — Shadow → Production 阶段检查

### 3.1 KillSwitchHistoryCheck — Kill Switch 历史检查

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "Paper Trading 期间无触发 Kill Switch"
- **已实现**: `KillSwitchHistoryCheck()` — 支持直接 `kill_switch_trigger_count` 或嵌套 `paper_trading_metrics`
- **涉及文件**: `qp/validation/checks/production_checks.py`

---

### 3.2 HighVolSurvivalCheck — 高波动生存检验

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "至少经历一次市场波动（VIX 分位数 > 70% 或等效指标）而未出现异常回撤"
- **已实现**: `HighVolSurvivalCheck(max_dd_during_high_vol=25.0)` — 双条件：至少 1 天高波动 + DD 不超标
- **涉及文件**: `qp/validation/checks/production_checks.py`

---

## 五、P3 — 流程与工程化

### 4.1 CodeReviewCheck — 代码审查检查

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "代码通过 Research Code Review（Rule 10）"
- **已实现**: `CodeReviewCheck()` — 支持 metadata flag 或 `.reviewed` 标记文件
- **涉及文件**: `qp/validation/checks/process_checks.py`

---

### 4.2 ExperimentRecordCheck — 实验记录完整性

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.2 "完整 Experiment 记录（Rule 6）"
- **已实现**: `ExperimentRecordCheck()` — 支持 ExperimentTracker 查询或 inline JSON
- **涉及文件**: `qp/validation/checks/process_checks.py`

---

### 4.3 ValidationPipeline — RuleEngine 包装为 BasePipeline

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §11 Phase 1
- **已实现**: `ValidationPipeline(BasePipeline)` — 生命周期感知（6 个 stage 自动选配 checks）+ `ValidationPipelineConfig` 阈值覆盖
- **涉及文件**: `qp/validation/pipeline.py`

---

### 4.4 CLI 入口

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: CLAUDE.md "CLI name is qp — all operations go through it"
- **已实现**: `qp validate --stage <stage> --strategy-id <id> --json` — 阶段选择 + 阈值覆盖 + JSON 输出
- **涉及文件**: `qp/platform/cli/main.py`

---

## 六、实现顺序建议

```
Week 1 ─ P1 核心检查（3 项）
  ├── 1.1  NeutralizationCheck（行业/市值中性化）
  ├── 1.2  MinSamplePeriodCheck（≥3 年）
  └── 1.3  CostAdjustedCheck（交易成本后验证）

Week 2 ─ P2 Paper Trading 检查 + Shadow→Prod（5 项）
  ├── 2.1  SignalCorrelationCheck
  ├── 2.2  SlippageDeviationCheck
  ├── 2.3  SignalInterruptionCheck
  ├── 3.1  KillSwitchHistoryCheck
  └── 3.2  HighVolSurvivalCheck

Week 3 ─ P3 流程串联（4 项）
  ├── 4.3  ValidationPipeline
  ├── 4.4  CLI 入口
  ├── 4.1  CodeReviewCheck
  └── 4.2  ExperimentRecordCheck
```

---

## 七、完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 1.1 NeutralizationCheck | 新增 `NeutralizationCheck(min_ratio=0.5)`，检验中性化后 IC 保留率 ≥ 50% |
| 2026-07-22 | 1.2 MinSamplePeriodCheck | 新增 `MinSamplePeriodCheck(min_years=3.0)`，从 train_start/end 计算年跨度 |
| 2026-07-22 | 1.3 CostAdjustedCheck | 新增 `CostAdjustedCheck`，对比 net/gross Sharpe/MaxDD + total_cost_pct fallback |
| 2026-07-22 | 配套 | `validation/__init__.py` 更新导出；新增 `tests/unit/test_validation_checks.py`（50→70 项测试） |
| 2026-07-22 | 2.1 SignalCorrelationCheck | 新增 `SignalCorrelationCheck(min_correlation=0.8)` — 每日截面 Spearman 相关性 |
| 2026-07-22 | 2.2 SlippageDeviationCheck | 新增 `SlippageDeviationCheck(max_deviation_pct=0.50)` — 对比实际 vs 假设 bps |
| 2026-07-22 | 2.3 SignalInterruptionCheck | 新增 `SignalInterruptionCheck(max_consecutive_missing=2)` — 连续缺失 + 比例双阈值 |
| 2026-07-22 | 3.1 KillSwitchHistoryCheck | 新增 `KillSwitchHistoryCheck()` — 支持直接 count 或嵌套 `paper_trading_metrics` |
| 2026-07-22 | 3.2 HighVolSurvivalCheck | 新增 `HighVolSurvivalCheck(max_dd_during_high_vol=25.0)` — 高波动天 + DD 双条件 |
| 2026-07-22 | 配套 | 新增 `paper_trading_checks.py`（3 check）+ `production_checks.py`（2 check），exports 14 个 check |
| 2026-07-22 | 4.1 CodeReviewCheck | 新增 `CodeReviewCheck()` — 支持 metadata flag 或 `.reviewed` 文件 |
| 2026-07-22 | 4.2 ExperimentRecordCheck | 新增 `ExperimentRecordCheck()` — 支持 ExperimentTracker 或 inline JSON |
| 2026-07-22 | 4.3 ValidationPipeline | 新增 `ValidationPipeline(BasePipeline)` — 6 stage 自动选配 checks + 阈值覆盖 |
| 2026-07-22 | 4.4 CLI | `qp validate` 升级为 `--stage` / `--strategy-id` / `--json` 三选项 |
| 2026-07-22 | 配套 | 新增 `process_checks.py`（2 check）+ `pipeline.py`；测试 70→80 项 |
