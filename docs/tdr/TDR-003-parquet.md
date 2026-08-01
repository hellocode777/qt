# TDR-003: Parquet

> Technology Decision Record — 列式存储格式

## 选择

**Apache Parquet** — 列式存储文件格式。

## 理由

- 列式存储：只读需要的列，I/O 大幅减少
- 压缩率高：相比 CSV 减少 70-90% 存储
- 自带 Schema：类型安全，不像 CSV 需要推断
- 跨语言：Python、Rust、C++ 均可读写
- DuckDB/Polars/Pandas 原生支持
- 不可变数据理念：写入后不修改，只追加（ADR-014）

## 使用方式

数据产品统一使用 Parquet 存储：

```
data/dataset/
├── daily_price_main.parquet       ← Gold 数据产品
├── daily_price_latest.parquet     ← 最新快照
├── momentum_20d.parquet           ← 特征数据
└── volatility_20d.parquet
```

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| CSV | 人类可读 | 无 Schema、体积大、读慢 |
| HDF5 | 压缩好 | Python 绑定弱 |
| Feather | 读写快 | 压缩率低 |
| **Parquet** ✅ | 全面最优 | 人类不可读 |
