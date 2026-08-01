# DP-005: Strategy Layer (L5)

> Design Proposal — 投资策略，输出 Decisions 而非 Orders
> 关联 ADR: 026, 027, 028

## 职责

将研究产物（因子 + 模型）转化为可交易信号。策略负责机会，风控负责生存。

## 子模块

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `strategy/signal/` | 4 | `SignalGenerator`, `GeneratorConfig` | 信号生成 |
| `strategy/ensemble/` | 2 | `EnsembleEngine`, `WeightEngine`, `WeightMethod` | 多因子集成融合 |
| `strategy/runner/` | 1 | 策略执行器 | 运行策略并产生结果 |
| `strategy/strategies/` | 5 | 具体策略 | 动量、低波等策略实现 |
| `strategy/models/` | 2 | `AlphaSignal`, `AlphaSignalBatch`, `StrategyResult` | 策略领域模型 |

## 核心类（顶层）

| 类 | 文件 | 功能 |
|----|------|------|
| `StrategyRegistry` | `strategy/registry.py` | 策略注册表（APPROVED → RESEARCH 回退） |
| `StrategyLoader` | `strategy/loader.py` | 策略加载器 |
| `MarketRegimeDetector` | `strategy/market_regime.py` | 8 种市场状态检测 |
| `MultiFactorStrategy` | `strategy/multifactor.py` | 多因子策略主类 |
| `PaperTradingTracker` | `strategy/paper_trading.py` | 30 天纸交易追踪 |
| `StrategyConfig` | `strategy/config.py` | 策略配置（回测/实盘一致） |

## 关键设计决策

- **ADR-026**: 策略产出 Decision，不产出 Order
- **ADR-027**: 模型在策略之前结束
- **ADR-028**: 策略优于算法

## 依赖

- **依赖**: L1 (Platform), L3 (Research), L4 (Validation)
- **被依赖**: L6 (Portfolio), L7 (Simulation)
