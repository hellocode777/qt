# 测试规范 / Testing Guidelines

> QP 项目测试标准。
> 最后更新：2026-08-01

---

## 1. 测试结构

```
tests/
├── __init__.py
├── conftest.py              ← 共享 fixtures
├── unit/                    ← 单元测试（镜像 qp/ 目录结构）
│   ├── platform/
│   │   ├── test_config.py
│   │   └── test_cli.py
│   ├── data/
│   ├── research/
│   ├── validation/
│   ├── strategy/
│   ├── portfolio/
│   ├── simulation/
│   ├── decision/
│   ├── monitoring/
│   └── knowledge/
└── e2e/                     ← 端到端测试
    └── test_daily_pipeline.py
```

## 2. 编写测试

### 2.1 基本模板

```python
"""测试模块描述。"""
import pytest
from qp.my_module import my_function


def test_my_function_basic():
    """基本功能测试。"""
    result = my_function(input_data)
    assert result is not None
    assert len(result) > 0


def test_my_function_edge_case():
    """边界条件测试。"""
    result = my_function([])
    assert result is not None


def test_my_function_error():
    """异常处理测试。"""
    with pytest.raises(ValueError, match="invalid input"):
        my_function(None)
```

### 2.2 使用 Fixtures

```python
import pytest
import polars as pl


@pytest.fixture
def sample_price_data() -> pl.DataFrame:
    """创建测试用行情数据。"""
    return pl.DataFrame({
        "trade_date": ["2024-01-01", "2024-01-02"],
        "symbol": ["000001", "000001"],
        "close": [10.0, 10.5],
        "volume": [1000000, 1200000],
    })


def test_with_fixture(sample_price_data):
    result = compute_returns(sample_price_data)
    assert not result.is_empty()
```

### 2.3 参数化测试

```python
@pytest.mark.parametrize("n_signals,expected", [
    (0, True),
    (5, True),
    (100, False),  # 超过阈值
])
def test_signal_limit(n_signals, expected):
    assert check_signal_limit(n_signals) == expected
```

## 3. 运行测试

```bash
uv run pytest                              # 全部测试
uv run pytest tests/unit/strategy/         # 某模块测试
uv run pytest tests/unit/strategy/test_config.py  # 单文件
uv run pytest -k "test_my_function"        # 按名称筛选
uv run pytest -x -q                        # 遇错即停，安静模式
uv run pytest -x -q --tb=short             # 简短 traceback
uv run pytest --cov=qp --cov-report=html   # 覆盖率报告
```

## 4. 测试原则

### 4.1 测试什么

| 优先级 | 内容 | 示例 |
|--------|------|------|
| 必须 | 公开 API 行为 | 函数输入→输出 |
| 必须 | 边界条件 | 空输入、极限值 |
| 必须 | 异常路径 | 错误输入、缺失数据 |
| 建议 | 回归测试 | 已修复的 bug |
| 可选 | 性能测试 | 超大数据集 |

### 4.2 不测试什么

- 私有方法（`_private_method`）— 通过公开 API 间接覆盖
- 第三方库行为 — 假设库已测试
- 日志输出 — 除非对系统行为至关重要

### 4.3 命名

```
test_<function_name>_<scenario>.py
例: test_compute_signals_empty_input.py
    test_compute_signals_large_dataset.py
```

## 5. Mock

```python
from unittest.mock import patch, MagicMock


@patch("qp.data.adapter.akshare.fetch_data")
def test_with_mock(mock_fetch):
    mock_fetch.return_value = pl.DataFrame({...})
    result = my_pipeline.run(context)
    assert result.status == PipelineStatus.SUCCESS
```

Mock 原则：只 mock 外部依赖（API 调用、文件系统、数据库），不 mock 项目内部模块。

## 6. 端到端测试

```python
# tests/e2e/test_daily_pipeline.py
def test_daily_pipeline_demo():
    """用 demo 数据跑完整每日管道。"""
    context = PipelineContext(
        pipeline_name="daily",
        parameters={"demo": True},
    )
    pipeline = DailyPipeline()
    result = pipeline.run(context)

    assert result.status == PipelineStatus.SUCCESS
    assert result.metrics.get("strategy_count", 0) > 0
```

## 7. CI 检查清单

提交前确保：

- [ ] `ruff format` 无修改
- [ ] `ruff check` 零错误
- [ ] `pyright` 零错误
- [ ] `pytest` 全部通过
- [ ] 新功能有测试覆盖
- [ ] 修复 bug 有回归测试
