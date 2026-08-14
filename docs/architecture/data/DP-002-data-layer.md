# DP-002: Data Layer (L2)

> Design Proposal — 可信、版本化、可复现的数据产品
> 关联 ADR: 013, 014, 015, 016, 017

## 职责

产出 Data Products。消费者（research, strategy 等）依赖 Dataset，永远不知道原始数据源。

## 数据处理管道

```
Raw → Bronze（清洗）→ Silver（校验）→ Gold（Dataset）
```

## 子模块

| 子模块 | 文件数 | 核心功能 |
|--------|--------|----------|
| `data/adapter/` | 7 | 数据源适配器（AkShare 等） |
| `data/loader/` | 4 | 从 Parquet/DuckDB 加载数据 |
| `data/dataset/` | 1 | 数据产品定义 |
| `data/feature_store/` | 7 + 4 | 特征存储 + 因子计算（动量、波动率、反转） |
| `data/fundamental/` | 2 | 基本面（EPS, NAV） |
| `data/valuation/` | 2 | PE/PB 估值（PIT 对齐） |
| `data/calendar/` | 1 | A 股交易日历 |
| `data/universe/` | 4 | 股票池定义与筛选 |
| `data/cleaning/` | 5 | 数据清洗管道 |
| `data/validation/` | 7 | 数据质量验证 |
| `data/metadata/` | 3 | 数据血缘与元信息 |
| `data/industry/` | 2 | 行业分类映射 |
| `data/corporate_action/` | 1 | 公司行为（分红、拆股、复权） |
| `data/capital_flow/` | 2 | 资金流向 |
| `data/contract/` | 1 | 数据合约 |
| `data/builder/` | 3 | 数据产品构建器 |

## 关键设计决策

- **ADR-013**: Data Product 架构 — 消费者依赖 Dataset
- **ADR-014**: 原始数据不可变 — 从不修改，只追加
- **ADR-015**: Dataset 是唯一公开接口
- **ADR-016**: 发布前必须验证
- **ADR-017**: 消费者永远不知道数据源

## 复权策略（2026-08-14 修订 — 事故根因修复）

### 背景

2026-08-14 发现 `daily_price_latest.parquet` 被污染：腾讯 `fqkline/get` + `qfq` 接口
对部分股票返回负价格坏数据（如 600438 2018-10 出现 -0.068 连续 -50%/-41% 跳变），
且历史上腾讯(前复权)/新浪(不复权)/akshare(qfq) 三种复权状态混入同一张表，
导致所有 fwd return 计算失真。

### 新策略（三原则）

1. **全库只存不复权原始价**（Raw prices only）
   - 腾讯 `kline/kline`（无复权参数，`day` 字段）— 长历史主源
   - 新浪 `getKLineData` — 近期增量 + 交叉验证源
   - akshare `stock_zh_a_hist(adjust="")` — 备用源

2. **复权因子独立成表**（adj_factor.parquet）
   - 数据源：akshare `stock_zh_a_daily(adjust="qfq-factor")` → `[symbol, ex_date, qfq_factor]`
   - 公式（已实测验证）: `close_qfq = close_raw / qfq_factor(适用除权日)`
   - 实现：`qp/data/dataset/adjust_factor.py`

3. **复权在计算层按需做**（Adjust at compute time）
   - 消费者需要复权价时：`qfq_price(raw, fac)`
   - 或直接用日涨跌幅 `change_pct` 构造收益（复权无关）
   - 禁止把复权价写回 daily_price 表

### ⛔ 已废弃接口（BANNED）

| 接口 | 原因 | 替代 |
|------|------|------|
| 腾讯 `fqkline/get` + `qfq` | 负价格坏数据 bug（600438 实证） | 腾讯 `kline/kline`（无复权参数）|
| akshare `adjust="qfq"/"hfq"` 写入价格表 | 复权价混入原始价表 | `adjust=""` + 因子表 |

> 任何新代码不得引用 fqkline/qfqday/hfqday 字段。已有引用见 git history。

### 数据质量门禁

`qp/data/pipeline.py::_validate_data_gate` 新增 §8 涨跌停合理性检查：
- |单日收益| > 21% 即报错（主板±10%、创业/科创±20%、ST±5%，21% 超出所有板）
- 增量批次中不应出现除权日跳变；出现即拦截
- 600438 事故（-50%/-41%）会被此 gate 捕获

### 消费者注意

- research/strategy 需要复权价时：`from qp.data.dataset.adjust_factor import load_adj_factor, qfq_price`
- 需要收益率时优先用 `change_pct`（官方涨跌幅，复权无关）
- `etl_pipeline.py` stage4 复权（`raw × cum_factor`）默认跳过（adj_factors=None）；
  其 cum_factor 语义与 akshare qfq-factor（除法语义）不同，混用时务必转换

## 依赖

- **依赖**: L1 (Platform) — 存储、日志、管道
- **被依赖**: L3 (Research) — 通过 Dataset
