# DP-007: Simulation Layer (L7)

> Design Proposal — 纸交易、影子交易、回测执行模拟

## 职责

在不影响实盘的情况下评估策略和组合。包括：
- 纸交易（30 天验证）
- 影子交易（与实盘持仓同步，每日运行）
- 回测执行模拟

## 模块

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `simulation/broker.py` | `SimulatedBroker`, `Position`, `Trade` | 模拟券商：订单执行、持仓管理 |
| `simulation/slippage.py` | `FixedSlippage`, `SqrtImpactModel`, `VolatilitySlippage` | 滑点模型（3 种） |
| `simulation/result.py` | `SimulationResult` | 模拟结果 |
| `simulation/shadow_ledger.py` | `ShadowLedger` | 影子账本（与实盘同步的模拟组合） |

## 关键设计

- `SimulatedBroker` 实现 `BaseBroker` 协议，与真实券商接口互换
- 影子账本每日自动运行（`DailyPipeline` Step 12.8）
- 滑点模型可插拔（固定/平方根/波动率）

## 依赖

- **依赖**: L1 (Platform), L6 (Portfolio)
- **被依赖**: L8 (Decision)
