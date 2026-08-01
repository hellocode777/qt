# TDR-010: Polars

> Technology Decision Record — DataFrame 库

## 选择

**Polars** — Rust 编写的高性能 DataFrame 库，作为 Pandas 的替代。（数据/研究层使用 Polars，组合/决策层使用 Pandas。）

## 理由

- 比 Pandas 快 5-10x（Rust 引擎 + 惰性求值 + 多线程）
- 内存效率高（零拷贝、Arrow 列式内存）
- 表达式 API 更安全（编译期错误，非运行时）
- 类型严格（无 NaN vs None 混淆）
- 与 Parquet/DuckDB 原生 Arrow 互操作

## 使用方式

```python
import polars as pl

# 加载数据
df = pl.read_parquet("data/dataset/daily_price_main.parquet")

# 表达式 API
result = (
    df
    .filter(pl.col("trade_date") >= "2024-01-01")
    .group_by("symbol")
    .agg([
        pl.col("close").last().alias("latest_close"),
        pl.col("volume").mean().alias("avg_volume"),
    ])
)
```

## Polars vs Pandas 分工

| 层 | 使用 | 理由 |
|----|------|------|
| L2 Data | Polars | 大数据量 ETL、特征计算 |
| L3 Research | Polars | 截面排序、因子计算 |
| L5 Strategy | Polars | 信号生成 |
| L6 Portfolio | Pandas | 少量数据、已有生态（`CapitalAllocator` 接口） |
| L8 Decision | Pandas | 少量数据 |

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| Pandas | 生态最大 | 慢、内存大 |
| Dask | 分布式 | 小数据没必要 |
| **Polars** ✅ | 极快+安全 | 部分 API 不兼容 Pandas |
