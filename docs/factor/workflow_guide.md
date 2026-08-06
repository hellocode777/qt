# 因子研究 → 策略上线 操作手册

## 概述

QP 系统将量化投资流程拆为两个平面：

- **Factor Research Plane（因子研究层）**：低频，回答"这个因子有没有 Alpha？"
- **Factor Execution Plane（因子执行层）**：高频，回答"今天每只股票的因子值是多少？"

本手册覆盖从因子研究到策略上线的完整链路。

---

## 1. 因子研究

### 1.1 查看已有因子库

```bash
# 列出所有因子及其生命周期状态、IC、IR
qp factor list

# 按类别查看
qp factor catalog
```

当前系统内置 **19 个量价因子**，分为 4 个大类：

| 类别 | 因子 |
|------|------|
| Momentum | Short_Term_Reversal_5D, Momentum_1M, Momentum_3M, Momentum_6M, Momentum_3M_vol_adj, Trend_MA120, Residual_Momentum_3M |
| Volatility | Volatility_20D, Volatility_60D, MaxDD_60D |
| Volume | Volume_Ratio_5D, Volume_Trend_10D, Price_Volume_Corr, Volume_Price_Trend, Volume_Expansion_20_120, Amount_Momentum_20_120 |
| Money Flow | Amplitude_5D, Volume_Concentration, Implied_Net_Flow |

### 1.2 验证单个因子

```bash
# 对全量历史数据计算 Rank IC、IC_IR、t-stat
qp factor validate Momentum_3M
```

输出示例：

```
=== Factor Validation: Momentum_3M ===
  Expected direction: -1

  Data source: full daily price (2015-01-05 ~ 2026-08-06)
  Stocks:      3075

  IC Mean              -0.0523
  IC IR                0.92
  IC t-stat            4.81
  IC Std               0.0521
  IC>0%                24.3%
  N Days               2712

  ✅ Rank IC ≥ 0.02    0.0523
  ✅ IC IR ≥ 0.30      0.92
  ✅ IC t-stat ≥ 2.0   4.81
  ❌ IC>0% ≥ 50%       24.3%
  ✅ Direction match   matches

  Passed: 4/5 checks
  ⚠️ Factor needs improvement — keep in RESEARCH stage
```

判断标准：

| 指标 | 阈值 | 说明 |
|------|------|------|
| IC Mean | ≥ 0.02 | 因子和未来收益的 Rank 相关性 |
| IC IR | ≥ 0.30 | IC 的稳定性（Mean/Std） |
| IC t-stat | ≥ 2.0 | 统计显著性 |
| IC>0% | ≥ 50% | IC 为正的天数占比 |
| Direction | 与预期一致 | IC 符号是否匹配预期方向 |

### 1.3 批量更新因子健康状态

```bash
# 对所有 19 个因子跑全量 IC 评估，更新生命周期
qp factor update-health
```

输出到 `data/monitoring/factor_health.parquet` 和 `factor_ic_series.parquet`。

### 1.4 查看因子详情

```bash
# 单个因子健康报告
qp factor health Momentum_3M

# 生成 Markdown 研究报告
qp factor report Momentum_3M
```

Web UI 也可以看：`GET /health/factors` 和 `/health/factors/{name}`

### 1.5 因子生命周期

```
RESEARCH → VALIDATED → PRODUCTION → WEAKENING → DEGRADED → RETIRED → ARCHIVED
```

- **RESEARCH → VALIDATED**：IC 和 IC_IR 连续 20 天达标
- **VALIDATED → PRODUCTION**：通过完整 Validation Gate
- **PRODUCTION → WEAKENING**：IC 持续衰减 15 天以上
- **PRODUCTION → DEGRADED**：衰减持续 30 天或 IC_IR 腰斩
- **DEGRADED → RETIRED**：IC 低于 0.01 持续 60 天

---

## 2. 设计策略

### 2.1 策略配置文件

在 `qp/strategy/strategies/` 下创建策略文件。以 `momentum_vol_full.py` 为模板：

```python
"""my_strategy.py — 自定义多因子策略"""

from qp.strategy.config import StrategyConfig, register_config

MY_STRATEGY = StrategyConfig(
    name="my_strategy",
    display_name="我的策略 V1",
    factors={
        # 从因子研究结果中选取，按 IC 贡献分配权重
        "Momentum_3M":          -0.30,   # IC=-0.052, 方向为负
        "Volatility_20D":       0.25,    # IC=+0.038, 低波异象
        "Amplitude_5D":        -0.25,    # IC=-0.041
        "Volume_Concentration": -0.20,   # IC=-0.035
    },
    max_positions=10,
    rebalance_freq=20,
    sell_buffer_multiplier=1.5,
    quality_filter=True,
    industry_neutral=True,
    anti_chase=True,
    use_market_filter=True,
)

register_config(MY_STRATEGY)
```

### 2.2 权重设计原则

- **IC 越大，权重越大**：按 IC 的绝对值比例分配
- **IC_IR 越高，权重越稳定**：IC_IR 低的因子降权
- **因子方向要匹配**：A 股动量反转（-1），低波异象（+1）
- **不要一次加太多**：从 2-3 个核心因子开始，逐步加

### 2.3 逐步加因子的推荐节奏

```
V1: 2 个因子 → 跑实验 → 看回测
V2: 3 个因子 → 跑实验 → 对比 V1
V3: 4-5 个因子 → 跑实验 → 对比 V2
最终版 → 通过 Gate → 上线
```

---

## 3. 跑实验

### 3.1 运行回测实验

```bash
# 用自定义策略跑全量回测
qp experiment run multifactor --strategy my_strategy

# 跳过 Gate（快速迭代阶段）
qp experiment run multifactor --strategy my_strategy --skip-gate
```

### 3.2 查看实验结果

```bash
# 列出所有实验
qp experiment list

# 查看某个实验详情
qp experiment show <experiment_id>

# 对比两个实验
qp experiment compare <id1> <id2>
```

关键指标：

| 指标 | 说明 | 参考阈值 |
|------|------|---------|
| Sharpe Ratio | 风险调整收益 | ≥ 1.0 |
| Max Drawdown | 最大回撤 | ≤ 25% |
| Annual Return | 年化收益 | ≥ 10% |
| Turnover | 换手率 | 5-200% |
| IC Mean | 因子有效性 | ≥ 0.02 |

### 3.3 实验输出

```
data/experiments/multifactor_<timestamp>/
├── price_data.parquet      # 实验数据快照
├── daily_nav.parquet       # 每日净值曲线
├── trade_log.parquet       # 交易记录
└── <name>_gate.json        # Gate 结果
```

---

## 4. Validation Gate

### 4.1 运行 Gate

```bash
qp validate
```

系统内置 **20 个检查**，分 6 个阶段：

| 阶段 | 检查项 |
|------|--------|
| Factor（10 项） | IC, IC_IR, t-stat, Stratification, Neutralization, Coverage, Missing Rate, Correlation, Turnover, Min Sample |
| Backtest（4 项） | Sharpe, Max Drawdown, Turnover, Cost Adjusted |
| Overfit（2 项） | OOS/IS Ratio, Feature Importance |
| Paper Trading（3 项） | Signal Correlation, Slippage, Signal Interruption |
| Production（2 项） | Kill Switch History, High Vol Survival |
| Process（2 项） | Code Review, Experiment Record |

### 4.2 Gate 结果

```
GateDecision:
  PASSED         → 可以上线
  RESEARCH_ONLY  → 继续研究
  BLOCKED        → 不通过
  OVERRIDDEN     → 人工强制通过
```

---

## 5. 上线

### 5.1 策略状态流转

```
RESEARCH → BACKTEST_PASSED → PAPER_TRADING → APPROVED → PRODUCTION
```

通过 Gate 后策略自动进入 `APPROVED` 状态。

### 5.2 每日生产

```bash
# 完整流程：拉数据 → 算因子 → 策略评分 → 生成决策包
qp run daily

# 跳过数据拉取（已有最新数据）
qp run daily --skip-fetch

# 不拉数据不算因子（最快，用已有因子值）
qp run daily --skip-fetch --skip-factor-calc
```

每日流水线步骤：

```
Step 1:   数据摄入 → daily_price_latest.parquet
Step 1.5: 因子计算 → factor_values_daily.parquet  ← 新增
Step 2:   Feature 计算
Step 3-5: 价格加载、Lineage、市场状态检测
Step 6:   策略注册（自动加载 APPROVED 策略）
Step 7:   质量 Gate
Step 8:   策略执行（优先读 factor_values_daily.parquet）
Step 9:   多策略融合
Step 10:  风险管理
Step 11-12: 成本估算、资金分配
Step 13:  决策包 → data/decisions/dp-{date}-{run_id}.json
```

### 5.3 查看每日决策

```bash
# 决策目录
ls data/decisions/

# 查看最新决策包
cat data/decisions/dp-$(date +%Y-%m-%d)-*.md
```

---

## 6. 因子计算

### 6.1 每日因子计算

```bash
# 增量（默认：最新一天）
qp factor compute

# 指定日期
qp factor compute --date 2026-08-06

# 只算部分因子
qp factor compute --subset Momentum_3M,Volatility_20D

# 全量重建（首次使用或修复时）
qp factor compute --full
```

### 6.2 产出文件

```
data/dataset/factor_values_daily.parquet
```

Schema：`[trade_date: Date, symbol: Utf8, <19 个因子列: f64>]`

---

## 7. 典型工作流示例

```bash
# === 周一：研究新因子 ===
qp factor validate Amplitude_5D        # 验证 IC
qp factor health Amplitude_5D          # 看详细健康状态

# === 周二：设计策略 V1 ===
# 编辑 qp/strategy/strategies/my_v1.py
# factors = {"Momentum_3M": -0.5, "Amplitude_5D": -0.5}

# === 周三：跑实验 ===
qp experiment run multifactor --strategy my_v1 --skip-gate

# === 周四：看结果、调权重 ===
qp experiment list
qp experiment show <id>
# IC 分解发现 Momentum_3M 贡献更大 → 调整权重

# === 周五：V2 加第三个因子 ===
# factors = {"Momentum_3M": -0.35, "Amplitude_5D": -0.35, "Volatility_20D": 0.30}
qp experiment run multifactor --strategy my_v2
qp experiment compare <v1_id> <v2_id>

# === 下周一：通过 Gate → 上线 ===
qp validate
# → PASSED
qp run daily --skip-fetch              # 首次上线
qp run daily                           # 之后每天自动跑
```

---

## 8. 日常运维

```bash
# 每月一次：更新因子健康状态（检测衰减）
qp factor update-health

# 每天：查看决策
ls data/decisions/

# 每周：检查策略健康
qp strategy health

# 出问题时：查看系统状态
qp doctor
```
