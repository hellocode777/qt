# 编码规范 / Coding Style

> QP 项目编码标准。违反以下规则会导致 CI 失败（ruff check）。
> 最后更新：2026-08-01

---

## 1. 格式化

使用 `ruff format`，无需配置。自动处理：缩进（4 空格）、行宽（88 字符）、引号、尾随逗号。

```bash
uv run ruff format    # 自动格式化所有文件
```

## 2. Lint 规则

```bash
uv run ruff check     # 零错误要求
```

关键规则：

| 规则 | 说明 |
|------|------|
| `E501` | 行宽 ≤ 88（与 ruff format 一致） |
| `F401` | 禁止未使用的导入 |
| `F841` | 禁止未使用的变量 |
| `I001` | 导入必须排序（`isort` 规则） |

## 3. 导入顺序

```python
# 1. 标准库
from __future__ import annotations
from datetime import date, datetime
from typing import Any

# 2. 第三方库
import polars as pl
from loguru import logger

# 3. 项目内部
from qp.platform.pipeline.context import PipelineContext
from qp.shared.protocols.base_pipeline import BasePipeline
```

## 4. 禁止事项

| 禁止 | 替代 |
|------|------|
| `print()` | `logger.info()` |
| 裸 `except:` | `except ValueError as e:` |
| `except Exception: pass` | 至少 `logger.warning()` |
| 循环导入 | 提取到 `shared/` 或延迟导入 |
| `utils/` `helpers/` `common/` 目录 | 归属到对应层 |
| 可变默认参数 `def f(x=[])` | `def f(x=None): x = x or []` |

## 5. 类型注解

```python
# 所有公开函数必须类型注解
def compute_signals(
    price_data: dict[str, pl.DataFrame],
    today: str,
    top_n: int = 10,
) -> pl.DataFrame:
    ...

# 可选类型
from typing import Any
value: dict[str, Any] | None = None
```

## 6. 文档字符串

```python
def run(self, context: PipelineContext) -> PipelineResult:
    """执行管道。

    Args:
        context: 包含 runtime, config, logger, parameters

    Returns:
        PipelineResult(status, metrics, artifacts, errors)
    """
```

## 7. 空行规范

```python
# 模块级：两空行
import os


class MyClass:
    """Docstring."""

    # 方法间：一空行
    def method_a(self) -> None:
        ...

    def method_b(self) -> None:
        ...
```

## 8. 字符串

- 优先双引号 `"hello"`
- 多行用三引号 `"""`
- f-string 仅用于简单表达式，复杂逻辑用变量

## 9. 组合 vs 继承

- 优先组合而非继承
- 抽象基类用 `ABC` + `@abstractmethod`
- 具体实现继承自 `Base*` 协议类

## 10. 质量门禁

```bash
uv run ruff format    # 格式化 → 零修改
uv run ruff check     # Lint → 零错误
uv run pyright        # 类型 → 零错误
uv run pytest         # 测试 → 全部通过
```

全部通过才能提交。
