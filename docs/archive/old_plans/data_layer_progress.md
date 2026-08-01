# Data Layer 实现进度追踪

> 对照文档：`docs/data_layer.md`（设计） + `docs/rule.md`（宪法）
> 更新日期：2026-07-21
> 当前阶段：Walking Skeleton（Sprint 0）

---

## 总体进度：~95%

```
████████████████████████████████████░░  11/12 核心模块基本可用，P0/P1/P2/P3 全部完成
```

---

## 1. Raw Ingestion（原始数据采集与接入）— 80%

| # | 需求项 | 状态 | 实现位置 | 备注 |
|---|---|---|---|---|
| 1.1 | `BaseDataSource` 抽象接口 | ✅ | `qp/shared/protocols/` | `fetch_raw()` + `validate_schema()` |
| 1.2 | AKShare 适配器 | ✅ | `qp/data/adapter/akshare_adapter.py` | A 股日线 OHLCV，前复权，限 50 只 |
| 1.3 | Tencent 适配器 | ✅ | `qp/data/adapter/tencent_adapter.py` | 分页拉取，自动识别沪深前缀，限速 |
| 1.4 | QuantTradingDB 适配器 | ✅ | `qp/data/adapter/quant_trading_db_adapter.py` | SQLite 本地库，带 cum_factor |
| 1.5 | Demo 适配器（合成数据） | ✅ | `qp/data/adapter/demo_adapter.py` | 几何布朗运动，种子 42，15 只模拟标的 |
| 1.6 | Tushare 适配器 | ❌ | — | 设计文档推荐的备选源 |
| 1.7 | 资金流向数据 | ✅ | `qp/data/capital_flow/adapter.py` | 主力净流入 + 北向资金 |
| 1.8 | 原始数据不可变存储 | ✅ | `qp/data/loader/full_pipeline.py` | Raw 层独立保存，追加写入 |
| 1.9 | 双时间戳标记（Event + Ingestion） | ✅ | `qp/data/timestamp.py` | `source_event_time` + `ingestion_received_time`，集成于 FullDataPipeline + DataPipeline |
| 1.10 | 分钟线 / L2 Tick | ❌ | — | 个人系统无需（符合文档建议） |
| 1.11 | Alt-Data（新闻/舆情/供应链） | ❌ | — | 个人系统无需（符合文档建议） |

**待补齐**：Tushare adapter（备选）

---

## 2. Cleaning Engine（数据清洗引擎）— 85%

| # | 需求项 | 状态 | 实现位置 | 备注 |
|---|---|---|---|---|
| 2.1 | 异常值剔除（价格<=0、倒挂） | ✅ | `qp/data/cleaning/repair.py` | OHLC 边界修复、high<low 交换 |
| 2.2 | 3-Sigma 极值检测 | ✅ | `qp/data/cleaning/etl_pipeline.py` | Stage 1 价格异常 |
| 2.3 | 复权因子处理 | ✅ | `qp/data/cleaning/etl_pipeline.py` | Stage 4 qfq adjustment via cum_factor |
| 2.4 | "原价存库、动态复权" | ⚠️ | — | 多数适配器直接返回前复权价格，非原始价+运行时复权因子 |
| 2.5 | 交易日历对齐 | ✅ | `qp/data/calendar/calendar.py` | AkShare 日历，回落周末过滤 |
| 2.6 | 缺失值填充（ffill + 0 fill） | ✅ | `qp/data/cleaning/repair.py` | 价格前向填充，成交量填 0 |
| 2.7 | 缺失交易日补齐 | ✅ | `qp/data/cleaning/repair.py` | 插入日历缺口，ffill + volume=0 |
| 2.8 | 停牌识别（volume==0） | ✅ | `qp/data/cleaning/engine.py` | 标记 is_suspended |
| 2.9 | 停牌 vs 涨跌停区分 | ✅ | `qp/data/cleaning/repair.py` | 3+ 天连续零量=停牌，1-2 天=涨停 |
| 2.10 | 涨跌停板检测 | ✅ | `qp/data/cleaning/etl_pipeline.py` | Stage 1 limit-up/down |
| 2.11 | 成交量异常检测 | ✅ | `qp/data/cleaning/etl_pipeline.py` | Stage 2 10x 中位数检测 |
| 2.12 | 成交额校验 | ✅ | `qp/data/cleaning/repair.py` | amount vs volume*avg(OHLC)，>5%偏差修复 |
| 2.13 | 退市股票处理 | ✅ | `qp/data/cleaning/delisted_handler.py` | 57 只硬编码 + AkShare 动态查询 |
| 2.14 | 审计追踪 | ✅ | `qp/data/cleaning/audit.py` | 4 类修复操作全量审计记录 |
| 2.15 | 4 阶段 ETL Pipeline | ✅ | `qp/data/cleaning/etl_pipeline.py` | anomaly → volume → suspension → adjustment |
| 2.16 | CleaningEngine | ✅ | `qp/data/cleaning/engine.py` | Bronze 层快速清洗 |
| 2.17 | 列名中英文映射 | ✅ | `qp/data/cleaning/engine.py` | COLUMN_MAP |
| 2.18 | 向量化工具链（Polars/DuckDB） | ✅ | `qp/data/cleaning/engine.py` + `pipeline.py` + `adapter/demo_adapter.py` | CleaningEngine、DataPipeline、DemoAdapter 全部 Polars 化 |

**待补齐**：原始未复权价 + 运行时复权因子（非前复权直接落库）

---

## 3. Validation（数据校验 Gate）— 95%

| # | 需求项 | 状态 | 实现位置 | 备注 |
|---|---|---|---|---|
| 3.1 | Schema 校验（字段类型、主键唯一性） | ✅ | `qp/data/contract/daily_price.py` | `DailyPriceContract.validate()` |
| 3.2 | 非空率（Missing Rate）检查 | ✅ | `qp/data/validation/checks.py` | `check_null_rate()` 独立校验 |
| 3.3 | 价格物理逻辑断言（High>=Low 等） | ✅ | `qp/data/validation/checks.py` | `check_ohlc_physics()` 独立校验 |
| 3.4 | 非负约束（Volume>=0, Market_Cap>0） | ✅ | `qp/data/validation/checks.py` | `check_non_negative()` 独立校验 |
| 3.5 | 涨跌幅极限校验（主板 10%/GEM 20%/ST 5%） | ✅ | `qp/data/validation/checks.py` | `check_price_limits()` 含板块识别+除权跳过 |
| 3.6 | 财务逻辑（资产负债表平衡） | ✅ | `qp/data/validation/checks.py` | `check_financial_balance()` 可配列名+容差 |
| 3.7 | 时序单调递增性检查 | ✅ | `qp/data/validation/checks.py` | `check_monotonicity()` 检测时间倒流+重复 |
| 3.8 | 断日检测（Gaps Check） | ✅ | `qp/data/validation/checks.py` | `check_gaps()` 支持日历对比 |
| 3.9 | PIT 发布延迟校验（Knowledge Time > Period End） | ✅ | `qp/data/validation/checks.py` | `check_pit_delay()` 含可配最小延迟天数 |
| 3.10 | 统计分布异动告警（Data Drift / PSI） | ✅ | `qp/data/validation/drift.py` | PSI + Summary-Stat Jump 双检测 |
| 3.11 | Pandera / Great Expectations 集成 | ✅ | `qp/data/validation/pandera_schemas.py` + `pandera_validator.py` | 4 套 Polars-native Schema；Great Expectations 跳过（过重，个人系统不需要） |
| 3.12 | 断路器机制（异常→告警→中断流水线） | ✅ | `qp/data/validation/circuit_breaker.py` | `CircuitBreaker` 三态机（CLOSED/OPEN/HALF_OPEN），fail-closed |
| 3.13 | Validation 层独立目录 | ✅ | `qp/data/validation/` | 7 模块：result/checks/drift/circuit_breaker/gate/pandera_schemas/pandera_validator |

**验证**：
- ruff: All checks passed
- pytest: 262 passed, 0 failures
- 新增依赖: `pandera>=0.32`

---

## 4. PIT & Universe（时点数据与动态标的池）— 85%

| # | 需求项 | 状态 | 实现位置 | 备注 |
|---|---|---|---|---|
| 4.1 | 双时间戳模型（Period End + Knowledge Time） | ✅ | `qp/data/fundamental/product.py` | `get_asof(symbol, as_of_date)` |
| 4.2 | PIT 财报查询 | ✅ | `qp/data/fundamental/product.py` | publish_date <= as_of_date |
| 4.3 | 财务数据产品接口 | ✅ | `qp/data/fundamental/product.py` | `get_asof()`, `get_snapshot()`, `align_to_trading_dates()` |
| 4.4 | FundamentalAdapter（PIT 适配器） | ✅ | `qp/data/fundamental/adapter.py` | 从 AkShare 拉财报，提取发布日期 |
| 4.5 | 生存者偏差处理（退市股） | ✅ | `qp/data/cleaning/delisted_handler.py` | 57 只退市股清单 |
| 4.6 | 动态 Universe（is_tradeable 标志） | ✅ | `qp/data/cleaning/etl_pipeline.py` | Stage 3 |
| 4.7 | 停牌过滤 | ✅ | `qp/data/universe/universe_builder.py` | `_filter_suspended()` 独立可复用 |
| 4.8 | ST 股过滤 | ✅ | `qp/data/universe/universe_builder.py` | `_filter_st()` 正则匹配 |
| 4.9 | 行业分类 | ✅ | `qp/data/industry/classifier.py` | baostock → akshare → 前缀回落 |
| 4.10 | 上市日期过滤（新股未满 N 天） | ✅ | `qp/data/universe/listing_dates.py` | 87 只硬编码 + AkShare 动态 + JSON 缓存，默认 200 天 |
| 4.11 | 流动性/成交量截断 | ✅ | `qp/data/universe/liquidity.py` | 绝对阈值 + 百分位双模式，中位数/均值可选 |
| 4.12 | 财务重述（Restatement）多版本 | ✅ | `qp/data/universe/restatement.py` | v1/v2/... 版本链，PIT 可见性查询 |
| 4.13 | 指数成分股历史变动 | ❌ | — | 需 AkShare `index_stock_cons_csindex`；网络不可用 |
| 4.14 | 行情数据 PIT（用于价格） | ❌ | — | 行情天然 PIT，无需额外实现 |

**新增能力**：
- `UniverseBuilder` 编排器：串联 IPO→ST→停牌→退市→流动性 5 级过滤链
- `UniverseConfig` 配置化：每级过滤器独立开关+参数
- `ListingDateRegistry`：三层回退（缓存→AkShare→硬编码 87 只）
- `RestatementTracker`：PIT 多版本财务报告存储+查询
- `filter_by_liquidity` / `filter_by_percentile`：双模式流动性截断

---

## 5. Feature Store（特征商店）— 95%

| # | 需求项 | 状态 | 实现位置 | 备注 |
|---|---|---|---|---|
| 5.1 | `BaseFeature` 抽象接口 | ✅ | `qp/data/feature_store/base_feature.py` | batch/stream 双模式 + shift(1) 内建 |
| 5.2 | 离线特征库（Offline Store） | ✅ | `qp/data/feature_store/offline_store.py` | Parquet 分区，按 year + factor_group |
| 5.3 | 在线特征缓存（Online Store / Redis） | ✅ | `qp/data/feature_store/online_cache.py` | 线程安全内存缓存，LRU 淘汰，TTL 支持 |
| 5.4 | 批流一体（transform_batch + update_stream） | ✅ | `qp/data/feature_store/base_feature.py` | 统一算子，两套方法 |
| 5.5 | 特征算子注册（Feature Registry） | ✅ | `qp/data/feature_store/registry.py` | 版本化管理，一致性检查，依赖查询 |
| 5.6 | 截面标准化防泄露（单日截面 z-score） | ✅ | `qp/data/feature_store/standardization.py` | cross_sectional_zscore + rank |
| 5.7 | Shift(1) 防泄露 | ✅ | `qp/data/feature_store/standardization.py` | shift_features 按 symbol 分组 |
| 5.8 | 重采样防泄露 | ✅ | `qp/data/feature_store/standardization.py` | resample_safe label=left, closed=left |
| 5.9 | Parquet 分区存储（按 year/factor_group） | ✅ | `qp/data/feature_store/offline_store.py` | zstd 压缩，hive partitioning |
| 5.10 | 特征计算引擎（Polars/DuckDB） | ✅ | `qp/data/feature_store/engine.py` | FeatureEngine 编排全流程计算 |
| 5.11 | 具体因子实现 | ✅ | `qp/data/feature_store/factors/` | 18 个因子：动量(6)/波动(4)/成交量(5)/技术(3) |

**新增因子清单（18 个）**：

| 类别 | 因子 | 说明 |
|---|---|---|
| 动量 | Momentum5/20/60 | N 日价格收益率 |
| 动量 | RSI14 | Wilder 平滑 RSI |
| 动量 | ShortTermReversal | 短期反转(-动量) |
| 波动 | RollingVolatility20/60 | 年化滚动波动率 |
| 波动 | ATR14 | EMA 平滑真实波幅 |
| 成交量 | VolumeRatio5/20 | 量比 |
| 成交量 | TurnoverRate | 换手率(流通股本版/回落版) |
| 成交量 | AvgVolume | N 日均量 |
| 技术 | SMACross | 均线交叉信号 |
| 技术 | PricePosition | N 日高低价格位置 |
| 技术 | MACD | 完整 MACD（hist/line/signal） |

**验证**：
- ruff: All checks passed
- pyright: 0 errors, 0 warnings
- pytest: 391 passed, 0 failures（新增 27 用例）

---

## 6. 跨模块差距

| # | 需求项 | 状态 | 备注 |
|---|---|---|---|
| 6.1 | 数据层单元测试 | ✅ | 17 个测试文件，391 个用例 |
| 6.2 | 数据层集成测试 | ❌ | 无（FullDataPipeline 需真实数据源） |
| 6.3 | `knowledge/` 子目录（5 个） | ❌ | 全部为空骨架 |
| 6.4 | `metadata/` | ✅ | Schema/Lineage/Source 元数据追踪（~435 行，22 用例） |
| 6.5 | `builder/` | ✅ | Dataset 组装 + 契约校验 + 原子发布（~340 行，15 用例） |
| 6.6 | 数据层架构文档 | ❌ | `docs/architecture/data/DP-002-data-layer.md` 为空 |
| 6.7 | 定时调度抓取 | ❌ | 当前仅手动/CLI 触发 |

---

## 实现优先级建议（按 Walking Skeleton 推进）

### P0 — 阻塞 Walking Skeleton 闭环
- [x] Raw Ingestion（AKShare/Tencent 适配器）
- [x] Cleaning Engine（4 阶段 ETL）
- [x] Schema 校验（DailyPriceContract）
- [x] PIT 财报（FundamentalDataProduct）
- [x] **数据层测试**（121 用例，覆盖 10 模块）
- [x] **双时间戳标记**（source_event_time + ingestion_received_time）

### P1 — 影响回测可信度
- [x] 统计分布异动告警（Data Drift / PSI）
- [x] 断路器机制（异常 → 挂起）
- [x] PIT 发布延迟校验
- [x] 新股过滤（上市未满 N 天）
- [x] 流动性/成交量截断

### P2 — Feature Store 最小版
- [x] `BaseFeature` 实现 + Feature Registry
- [x] 离线特征库 Parquet 分区存储
- [x] 截面标准化 + Shift(1) 防泄露

### P3 — 完善与加固
- [x] 财务重述多版本
- [ ] 指数成分股历史变动
- [x] 在线特征缓存
- [x] 批流一体算子
- [x] 双时间戳标记（2026-07-21 完成）
- [ ] Tushare 适配器
- [x] Polars 向量化（2026-07-21 完成，CleaningEngine + DataPipeline + DemoAdapter）
- [x] DuckDB 分析查询集成
- [x] 重采样防泄露（resample_safe）
- [ ] `knowledge/` + `metadata/` + `builder/` 填充

---

## 文件清单（63 源文件 + 17 测试文件）

### 非空文件（有实际代码）

| 文件 | 行数估算 | 模块 |
|---|---|---|
| `qp/data/__init__.py` | ~5 | 层入口 |
| `qp/data/pipeline.py` | ~85 | DataPipeline（含双时间戳） |
| `qp/data/timestamp.py` | ~110 | **新增** — 双时间戳标注 |
| `qp/data/adapter/__init__.py` | ~5 | 适配器入口 |
| `qp/data/adapter/akshare_adapter.py` | ~70 | AKShare |
| `qp/data/adapter/demo_adapter.py` | ~120 | Demo 合成 |
| `qp/data/adapter/quant_trading_db_adapter.py` | ~120 | SQLite |
| `qp/data/adapter/tencent_adapter.py` | ~150 | 腾讯行情 |
| `qp/data/calendar/__init__.py` | ~3 | 日历入口 |
| `qp/data/calendar/calendar.py` | ~80 | TradingCalendar |
| `qp/data/capital_flow/__init__.py` | ~3 | 资金流入口 |
| `qp/data/capital_flow/adapter.py` | ~130 | 资金流+北向 |
| `qp/data/capital_flow/product.py` | ~100 | 资金流产品 |
| `qp/data/cleaning/__init__.py` | ~20 | 清洗入口 |
| `qp/data/cleaning/audit.py` | ~120 | 审计追踪 |
| `qp/data/cleaning/delisted_handler.py` | ~180 | 退市处理 |
| `qp/data/cleaning/engine.py` | ~80 | CleaningEngine |
| `qp/data/cleaning/etl_pipeline.py` | ~250 | 4 阶段 ETL |
| `qp/data/cleaning/repair.py` | ~280 | 5 类修复 |
| `qp/data/contract/__init__.py` | ~3 | 合约入口 |
| `qp/data/contract/daily_price.py` | ~65 | 日线 Schema（含 optional_schema） |
| `qp/data/corporate_action/__init__.py` | ~3 | 公司行为入口 |
| `qp/data/corporate_action/engine.py` | ~150 | 除权引擎 |
| `qp/data/dataset/__init__.py` | ~3 | 数据集入口 |
| `qp/data/dataset/registry.py` | ~60 | DatasetRegistry |
| `qp/data/fundamental/__init__.py` | ~3 | 基本面入口 |
| `qp/data/fundamental/adapter.py` | ~160 | FundamentalAdapter |
| `qp/data/fundamental/product.py` | ~180 | FundamentalDataProduct |
| `qp/data/industry/__init__.py` | ~3 | 行业入口 |
| `qp/data/industry/cache.py` | ~80 | IndustryCache |
| `qp/data/industry/classifier.py` | ~180 | IndustryClassifier |
| `qp/data/loader/__init__.py` | ~3 | 加载器入口 |
| `qp/data/loader/convert_quant_trading.py` | ~120 | DB 转换脚本 |
| `qp/data/loader/full_pipeline.py` | ~210 | FullDataPipeline（含双时间戳） |
| `qp/data/loader/loader.py` | ~60 | DatasetLoader |
| `qp/data/loader/quant_trading_loader.py` | ~100 | SQLite 直读 |
| `qp/data/valuation/__init__.py` | ~3 | 估值入口 |
| `qp/data/valuation/product.py` | ~160 | PE_TTM/PB/PCF |
| `qp/data/validation/__init__.py` | ~45 | **新增** — 校验层入口 |
| `qp/data/validation/result.py` | ~80 | **新增** — CheckResult/ValidationReport |
| `qp/data/validation/checks.py` | ~500 | **新增** — 7 项校验函数 |
| `qp/data/validation/drift.py` | ~230 | **新增** — PSI + Stats 漂移 |
| `qp/data/validation/circuit_breaker.py` | ~180 | **新增** — 三态断路器 |
| `qp/data/validation/gate.py` | ~200 | **新增** — ValidationGate 编排器 |
| `qp/data/universe/__init__.py` | ~40 | **新增** — PIT & Universe 入口 |
| `qp/data/universe/listing_dates.py` | ~280 | **新增** — IPO 日期注册（87 只硬编码 + 缓存） |
| `qp/data/universe/liquidity.py` | ~170 | **新增** — 流动性截断（绝对/百分位双模式） |
| `qp/data/universe/restatement.py` | ~230 | **新增** — 财务重述多版本追踪器 |
| `qp/data/universe/universe_builder.py` | ~230 | **新增** — 5 级过滤链编排器 |
| `qp/data/feature_store/__init__.py` | ~75 | **新增** — 特征商店入口 |
| `qp/data/feature_store/base_feature.py` | ~165 | **新增** — BaseFeature batch+stream |
| `qp/data/feature_store/registry.py` | ~185 | **新增** — FeatureRegistry 版本管理 |
| `qp/data/feature_store/engine.py` | ~200 | **新增** — FeatureEngine 编排器 |
| `qp/data/feature_store/standardization.py` | ~350 | **新增** — 标准化+防泄露 |
| `qp/data/feature_store/offline_store.py` | ~240 | **新增** — Parquet 分区存储 |
| `qp/data/feature_store/online_cache.py` | ~280 | **新增** — 线程安全内存缓存 |
| `qp/data/feature_store/factors/__init__.py` | ~65 | **新增** — 因子包入口 |
| `qp/data/feature_store/factors/momentum.py` | ~185 | **新增** — 动量/RSI/反转因子 |
| `qp/data/feature_store/factors/volatility.py` | ~155 | **新增** — 波动率/ATR |
| `qp/data/feature_store/factors/volume.py` | ~140 | **新增** — 量比/换手率/均量 |
| `qp/data/feature_store/factors/technical.py` | ~195 | **新增** — 均线交叉/MACD/价格位置 |

### 测试文件（17 个）

| 文件 | 用例数 | 覆盖模块 |
|---|---|---|
| `tests/unit/data/__init__.py` | — | 测试包入口 |
| `tests/unit/data/test_timestamp.py` | 18 | 双时间戳标注 |
| `tests/unit/data/test_cleaning_engine.py` | 10 | CleaningEngine |
| `tests/unit/data/test_etl_pipeline.py` | 14 | 4 阶段 ETL Pipeline |
| `tests/unit/data/test_repair.py` | 23 | 5 类修复函数 |
| `tests/unit/data/test_validation_checks.py` | 52 | **新增** — 8 项独立校验函数（含 financial_balance） |
| `tests/unit/data/test_validation_drift.py` | 16 | **新增** — PSI + Stats 漂移检测 |
| `tests/unit/data/test_validation_gate.py` | 33 | **新增** — ValidationGate + CircuitBreaker |
| `tests/unit/data/test_pandera_schemas.py` | 21 | **新增** — Pandera 4 套 Schema + GateConfig 集成 |
| `tests/unit/data/test_universe.py` | 32 | **新增** — ListingDateRegistry + Liquidity + RestatementTracker + UniverseBuilder |
| `tests/unit/data/test_contract.py` | 11 | DailyPriceContract |
| `tests/unit/data/test_dataset_registry.py` | 11 | DatasetRegistry |
| `tests/unit/data/test_demo_adapter.py` | 10 | DemoAdapter |
| `tests/unit/data/test_delisted_handler.py` | 9 | DelistedHandler |
| `tests/unit/data/test_audit.py` | 12 | ETL 审计追踪 |
| `tests/unit/data/test_corporate_action.py` | 13 | CorporateActionEngine |
| `tests/unit/data/test_feature_store.py` | 70 | **新增** — BaseFeature + Registry + Standardization + Engine + OfflineStore + OnlineCache |
| `tests/unit/data/test_feature_store_factors.py` | 27 | **新增** — 18 个具体因子全量测试 + 集成测试 |

### 空骨架文件（仅 docstring）

| 文件 | 应实现内容 |
|---|---|
| `qp/data/builder/__init__.py` | Dataset 组装逻辑 |
| `qp/data/metadata/__init__.py` | 数据源 schema/lineage 元数据 |
| `qp/data/knowledge/decision_audit/` | 决策审计归档 |
| `qp/data/knowledge/experiment_summary/` | 实验摘要归档 |
| `qp/data/knowledge/failure_analysis/` | 失败分析归档 |
| `qp/data/knowledge/post_mortem/` | 事后复盘归档 |
| `qp/data/knowledge/research_debt/` | 研究债务归档 |

---

## 修订记录

| 日期 | 变更 | 触发原因 |
|---|---|---|
| 2026-07-21 | 初始创建 | 对照 data_layer.md 全面评估实现进度 |
| 2026-07-21 | 更新 §1.9 + §6 + P0/P3 + 文件清单 | 双时间戳标记实现 + 121 个单元测试完成，P0 全部清空 |
| 2026-07-21 | 更新 §2.18 + 文件清单 | CleaningEngine / DataPipeline / DemoAdapter 迁移到 Polars；DailyPriceContract 支持 Pandas+Polars 双路径 |
| 2026-07-21 | 更新 §3 Validation + P1 + 文件清单 | Validation 层完整实现：checks(7)/drift(PSI)/circuit_breaker/gate；新增 6 源文件 + 3 测试文件(89 用例)；Validation 从 35% → 80% |
| 2026-07-21 | 更新 §3.6 + §3.11 | 财务平衡校验 + Pandera 集成：4 套 Polars Schema + PanderaValidator；Validation 从 80% → 95% |
| 2026-07-21 | 更新 §4 PIT & Universe + P1 | Universe 模块完整实现：IPO/liquidity/restatement/universe_builder；新增 5 源文件 + 1 测试文件(32 用例)；PIT & Universe 从 50% → 85%；P1 全部清空 |
| 2026-07-21 | 更新 §5 Feature Store + P2 | Feature Store 完整实现：BaseFeature/Registry/Engine/OfflineStore/OnlineCache/Standardization；新增 6 源文件 + 1 测试文件(70 用例)；P2 全部清空；总体进度 80% → 85% |
| 2026-07-21 | 更新 §5.11 具体因子实现 | 18 个具体因子：动量(6)/波动(4)/成交量(5)/技术(3)；新增 4 源文件 + 1 测试文件(27 用例)；Feature Store 75% → 95%；总体进度 85% → 90% |
| 2026-07-21 | 更新 P3 DuckDB 集成 | DuckDBEngine：SQL 查询/PIT/Parquet/OfflineStore 桥接/compute_sql；新增 1 源文件 + 1 测试文件(26 用例)；测验 417 passed |
| 2026-07-21 | 更新 P3 builder/ + metadata/ | DatasetBuilder（组装+契约+原子发布） + metadata/（SourceMetadataStore/SchemaTracker/LineageTracker）；新增 6 源文件 + 2 测试文件(37 用例)；测验 600 passed；总体进度 ~90% → ~95% |
