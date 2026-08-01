# 策略冻结 & 研究/生产分离 — 实施路线图

> 创建：2026-07-31
> 关联：ADR-031（Research/Production 分离）

---

## 总览

```
当前状态                    目标状态
────────                    ────────
Daily 每次全量算15因子        Daily 加载冻结权重 → 增量算5因子
Daily 跑 Gate（全fail）       Daily 不跑 Gate
策略在内存中、进程退出即消失       策略持久化为 ApprovedStrategy 快照
无 online monitoring           Rolling IC + PSI + Drawdown 每日检查
```

## Step 1 — StrategyMeta 扩展

**目标**：`StrategyMeta` 能存储冻结版本所需的所有信息。

**改动**：
```python
@dataclass
class StrategyMeta:
    # 现有字段...
    strategy_version: str = "1.0.0"
    owner: str = ""
    description: str = ""

    # 新增 — 冻结权重
    weights: dict[str, float] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)  # top_n, rebalance, filters

    # 新增 — 回测摘要
    backtest_ic: float = 0.0
    backtest_sharpe: float = 0.0
    backtest_max_dd: float = 0.0
    backtest_excess_return: float = 0.0
```

**文件**：`qp/strategy/registry.py`

**验证**：`to_dict()` / `from_dict()` 往返序列化

---

## Step 2 — ApprovedStrategy 不可变快照

**目标**：创建一个数据类，代表"已批准上线"的冻结策略。

**改动**：
```python
@dataclass(frozen=True)  # 不可变
class ApprovedStrategy:
    strategy_id: str
    version: str
    approved_at: datetime
    approved_by: str
    weights: dict[str, float]
    parameters: dict[str, Any]
    backtest_summary: dict[str, float]
    validation_report_id: str
```

**文件**：`qp/strategy/approved.py`（新文件）

**验证**：JSON 序列化往返

---

## Step 3 — Registry 持久化 + 审批操作

**目标**：`StrategyRegistry` 支持冻结策略的持久化和版本管理。

**改动**：
- `approve(strategy_id, approved_by)` → 从 experiment 结果创建 `ApprovedStrategy` 快照
- `load_active()` → 返回当前活跃的 ApprovedStrategy（或列表）
- `deactivate(strategy_id)` → 将旧版本标记为非活跃
- `_save_approved()` / `_load_approved()` → 写入 `data/strategy_registry.json`

**文件**：`qp/strategy/registry.py`

**持久化格式**：
```json
{
  "strategies": {
    "momentum_vol_full": {
      "lifecycle": "approved",
      "approved_version": "v20260731",
      "active": true,
      "approved_at": "2026-07-31T21:00:00Z",
      "approved_by": "researcher",
      "weights": {"Amplitude_5D": -0.252, ...},
      "parameters": {"top_n": 10, "rebalance": 20, ...},
      "backtest_summary": {"ic": 0.08, "sharpe": 1.03, "max_dd": 8.9}
    }
  }
}
```

---

## Step 4 — CLI: `qp strategy approve`

**目标**：将实验通过的策略正式冻结上线。

**命令**：
```bash
# 从 experiment 结果创建 ApprovedStrategy
qp strategy approve momentum_vol_full \
  --from-experiment multifactor_20260731_095738 \
  --by "researcher"

# 列出所有已批准策略
qp strategy approved list

# 查看冻结快照
qp strategy approved show momentum_vol_full

# 切换活跃版本
qp strategy activate momentum_vol_full --version v20260731

# 下线
qp strategy deactivate momentum_vol_full
```

**文件**：`qp/platform/cli/commands/strategy.py`（新文件或扩展 existing）

---

## Step 5 — Daily Pipeline 重构

**目标**：Daily pipeline 不再做研究，只做执行。

**改动**：

```
移除：
  - compute_cross_sectional_scores（全量历史因子计算）
  - ValidationPipeline / ValidationPipelineConfig
  - _build_validation_context
  - Quality Gate（基于历史验证分）
  - StrategyLoader（动态发现）

新增：
  + registry.load_active() → 获取 ApprovedStrategy
  + _compute_daily_scores(price_data, weights) → 增量因子计算
  + _check_data_health() → 数据完整性检查
  + _check_signal_drift() → 信号漂移检查（online monitoring）

保留：
  ✓ 市场状态检测（RegimeDetector）
  ✓ 风控过滤（RiskFilter）
  ✓ 信号融合（EnsembleEngine）
  ✓ DecisionPackage 生成
```

**文件**：`qp/pipeline/daily_pipeline.py`

**预期性能**：~15 分钟 → ~2 分钟

---

## Step 6 — Online Monitoring 模块

**目标**：每日检查已上线策略是否出现信号衰减。

**新增检查**：

| 检查 | 指标 | 阈值 | 动作 |
|------|------|------|------|
| Rolling IC | 近 20 日 Rank IC | < 0.02 | WARNING |
| Rolling IC | 近 60 日 Rank IC | < 0.01 | HALT |
| PSI Drift | 因子分布 PSI | > 0.25 | WARNING |
| Signal Concentration | Top-3 行业占比 | > 60% | WARNING |
| Drawdown | 近 20 日回撤 | > 历史 1.5x | HALT |

**区别于 Research Validation**：
- Research 在实验时一次性验证（Sharpe, overfit, PurgedCV）
- Online 在 daily 运行时持续监控（rolling IC, PSI, drawdown）
- Online 失败不会删除策略，只会触发警告/降级/暂停买入

**文件**：`qp/monitoring/online_monitor.py`（新文件）

---

## Step 7 — 迁移：momentum_vol_full 首次冻结

**目标**：将当前已验证的 `momentum_vol_full` 提升为第一个 `ApprovedStrategy`。

**步骤**：
1. 从最新 experiment 结果读取回测指标
2. 从 `StrategyConfig` 读取权重和参数
3. 运行 `qp strategy approve momentum_vol_full --from-experiment <id>`
4. 验证 `data/strategy_registry.json` 中包含完整快照
5. 运行 `qp run daily` → 确认从 Registry 加载而非重算

---

## 优先级

| 步骤 | 优先级 | 原因 |
|------|--------|------|
| Step 1+2 | P0 | 基础设施，后续步骤依赖 |
| Step 3 | P0 | Registry 持久化是分离的基础 |
| Step 5 | P0 | 解决当前 daily pipeline 的架构问题 |
| Step 7 | P1 | 让当前策略立即受益 |
| Step 4 | P1 | 提供审批 CLI |
| Step 6 | P2 | 可以在 Step 5 完成后逐步添加 |
