# QP vs QuantTrading — 纯代码级对比

> 对比日期：2026-07-23
> 基于源代码分析，不含文档推断

---

## 一、总体数据

| | **QP** | **QuantTrading** |
|---|---|---|
| 源代码行数 | ~49,435 (`qp/`) | ~25,970 |
| 测试行数 | ~12,655 | ~2,820 |
| 源文件数 | 158 | 92 |
| 测试文件数 | 32 | 15 |
| DataFrame 引擎 | **Polars** | **Pandas** |
| Python | 3.12+ / 3.14 实际 | 3.14 |
| 包管理 | `uv` + `pyproject.toml` | `pip` + `requirements.txt` |
| 架构风格 | 严格 10 层分层 + 协议驱动 | 松散分层 + 函数驱动 |
| Git 历史 | 22 commits (~1 个月) | 41 commits (~1 个月) |

---

## 二、数据层代码对比

### 2.1 数据获取

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `tencent_adapter.py` 202 行 + `akshare_adapter.py` 71 行 | `fetcher.py` 779 行 |
| 架构 | ABC 协议 `BaseDataSource`，每个数据源独立 class | 无抽象基类，所有抓取逻辑在一个文件 |
| 接口规范 | `fetch_raw()` + `validate_schema()` + `dataset_name` property | 松散函数，无统一接口 |
| 多源回退 | 无 | Tencent → Sina → AKShare 三级回退链 |
| 重试机制 | 无 | `retry_times` + `retry_delay` 可配置 |
| 并发 | 无 | ThreadPoolExecutor(3 workers) |
| 代理处理 | 无 | 临时清空代理环境变量后调用 AKShare |
| 索引数据 | 无 | SQLite 本地缓存 + 实时行情补丁 |
| except 分支数 | 4 | 18 |
| A 股成交量单位 | 未处理沪市(手)/深市(股)差异 | 明确 `v * 100 if sh else v` |

**代码示例 — QP 的协议隔离：**

```python
# qp/shared/protocols/base_data_source.py
class BaseDataSource(ABC):
    @property
    @abstractmethod
    def dataset_name(self) -> str: ...

    @abstractmethod
    def fetch_raw(self, start_date: date, end_date: date, **kwargs) -> pd.DataFrame: ...

    @abstractmethod
    def validate_schema(self, df: pd.DataFrame) -> bool: ...
```

```python
# qp/data/adapter/tencent_adapter.py
class TencentAdapter(BaseDataSource):
    @property
    def dataset_name(self) -> str:
        return "daily_price_tencent"

    def fetch_raw(self, start_date, end_date, **kwargs):
        # 清晰、单一职责的抓取逻辑
        ...
```

**代码示例 — QuantTrading 的实用回退：**

```python
# data/fetcher.py
for attempt in range(FETCH["retry_times"]):
    try:
        result = _query_tencent(code, start, end)
        if result:
            return result
    except Exception:
        time.sleep(FETCH["retry_delay"])

# 三级回退
result = _try_tencent(code) or _try_sina(code) or _try_akshare(code)
```

**差异总结**：QP 的接口设计允许多个数据源互换而不改上层代码；QuantTrading 在真实网络环境中经过充分打磨，有更多的异常处理和回退策略。

### 2.2 数据清洗

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 核心清洗 | `cleaning/engine.py` 103 行 | `cleaning.py` 619 行 + 4 个 stage 子模块 |
| 风格 | Polars 声明式，极简 | Pandas 过程式，详尽 |
| 异常处理 | 删除异常值 | 修复异常值（ffill、swap high/low、clip） |
| 停牌检测 | `volume <= 0` | `np.isclose(volume, 0.0, atol=1e-8)` + 区分「停牌」vs「一字板」 |
| 涨跌停检测 | 委托给 `validation/checks.py` | 内置：主板±10%、科创/创业±20%、ST±5%，20% 容差 |
| 复权跳空 | 未处理 | 区分「真正涨跌停」vs「复权因子跳空」（相邻日检测） |
| 金额验证 | 无 | `abs(amount - volume * avg_price) / amount` 5% 容差 |
| 成交量单位 | 未转换 | `shares = v * 100 if tc.startswith("sh") else v` |
| 数据合约 | `DailyPriceContract` Pydantic 模型 | 无显式合约 |
| 验证体系 | ValidationGate + CircuitBreaker + Pandera schema + PSI 漂移检测 | 内联 `quality_report()` dict |
| 退市处理 | `DelistedHandler` + 58 只硬编码股票列表 + JSON 缓存 + 生存偏差统计 | 基本退市标记 |
| 复权因子 | 委托给 `corporate_action/engine.py` | 4 阶段 ETL，含「后向影响」增量更新 |

**代码示例 — QP 的断路器验证：**

```python
# qp/data/validation/gate.py
class ValidationGate:
    def validate(self, df, calendar=None, baseline=None):
        all_checks = []
        if self.config.enable_gaps:
            all_checks.append(check_gaps(df, ...))
        if self.config.enable_ohlc_physics:
            all_checks.append(check_ohlc_physics(df))
        # ... 6-9 个物理检查

        report = ValidationReport(checks=all_checks)
        breaker_result = self.breaker.evaluate(all_checks)
        report.circuit_triggered = breaker_result.tripped
        return report
```

```python
# qp/data/validation/checks.py — 资产负债表平衡检验
def check_financial_balance(df, tolerance=0.01):
    """验证 资产 == 负债 + 所有者权益"""
    balance_error = |assets - (liabilities + equity)| / max(|assets|, 1)
    # 检测单位转换错误（万元 vs 元，误差 10,000×）
```

**代码示例 — QuantTrading 的 A 股细节：**

```python
# data/cleaning.py
def _detect_price_limit(df):
    # 分板块涨跌停阈值
    limit = 0.10
    if code.startswith("688") or code.startswith("300"): limit = 0.20
    if "ST" in name: limit = 0.05

    # 区分涨跌停 vs 复权跳空
    if abs(ret_adj) > limit_buffer:
        if abs(ret_same_day_other) > limit_buffer:
            label = "adj_jump"   # 相邻日也超限 = 复权跳空
        else:
            label = "price_limit" # 单日超限 = 涨跌停
```

**差异总结**：QP 的清洗引擎极简但验证体系完善（8 个物理检查 + 财务平衡 + PIT 延迟 + 断路器）；QuantTrading 的清洗逻辑在处理 A 股真实数据异常方面远超 QP。

### 2.3 行业分类

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `classifier.py` 433 行 + `cache.py` | `industry.py` 346 行 |
| 设计 | `IndustryClassifier` class + `IndustryCache` | 模块级函数，无 class |
| 板块列表 | 60 个申万板块 | 60 个申万板块（一致） |
| 回退策略 | 12 类前缀回退 | 12 类前缀回退（一致） |
| 缓存验证 | `len(data) > 100` 阈值检查 | 无数据量验证 |
| 强制刷新 | `force_refresh=True` + `refresh()` | 无 |
| 错误处理 | `contextlib.suppress(Exception)` | 裸 `try/except: pass` |

两个项目的行业分类实现高度同源，60 个板块代码、CSRC 字母映射、前缀回退逻辑基本一致。

### 2.4 基本面数据

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `adapter.py` 272 行 + `product.py` 302 行 | `fundamental.py` 508 行 |
| 架构 | Adapter(抓取) + Product(PIT 访问) 分离 | 单体文件：抓取+存储+因子提取 |
| PIT 保证 | `get_asof(symbol, as_of_date)` + NaN 守卫 `val != val` | `effective_date = publish_date.fillna(report_date)` |
| 时间对齐 | 手动 forward-fill，`pair_idx` 追踪 | 向量化 `reindex + ffill` |
| 批量因子提取 | 个股循环 | `pivot_table + reindex + ffill` 全局向量化 |
| 并发 | 无 | ThreadPoolExecutor(10 workers) |
| 发布日期估算 | 年报 04-25 / Q1 04-25 / 中报 08-26 / Q3 10-26 | 同，带 `@lru_cache(maxsize=128)` |
| 数值清洗 | `float(str(x).replace("%","").replace("亿","").replace("万",""))` | 同 |
| 特殊守卫 | `x is not None and x is not False`（AkShare 返回 boolean False） | 无此守卫 |
| DB 存储 | 委托给独立 ETL | 内联 `store_fundamental_to_db()` EAV 格式 |
| ABC 协议 | `FundamentalAdapter(BaseDataSource)` | 无 |

**代码示例 — QP 的 PIT 数据产品：**

```python
# qp/data/fundamental/product.py
class FundamentalDataProduct:
    def get_asof(self, symbol: str, as_of_date: str) -> dict:
        """PIT-safe: 只返回 as_of_date 之前已发布的数据"""
        visible = df.filter(pl.col("publish_date").cast(pl.Utf8) <= as_of_date)
        latest = visible.sort("report_date", descending=True).head(1)
        # NaN 守卫
        if val is not None and not (isinstance(val, float) and val != val):
            result[key] = val
```

**代码示例 — QuantTrading 的批量向量化提取：**

```python
# data/fundamental.py
def batch_get_factor_df(symbols, trading_dates, factor_fields):
    """全局 pivot_table 避免 N+1 查询"""
    pivot = raw.pivot_table(
        index="symbol", columns="report_date", values=field
    ).reindex(columns=trading_dates).ffill(axis=1)
```

**差异总结**：QP 将抓取与 PIT 访问分离，`FundamentalDataProduct` 是真正的数据产品（PIT 安全 + 时间对齐 + 字段自省）；QuantTrading 通过全局 `pivot_table` 实现向量化批量提取，性能更好。

---

## 三、策略层代码对比

### 3.1 因子体系

两个项目的因子集高度相似（均含 15 个价量因子 + 估值因子 + 资金流向因子），表明 QuantTrading 可能是 QP 的上游参考实现。

核心实现差异：

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 因子架构 | `BaseFeature` 子类（13 个独立 class）+ 批量函数 | `@register_factor` 装饰器 + `FACTOR_REGISTRY` dict |
| 未来信息泄漏 | 统一 `shift(1)` + 明确注释 | **无 shift(1)**，依赖外部处理（潜在 bug） |
| 波动率计算 | `log().diff()` 对数收益率 | `pct_change()` 简单收益率 |
| 因子方向 | 5 类因子明确定义 direction（A 股校准） | 权重符号隐含方向（如 `PE_TTM: -0.12`） |
| 隐含净流量回退 | 检查 `amount` 列 → 回退 `close * volume` | 同 |
| 可测试性 | 高（独立类，可单独实例化） | 中（装饰器注册，依赖全局状态） |

**代码示例 — QP 的防未来信息泄漏：**

```python
# qp/research/feature/momentum.py
def compute_momentum_factors(df: pl.DataFrame) -> pl.DataFrame:
    ...
    # shift(1): prevent future information leakage
    # factor for day T only uses data <= T-1
    result = result.with_columns([
        pl.col(c).shift(1).alias(c)
        for c in factor_columns
    ])
    return result
```

QuantTrading 的 `compute_all_factors()` 直接返回原始因子值，未做 shift，未来信息泄漏防护依赖调用方处理。

### 3.2 因子处理

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `factor_processor.py` **962 行** | `factor_processor.py` 447 行 |
| 缩尾 | MAD (n=5.0 可配) / Percentile | MAD (n=5 硬编码) / Percentile |
| 标准化 | z-score / rank / minmax | z-score / rank / minmax |
| 行业中性化 | median **+ OLS** | median only |
| OLS 中性化 | Size + Industry 同时回归 → 残差取纯 alpha | **无** |
| 正交化 | VIF + 回归残差，NaN 行对齐 | VIF + 回归残差，inf→NaN 替换 |
| 诊断输出 | `return_diagnostics=True` + `@overload` | `return_diagnostics=True` |
| 类型注解 | 完整 + `@overload` 分支判别 | 部分类型提示 |
| 防御性 | 空输入→空 Series、除零守卫、秩亏检测 | 基本防御 |
| ML 模式 | `MLPipelineKernel.score_walk_forward()` | `walk_forward_scores()` |

**代码示例 — QP 的 OLS 中性化（QuantTrading 完全缺失的能力）：**

```python
# qp/research/factor_processor.py
def neutralize_cross_section_ols(factor_values, risk_matrix):
    """OLS 截面中性化: 因子 ~ Size + Industry dummies → 残差 = 纯 alpha"""
    X = np.column_stack([log_mcap, *industry_dummies])
    # 在完整案例上拟合
    coeffs, _, _, _ = np.linalg.lstsq(X_valid, y_valid, rcond=None)
    residuals = y - X @ coeffs  # 不含市值/行业影响的纯 alpha
    return residuals
```

QuantTrading 的中性化只是中位数减法：`factor - industry_median`，无法同时剥离市值和行业效应。

### 3.3 策略注册

两个项目采用完全不同的设计：

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `registry.py` 373 行 | `registry.py` 774 行 |
| 设计模式 | **生命周期状态机** | **评估对比框架** |
| 核心数据结构 | `StrategyMeta` dataclass（版本、模型版本、特征集） | `StrategyResult` dataclass（回测指标全集） |
| 状态流转 | RESEARCH → BACKTEST_PASSED → PAPER_TRADING → PRODUCTION → KILL_SWITCH | 无生命周期 |
| 上线门禁 | 血缘链验证（Data→Feature→Model→Strategy） | 无 |
| 策略对比 | 无 | `compare_strategies()` → `StrategyComparison` |
| 评估功能 | 无 | `evaluate_strategy()` 自动跑回测 |
| 策略存储 | `BaseStrategy` 实例 | 纯函数 + `@register_strategy` 装饰器 |

**差异**：QP 强调生产安全（生命周期门禁），QuantTrading 强调研究效率（自动评估对比）。两者互补。

### 3.4 市场状态 / IC 状态（不重叠的功能）

这是两个项目最不重叠的功能模块：

**QP `market_regime.py` (480 行)**：检测大盘宏观状态
- 4 维度（趋势/波动/宽度/成交量）→ 6 状态（牛市/横盘上/横盘下/熊市/中性/危机）
- 输出：建议仓位比例、建议策略类型、建议持仓数量、是否允许买入
- `_rolling_mean` 用 cumsum 实现性能优化

**QuantTrading `regime_switch.py` (299 行)**：检测因子 IC 状态
- 基于因子 IC 的 EWMA（半衰期=2 周期）
- 5 状态：动量/反转/质量/混合/中性
- 动态翻转因子符号：`IC_STRONG=0.03`, `IC_WEAK=0.015`
- 权重放大：`abs_w *= (1.0 + min(abs(ewma), 0.3))`

**QP 没有因子 IC 状态机；QuantTrading 没有完整的仓位/频率建议系统。**

### 3.5 风控（互补）

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `portfolio/risk_manager.py` 257 行 | `strategy/risk_manager.py` 274 行 |
| 定位 | **事前风控**（组合构建阶段） | **事后风控**（持仓阶段） |
| 验证规则 | 单仓上限 8%、单行业 25%、相关性 >0.7 剔除 | 固定止损 -8%、移动止盈、最大持仓天数 |
| 风控档位 | 无预设 | 保守/平衡/激进三档（-5%/-8%/-12% 止损） |
| 组合熔断 | 无 | `PortfolioRiskState`：20% 回撤/单日 5%/3 连跌熔断 |
| 结果输出 | `RiskReport` dataclass | `(should_sell, reason)` tuple |

**两者完全互补，覆盖了交易生命周期的不同阶段。** QP 缺止损止盈；QuantTrading 缺行业相关性限制。

### 3.6 QP 独有的信号后处理管线

QuantTrading 完全没有以下模块：

| 模块 | 行数 | 功能 |
|------|------|------|
| `signal/normalizer.py` | 227 | 4 种跨截面标准化（min_max, z_score→sigmoid, rank_percentile, direct_sigmoid） |
| `signal/threshold.py` | 226 | SignalClipper（缩尾/cut）+ SignalThreshold（最低分门禁、每日上限、置信度过滤） |
| `signal/smoother.py` | 237 | 信号平滑处理 |
| `signal/confidence.py` | 207 | 置信度评分（得分幅度 + 截面离散度 + 覆盖质量 + IC 混合） |
| `aggregator.py` | 202 | 多策略信号聚合（rank_blend / equal_weight / vote） |
| `ensemble/` | 657 | 集成引擎 + 加权策略（等权/IC/绩效） |

---

## 四、回测引擎代码对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | 656 行（3 文件） | 1,312 行（3 文件） |
| 架构 | 分层：`SimpleVectorBacktest`(87行) + `SimulatedBroker`(417行) | 单体：`BacktestEngine`(613行) |
| 滑点 | 策略模式：`BaseSlippageModel` ABC + 3 种实现（固定/波动率/sqrt冲击）+ 工厂函数 | 内联函数：20 日均量流动性分层（NORMAL 0.1% / HIGH 0.5%） |
| 订单生命周期 | PENDING → FILLED → REJECTED → CANCELLED | 信号直接消费，无结构化订单 |
| 涨跌停 | 委托给 strategy/risk 层 | 分板块 10%/5%/20%，涨停买不进/跌停卖不出 |
| 停牌 | 未在 broker 处理 | `_is_halted()`: volume < 1 |
| 闲置资金 | 无 | 年化 2% 利息 |
| 过拟合检测 | 委托 `validation/` 层 | 置换检验(200次) + split-test + walk-forward → 0-5 分 |
| A 股细节 | 印花税(0.05%) + 佣金(0.025%) + 100 股整数倍 | 同 + ST 剔除 + 科创板识别 |
| 成本模型 | 分离 `CostModel`：印花税+佣金+滑点+sqrt 冲击 | 内联 backtest engine |

**代码示例 — QP 的订单生命周期：**

```python
# qp/simulation/broker.py
class SimulatedBroker(BaseBroker):
    class Order:
        status: str  # PENDING → FILLED | REJECTED | CANCELLED
        reject_reason: str | None
        filled_price: float | None
        filled_quantity: int | None
```

**代码示例 — QuantTrading 的涨跌停保护：**

```python
# backtest/engine.py
def _check_limit(self, code, date, action):
    limit = 0.10
    if code.startswith("688") or code.startswith("300"): limit = 0.20
    if "ST" in self._names.get(code, ""): limit = 0.05
    if action == "BUY" and close >= prev_close * (1 + limit - 0.002):
        return False  # 涨停买不进
    if action == "SELL" and close <= prev_close * (1 - limit + 0.002):
        return False  # 跌停卖不出
```

**差异**：QP 架构好（插件化滑点、订单生命周期），QuantTrading 的 A 股细节和过拟合检测更实用。

---

## 五、Pipeline 代码对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `daily_pipeline.py` 445 行 + `multifactor_pipeline.py` 1,034 行 | `daily_run.py` 1,098 行 |
| 协议 | 实现 `BasePipeline`：`run(context) → PipelineResult` | 无协议，单体 class |
| 步骤数 | 11 步（数据→特征→市场状态→策略发现→执行→集成→风控→成本→分配→回测→报告） | 6 步（init→pool→fetch→strategy→notify→review） |
| 状态管理 | 无状态 | DB 持久化持仓、信号历史 |
| 持有期管理 | 无 | 非换仓日只跑风控不执行策略 |
| 自优化 | 无 | 结算时计算 IC、调整权重 |
| 运营完整性 | 研究工具 | 完整的交易运营管线 |

**QP 是研究工具**：跑完回测，生成报告，人工分析。
**QuantTrading 是交易系统**：持久化信号、管理持仓、每日结算、通知推送。

---

## 六、CLI / Web UI / 测试对比

### CLI

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 代码量 | `main.py` 1,696 行 | `run_pipeline.py` 143 行 |
| 命令数 | 20+ 子命令 | 4 模式 |
| 输出 | 中英双语 | 中文 |
| 覆盖层数 | 全部 10 层 | 仅管线 |

### Web UI

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 存在 | **无** | Streamlit 13 页仪表盘 (2,909 行) |
| 功能 | - | 实时信号、组合跟踪、回测、因子 IC、风控看板、日志、数据质量 |

### 测试

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| 总测试行数 | 12,655 | 2,820 |
| 测试文件数 | 32 | 15 |
| 覆盖范围 | 全层级（策略 2,451 行 + 组合 2,055 行 + 数据 5,700 行） | 集中在数据管线（清洗/ETL/存储/schema） |
| 策略测试 | ✅ 2,451 行 | ❌ 无 |
| 回测测试 | ❌ 无独立测试 | ❌ 无 |
| 组合风险测试 | ✅ 2,055 行 | ❌ 无 |
| 固定装置 | 内联 | `conftest.py` 163 行（合成 OHLC、停牌、涨跌停、坏数据） |

---

## 七、总览矩阵

| 维度 | QP 胜出 | QuantTrading 胜出 |
|------|---------|-------------------|
| **架构设计** | ✅ 10 层严格分层 + 11 个 ABC 协议 | 松散分层 |
| **代码类型安全** | ✅ 完整类型注解 + @overload | 部分类型提示 |
| **数据验证** | ✅ ValidationGate + CircuitBreaker + Pandera | 内联 quality_report |
| **数据获取鲁棒性** | | ✅ 三级回退 + 重试 + 代理处理 |
| **A 股数据清洗** | | ✅ 分板块涨跌停、复权跳空、成交量单位 |
| **OLS 截面中性化** | ✅ Size+Industry 同时回归 | ❌ 无 |
| **信号后处理管线** | ✅ 5 模块管线（归一化→裁剪→阈值→置信度→聚合） | ❌ 无 |
| **因子 IC 状态机** | | ✅ 动态翻转因子符号 |
| **策略评估框架** | | ✅ 自动回测+对比排序 |
| **回测 A 股细节** | | ✅ 分板块涨跌停、闲置利息、置换检验 |
| **回测架构** | ✅ 插件化滑点 + 订单生命周期 | 单体 engine |
| **组合优化** | ✅ MVO + Ledoit-Wolf + 风险预算 | 简单 Kelly/等权 |
| **事前风控** | ✅ 仓位/行业/相关性三层过滤 | 无 |
| **事后风控** | | ✅ 止损/止盈/持仓天数 + 组合熔断 |
| **Kill Switch** | ✅ 3 触发器（回撤/组合回撤/PSI） | 组合熔断 |
| **监控系统** | ✅ PSI+KS+Wasserstein 漂移 + 模型衰减 | ❌ 无 |
| **知识归档** | ✅ KnowledgeArchive + 5 模板 + 全文搜索 | ❌ 无 |
| **实验追踪** | ✅ 血缘图 (lineage graph) | ❌ 无 |
| **Web UI** | | ✅ Streamlit 13 页仪表盘 |
| **多渠道告警** | | ✅ 钉钉+企微+邮件 |
| **测试覆盖** | ✅ 12,655 行 / 全层级 | 2,820 行 / 仅数据层 |
| **运营完整性** | | ✅ DB 持久化 + 持仓管理 + 自优化回路 |

---

## 八、核心结论

### 两个项目本质上是同源分叉

```
QuantTrading (早)                    QP (晚)
    │                                   │
    ├── 实战驱动                        ├── 架构重构
    ├── Pandas                          ├── Polars
    ├── 单体 engine                     ├── 协议 + 分层
    ├── 无类型注解                      ├── 完整类型注解 + @overload
    ├── 无抽象基类                      ├── 11 个 Base* 协议
    ├── 策略无测试                      ├── 策略 2,451 行测试
    ├── A 股细节丰富                    ├── A 股细节从简
    └── 有 Web UI / 钉钉告警           └── 有 Kill Switch / 知识归档
```

### 各自不可替代的优势

**QP 独有且 QuantTrading 值得借鉴：**
1. OLS 截面中性化（Size + Industry 同时回归取纯 alpha）
2. ValidationGate + CircuitBreaker 数据质量体系
3. PurgedKFold 严谨实现（245 行，含 Purge + Embargo）
4. 订单生命周期管理（PENDING→FILLED→REJECTED→CANCELLED）
5. KnowledgeArchive 知识沉淀体系（5 模板 + 全文搜索）
6. 实验血缘追踪（Data→Feature→Model→Strategy 完整链）
7. 信号后处理管线（5 模块：归一化→裁剪→阈值→置信度→聚合）
8. 模型衰减监控（滚动 IC < 训练 IC 的 30%）
9. 配置 4 级优先级 + 启动后冻结

**QuantTrading 独有且 QP 值得借鉴：**
1. 因子 IC 状态机（EWMA 动态翻转因子符号）
2. 数据获取三级回退（Tencent → Sina → AKShare + 重试）
3. A 股数据清洗细节（分板块涨跌停、复权跳空 vs 真实涨跌停、成交量单位转换、金额验证）
4. 退市处理 + 生存偏差统计
5. Streamlit 13 页仪表盘
6. 组合熔断（20% 回撤 / 5% 单日 / 3 连跌）
7. 事后止损止盈（保守/平衡/激进三档）
8. 多渠道告警（钉钉、企微、邮件）
9. 闲置资金利息 + 科创/创业板涨跌幅区分
10. 过拟合检测（200 次蒙特卡洛置换检验 + split-test + walk-forward）

**共同盲区：**
- 无实盘对接（QP 明确是决策支持系统；QuantTrading 虽声明「可接入实盘」但代码仍以研究为主）
- 无 Point-in-Time 财务数据（用最新 restated 数据回看历史 = 前视偏差）
- 无集成/E2E 测试
- QP 缺乏真实基本面因子数据链路（有框架无内容）；QuantTrading 虽有基本面数据但缺乏系统化的因子评估框架
