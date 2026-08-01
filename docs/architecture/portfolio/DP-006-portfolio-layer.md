# DP-006: Portfolio Layer (L6)

> Design Proposal — 组合构建、风险控制、资金分配
> 关联 ADR: 029, 030

## 职责

合并了三层职责（ADR-029, ADR-030）：
- 组合构建（Portfolio Construction）
- 风险控制（Risk Control）
- 资金分配（Capital Allocation）

## 子模块

| 子模块 | 文件数 | 核心类 | 功能 |
|--------|--------|--------|------|
| `portfolio/allocator/` | 5 | `EqualWeightAllocator`, `KellyAllocator`, `RiskParityAllocator`, `VolatilityTargetAllocator` | 资金分配策略 |
| `portfolio/optimization/` | 1 | `PortfolioOptimizer` | 组合优化 |
| `portfolio/constraints/` | 1 | `TrimAndRefill` | 换仓限制 |
| `portfolio/exposure/` | 3 | `FactorExposureAnalyzer`, `MarketCapExposure`, `LiquidityExposure` | 风险暴露分析 |
| `portfolio/sizing/` | 2 | 仓位计算 | 个股权重 |
| `portfolio/budget/` | 3 | `RiskBudget`, `VaRBudget`, `CVaRBudget` | 风险预算 |
| `portfolio/cash/` | 2 | `CashManager`, `CashDecision` | 现金管理 |
| `portfolio/models/` | 4 | `AllocationResult`, `PortfolioState` | 组合模型 |

## 核心类（顶层）

| 类 | 功能 |
|----|------|
| `CapitalAllocator` | 资金分配引擎 |
| `PortfolioRiskManager` | 组合风控（单票/行业/相关性） |
| `RiskExitManager` | 退出信号（止损/ST/退市） |
| `CostModel` | 交易成本模型 |
| `PortfolioMetrics` | 组合绩效（Sharpe, MaxDD, Alpha） |
| `NAVLedger` | NAV 历史账本 |
| `CorrelationAnalyzer` | 相关性分析 |
| `IndustryMapper` | 行业分类映射 |

## 关键设计决策

- **ADR-029**: 组合拥有风控（不再分拆）
- **ADR-030**: 资金分配是组合的责任

## 依赖

- **依赖**: L1 (Platform), L5 (Strategy)
- **被依赖**: L7 (Simulation), L8 (Decision)
