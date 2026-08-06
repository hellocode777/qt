# Strategy Engine Layer 差距追踪文档

> 对照 `docs/6_Strategy_Engine.md`，逐项追踪 Layer 6（Strategy Engine）的待实现项。
> 最后更新：2026-07-22（全部完成 ✅）

---

## 状态说明

- ⬜ `[ ]` 待实现
- 🟡 `[~]` 部分实现，有缺陷
- ✅ `[x]` 已完成

---

## 一、模块一：Strategy Registry（策略注册中心）

### 1.1 StrategyRegistry — 策略注册管理

- **状态**: `[x]` ✅ 已完成
- **已实现**: `registry.py`（~240 行），支持 register/get/list/get_active/set_lifecycle + lineage gate
- **涉及文件**: `qp/strategy/registry.py`

### 1.2 Strategy Loader — 动态加载（Hot-Plug）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `StrategyLoader` — `discover()` 扫描包中 `BaseStrategy` 子类（importlib + pkgutil）+ `register_all()` 自动实例化并注册到 Registry
- **文档出处**: 6_Strategy_Engine.md §模块一 "Runner 只需要扫描 Registry，通过类名或动态 import（importlib）实例化策略"
- **要求**: 扫描 `strategies/` 目录，通过 `importlib` 动态加载 `BaseStrategy` 子类，自动注册到 Registry
- **涉及文件**: 待创建

### 1.3 策略元数据存储

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `StrategyMeta` dataclass（strategy_version, model_version, feature_version, feature_set, rebalance_frequency, rebalance_day, owner, description, tags）+ `StrategyRegistry.register()` 接受可选 meta 参数，新增 `get_meta()`, `set_meta()`, `get_by_owner()`, `get_by_frequency()`, `get_by_tag()`, `list_metadata()`, `count` 属性
- **涉及文件**: `qp/strategy/registry.py`, `qp/shared/types/__init__.py`（新增 `RebalanceSchedule` 枚举）

---

## 二、模块二：Strategy Runner（调度器）

### 2.1 StrategyRunner — 策略调度核心

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `StrategyRunner` 类（~200 行）— 查询 active 策略 → 按 rebalance 频率调度 → 执行 generate_signals() → 返回 `RunnerResult`；支持 dry_run 和 force_all 模式
- **涉及文件**: `qp/strategy/runner/strategy_runner.py`

### 2.2 调仓频率日历

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `RebalanceSchedule` 枚举（DAILY/WEEKLY/BIWEEKLY/MONTHLY）+ `_should_run_today()` / `_next_rebalance_date()` 调度逻辑，支持 WEEKLY 指定 weekday、BIWEEKLY 偶数 ISO 周、MONTHLY 月末
- **涉及文件**: `qp/shared/types/__init__.py` + `qp/strategy/runner/strategy_runner.py`

---

## 三、模块三：Signal Generation（信号生成）

### 3.1 BaseStrategy ABC

- **状态**: `[x]` ✅ 已完成
- **已实现**: `qp/shared/protocols/base_strategy.py` — 定义 `strategy_id` + `generate_signals(as_of_date)` 接口
- **涉及文件**: `qp/shared/protocols/base_strategy.py`

### 3.2 独立策略文件 — Momentum

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `MomentumStrategy(BaseStrategy)` — 3 种动量变体（raw/residual/risk_adjusted），config-driven，PIT 安全，支持 `skip_suspended` 停牌检测
- **文档出处**: 6_Strategy_Engine.md 目录结构 `strategies/momentum.py`
- **要求**: 动量策略（价格动量/残差动量），继承 `BaseStrategy`，返回 `[symbol, raw_score, rank]`
- **涉及文件**: 待创建

### 3.3 独立策略文件 — Quality

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `QualityStrategy(BaseStrategy)` — 8 种质量指标加权（ROE/gross_margin/net_margin/debt_ratio/revenue_growth/net_profit_growth/EPS/NAV），硬性剔除（ROE<0, debt>85%）+ 增长要求双门控

### 3.4 独立策略文件 — Value

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `ValueStrategy(BaseStrategy)` — 5 种估值指标加权合成（PE/PB/PS/PCF/DY），支持行业相对估值、负盈利剔除、scipy 百分位排名
- **文档出处**: 6_Strategy_Engine.md 目录结构 `strategies/value.py`
- **要求**: 价值策略（PE/PB/股息率），继承 `BaseStrategy`
- **涉及文件**: 待创建

### 3.5 SignalGenerator — 统一信号编排

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `SignalGenerator` + `GeneratorConfig` — Feature → Model → Normalize → Clip → Smooth → Threshold → Confidence 7 步流水线，支持 DataFrame 和 numpy 数组两种入口

---

## 四、模块四：Signal Post Processing（信号后处理）

### 4.1 SignalNormalizer — 归一化

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `SignalNormalizer` 类 — 支持 4 种方法（min_max / z_score+sigmoid / rank percentile / direct sigmoid），跨截面归一化到 [0,1]。提供 `normalize()`, `normalize_with_symbols()`, `normalize_polars()`, `normalize_by_date()` 便捷方法
- **涉及文件**: `qp/strategy/signal/normalizer.py`

### 4.2 SignalSmoother — 信号平滑

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `SignalSmoother` 类 — 3 种方法（EMA / ROLLING_MEAN / DECAY），支持 `smooth_array()`, `smooth_polars()`, `smooth_cross_sectional()` 按个股时间序列独立平滑
- **文档出处**: 6_Strategy_Engine.md 补充 "Post-Processing 里加上 Smoother（比如指数移动平均 EMA 或近 N 天衰减）是极明智的做法，能极大地降低后续 Layer 7/8 的换手率（Turnover Cost）"
- **要求**: EMA 衰减、rolling average、decay factor 等平滑方法
- **涉及文件**: 待创建

### 4.3 SignalClipper / Threshold — 裁剪与阈值

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `SignalClipper`（WINSORIZE/SIGMA/ABSOLUTE 3 种裁剪方法）+ `SignalThreshold`（min_score/max_per_day/min_confidence 三重门控）
- **文档出处**: 6_Strategy_Engine.md §模块四 "Clip" + "Threshold"
- **要求**: 极端值裁剪（winsorize）、最小信号阈值过滤、置信度评分
- **涉及文件**: 待创建

### 4.4 Confidence Scoring — 置信度评分

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `ConfidenceScorer` 类 — 3 因子加权（score_magnitude + dispersion + coverage），支持 IC_IR 增强的 `score_from_ic()` + `score_by_date()` 按日分组评分
- **文档出处**: 6_Strategy_Engine.md §模块四 "Confidence"
- **要求**: 每个信号附带 confidence 字段，基于历史 IC/信号稳定性计算
- **涉及文件**: 待创建

---

## 五、模块五：Multi-Strategy Ensemble（多策略融合）

### 5.1 SignalAggregator — 基础融合

- **状态**: `[x]` ✅ 已完成
- **已实现**: `aggregator.py` — rank_blend / equal_weight / vote 三种方法
- **涉及文件**: `qp/strategy/aggregator.py`

### 5.2 EnsembleEngine — 融合编排

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `EnsembleEngine` 类 — 4 步流程（对齐 Universe → 动态权重 → 加权融合 → AlphaSignalBatch 输出），5 种 Universe 策略（fill_zero/fill_median/renormalize/intersection/union）
- **文档出处**: 6_Strategy_Engine.md §模块五 "输入多个策略 → 融合 → Final Score"
- **要求**: 整合 weight + fusion，接收多策略信号 → 输出统一 Alpha Signal
- **涉及文件**: 待创建

### 5.3 Dynamic Weighting — 动态权重

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `WeightEngine` — 5 种加权方法（FIXED/EQUAL/IC_WEIGHTED/SHARPE_WEIGHTED/REGIME），支持 min_weight 地板 + EMA 平滑 + 6 种市场 regime 预设权重矩阵
- **文档出处**: 6_Strategy_Engine.md §模块五 "Final Score = 0.4 × Momentum + 0.4 × Quality + 0.2 × Value" + 补充 "保留各子策略原始分，方便归因"
- **要求**:
  - 固定权重分配
  - IC-weighted（按近期 IC 分配权重）
  - Sharpe-weighted（按近期表现分配）
  - Regime-weighted（按市场状态分配，如 bear → defensive 权重高）
- **涉及文件**: 待创建

### 5.4 Cross-Section Universe 对齐

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 集成在 `EnsembleEngine._align_universes()` — 5 种策略（fill_zero/fill_median/renormalize/intersection/union），处理 "全A股 vs 沪深300" 截面错位问题
- **文档出处**: 6_Strategy_Engine.md 补充 §1 "Universe 对齐：策略 A 可能是针对全 A 股（5000只），策略 B 可能只针对沪深300（300只）。在融合（Ensemble）前，缺失值（NaN）是当做 0 处置，还是直接在权重计算中重新归一化？"
- **要求**:
  - 定义 Universe 概念
  - 合并时缺失值处理策略（fill 0 / fill median / re-normalize）
  - 仅交集 vs 全并集选项
- **涉及文件**: 待创建（可并入 EnsembleEngine）

---

## 六、数据模型

### 6.1 AlphaSignal — 标准化信号输出

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `AlphaSignal` dataclass（date/symbol/alpha_score/raw_components/confidence/strategy_id/generated_at）+ `AlphaSignalBatch` 容器类（top_n/above_threshold/filter_confidence/summary/to_polars/from_polars）
- **涉及文件**: `qp/strategy/models/alpha_signal.py`

### 6.2 StrategyResult — 策略结果包装

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `StrategyResult` dataclass — signals 列表 + 执行元数据（elapsed_ms/coverage/n_evaluated）+ to_dict/from_dict 序列化 + `failed()` 工厂方法
- **文档出处**: 6_Strategy_Engine.md 目录结构 `models/strategy_result.py`
- **要求**: 单次策略运行的输出包装（信号列表 + 元数据 + 时间戳）
- **涉及文件**: 待创建

---

## 七、已有的超额实现（不在文档中但已存在）

| 模块 | 文件 | 说明 |
|---|---|---|
| Market Regime | `market_regime.py` | 4 维市场状态检测（trend/vol/breadth/volume），6 种 regime |
| Market Filter | `market_filter.py` | 大盘 MA 环境过滤 + regime gating |
| Quality Filter | `quality_filter.py` | 基本面质量预筛选（ROE/负债率/PE 硬性剔除） |
| Paper Trading | `paper_trading.py` | 30 天模拟盘跟踪 + 自动评估 |
| Multi-Factor | `multifactor.py` | 15+ 因子多因子引擎（cross-sectional + rebalance） |

---

## 八、实现顺序建议

```
Week 1 — P0 核心骨架（4 项）
  ├── 6.1  AlphaSignal 数据模型
  ├── 1.3  策略元数据存储（Registry 扩展）
  ├── 2.1  StrategyRunner + 2.2 调仓频率日历
  └── 4.1  SignalNormalizer（归一化）

Week 2 — P1 信号后处理 + 独立策略（5 项）
  ├── 4.2  SignalSmoother（EMA 平滑）
  ├── 4.3  SignalClipper / Threshold
  ├── 4.4  Confidence Scoring
  ├── 3.2  Momentum 策略
  └── 3.4  Value 策略

Week 3 — P2 融合 + 完整性（5 项）
  ├── 5.2  EnsembleEngine
  ├── 5.3  Dynamic Weighting（IC/Sharpe/Regime）
  ├── 5.4  Cross-Section Universe 对齐
  ├── 1.2  Strategy Loader（Hot-Plug）
  └── 6.2  StrategyResult

Week 4 — 收尾（2 项）
  ├── 3.3  Quality 策略
  └── 3.5  SignalGenerator（统一编排）
```

---

## 九、完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 6.1 AlphaSignal | 新增 `AlphaSignal` + `AlphaSignalBatch` dataclass，标准 [0,1] 输出 + 序列化 + Polars 互转 |
| 2026-07-22 | 1.3 StrategyMeta | 新增 `StrategyMeta` dataclass（9 字段），扩展 `StrategyRegistry` 支持元数据存储/查询 |
| 2026-07-22 | 2.1 + 2.2 StrategyRunner | 新增 `StrategyRunner` + `RunnerResult`，支持 DAILY/WEEKLY/BIWEEKLY/MONTHLY 调仓调度 |
| 2026-07-22 | 4.1 SignalNormalizer | 新增 `SignalNormalizer` 类，4 种归一化方法 + Polars/按日期分组支持 |
| 2026-07-22 | 4.2 SignalSmoother | 新增 `SignalSmoother` 类，3 种平滑方法（EMA/ROLLING_MEAN/DECAY）+ Polars 按股独立平滑 |
| 2026-07-22 | 4.3 Clipper + Threshold | 新增 `SignalClipper`（3 种裁剪）+ `SignalThreshold`（三重门控：min_score/max_per_day/min_confidence） |
| 2026-07-22 | 4.4 ConfidenceScorer | 新增 `ConfidenceScorer`，3 因子加权 + IC_IR 增强 + 按日分组 |
| 2026-07-22 | 3.2 MomentumStrategy | 新增 `MomentumStrategy(BaseStrategy)` — raw/residual/risk_adjusted 三变体 |
| 2026-07-22 | 3.4 ValueStrategy | 新增 `ValueStrategy(BaseStrategy)` — 5 估值指标加权 + 行业相对 + scipy 百分位 |
| 2026-07-22 | 5.3 Dynamic Weighting | 新增 `WeightEngine` — 5 种加权方法 + min_weight + EMA 平滑 + 6 regime 预设矩阵 |
| 2026-07-22 | 5.2 EnsembleEngine | 新增 `EnsembleEngine` — 4 步融合流程 + 5 种 Universe 对齐策略 |
| 2026-07-22 | 5.4 Universe Align | 集成在 `EnsembleEngine._align_universes()` — fill_zero/median/renormalize/intersection/union |
| 2026-07-22 | 1.2 StrategyLoader | 新增 `StrategyLoader` — importlib 扫描 → 发现 BaseStrategy 子类 → 自动注册 |
| 2026-07-22 | 6.2 StrategyResult | 新增 `StrategyResult` dataclass — 执行元数据 + to/from_dict + failed() 工厂 |
| 2026-07-22 | 3.3 QualityStrategy | 新增 `QualityStrategy(BaseStrategy)` — 8 指标加权 + ROE/debt 硬性剔除 + 增长要求 |
| 2026-07-22 | 3.5 SignalGenerator | 新增 `SignalGenerator` + `GeneratorConfig` — 7 步流水线（Feature→Model→Normalize→Clip→Smooth→Threshold→Confidence） |
| 2026-07-22 | 配套 | `strategies/quality.py`；`generator.py`；StrategyLoader 发现全部 3 个策略 |
