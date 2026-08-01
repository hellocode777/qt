# 命名规范 / Naming Conventions

> QP 项目命名标准。一致性是代码可维护性的基础。
> 最后更新：2026-08-01

---

## 1. 文件命名

| 类型 | 规则 | 示例 |
|------|------|------|
| Python 文件 | `snake_case.py` | `feature_pipeline.py` |
| 测试文件 | `test_<module>.py` | `test_feature_pipeline.py` |
| Markdown 文件 | `snake_case.md` | `developer_guide.md` |
| 数据文件 | `snake_case.parquet` | `daily_price_main.parquet` |

## 2. 类命名

| 类型 | 规则 | 示例 |
|------|------|------|
| 普通类 | `PascalCase` | `FeaturePipeline`, `RiskManager` |
| 抽象基类 | `BaseXxxx` | `BasePipeline`, `BaseStrategy` |
| 异常类 | `XxxxError` | `DataValidationError` |
| 配置类 | `XxxxConfig` | `StorageConfig`, `ProjectConfig` |
| Pydantic 模型 | `PascalCase` | `DecisionReport`, `AlphaSignal` |

## 3. 函数/方法命名

| 类型 | 规则 | 示例 |
|------|------|------|
| 公开函数 | `snake_case` | `compute_signals()`, `load_price_data()` |
| 私有函数 | `_snake_case` | `_build_index_df()`, `_load_snapshot()` |
| 工厂函数 | `create_*` | `create_slippage_model()` |
| 获取器 | `get_*` | `get_strategy_config()` |
| CLI handler | `cmd_*` | `cmd_experiment_run()` |

## 4. 变量命名

| 类型 | 规则 | 示例 |
|------|------|------|
| 常量 | `UPPER_CASE` | `DEFAULT_TIMEZONE`, `SELL_BUFFER_RANK` |
| 布尔变量 | `is_*`, `has_*`, `can_*` | `is_rebalance_day`, `has_signals` |
| 计数/索引 | `n_*` | `n_signals`, `n_positions` |
| 字典/映射 | `*_map`, `*_dict` | `signals_map`, `price_data` |

## 5. 统一术语（Ubiquitous Language）

| 术语 | 含义 | 禁止用 |
|------|------|--------|
| **Pipeline** | 管道 | Workflow, Flow, Process |
| **Job** | 调度计划 | Cron, Task |
| **Task** | Job 中的动作 | Job |
| **Run** | 一次执行实例 | Execution |
| **Signal** | 可交易信号 | Prediction |
| **Order** | 订单（可能被拒） | Trade |
| **Trade** | 已成交 | Order |
| **Experiment** | 实验容器 | Trial |
| **Dataset** | 可信数据产品 | Data Source, Table |
| **Data Source** | 原始数据提供商 | Dataset, API |
| **DecisionPackage** | 每日决策包 | Report, Output |

## 6. 目录命名

| 目录 | 规则 |
|------|------|
| 层级目录 | `snake_case`（`platform/`, `data/`, `research/` 等） |
| 不允许 | `utils/`, `helpers/`, `misc/`, `scripts/`, `common_utils/` |

## 7. 策略/模型 ID

```
{描述符}_{主版本}.{次版本}
例: momentum_vol_full, simple_rank_v1.0

模型: {algo}_{objective}_v{major}.{minor}
例: lgb_lambdarank_v3.1
```
