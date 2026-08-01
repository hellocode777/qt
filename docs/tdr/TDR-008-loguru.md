# TDR-008: Loguru

> Technology Decision Record — 日志系统

## 选择

**Loguru** — Python 日志库。

## 理由

- 零配置即可用（`from loguru import logger`）
- 结构化日志（`logger.info("{} records", n)`）
- 自动轮转、压缩、保留策略
- JSON 格式支持（生产环境）
- 彩色终端输出（开发环境）

## 使用方式

```python
from loguru import logger

# 正确 ✅
logger.info("处理 {} 条记录", len(data))
logger.warning("数据缺失: symbol={}", symbol)

# 禁止 ❌
print("处理完了")          # 永远不用 print
logger.info(f"处理完了")   # 不用 f-string（延迟求值）
```

## 配置

```toml
[logging]
level = "INFO"              # DEBUG | INFO | WARNING | ERROR
format = "colored"          # colored | json
```

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| logging | 标准库 | 配置繁琐 |
| structlog | 结构化 | 学习曲线 |
| **Loguru** ✅ | 开箱即用 | 非标准库 |
