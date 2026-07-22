# Portfolio Risk Layer 差距追踪文档

> 对照 `docs/7_Portfolio_Risk_Layer.md`，逐项追踪 Layer 7（Portfolio Risk）的待实现项。
> 最后更新：2026-07-22（全部完成 ✅）

---

## 状态说明

- ⬜ `[ ]` 待实现
- 🟡 `[~]` 部分实现，有缺陷
- ✅ `[x]` 已完成

---

## 一、模块一：Exposure Analysis（暴露分析）

### 1.1 Sector Exposure（行业暴露）

- **状态**: `[x]` ✅ 已完成
- **已实现**: `IndustryMapper.get_sector_weights()` + `PortfolioRiskManager` 行业上限检查
- **不足**: 硬编码 18 只股票，Phase 4 才升级
- **涉及文件**: `qp/portfolio/industry.py`, `qp/portfolio/risk_manager.py`

### 1.2 Market Cap Exposure（市值暴露）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `MarketCapExposure` — 三档分类（large≥50B/mid≥10B/small）+ `analyze()` 组合分布 + `check_small_cap_limit()` + 已集成到 `PortfolioRiskEngine._analyze_exposures()`
- **涉及文件**: `qp/portfolio/exposure/marketcap_exposure.py`

### 1.3 Factor Exposure（因子暴露）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `FactorExposureAnalyzer` — 3 因子（momentum/volatility/size）ex-ante 暴露 + cross-sectional Z-score 标准化 + `portfolio_exposure()` 加权 + `bias_report()` 偏差检测 + 已集成到 Engine
- **涉及文件**: `qp/portfolio/exposure/factor_exposure.py`

### 1.4 Liquidity Exposure（流动性暴露）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **涉及文件**: `qp/portfolio/exposure/liquidity_exposure.py`

---

## 二、模块二：Correlation Analysis（相关性分析）

### 2.1 Correlation Matrix（相关性矩阵）

- **状态**: `[x]` ✅ 已完成
- **已实现**: `CorrelationAnalyzer.get_correlation_matrix()` — 每日收益率 Pearson 相关矩阵
- **涉及文件**: `qp/portfolio/correlation.py`

### 2.2 Dynamic Clustering（动态层次聚类）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `RiskClusterer` — scipy Agglomerative Clustering（ward/average/complete/single）+ 1-|corr| 距离转换 + dendrogram 自动切割 → 3~5 Risk Cluster + `check_cluster_concentration()` + scipy 不可用时的 threshold fallback
- **涉及文件**: `qp/portfolio/clustering.py`

### 2.3 Diversification 度量

- **状态**: `[x]` ✅ 已完成
- **已实现**: `RiskModel.effective_n()` + `AttributionReport.diversification_score` + `concentration_ratio`
- **涉及文件**: `qp/portfolio/risk_model.py`

---

## 三、模块三：Risk Constraints（风险约束）

### 3.1 个股权重限制

- **状态**: `[x]` ✅ 已完成
- **已实现**: `PortfolioRiskManager` 默认 8%（文档建议 15%），可配置
- **涉及文件**: `qp/portfolio/risk_manager.py`

### 3.2 行业集中度限制

- **状态**: `[x]` ✅ 已完成
- **已实现**: `PortfolioRiskManager` 默认 25%（文档建议 30%），可配置
- **涉及文件**: `qp/portfolio/risk_manager.py`

### 3.3 ST/停牌 + Beta + 小市值 + Top3 硬约束

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: ST/PT 检测（`enable_st_check`）、Beta 约束（`enable_beta_check`）、小市值上限（`max_small_cap`）、Top3 集中度（`max_top3`）— 全部集成到 `PortfolioRiskEngine._apply_constraints()`
- **涉及文件**: `qp/portfolio/portfolio_risk_engine.py`
- **文档出处**: 7_Portfolio_Risk_Layer.md §第三部分 "ST 0%、停牌 0%"
- **要求**: ST/PT/\*ST 股票直接 Reject；停牌股票直接 Reject
- **涉及文件**: 待创建（可并入 constraints 模块）

### 3.4 Beta 约束

- **状态**: `[x]` ✅ 已完成 (2026-07-22) — 合并入 3.3

### 3.5 小市值 + Top3 集中度约束

- **状态**: `[x]` ✅ 已完成 (2026-07-22) — 合并入 3.3

### 3.6 "截断+补位" (Trim & Refill) 机制

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **涉及文件**: `qp/portfolio/constraints/trim_refill.py`

---

## 四、模块四：Risk Budgeting（风险预算）

### 4.1 Inverse Volatility Budget

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **涉及文件**: `qp/portfolio/budget/risk_budget.py`

### 4.2 VaR Budget

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **涉及文件**: `qp/portfolio/budget/var_budget.py`

### 4.3 CVaR Budget

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **涉及文件**: `qp/portfolio/budget/cvar_budget.py`

---

## 五、数据模型

### 5.1 RiskApprovedCandidate

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `RiskApprovedCandidate` dataclass — 7 核心字段 + 4 扩展字段（sector/market_cap/beta/liquidity_score）+ to/from_dict + `rejected()` 工厂方法
- **涉及文件**: `qp/portfolio/models/risk_approved_candidate.py`

### 5.2 RiskReport

- **状态**: `[x]` ✅ 已完成
- **已实现**: `RiskReport` dataclass（6 字段：passed/candidates_in/out/violations/sector_exposure/position_weights/dropped/correlated_pairs）
- **涉及文件**: `qp/portfolio/risk_manager.py`

### 5.3 PortfolioSnapshot

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **涉及文件**: `qp/portfolio/models/portfolio_snapshot.py`

---

## 六、编排引擎

### 6.1 PortfolioRiskEngine

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `PortfolioRiskEngine` + `RiskEngineConfig` — 4 步流水线（Exposure→Clustering→Constraints→Budget）+ `evaluate()`/`evaluate_batch()`/`summary()` + 可配置 limits
- **涉及文件**: `qp/portfolio/portfolio_risk_engine.py`

---

## 七、已有的超额实现（不在文档中但已存在）

| 模块 | 文件 | 说明 |
|---|---|---|
| Mean-Variance Optimizer | `optimizer.py` | Max Sharpe + Ledoit-Wolf + SLSQP |
| Transaction Cost Model | `cost_model.py` | 印花税/佣金/滑点/Almgren-Chriss 冲击成本 |
| Risk Model | `risk_model.py` | 多因子风险分解（Market/Style/Sector/Idio） |
| Attribution Report | `risk_model.py` | Effective N + Diversification Score + Concentration |
| Kelly Allocator | `allocator/kelly.py` | Fractional Kelly 仓位分配 |
| Risk Parity Allocator | `allocator/risk_parity.py` | 逆波动率加权 |
| SinglePortfolio | `single_portfolio.py` | 等权组合 + Order 生成（Walking Skeleton） |
| Correlation Analyzer | `correlation.py` | 成对相关性 + 冗余候选标记 |
| Industry Mapper | `industry.py` | 申万行业映射（18 只股票） |

---

## 八、实现顺序建议

```
Week 1 — P0 核心骨架（3 项）
  ├── 5.1  RiskApprovedCandidate 数据模型
  ├── 2.2  Dynamic Clustering（层次聚类）
  └── 6.1  PortfolioRiskEngine 编排器

Week 2 — P0 暴露分析 + 约束（3 项）
  ├── 1.2  Market Cap Exposure
  ├── 1.3  Factor Exposure
  └── 3.3  ST/停牌 + 3.4 Beta + 3.5 小市值/Top3 硬约束

Week 3 — P1 风险预算（3 项）
  ├── 4.1  Inverse Volatility Budget（独立模块）
  ├── 4.2  VaR Budget
  └── 3.6  "截断+补位" (Trim & Refill) 机制

Week 4 — P2 收尾（3 项）
  ├── 1.4  Liquidity Exposure
  ├── 5.3  PortfolioSnapshot
  └── 4.3  CVaR Budget
```

---

## 九、完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 5.1 RiskApprovedCandidate | 新增 `RiskApprovedCandidate` dataclass（7+4 字段）+ to/from_dict + `rejected()` 工厂 |
| 2026-07-22 | 2.2 Dynamic Clustering | 新增 `RiskClusterer` — scipy 层次聚类 + correlation→distance + dendrogram 自动切割 |
| 2026-07-22 | 6.1 PortfolioRiskEngine | 新增 `PortfolioRiskEngine` + `RiskEngineConfig` — 4 步流水线编排 |
| 2026-07-22 | 1.2 MarketCapExposure | 新增 `MarketCapExposure` — 三档分类 + 组合分布 + `check_small_cap_limit()` + 集成到 Engine |
| 2026-07-22 | 1.3 FactorExposure | 新增 `FactorExposureAnalyzer` — 3 因子 ex-ante 暴露 + Z-score + bias_report |
| 2026-07-22 | 3.3-3.5 硬约束 | 新增 ST/PT + Beta + small-cap + Top3 约束到 `_apply_constraints()`；`enable_beta_check` |
| 2026-07-22 | 4.1 VolatilityBudget | 新增 `VolatilityBudget(RiskBudget)` — 逆波动率 + target_vol 缩放 + cluster budgets |
| 2026-07-22 | 4.2 VaRBudget | 新增 `VaRBudget` — historical/parametric VaR + position_limits |
| 2026-07-22 | 3.6 Trim & Refill | 新增 `TrimAndRefill` — 梯度截断 + 低相关补位机制 |
| 2026-07-22 | 1.4 LiquidityExposure | 新增 `LiquidityExposure` — ADV 评分 + 三档分类 + Days to Liquidate |
| 2026-07-22 | 5.3 PortfolioSnapshot | 新增 `PortfolioSnapshot` — 20 字段组合快照 + `from_engine_output()` 工厂 |
| 2026-07-22 | 4.3 CVaRBudget | 新增 `CVaRBudget` — historical/parametric CVaR + CVaR/VaR 比率 + position_limits |
| 2026-07-22 | 配套 | 测试 799→809（+10 项） |
