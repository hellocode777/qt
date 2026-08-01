# TDR-002: DuckDB

> Technology Decision Record — 分析数据库

## 选择

**DuckDB** — 嵌入式 OLAP 数据库。

## 理由

- 零配置、零依赖部署（单文件嵌入，无需独立服务）
- 列式存储引擎，分析查询性能远超 SQLite
- 原生支持 Parquet 读写（与 TDR-003 协同）
- Python 一等公民支持
- 个人量化场景无需 PostgreSQL/ClickHouse 的运维负担

## 使用方式

```python
from qp.platform.storage.factory import StorageFactory

storage = StorageFactory.create(backend="duckdb")
storage.query("SELECT * FROM daily_price WHERE symbol = '000001'")
```

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| SQLite | 嵌入式、简单 | OLTP 优化，分析慢 |
| PostgreSQL | 功能全 | 需要独立部署 |
| ClickHouse | 分析极快 | 运维重 |
| **DuckDB** ✅ | 嵌入+分析+Parquet | 并发写入限制 |

## 配置

```toml
[storage]
backend = "duckdb"
duckdb_path = "data/quant.duckdb"
```
