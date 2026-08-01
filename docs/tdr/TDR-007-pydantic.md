# TDR-007: Pydantic

> Technology Decision Record — 配置与数据模型

## 选择

**Pydantic** — Python 数据验证库。

## 理由

- 类型安全：运行时自动验证 + 类型转换
- 与 Python 类型注解无缝集成
- `BaseModel` 支持嵌套模型、默认值、自定义验证器
- 配置冻结（`frozen=True`）防止运行时篡改（ADR-011）
- JSON Schema 导出

## 使用方式

```python
from qp.platform.config.models import Config

# 自动从 config.toml + 环境变量加载并验证
config = Config.load()

# 启动后冻结，不可修改
config.freeze()
```

## QP 中的使用范围

- `platform/config/models.py` — 全部配置模型（`Config`, `StorageConfig`, `ModelConfig` 等 10+ 模型）
- `decision/models.py` — `DecisionReport`, `TradeRecommendation`
- `strategy/models.py` — `AlphaSignal`, `AlphaSignalBatch`, `StrategyResult`
- `portfolio/models.py` — `AllocationResult`, `TargetPortfolio`
- `platform/proposals/models.py` — `StrategyProposal`

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| dataclasses | 标准库 | 无验证、无冻结 |
| attrs | 功能强 | 额外依赖 |
| **Pydantic** ✅ | 验证+配置+冻结 | 启动稍慢 |
