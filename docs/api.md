# QP 公开 API 参考 / Public API Reference

> 所有抽象接口定义在 `qp/shared/protocols/`。实现类必须遵循这些契约。
> 最后更新：2026-08-01

---

## 目录

1. [BasePipeline](#1-basepipeline) — 管道
2. [BaseDataSource](#2-basedatasource) — 数据源
3. [BaseFeature](#3-basefeature) — 特征/因子
4. [BaseModel](#4-basemodel) — ML 模型
5. [BaseStrategy](#5-basestrategy) — 策略
6. [BaseExperimentTracker](#6-baseexperimenttracker) — 实验追踪
7. [BasePortfolioRiskManager](#7-baseportfolioriskmanager) — 组合风控
8. [BaseRiskModel](#8-baseriskmodel) — 风险归因
9. [BaseCapitalAllocator](#9-basecapitalallocator) — 资金分配
10. [BaseBroker](#10-basebroker) — 券商
11. [CorporateActionEngine](#11-corporateactionengine) — 公司行为

---

## 1. BasePipeline

**文件**: `qp/shared/protocols/base_pipeline.py`
**关联 ADR**: 006（一切皆 Pipeline）

所有长运行任务的抽象基类。`DailyPipeline`、`FeaturePipeline`、`DataPipeline` 等均继承此类。

```python
class BasePipeline(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """唯一管道标识符（如 'daily_ingest', 'momentum_20d'）"""
        ...

    @abstractmethod
    def run(self, context: PipelineContext) -> PipelineResult:
        """执行管道。

        Args:
            context: 包含 runtime, config, logger, parameters

        Returns:
            PipelineResult(status, metrics, artifacts, errors)
        """
        ...
```

---

## 2. BaseDataSource

**文件**: `qp/shared/protocols/base_data_source.py`
**关联 ADR**: 013, 017（消费者不知道数据源）

所有原始数据源适配器（AkShare, Tushare 等）的统一接口。

```python
class BaseDataSource(ABC):
    @property
    @abstractmethod
    def dataset_name(self) -> str:
        """唯一数据源标识符（如 'daily_price', 'financial_pit'）"""
        ...

    @abstractmethod
    def fetch_raw(
        self, start_date: date, end_date: date, **kwargs
    ) -> pd.DataFrame | pl.DataFrame:
        """从外部 API/数据库拉取原始数据（未经清洗）"""
        ...

    @abstractmethod
    def validate_schema(self, df: pd.DataFrame) -> bool:
        """验证原始 DataFrame 是否符合预期的 schema"""
        ...
```

---

## 3. BaseFeature

**文件**: `qp/shared/protocols/base_feature.py`
**关联 ADR**: 019（特征是头等资产）

所有因子/特征计算逻辑的统一接口。必须遵循 PIT（Point-in-Time）原则。

```python
class BaseFeature(ABC):
    @property
    @abstractmethod
    def feature_name(self) -> str:
        """唯一特征标识符，注册在 FeatureRegistry 中"""
        ...

    @property
    @abstractmethod
    def required_data(self) -> list[str]:
        """此特征依赖的底层 Dataset 名称列表"""
        ...

    @abstractmethod
    def compute(self, data_map: dict[str, Any]) -> Any:
        """计算特征值。

        Args:
            data_map: {dataset_name → DataFrame}，包含所有 required_data

        Returns:
            DataFrame[ trade_date, symbol, feature_value ]
            必须严格遵守单日截面原则（无未来信息泄漏）
        """
        ...
```

**已实现的特征**（`qp/research/feature/`）：

| 特征 | feature_name |
|------|-------------|
| `Momentum1M` | `Momentum_1M` |
| `Momentum3M` | `Momentum_3M` |
| `Momentum6M` | `Momentum_6M` |
| `Momentum20dFeature` | `Momentum_20D` |
| `ShortTermReversal5D` | `Short_Term_Reversal_5D` |
| `Volatility20dFeature` | `Volatility_20D` |
| `Volatility60D` | `Volatility_60D` |

---

## 4. BaseModel

**文件**: `qp/shared/protocols/base_model.py`
**关联 ADR**: 021（Purged KFold 强制）

所有 ML/统计模型的统一接口。默认实现：`LightGBMRankModel`。

```python
class BaseModel(ABC):
    @abstractmethod
    def fit(
        self, X: pd.DataFrame, y: pd.Series,
        sample_weight: pd.Series | None = None,
    ) -> None:
        """训练模型"""
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """生成预测/排序分数"""
        ...

    @abstractmethod
    def save_model(self, path: str) -> None:
        """序列化模型到磁盘，记录超参数元数据"""
        ...

    @abstractmethod
    def load_model(self, path: str) -> None:
        """加载之前注册的模型版本"""
        ...
```

**已实现的模型**（`qp/research/trainer/`）：

| 模型 | 说明 |
|------|------|
| `LightGBMRankModel` | LightGBM LambdaRank（默认），objective: lambdarank, metric: ndcg |

---

## 5. BaseStrategy

**文件**: `qp/shared/protocols/base_strategy.py`
**关联 ADR**: 026（策略产出 Decision）、027、028

所有投资策略的统一接口。策略 = 特征 + 标签 + 模型 + 组合规则 + 执行规则 + 退出规则。

```python
class BaseStrategy(ABC):
    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """唯一策略标识符（含版本号，如 'lgb_rank_v3.1'）"""
        ...

    @abstractmethod
    def generate_signals(self, as_of_date: date) -> Any:
        """从 PIT 视角生成原始 Alpha 信号。

        Args:
            as_of_date: 信号生成的参考日期。此日期之后的数据不可使用。

        Returns:
            DataFrame[ symbol, raw_score, rank ]
        """
        ...
```

---

## 6. BaseExperimentTracker

**文件**: `qp/shared/protocols/base_experiment_tracker.py`
**关联 ADR**: 018（一切皆实验）

记录完整依赖链：Dataset → Feature → Label → Model → Strategy → Metrics。

```python
class BaseExperimentTracker(ABC):
    @abstractmethod
    def log_experiment(
        self,
        experiment_id: str,
        config: dict[str, Any],
        metrics: dict[str, float],
        lineage_graph: dict[str, str],
    ) -> None:
        """记录完整实验：配置 + 指标 + 数据血缘。

        Args:
            experiment_id: 唯一实验标识符
            config: 完整实验配置（参数、版本、日期）
            metrics: 评估指标（IC, Sharpe 等）
            lineage_graph: 所有上游资产的版本绑定
        """
        ...
```

**实现**: `qp/research/experiment/tracker.py:ExperimentTracker`

---

## 7. BasePortfolioRiskManager

**文件**: `qp/shared/protocols/base_portfolio_risk.py`

组合层面的风控引擎。强制执行行业敞口限制、集中度限制和相关性过滤。

```python
class BasePortfolioRiskManager(ABC):
    @abstractmethod
    def apply_risk_limits(
        self,
        raw_signals: pd.DataFrame,
        current_positions: pd.DataFrame,
    ) -> pd.DataFrame:
        """对原始策略信号应用风控限制。

        Args:
            raw_signals: 策略输出信号
            current_positions: 当前持仓

        Returns:
            风控检查后的候选标的
        """
        ...
```

**实现**: `qp/portfolio/risk_manager.py:PortfolioRiskManager`

---

## 8. BaseRiskModel

**文件**: `qp/shared/protocols/base_risk_model.py`

多因子风险归因模型。分解总风险为系统性风险和特异性风险。

```python
class BaseRiskModel(ABC):
    @abstractmethod
    def decompose_risk(
        self, portfolio_holdings: pd.DataFrame,
    ) -> dict[str, float]:
        """将总风险分解为因子组件。

        Total Risk = Market Risk + Style Risk + Sector Risk + Idiosyncratic Risk

        Returns:
            {风险组件名: 风险值}
        """
        ...
```

---

## 9. BaseCapitalAllocator

**文件**: `qp/shared/protocols/base_capital_allocator.py`
**关联 ADR**: 029, 030（资金分配是组合的责任）

资金分配引擎。支持等权、风险平价、波动率目标、凯利公式等。

```python
class BaseCapitalAllocator(ABC):
    @abstractmethod
    def allocate(
        self,
        candidates: pd.DataFrame,
        risk_report: dict[str, Any] | None,
        total_capital: float,
    ) -> pd.DataFrame:
        """计算每个风控通过的候选标的的目标权重。

        Args:
            candidates: 风控通过后的候选标的，列：
                [symbol, alpha_score, risk_cluster, max_weight_limit,
                 risk_volatility, pass_status, ...]
            risk_report: 风控报告（行业敞口、违规项等），可为 None
            total_capital: 总可用资金（CNY）

        Returns:
            DataFrame[ symbol, target_weight, target_capital ]
        """
        ...

    def allocate_capital(
        self,
        candidate_signals: pd.DataFrame,
        total_capital: float,
    ) -> pd.DataFrame:
        """旧版接口 — 委托给 allocate()。保留用于向后兼容。"""
        ...

    @property
    def name(self) -> str:
        """分配器名称（默认返回类名）"""
        ...
```

**已实现的分配器**（`qp/portfolio/allocator/`）：

| 分配器 | 策略 |
|--------|------|
| `EqualWeightAllocator` | 等权分配 |
| `RiskParityAllocator` | 风险平价 |
| `VolatilityTargetAllocator` | 波动率目标 |
| `KellyAllocator` | 凯利公式 |

---

## 10. BaseBroker

**文件**: `qp/shared/protocols/base_broker.py`

统一券商接口。**设计说明**：QP 是决策辅助系统，非自动交易系统。此接口仅用于回测和纸交易模拟。

```python
class BaseBroker(ABC):
    @abstractmethod
    def submit_order(self, order: dict) -> str:
        """提交订单。返回券商分配的订单 ID。"""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """取消待处理订单。返回是否成功取消。"""
        ...

    @abstractmethod
    def get_positions(self) -> pd.DataFrame:
        """获取当前持仓"""
        ...

    @abstractmethod
    def get_cash(self) -> float:
        """获取可用现金余额"""
        ...
```

**实现**: `qp/simulation/broker.py:SimulatedBroker`

---

## 11. CorporateActionEngine

**文件**: `qp/shared/protocols/base_corporate_action.py`

公司行为调整引擎。处理分红、拆股、配股、分拆等事件。

```python
class CorporateActionEngine(ABC):
    @abstractmethod
    def adjust_portfolio(
        self,
        portfolio: pd.DataFrame,
        actions_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """应用公司行为调整持仓。

        Args:
            portfolio: 当前组合状态（持仓 DataFrame）
            actions_df: 公司行为 DataFrame（分红、拆股等）

        Returns:
            调整后的组合（更新后的数量和成本基准）
        """
        ...
```

---

## 实现映射速查

| 协议 | 实现位置 |
|------|----------|
| `BasePipeline` | `qp/platform/pipeline/runner.py` + `qp/pipeline/*.py` |
| `BaseDataSource` | `qp/data/adapter/` |
| `BaseFeature` | `qp/research/feature/` |
| `BaseModel` | `qp/research/trainer/lgb_rank.py` |
| `BaseStrategy` | `qp/strategy/strategies/` |
| `BaseExperimentTracker` | `qp/research/experiment/tracker.py` |
| `BasePortfolioRiskManager` | `qp/portfolio/risk_manager.py` |
| `BaseRiskModel` | `qp/portfolio/risk_model.py` |
| `BaseCapitalAllocator` | `qp/portfolio/allocator/` |
| `BaseBroker` | `qp/simulation/broker.py` |
| `CorporateActionEngine` | `qp/data/corporate_action/` |

---

## 如何添加新实现

1. 在对应目录创建新文件
2. 继承对应的 `Base*` 抽象类
3. 实现所有 `@abstractmethod` 方法
4. 在层的 `__init__.py` 中导出

## 关联文档

- [`developer_guide.md`](developer_guide.md) — 开发者指南
- [`user_guide.md`](user_guide.md) — 用户指南
- [`architecture/reference/twelve-layer-overview.md`](architecture/reference/twelve-layer-overview.md) — 架构总览
