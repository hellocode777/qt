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

## 依赖

- **依赖**: L1 (Platform) — 存储、日志、管道
- **被依赖**: L3 (Research) — 通过 Dataset
