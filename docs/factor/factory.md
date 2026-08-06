# Factor Factory — AI Coding Reference

本文档是 QP 因子系统的完整编码参考。AI 在写任何因子相关代码时，必须严格遵循以下全部规范。

---

## 1. Architecture Overview

```
qp/research/feature/          ← 因子定义与计算（原子层）
  ├── compute.py              ← 主入口：compute_all_factors(), 方向/描述注册表
  ├── volatility.py           ← 低波动因子族
  ├── momentum.py             ← 动量/反转因子族
  ├── volume.py               ← 成交量因子族
  ├── money_flow.py           ← 资金流因子族
  ├── quality.py              ← 质量因子族（基本面）
  ├── fundamental.py          ← 基本面因子批量计算
  └── registry.py             ← FeatureRegistry: auto_register_all() / catalog()

qp/strategy/
  ├── multifactor.py          ← compute_cross_sectional_scores(): 截面打分主入口
  ├── factor_composite.py     ← FactorCompositeEngine: 6 大 Alpha Family 合成
  ├── factor_layers.py        ← FACTOR_LAYERS_V2: 四层因子体系 + FactorEnsemble
  └── regime_ensemble.py      ← REGIME_LAYER_WEIGHTS: 市场状态 → 层权重映射

qp/research/
  └── factor_processor.py     ← factor_pipeline(): Winsorize→Normalize→Combine

qp/validation/checks/
  └── factor_checks.py        ← 10 项因子验证 Gate（IC/IR/Coverage/Correlation 等）

qp/monitoring/
  └── factor_health.py        ← FactorHealthMonitor + FactorLifecycle 状态机

qp/shared/protocols/
  └── base_feature.py         ← BaseFeature ABC: 所有因子的抽象基类
```

### 严格边界规则

- **Layer 2 (data/)** — 只产出 Data Products，不计算因子
- **Layer 3 (research/)** — 因子计算 + IC 评估 + 特征工程。永远不直接调用 `ak.stock_zh_a_hist()`
- **Layer 5 (strategy/)** — 因子权重 + 复合 + 层配置。输出 Scores，不输出原始因子值
- **Layer 9 (monitoring/)** — 只观测不决策。输出 health status，不修改权重

---

## 2. 因子定义：两类 API（必须同时实现）

### 2A. BaseFeature 子类（registry 兼容 + 元数据）

```python
# 文件位置: qp/research/feature/<category>.py
from qp.shared.protocols.base_feature import BaseFeature

class MyFactor(BaseFeature):
    """What this factor measures and how."""

    @property
    def feature_name(self) -> str:
        return "My_Factor_Name"           # 必须: 全局唯一标识符

    @property
    def required_data(self) -> list[str]:
        return ["daily_price"]            # 必须: 依赖的 Dataset 名

    def compute(self, data_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
        df = data_map["daily_price"].clone()
        df = df.sort(["symbol", "trade_date"])
        # ... 向量化计算 ...
        df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))
        df = df.drop_nulls(subset=["feature_value"])
        return df.select(["trade_date", "symbol", "feature_value"])

    # ── 以下元数据全部必填 ──
    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "Momentum"
        # Momentum|Volatility|Volume|MoneyFlow|Value|Quality|Growth|Risk|Sentiment|Custom

    @property
    def lookback(self) -> int:
        return 60  # 回看交易日数

    @property
    def direction(self) -> int:
        return +1  # +1=因子值越大越好; -1=因子值越大越差

    @property
    def author(self) -> str:
        return "your-name"

    @property
    def description(self) -> str:
        return "What this factor measures"

    @property
    def neutralize(self) -> list[str]:
        return []  # ["Industry"] | ["MarketCap"] | []

    @property
    def winsorize(self) -> str:
        return "MAD"  # MAD | Percentile | None

    @property
    def normalize(self) -> str:
        return "ZScore"  # ZScore | Rank | MinMax | None
```

### 2B. Batch 计算函数（策略管线调用的高性能版本）

```python
# 同一文件内
MY_FACTOR_DIRECTIONS: dict[str, int] = {
    "My_Factor_Name": +1,
}
MY_FACTOR_DESCRIPTIONS: dict[str, str] = {
    "My_Factor_Name": "描述文字",
}

def compute_my_factors(df: pl.DataFrame) -> pl.DataFrame:
    """对单只股票计算所有 MyCategory 类因子。

    Args:
        df: 单只股票 DataFrame [trade_date, open, high, low, close, volume]，已排序

    Returns:
        [trade_date, Factor_A, Factor_B, ...]，drop_nulls() 后返回
    """
    df = df.sort("trade_date")
    # ... 向量化计算 ...
    # ⚠️ 强制: shift(1) 防未来信息泄漏
    for name in factor_names:
        df = df.with_columns(pl.col(name).shift(1).alias(name))
    return df.select(["trade_date", *factor_names]).drop_nulls()
```

### 2C. 注册到主入口

在 `qp/research/feature/compute.py` 中：

```python
from qp.research.feature.my_category import (
    MY_FACTOR_DESCRIPTIONS,
    MY_FACTOR_DIRECTIONS,
    compute_my_factors,
)

# 合并到主注册表
ALL_FACTOR_DIRECTIONS: dict[str, int] = {
    **MOMENTUM_DIRECTIONS,
    **VOLATILITY_DIRECTIONS,
    **MY_FACTOR_DIRECTIONS,       # ← 新增
    ...
}
ALL_FACTOR_DESCRIPTIONS: dict[str, str] = {
    **MOMENTUM_DESCRIPTIONS,
    **VOLATILITY_DESCRIPTIONS,
    **MY_FACTOR_DESCRIPTIONS,     # ← 新增
    ...
}
PRICE_VOLUME_FACTORS: list[str] = (
    list(MOMENTUM_DIRECTIONS.keys())
    + list(VOLATILITY_DIRECTIONS.keys())
    + list(MY_FACTOR_DIRECTIONS.keys())  # ← 新增
    ...
)

# 在 compute_all_factors() 中加入调用
def compute_all_factors(df, subset=None, index_df=None):
    ...
    my_factors = compute_my_factors(df)  # ← 新增
    result = result.join(my_factors, on="trade_date", how="inner")
    ...
```

---

## 3. 方向 (Direction) 约定 — 最容易出错的地方

### 判定流程

```
1. IC_raw = SpearmanRank(因子值, 未来收益)
2. 如果 direction = +1:  effective_IC = IC_raw       (不翻转)
   如果 direction = -1:  effective_IC = -IC_raw      (翻转)
3. sign(weight) 必须 = sign(effective_IC)
```

### 关键区别

- **BaseFeature.compute()** 产出原始因子值 (feature_value)，不预设方向
- **Batch 函数**（如 `compute_volatility_factors`）产出**已编码方向的因子值**（如波动率用 `-rolling_std` 即取负，使低波=高分），此时 `DIRECTIONS` 必须设为 `+1`（不需再次翻转）
- **factor_pipeline** 中的 `adjust_direction()` 根据 `ALL_FACTOR_DIRECTIONS` 再次翻转

### 一致性检查

- [ ] `ALL_FACTOR_DIRECTIONS[fname]` 与 batch 函数中的符号编码是否一致？
- [ ] 如果 batch 函数已内置方向（如 negated volatility），DIRECTIONS 必须为 `+1`
- [ ] `sign(weight)` 是否与 `sign(effective_IC)` 一致？

---

## 4. PIT (Point-in-Time) 防泄漏 — 强制规则

### 必须 shift(1)

```python
# ✅ 正确: 因子 T 日值仅使用 ≤ T-1 的数据
df = df.with_columns(pl.col("feature_value").shift(1).over("symbol"))

# ❌ 错误: 使用了当日收盘价计算因子，再用当日收盘价算收益
df = df.with_columns(...)  # 无 shift
```

### 前向收益

```python
# ✅ 正确
fwd_return = close.shift(-5) / close - 1  # T+5 vs T
```

---

## 5. 因子处理管线

### factor_pipeline 步骤

```
all_raw: {date: {symbol: {factor_name: value}}}
  │
  ├── Step 0: Orthogonalize (可选) — VIF 检测 → 回归残差
  ├── Step 1-3: Neutralize (可选)
  │     ├── "median": 减去行业内中位数
  │     └── "ols": OLS 回归残差 (Size + Vol + Amount + Industry)
  ├── Winsorize: MAD 或 Percentile 去极值
  ├── Normalize: Rank / ZScore / MinMax
  ├── adjust_direction(): 根据 ALL_FACTOR_DIRECTIONS 翻转符号
  └── Combine: Σ(factor_value × weight) → 截面排名
  │
  └── scores: [trade_date, symbol, score]
```

### 调用

```python
from qp.research.factor_processor import factor_pipeline

scores = factor_pipeline(
    all_factors=all_raw,        # {date: {symbol: {factor: value}}}
    weights=weights,            # {factor_name: weight}
    normalize_method="rank",    # rank | zscore | minmax
    winsorize_method="mad",     # mad | percentile | None
    industry_map=industry_map,  # {symbol: industry_name} | None
    neutralize_method="median", # median | ols | None
    orthogonalize=False,
    return_diagnostics=False,   # True → (scores, diagnostics)
)
```

---

## 6. 因子验证 Gate

10 项检查（`qp/validation/checks/factor_checks.py`）：

| # | Check | 阈值 |
|:-:|-------|:----:|
| 1 | RankICCheck | \|IC\| ≥ 0.02 |
| 2 | ICIrCheck | IC_IR ≥ 0.30 |
| 3 | ICTStatCheck | t ≥ 2.0 |
| 4 | ICPositivePctCheck | IC>0 比例 ≥ 50% |
| 5 | StratificationCheck | Top-Bottom 单调 |
| 6 | NeutralizationSurvivalCheck | 中性化后 IC 保持 ≥ 50% |
| 7 | MinSamplePeriodCheck | ≥ 252 天 |
| 8 | CoverageCheck | ≥ 95% |
| 9 | MissingRateCheck | < 5% |
| 10 | MaxCorrelationCheck | < 0.85 |

---

## 7. 因子生命周期状态机

```
RESEARCH ──→ VALIDATED ──→ PRODUCTION ──→ WEAKENING ──→ DEGRADED ──→ RETIRED ──→ ARCHIVED
  🔬             ✅             🚀             🟠            🔴          💀          📦
```

### 转移条件（`FactorHealthMonitor._classify_state`）

| 转移 | 条件 |
|------|------|
| → PRODUCTION | \|IC_30d\| ≥ 0.02 AND IC_IR ≥ 0.30 AND 连续健康 ≥ 20天 |
| → WEAKENING | \|IC\| still ≥ 0.02 but decay_rate < -0.001 for 15+ days |
| → DEGRADED | decay < -0.001 for 30+ days OR IC_IR drops 50% |
| → RETIRED | \|IC\| < 0.01 for 60+ days OR IC_IR < 0.1 for 60+ days |
| → ARCHIVED | Manual only |

### 权重乘数

| Stage | RESEARCH | VALIDATED | PRODUCTION | WEAKENING | DEGRADED | RETIRED |
|-------|:--------:|:---------:|:----------:|:---------:|:--------:|:-------:|
| Mult. | 0.25 | 0.50 | 1.00 | 0.75 | 0.50 | 0.00 |

---

## 8. Alpha Family 聚类 & Composite Engine

### 6 大 Alpha Family

| Family | Member Factors | Direction |
|--------|---------------|:---------:|
| 低波动 LowVol | Volatility_20D, Amplitude_5D, Volatility_60D | +1 |
| 动量 Momentum | Residual_Momentum_3M, Momentum_3M | -1 |
| 反转 Reversal | Short_Term_Reversal_5D | -1 |
| 成交量 Volume | Volume_Concentration, Volume_Trend_10D | -1 |
| 价值 Value | PE_TTM, PB, PCF_OCF | -1 |
| 质量 Quality | ROE, gross_margin, net_margin, debt_ratio | +1 |

### 复合 = rank-based mean × direction

```python
composite_score = mean(rank(m1), rank(m2), ...) × composite_direction
```

---

## 9. Factor Layer v2 四层体系

```python
FACTOR_LAYERS_V2 = {
    "price_alpha": {"weight": 0.30, ...},   # 量价 alpha
    "value":       {"weight": 0.25, ...},   # 估值锚
    "quality":     {"weight": 0.25, ...},   # 盈利质量
    "growth":      {"weight": 0.20, ...},   # 成长轨迹
}
```

### Regime → Layer Weight Mapping

| Regime | price_alpha | value | quality | growth |
|--------|:----------:|:-----:|:-------:|:------:|
| bull | 35% | 15% | 20% | 30% |
| sideways_up | 30% | 20% | 30% | 20% |
| neutral | 25% | 25% | 25% | 25% |
| sideways_down | 15% | 35% | 30% | 20% |
| bear | 5% | 40% | 35% | 20% |
| crisis | 0% | 50% | 50% | 0% |

---

## 10. 添加新因子：完整 Checklist

### Step 1: 确定类别
- 纯价格/量价 → `qp/research/feature/<category>.py`
- 基本面 → `qp/research/feature/fundamental.py` 或新 `quality.py`
- 估值 → 数据在 Layer 2 已提供，因子通过 `valuation_factor_names` 路由

### Step 2: 实现 BaseFeature 子类
- [ ] `feature_name` — 全局唯一
- [ ] `required_data` — 依赖列表
- [ ] `compute()` — **shift(1)** + drop_nulls + 返回 `[trade_date, symbol, feature_value]`
- [ ] 全部 10 项元数据属性

### Step 3: 实现 batch 计算函数
- [ ] `XXX_DIRECTIONS: dict[str, int]` — 与 BaseFeature.direction 一致
- [ ] `XXX_DESCRIPTIONS: dict[str, str]`
- [ ] `compute_xxx_factors(df)` — 单只股票、向量化、**shift(1)**、**drop_nulls()**
- [ ] 如 batch 函数已内置方向编码，DIRECTIONS 必须为 `+1`

### Step 4: 注册到 compute.py
- [ ] import 三个对象
- [ ] 合并到 `ALL_FACTOR_DIRECTIONS`、`ALL_FACTOR_DESCRIPTIONS`、`PRICE_VOLUME_FACTORS`
- [ ] 在 `compute_all_factors()` 中调用并 join

### Step 5: 注册到 FactorHealthService FAMILY_MAP（推荐）

### Step 6: 验证
- [ ] `uv run ruff check` → 0 errors
- [ ] `uv run pyright` → 0 errors
- [ ] `uv run qp run daily --demo --skip-gate` 端到端跑通
- [ ] IC 方向与预期一致

---

## 11. 常见错误排查

| 症状 | 原因 | 排查 |
|------|------|------|
| IC 符号与预期相反 | direction 设置错误 / batch 函数已内置方向 | 直接用 raw 因子值算 SpearmanR |
| IC 极高（>0.20） | 未来信息泄漏 / 存活性偏差 | 检查 shift(1)；检查 universe |
| 基本面因子 IC≈0 | daily 频率基本面无变化，填值方式问题 | 基本面是季频 ffill，日频 IC 天然低 |
| "factor not found" | 未注册到 compute.py / 未加入 subset | 检查 PRICE_VOLUME_FACTORS |
| Composite 不工作 | 成员因子未在 compute_all_factors 中计算 | 检查 composite 展开逻辑 |

---

## 12. 关键文件速查

| 需求 | 文件 |
|------|------|
| 定义新 BaseFeature | `qp/research/feature/<category>.py` |
| 注册因子 | `qp/research/feature/compute.py` |
| 截面打分入口 | `qp/strategy/multifactor.py` → `compute_cross_sectional_scores()` |
| 因子管线 | `qp/research/factor_processor.py` → `factor_pipeline()` |
| 复合合成 | `qp/strategy/factor_composite.py` → `FactorCompositeEngine` |
| 四层体系 | `qp/strategy/factor_layers.py` → `FACTOR_LAYERS_V2` |
| 市场状态映射 | `qp/strategy/regime_ensemble.py` → `REGIME_LAYER_WEIGHTS` |
| 验证 Gate | `qp/validation/checks/factor_checks.py` |
| 生命周期状态机 | `qp/monitoring/factor_health.py` → `FactorHealthMonitor` |
| 健康持久化 | `qp/monitoring/factor_health_logger.py` → `FactorHealthLogger` |
| 抽象基类 | `qp/shared/protocols/base_feature.py` → `BaseFeature` |
| 健康 Web 服务 | `qp/web/services/factor_health_service.py` → `FactorHealthService` |

---

## 13. 因子资产清单 & 追踪 Checklist

> 状态图例：✅ 完成 · 🔧 进行中 · 📋 计划中 · ❌ 未开始 · 💀 已淘汰 · ⚠️ 需关注

### 13A. 价格/量价因子（15 个）— `PRICE_VOLUME_FACTORS`

#### 动量族 Momentum（5 个）

| # | 因子名 | BaseFeature | Batch计算 | 注册 | 验证 | 生命状态 | 备注 |
|:-:|--------|:-----------:|:---------:|:----:|:----:|:--------:|------|
| 1 | `Short_Term_Reversal_5D` | ✅ | ✅ | ✅ | ✅ | 🔴 DEGRADED | IC_IR 0.20 < 0.30 |
| 2 | `Momentum_1M` | ✅ | ✅ | ✅ | ✅ | 🔬 RESEARCH | 待评估 |
| 3 | `Momentum_3M` | ✅ | ✅ | ✅ | ✅ | 🟠 WEAKENING | 衰减中 |
| 4 | `Momentum_6M` | ✅ | ✅ | ✅ | ✅ | 🔬 RESEARCH | 待评估 |
| 5 | `Momentum_3M_vol_adj` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 波动率调整动量 |

#### 波动率族 Volatility（3 个）

| # | 因子名 | BaseFeature | Batch计算 | 注册 | 验证 | 生命状态 | 备注 |
|:-:|--------|:-----------:|:---------:|:----:|:----:|:--------:|------|
| 6 | `Volatility_20D` | ✅ | ✅ | ✅ | ✅ | 🚀 PRODUCTION | 唯一生产因子，全周期 IC=+0.07 |
| 7 | `Volatility_60D` | ✅ | ✅ | ✅ | ✅ | 🔬 RESEARCH | 待评估 |
| 8 | `MaxDD_60D` | ✅ | ✅ | ✅ | ✅ | 🔬 RESEARCH | 待评估 |

#### 成交量族 Volume（4 个）

| # | 因子名 | BaseFeature | Batch计算 | 注册 | 验证 | 生命状态 | 备注 |
|:-:|--------|:-----------:|:---------:|:----:|:----:|:--------:|------|
| 9 | `Volume_Ratio_5D` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 待评估 |
| 10 | `Volume_Trend_10D` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | IC 微弱，≈0 |
| 11 | `Price_Volume_Corr` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 待评估 |
| 12 | `Volume_Price_Trend` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 待评估 |

#### 资金流族 MoneyFlow（3 个）

| # | 因子名 | BaseFeature | Batch计算 | 注册 | 验证 | 生命状态 | 备注 |
|:-:|--------|:-----------:|:---------:|:----:|:----:|:--------:|------|
| 13 | `Amplitude_5D` | ✅ | ✅ | ✅ | ✅ | 🟠 WEAKENING | 衰减中 |
| 14 | `Volume_Concentration` | ✅ | ✅ | ✅ | ✅ | 🟠 WEAKENING | IC_IR=0.70 但衰减 |
| 15 | `Implied_Net_Flow` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 待评估 |

### 13B. 估值因子（3 个）— `valuation_factor_names`

| # | 因子名 | 数据源 | 注册 | 验证 | 生命状态 | 备注 |
|:-:|--------|--------|:----:|:----:|:--------:|------|
| 16 | `PE_TTM` | ValuationDataProduct | ✅ | ✅ | 🔴 DEGRADED | IC 反转，A 股低 PE 不灵 |
| 17 | `PB` | ValuationDataProduct | ✅ | ✅ | 🔴 DEGRADED | 同上 |
| 18 | `PCF_OCF` | ValuationDataProduct | ✅ | ✅ | 💀 RETIRED | IC_IR=0.09，已淘汰 |

### 13C. 基本面因子（8 个）— `fundamental_factor_names`

| # | 因子名 | 数据源 | 注册 | 验证 | 生命状态 | 备注 |
|:-:|--------|--------|:----:|:----:|:--------:|------|
| 19 | `ROE` | FundamentalAdapter | ✅ | ✅ | 🔴 DEGRADED | 日频 IC 弱 |
| 20 | `revenue_growth` | FundamentalAdapter | ✅ | ✅ | 🔴 DEGRADED | 日频 IC 弱 |
| 21 | `net_profit_growth` | FundamentalAdapter | ✅ | ✅ | 🔴 DEGRADED | 日频 IC 弱 |
| 22 | `gross_margin` | FundamentalAdapter | ✅ | ✅ | 💀 RETIRED | IC_IR=0.01 |
| 23 | `net_margin` | FundamentalAdapter | ✅ | ✅ | 🔴 DEGRADED | 日频 IC 弱 |
| 24 | `debt_ratio` | FundamentalAdapter | ✅ | ✅ | 🔴 DEGRADED | 日频 IC 弱 |
| 25 | `EPS` | FundamentalAdapter | ✅ | ❌ | 🔬 RESEARCH | 待评估 |
| 26 | `NAV` | FundamentalAdapter | ✅ | ❌ | 🔬 RESEARCH | 待评估 |

### 13D. 扩展因子（+5 个）

| # | 因子名 | BaseFeature | Batch计算 | 注册 | 验证 | 生命状态 | 备注 |
|:-:|--------|:-----------:|:---------:|:----:|:----:|:--------:|------|
| 27 | `Residual_Momentum_3M` | ✅ | ✅ | ✅ | ✅ | 🔴 DEGRADED | 市场中性动量 |
| 28 | `ROE_Level` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 截面 ROE 水平 |
| 29 | `Profit_Stability` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | ROE 稳定性 |
| 30 | `Earnings_Quality` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 现金流质量 |
| 31 | `Margin_Composite` | ✅ | ✅ | ✅ | ❌ | 🔬 RESEARCH | 利润率综合 |

### 13E. Composite 合成因子（6 个）

| # | 因子名 | 成员数 | 实现 | 策略集成 | 实验验证 | 结论 | 备注 |
|:-:|--------|:-----:|:----:|:-------:|:--------:|:----:|------|
| C1 | `LowVol_Composite` | 3 | ✅ | ✅ | ✅ | ✅ 有效 | 唯一正贡献 Composite |
| C2 | `Momentum_Composite` | 2 | ✅ | ✅ | ✅ | ❌ 日频无效 | A 股动量反转 |
| C3 | `Value_Composite` | 3 | ✅ | ✅ | ✅ | ❌ 日频无效 | 低 PE 策略在 A 股失效 |
| C4 | `Quality_Composite` | 4 | ✅ | ✅ | ✅ | ❌ 日频无效 | 季频数据日频噪音 |
| C5 | `Volume_Composite` | 2 | ✅ | ✅ | ❌ | 📋 待测 | |
| C6 | `Reversal_Composite` | 1 | ✅ | ✅ | ❌ | 📋 待测 | 目前仅 Short_Term_Reversal_5D |

### 13F. 基础设施 Checklist

#### 已实现 ✅

- [x] `BaseFeature` ABC + 10 项元数据属性
- [x] `compute_all_factors()` 15 因子批量计算
- [x] `ALL_FACTOR_DIRECTIONS` / `ALL_FACTOR_DESCRIPTIONS` 注册表
- [x] `factor_pipeline()` Winsorize → Normalize → Combine
- [x] `compute_cross_sectional_scores()` 截面打分
- [x] `FeatureRegistry` + `auto_register_all()` + `catalog()`
- [x] 10 项因子验证 Gate
- [x] `FactorLifecycle` 状态机（7 状态）
- [x] `FactorHealthMonitor` + 衰减/IC_IR/连续天检测
- [x] `FactorHealthLogger` → Parquet 持久化
- [x] `FactorHealthService` + WebUI 因子健康页
- [x] `FactorCompositeEngine` + 6 Composite
- [x] `FACTOR_LAYERS_V2` 四层体系
- [x] `REGIME_LAYER_WEIGHTS` 市场状态映射
- [x] `FactorStore` 三阶段因子存储（raw/refined/feature）
- [x] `GateRegistryBridge` 验证 → 注册表生命周期联动
- [x] DP-002 55 项全部完成 ✅
- [x] **Daily IC Series 持久化** — `factor_ic_series.parquet` (2026-08-06)
- [x] **Multi-Horizon IC Decay** — 1d/3d/5d/10d/20d 衰减曲线 (2026-08-06)
- [x] **CLI `qp factor`** — list/health/report/validate/catalog 命令组 (2026-08-06)
- [x] **Factor Research Report 自动生成** — markdown 单因子/总览报告 (2026-08-06)
- [x] **Factor Store Pipeline 集成** — 实验自动保存 raw tier (2026-08-06)
- [x] **PSI Drift Alert** — PSI>0.25 自动告警 + IC horizon 反转检测 (2026-08-06)
- [x] **Residual_Momentum_3M index_df 修复** — legacy 路径自动加载 index (2026-08-06)

#### 待实现 📋

- [ ] **WebUI 因子编辑器** — 可视化因子定义 → 即时 IC 预览
- [ ] **因子版本管理** — 同一因子多版本对比（v1.0 vs v1.1）
- [ ] **基本面因子日频化方案** — 解决季频数据在日频 IC 中的噪音问题

### 13G. 已知问题 & 技术债

| # | 问题 | 严重程度 | 状态 |
|:-:|------|:-------:|:----:|
| 1 | IC_30d 数值异常高（0.2633 vs 全周期 0.07）需验证计算链路 | ⚠️ 中 | 📋 待查 |
| 2 | 基本面因子日频 IC 接近 0，当前无有效解决方案 | ⚠️ 中 | 📋 待设计 |
| 3 | VOLATILITY_DIRECTIONS=1 但 batch 函数已内置 negate，需确认不重复翻转 | ⚠️ 中 | 📋 待审计 |
| 4 | Residual_Momentum_3M 需要 index_df 参数，但非所有调用路径都传入 | ⚠️ 低 | 📋 待修复 |
| 5 | 复合实验结论已归档，但 Composite 框架仍留在策略管线中 | 💡 低 | 📋 待清理/重构 |
| 6 | `_classify_state` 中 PRODUCTION 判定使用 60d decay 斜率而非 30d | 💡 低 | 设计选择，暂不修改 |

### 13H. 最近更新日志

| 日期 | 变更 |
|------|------|
| 2026-08-06 | **CLI `qp factor`**: list/health/report/validate/catalog 5 命令 |
| 2026-08-06 | **Daily IC Series 持久化**: `factor_ic_series.parquet` 支持相关矩阵真实计算 |
| 2026-08-06 | **Multi-Horizon IC Decay**: 1d/3d/5d/10d/20d 衰减曲线集成到 health |
| 2026-08-06 | **Factor Research Report**: 自动生成 markdown 单因子/总览报告 |
| 2026-08-06 | **Factor Store Pipeline 集成**: 实验自动写 raw tier |
| 2026-08-06 | **PSI Drift Alert**: PSI>0.25 自动告警 + IC horizon 反转检测 |
| 2026-08-06 | **Residual_Momentum_3M fix**: legacy 路径自动加载 index_df |
| 2026-08-05 | Composite 实验归档 (alpha_ensemble_v3) — 日频 Value/Quality/Growth 不加 alpha |
| 2026-08-05 | Benchmark MaxDD 修复 (mean→median, penny stock filter, 3x daily cap) |
| 2026-08-04 | Factor Lifecycle State Machine v2 (7 states + WEAKENING) |
| 2026-08-04 | FactorCompositeEngine + 6 Composite Definitions |
| 2026-08-03 | Factor Store 三阶段持久化 (raw/refined/feature) |
| 2026-08-03 | GateRegistryBridge — 验证门 → 注册表生命周期联动 |
