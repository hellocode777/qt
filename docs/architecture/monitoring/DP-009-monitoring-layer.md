# DP-009: Monitoring Layer (L9)

> Design Proposal — 只观察不决策

## 职责

全维度安全监控。**铁律：监控层绝不修改任何决策或持仓。**

## 模块

| 文件 | 核心类 | 功能 |
|------|--------|------|
| `monitoring/alerts.py` | `AlertManager` + 7 通道 | 告警（Terminal, Log, Telegram, Email, DingTalk, WeCom, File） |
| `monitoring/drift.py` | `DriftMonitor`, `DriftReport` | 特征/预测分布漂移（PSI） |
| `monitoring/kill_switch.py` | `KillSwitch` | 7 个熔断触发器 |
| `monitoring/kill_switch_pipeline.py` | `KillSwitchPipeline` | 熔断管道 |
| `monitoring/model_decay.py` | `ModelDecayDetector` | 模型 IC 衰减检测 |
| `monitoring/model_decay_lifecycle.py` | `ModelDecayLifecycle` | 衰减 → 策略降级联动 |
| `monitoring/regime.py` | `MarketRegimeEngine` | 8 种市场状态 |
| `monitoring/strategy_monitor.py` | `StrategyMonitor`, `StrategyHealth` | 策略健康监控 |
| `monitoring/strategy_health_logger.py` | `StrategyHealthLogger` | 健康分持久化 |
| `monitoring/strategy_health_report.py` | `StrategyHealthReport` | 健康报告生成 |
| `monitoring/online_monitor.py` | `OnlineSignalMonitor` | 在线信号质量检查 |
| `monitoring/system_state.py` | `SystemStateManager` | 系统状态机 |
| `monitoring/retrain_signal.py` | RetrainSignal | 重训信号触发 |

## 熔断体系

### 触发器（按优先级）

| 优先级 | 触发器 | 条件 | 动作 |
|--------|--------|------|------|
| 10 | AbnormalTurnover | 单日换手 > 80% 持仓 | FULL_STOP |
| 15 | WeeklyDrawdown | 周回撤 > 5% | HALT_BUY |
| 20 | Drawdown | 回撤 > 历史最大 ×1.5 | HALT_BUY |
| 25 | PortfolioDrawdown | 月回撤 > 15% | HALT_BUY |
| 30 | ConsecutiveLoss | 连续 5 日负 PnL | WARNING |
| 40 | ModelDecay | IC 衰减至 30% 以下 | WARNING |
| 50 | PSI | 特征 PSI ≥ 0.25 | WARNING |

### 状态级别

```
NORMAL → WARNING → HALT_BUY → FULL_STOP
```

## 依赖

- **依赖**: L1 (Platform), L5 (Strategy), L8 (Decision) — 只读
- **被依赖**: 无 — 监控只观察
