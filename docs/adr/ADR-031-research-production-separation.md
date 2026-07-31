# ADR-031: Research 与 Production 彻底分离

- **状态**：提议
- **日期**：2026-07-31
- **决策者**：QP 项目
- **关联**：ADR-023（Validation is Gate）、ADR-025（Only Validation Can Promote Strategy）、ADR-026（Strategy Produces Decision）

---

## 上下文

当前 Daily Pipeline（`qp run daily`）在运行时：

1. 从头计算全部 15 个因子的历史序列（~15 分钟）
2. 用默认等权权重合成 score（非实验验证版本）
3. 运行 Validation Gate（但 context 缺少历史数据，全部得 0 分）
4. 依赖 Quality Gate 决定今天是否交易（但 Gate 永远拦截）

这违反了研究/生产的边界：

- **Research** 问："这个策略值不值得上线？"（需要 IC、Sharpe、PurgedCV、Overfit）
- **Production** 问："这个已上线的策略，今天还能继续运行吗？"（需要数据健康、市场状态、信号漂移）

两者是**完全不同的系统**，不应混在同一个 pipeline 中。

## 决策

### 1. 新增 `APPROVED` 生命周期状态

```
RESEARCH → BACKTEST_PASSED → PAPER_TRADING → APPROVED → PRODUCTION
                                                    ↑
                                              新增：冻结版本
```

`APPROVED` 的策略是**不可变快照**（Frozen Strategy），包含：

```python
@dataclass
class ApprovedStrategy:
    strategy_id: str
    version: str
    approved_at: datetime
    approved_by: str
    weights: dict[str, float]           # 冻结因子权重
    parameters: StrategyParameters       # top_n, rebalance, filters
    backtest_summary: BacktestSummary    # IC, Sharpe, MaxDD
    validation_report: ValidationReport  # Gate 完整结果
```

Daily pipeline 只读取 `ApprovedStrategy`，不做任何研究计算。

### 2. Daily Pipeline 职责重新定义

```
Daily Pipeline（新版）
    │
    ├── Step 1: 数据健康检查     ← 新增
    ├── Step 2: 加载 Approved Strategy（从 Registry）
    ├── Step 3: 市场状态检测     ← 保留
    ├── Step 4: 今日信号生成     ← 增量计算，非全量
    ├── Step 5: Online Monitoring ← 新增（rolling IC, PSI）
    └── Step 6: DecisionPackage  ← 保留
```

**移除**：
- 因子计算（`compute_cross_sectional_scores` — 全量历史重算）
- Validation Gate（实验阶段专属）
- StrategyLoader 动态发现（改为 Registry 加载）
- Quality Gate 基于历史验证分（改为 Online Monitoring）

### 3. 策略升级流程

```
实验通过 → 创建 ApprovedStrategy 快照 → 写入 Registry
                                              │
                                              ▼
                                    Daily Pipeline 自动加载
                                    （无需重启、无感知切换）
```

v2 替代 v1 时：
```
v1 (active=false)  →  v2 (active=true)
                          │
                          ▼
                    Daily 下次运行自动用 v2
```

### 4. Online Monitoring vs Research Validation

| | Research Validation（Experiment） | Online Monitoring（Daily） |
|---|---|---|
| 问题 | 策略值得上线吗？ | 策略今天还能继续运行吗？ |
| 检查 | IC, Sharpe, MaxDD, Overfit | Rolling IC, PSI, Drawdown |
| 数据 | 历史回测区间 | 最近 N 个交易日 |
| 失败 | 策略被拒绝 | 触发警告/降级 |
| 频率 | 一次性（实验时） | 每次 daily 运行 |

## 后果

### 正面

- Daily pipeline 从 ~15 分钟降到 ~2 分钟（增量计算替代全量）
- 生产环境不跑研究代码 → 不可能出现"今天 IC 算不出来所以不交易"
- 策略版本可追溯、可审计（每次决策对应一个 ApprovedStrategy 快照）
- 策略升级无感知（Registry 切换，Daily 自动跟随）

### 负面

- 需要维护 `ApprovedStrategy` 快照的持久化
- 需要新增 Online Monitoring 模块（不同于现有 Validation Gate）
- 策略升级需要显式的"审批"步骤（`qp strategy approve`）
- 向后兼容：旧的 `StrategyLoader` 和实验策略需要迁移路径

### 风险

- 如果 ApprovedStrategy 快照与实际市场状态不符（因子衰退未被检测），可能持续产生低质量信号
- 缓解：Online Monitoring 的 rolling IC 检查会在信号衰退时触发警告

---

## 实施步骤

详见 `docs/strategy_freeze_roadmap.md`。

1. **StrategyMeta 扩展** — 添加 `weights`, `parameters`, `backtest_summary` 字段
2. **ApprovedStrategy 数据类** — 不可变快照 + 序列化
3. **Registry 持久化升级** — 支持 `approve()`, `load_active()`, `deactivate()`
4. **CLI: `qp strategy approve`** — 实验 → 审批 → 冻结
5. **Daily Pipeline 重构** — 移除 Gate、全量计算；改为加载 Approved + 增量
6. **Online Monitoring 模块** — Rolling IC, PSI, 信号漂移检测
7. **迁移** — 将 `momentum_vol_full` 提升为第一个 ApprovedStrategy





Registry 新增能力：

┌───────────────────────┬───────────────────────────────────────────────────────────────────┐
│         方法          │                               功能                                │
├───────────────────────┼───────────────────────────────────────────────────────────────────┤
│ approve(id, by)       │ 从 StrategyMeta 创建 ApprovedStrategy 快照 → 设 APPROVED → 持久化 │
├───────────────────────┼───────────────────────────────────────────────────────────────────┤
│ load_active()         │ 返回所有活跃的 ApprovedStrategy（跨进程可用）                     │
├───────────────────────┼───────────────────────────────────────────────────────────────────┤
│ load_active_as_meta() │ 返回活跃策略的 StrategyMeta（Daily Pipeline 可直接构建策略）      │
├───────────────────────┼───────────────────────────────────────────────────────────────────┤
│ get_approved(id)      │ 获取单个 ApprovedStrategy 快照                                    │
├───────────────────────┼───────────────────────────────────────────────────────────────────┤
│ deactivate(id)        │ 下线策略，保留快照供审计                                          │
└───────────────────────┴───────────────────────────────────────────────────────────────────┘

完整流程：
注册 → 设 weights/回测指标 → approve() → APPROVED + 持久化
                                              │
                                      新进程 StrategyRegistry()
                                              │
                                      load_active() → 拿到冻结快照
