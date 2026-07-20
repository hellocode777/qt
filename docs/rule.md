# 🏛️ Personal Quant Research & Investment Decision Platform
## 项目宪法与工程落地规范（v4.2 · Enterprise Frozen & Walking Skeleton Edition）

> 本文档整合并重组原 v4.0 与 v4.1 两版讨论内容，去除重复表述，按「先看懂全局 → 再查宪法条文 → 再查接口规范 → 最后看执行计划」的顺序编排，供未来数年开发中随时查阅、对照与自我审查。

---

## 目录

1. [定位与使命](#1-定位与使命)
2. [核心工程哲学](#2-核心工程哲学)
3. [十二层企业级架构](#3-十二层企业级架构)
4. [九大核心领域对象](#4-九大核心领域对象)
5. [两大生命周期状态机](#5-两大生命周期状态机)
6. [二十八条系统宪法](#6-二十八条系统宪法)
7. [Phase 0.1 核心抽象接口定义](#7-phase-01-核心抽象接口定义)
8. [Walking Skeleton 落地路线图](#8-walking-skeleton-落地路线图)
9. [架构完整性自查表](#9-架构完整性自查表)
10. [量化判定标准与运营参数](#10-量化判定标准与运营参数)
11. [Walking Skeleton 之后：Phase 1 优先级](#11-walking-skeleton-之后phase-1-优先级)
12. [宪法修订流程](#12-宪法修订流程)
13. [使用说明：如何在未来的开发中使用本文档](#13-使用说明如何在未来的开发中使用本文档)

---

## 1. 定位与使命

**定位宣言**：这是一个面向个人投资者的量化研究与投资决策操作系统（Personal Quant Research & Decision Operating System）。系统负责海量数据治理、因子研究、策略研发、组合风险建模、资金配置、组合归因、持仓生命周期管理与决策审计；**人负责最终的投资判断与决策执行**。

**核心使命**：系统不为单纯预测股票，而为建立一个可以伴随投资者成长十年以上、能够持续产生假设、验证假设、控制风险、淘汰错误、沉淀知识并最终辅助投资决策的量化基础设施与决策闭环。

**终极目标**：策略产生 Alpha，组合管理风险，系统承载计算，人类执行决策，最小闭环驱动演进。

---

## 2. 核心工程哲学

> 系统以 **Domain Objects（领域对象）** 为核心流动，以 **12-Layer Architecture** 为边界，以 **Walking Skeleton（行走骨架）** 为建设原则。

三句话概括整套方法论：

- **不以模块视角开发，以对象视角开发** —— 代码不是孤立的函数集合，而是围绕 9 个强类型、可全生命周期追溯的领域对象在流动。
- **架构定边界，不定优先级** —— 12 层架构描述的是"系统最终应该长成什么样"，不代表"现在就要把每一层都建完"。
- **先跑通，再加深** —— 任何抽象层的扩建，必须在 Walking Skeleton（端到端最小闭环）跑通之后才允许进行。

---

## 3. 十二层企业级架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                             1. Platform Layer                            │
│ Config System · Structured Logging · Task Scheduler · Experiment Tracker  │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                                2. Data Layer                             │
│ Raw Ingestion ──► Cleaning Engine ──► Validation ──► PIT & Universe ──► Feature Store │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                              3. Research Layer                           │
│ Exploratory (Notebooks) ──► Production Src ──► Neutralization ──► Purged CV│
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                   4. Registry & Lineage Layer（注册与血缘中心）           │
│ Data / Feature / Model / Strategy Registry · Full Data Lineage Graph      │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                 5. Validation Gate & Research Review Process             │
│   Strategy Proposal ──► Data Check ──► Stat Check ──► Backtest Check     │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │ （仅批准通过的策略可进入下一层）
┌────────────────────────────────────▼─────────────────────────────────────┐
│                             6. Strategy Engine                           │
│               Signal Generation ──► Multi-Strategy Ensemble               │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                         7. Portfolio Risk Layer（组合风控）               │
│    Sector/MarketCap Concentration · Correlation Analysis · Risk Budget   │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                      8. Capital Allocation Layer（资金管理）              │
│     Kelly Criterion · Risk Parity · Volatility Target · Equal Weight     │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                             9. Simulation Layer                          │
│     Paper Trading · Order Simulation · Slippage Check · Alpha Decay Check │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                            10. Decision Layer                            │
│ Candidate Manager · Position Manager · Exit Engine · Human Decision Audit│
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                            11. Monitoring Layer                          │
│ Drift & Decay Detection · Market Regime Engine · Kill Switch（策略熔断）  │
└────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌────────────────────────────────────▼─────────────────────────────────────┐
│                       12. Knowledge Layer（知识与资产库）                 │
│ Research Debt · Failure Archive · Market Regime Notes · Decision Audit   │
└──────────────────────────────────────────────────────────────────────────┘
```

**各层一句话职责速查：**

| 层级 | 职责 |
|---|---|
| 1. Platform | 配置、日志、调度、实验追踪等基础设施 |
| 2. Data | 从原始数据到 PIT、可用于建模的特征存储 |
| 3. Research | 探索性研究到生产代码的转化，含中性化与防泄漏交叉验证 |
| 4. Registry & Lineage | 所有资产（数据/特征/模型/策略）的注册与全链路血缘 |
| 5. Validation Gate | 策略上生产前的强制审查关卡 |
| 6. Strategy Engine | 信号生成与多策略融合 |
| 7. Portfolio Risk | 组合层面的集中度、相关性、风险预算控制 |
| 8. Capital Allocation | 把信号转化为具体仓位金额 |
| 9. Simulation | 纸面交易，检验滑点与信号衰减 |
| 10. Decision | 候选/持仓管理、离场引擎、人工决策审计 |
| 11. Monitoring | 漂移检测、市场状态感知、熔断机制 |
| 12. Knowledge | 研究债务、失败归档、决策审计等知识沉淀 |

---

## 4. 九大核心领域对象

系统不再以"孤立代码模块"视角运转，而是围绕以下 9 个强类型、全生命周期可追溯的一等公民（First-Class Citizens）流动：

```
 [ DataSet ] ────────► [ Feature ] ────────► [ Model ]
                                                  │
                                                  ▼
  [ Position ] ◄─────── [ Portfolio ] ◄─────── [ Strategy ]
       │                      │
       ▼                      ▼
   [ Order ]            [ Decision ] ────► (Human Audit & Exec)

  ──────────────────────────────────────────────────────────
  * Experiment（横向穿透：记录从 Dataset 到 Order 的全依赖血缘与元数据）
```

| 对象 | 定义 |
|---|---|
| **DataSet** | PIT 视角下的清洗后数据集，具备 Data Contract 约束 |
| **Feature** | 截面中性化后的因子/特征数据 |
| **Model** | 训练完毕、具备版本号与预测接口的算法模型 |
| **Strategy** | 绑定 Feature + Model + Signal 逻辑的 Alpha 产生器 |
| **Portfolio**（核心） | 最终投资对象，承载多策略 Alpha 融合、风险拆解、资金分配与总风险预算 |
| **Position** | 持仓对象，拥有严格的生命周期状态机 |
| **Order** | 交易订单，包含滑点、冲击成本、ADV 限制与 Broker 执行状态 |
| **Decision** | 人的决策审计日志，记录人对系统推荐的接受/拒绝/改单及理由 |
| **Experiment** | 实验记录与全图数据血缘（Lineage Graph） |

> **关键认知**：`Strategy` 产生 Alpha，`Portfolio` 才是最终对投资结果负责的对象。单股 Alpha 好 ≠ 组合表现好，这是本宪法反复强调的机构级底层思维。

---

## 5. 两大生命周期状态机

### 5.1 策略生命周期（Strategy Lifecycle）

```
  [ Research ]
       │
       ▼ (Research Proposal & IC Passed)
  [ Backtest Passed ]
       │
       ▼ (Validation Gate Passed)
  [ Paper Trading ]  ◄── 模拟撮合、实时滑点与衰减检验
       │
       ▼ (Pass Paper Test > 30 Days)
  [ Shadow Production ] ◄── 观察生产输出，少量模拟资金验证
       │
       ▼ (Production Approval)
  [ Production ]
       │
       ├─────────────────────────────────┐
       ▼ (Drift/Decay Warning)           ▼ (Trigger Risk Limit)
   [ Warning ]                      [ Kill Switch (Suspended) ]
       │                                 │
       └────────────────┬────────────────┘
                         ▼
                  [ Deprecated ]
                         │
                         ▼
                   [ Archived ]
```

### 5.2 持仓生命周期（Position Lifecycle）

任何标的从进入视野到彻底平仓，必须拥有完整且状态可追踪的生命周期：

```
[ Idea ] → [ Candidate ] → [ Approved ] → [ Holding ] → [ Reducing ] → [ Closed ] → [ Archived ]
```

对应枚举定义见第 7 节 `PositionState`。

---

## 6. 二十八条系统宪法

> 保留全部条文，按主题分类编号，方便未来开发中按场景快速定位对应原则。

### 6.1 数据与基础原则（Data & Foundation）

1. **Research First** —— 研究效率高于工程复杂度，拒绝过度设计。
2. **Data is Foundation** —— 数据质量决定策略上限，Garbage In, Garbage Out。
3. **Every Data Point Has Timestamp** —— 数据必须具备 Point-in-Time（PIT）视角，任何时间节点只能访问当时公开可见的信息。
4. **Data Has Contracts** —— 所有下游数据依赖必须通过 Data Contract 进行 Schema 与质量校验。
5. **Granular Data Cleaning** —— 停牌（volume=0）、涨跌停（无法成交）、除权除息（复权因子）与 ST/退市状态必须在底层处理完毕，严禁直接 `fillna(0)` 或假设随时按盘后价成交。

### 6.2 研究、血缘与验证原则（Research, Lineage & Validation）

6. **Everything is Experiment** —— 所有假设与代码调整必须记录为 Experiment，且保证 100% 可复现。
7. **Full Data Lineage** —— 所有决策、信号、策略与模型输出必须保持从数据源到最终 Order 的完全可追溯数据血缘图谱。
8. **IC Before Backtest** —— 因子必须先通过 IC/Rank IC 统计显著性、单日截面中性化与分层测试，才能进入复杂模型与回测。
9. **Alpha Must Survive Neutralization** —— 无法通过行业与市值中性化检验的"收益"，只是 Beta 风格暴露，非纯 Alpha。
10. **Research Code Is Not Production Code** —— Notebook 仅用于探索实验，严禁直接导入生产模块。进入生产前必须重构为模块化代码（`src/`）。
11. **Production Is Earned, Not Assumed** —— 策略必须经过严格的 Strategy Proposal、Validation Gate 审查以及 Paper Trading 验证，才能进入生产。
12. **Pay Down Research Debt** —— 研究失败的假设与验证必须存档归类（Research Debt Archive），避免在相同错误方向上重复浪费时间。

### 6.3 策略、组合与资金管理原则（Portfolio & Capital Management）

13. **Alpha is Product** —— 系统只是工具，可理解、可演进的 Alpha 才是真正的产品。
14. **Simple is Better** —— 优先选择简单可维护的模型，Alpha 来源于特征工程，而非模型复杂度。
15. **Strategy Is The Core Object** —— Strategy = Feature + Label + Model + Portfolio Rule + Execution Rule + Exit Rule。
16. **Separate Stock Selection from Portfolio Construction** —— 单股 Alpha 不等于组合优劣。组合层必须独立进行行业集中度、市值暴露限制与风险预算分配。
17. **Respect Market Regimes** —— 根据市场状态（Regime）动态感知不同风格和策略的权重与适用性。

### 6.4 执行、决策、监控与熔断原则（Execution, Decision & Governance）

18. **Backtest & Paper Must Simulate Reality** —— 必须真实模拟滑点、印花税、冲击成本与 ADV 限制，彻底杜绝盘后价格错配。
19. **Manage Positions, Not Just Picks** —— 选股仅占 20%，持仓生命周期管理与 Exit Engine 占剩下的 80%。
20. **Human in the Loop** —— 系统负责海量计算与决策支持，人负责最终判断与下单。人的决策过程必须录入审计日志。
21. **Production Needs Monitoring** —— 策略上线后必须持续监控 Performance Drift、Feature Drift 与 Model Decay。
22. **Every Alpha Needs Attribution** —— 任何组合收益必须进行因子归因与行业归因，清晰区分 Alpha 与 Beta。
23. **Version Everything** —— 所有影响结果的组件（数据、特征、模型、策略配置、引擎）必须全栈版本化管理。
24. **Same Input, Same Output**（确定性可复现） —— 在指定输入版本、随机种子与运行环境中，研究结果必须确定性复现。
25. **Protect Capital Before Pursuing Alpha (Kill Switch)** —— 系统安全高于收益。策略触发严重回撤或指标异常时，触发熔断机制，暂停推送买入推荐。

### 6.5 组合、状态与工程落地原则（v4.1 新增）

26. **Portfolio Is The Final Investment Object** —— 策略产生 Alpha，组合承载与管理风险。单股 Alpha 不等同于投资组合，所有交易指令与风险暴露必须在 Portfolio 层统一求解与归因。
27. **Every Position Has A Lifecycle** —— 持仓不是简单的数字更新，任何标的从进入视野到彻底平仓必须拥有完整且状态可追踪的生命周期状态机（详见第 5.2 节）。
28. **Build Walking Skeleton Before Expansion** —— 架构深度服从于端到端闭环。严禁在没有走通第一条 Minimal Pipeline（Data → Feature → Strategy → Backtest → Report）的前提下进行抽象扩建。

> **执行提示**：Rule 28 是对 Rule 1（Research First）在工程层面的强化。未来每次想要"新增一层抽象"之前，先自问：Walking Skeleton 是否已经跑通？这一层是否已经被至少一次真实需求逼出来，而不是提前预判？

---

## 7. Phase 0.1 核心抽象接口定义

以 Python 3.12+ `typing` / `abc` 为标准。所有核心模块必须实现以下抽象类与强类型接口，确保未来 5 年架构不发生腐化。

### 7.1 数据源接口（BaseDataSource）

```python
from abc import ABC, abstractmethod
from datetime import date
import pandas as pd

class BaseDataSource(ABC):
    """所有原始数据采集器的统一接口"""

    @property
    @abstractmethod
    def dataset_name(self) -> str:
        """数据源标识符，如 daily_price, financial_pit"""
        pass

    @abstractmethod
    def fetch_raw(self, start_date: date, end_date: date, **kwargs) -> pd.DataFrame:
        """从源端 API 或数据库拉取原始数据 (Raw)"""
        pass

    @abstractmethod
    def validate_schema(self, df: pd.DataFrame) -> bool:
        """配合 Data Contract 验证 Schema 与约束"""
        pass
```

### 7.2 特征工程接口（BaseFeature）

```python
from abc import ABC, abstractmethod
import pandas as pd

class BaseFeature(ABC):
    """所有因子/特征计算逻辑的统一接口"""

    @property
    @abstractmethod
    def feature_name(self) -> str:
        """因子标识符，必须在 Feature Registry 登记"""
        pass

    @property
    @abstractmethod
    def required_data(self) -> list[str]:
        """依赖的底层 Dataset 列表"""
        pass

    @abstractmethod
    def compute(self, data_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        计算因子值
        返回格式: DataFrame[trade_date, symbol, feature_value]
        严格遵守单日截面原则，严禁使用未来信息
        """
        pass
```

### 7.3 模型接口（BaseModel）

```python
from abc import ABC, abstractmethod
import pandas as pd
from typing import Any

class BaseModel(ABC):
    """所有机器学习与统计模型的统一抽象"""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: pd.Series | None = None) -> None:
        """模型训练"""
        pass

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """预测概率或 Ranking 预测得分"""
        pass

    @abstractmethod
    def save_model(self, path: str) -> None:
        """序列化存盘并记录超参元数据"""
        pass

    @abstractmethod
    def load_model(self, path: str) -> None:
        """加载已注册的模型版本"""
        pass
```

### 7.4 策略接口（BaseStrategy）

```python
from abc import ABC, abstractmethod
from datetime import date
import pandas as pd

class BaseStrategy(ABC):
    """策略核心对象，绑定特征、模型与执行逻辑"""

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """策略唯一标识（包含版本号，如 lgb_rank_v3.1）"""
        pass

    @abstractmethod
    def generate_signals(self, as_of_date: date) -> pd.DataFrame:
        """
        基于 PIT 视角生成原始 Alpha 信号
        返回: DataFrame[symbol, raw_score, rank]
        """
        pass
```

### 7.5 组合风控与资金分配接口

```python
from abc import ABC, abstractmethod
import pandas as pd

class BasePortfolioRiskManager(ABC):
    """组合层风控引擎接口"""

    @abstractmethod
    def apply_risk_limits(
        self, raw_signals: pd.DataFrame, current_positions: pd.DataFrame
    ) -> pd.DataFrame:
        """
        执行行业暴露、集中度与相关性过滤
        返回过滤后的目标持仓候选清单
        """
        pass


class BaseCapitalAllocator(ABC):
    """资金配置引擎接口"""

    @abstractmethod
    def allocate_capital(
        self, candidate_signals: pd.DataFrame, total_capital: float
    ) -> pd.DataFrame:
        """
        计算每只股票的具体目标持仓金额与权重 (Weight / Target Amount)
        使用 Kelly / Risk Parity / Equal Weight 等算法
        """
        pass
```

### 7.6 实验与生命周期审计接口（BaseExperimentTracker）

```python
from abc import ABC, abstractmethod
from typing import Any

class BaseExperimentTracker(ABC):
    """实验追踪与 Full Lineage 数据血缘记录器"""

    @abstractmethod
    def log_experiment(
        self,
        experiment_id: str,
        config: dict[str, Any],
        metrics: dict[str, float],
        lineage_graph: dict[str, str]
    ) -> None:
        """记录完整的实验配置、评价指标与全图血缘版本绑定关系"""
        pass
```

### 7.7 券商抽象与除权引擎（v4.1 新增，execution/ 与 data/）

```python
from abc import ABC, abstractmethod
from enum import Enum
import pandas as pd

class PositionState(Enum):
    IDEA = 1
    CANDIDATE = 2
    APPROVED = 3
    HOLDING = 4
    REDUCING = 5
    CLOSED = 6
    ARCHIVED = 7


class BaseBroker(ABC):
    """统一券商 API 接口，实现 Paper Trading 与 Live Trading 的无缝切换"""

    @abstractmethod
    def submit_order(self, order: dict) -> str: pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: pass

    @abstractmethod
    def get_positions(self) -> pd.DataFrame: pass

    @abstractmethod
    def get_cash(self) -> float: pass


class CorporateActionEngine(ABC):
    """处理分红、送股、拆股、配股造成的持仓股数与成本调整"""

    @abstractmethod
    def adjust_portfolio(self, portfolio: object, actions_df: pd.DataFrame) -> object: pass
```

### 7.8 多因子风险模型拆解（v4.1 新增，portfolio/risk/）

```python
from abc import ABC, abstractmethod
import pandas as pd

class BaseRiskModel(ABC):
    """组合风险因子归因模型"""

    @abstractmethod
    def decompose_risk(self, portfolio_holdings: pd.DataFrame) -> dict[str, float]:
        """
        拆解 Total Risk = Market Risk + Style Risk + Sector Risk + Idiosyncratic Risk
        """
        pass
```

### 7.9 模型选择与训练规范：LightGBM 实践（v4.2 新增）

> `BaseModel`（第 7.3 节）只定义了接口，本节针对确定使用 **LightGBM** 作为默认建模算法的情况，把 Rule 14「Simple is Better」落到具体训练规范上。不脱离该原则的前提下使用 LightGBM，是因为它在树模型中训练快、原生支持类别特征与单调约束、可解释性优于神经网络，属于"简单可维护"范畴内相对复杂的一端——**这不意味着可以放弃特征工程，转而依赖模型复杂度**。

#### 7.9.1 建模目标

- **默认使用 LambdaRank（排序目标）**，而非直接回归未来收益率。个股收益率噪声极大，排序目标只要求模型正确区分相对强弱，比精确预测收益率更稳健、也更贴近选股场景的实际用途。
- 若需要输出可用于 Capital Allocation 的连续分数（见第 7.5 节 `BaseCapitalAllocator`），对 LambdaRank 的原始输出做单调变换（如按截面 rank 百分位映射），不要直接把它当作预期收益率使用。
- 标签（Label）默认使用未来 N 个交易日的**行业中性化后收益率排名**（呼应 Rule 9），N 的取值需与调仓频率一致，避免标签周期与实际持仓周期错配。

#### 7.9.2 特征输入规范

- 所有特征在喂入模型前，必须完成**单日截面标准化**（z-score 或 rank-normalize），严禁跨日期直接使用原始量纲的特征。
- 类别特征（如行业代码）使用 LightGBM 原生类别特征支持（`categorical_feature` 参数），不做 one-hot 展开。
- 缺失值：默认不做人工填充，直接交给 LightGBM 原生缺失值处理机制（除非能证明缺失本身不具备信息量，此时才允许中性填充）。
- 特征数量上限：单模型默认不超过 60 个特征。超过此数量前，先检查是否有特征冗余（相关性 > 0.9 的特征只保留一个），呼应 Rule 14。

#### 7.9.3 Purged Cross-Validation 具体做法

对应第 3 层 Research Layer 中提到的 "Purged CV"，具体规则如下：

- **切分方式**：严格按时间顺序切分（Walk-Forward），默认 5 折，每折训练窗口滚动前进，**禁止随机 shuffle**。
- **Purge（净化）**：训练集与验证集之间，凡是标签计算窗口存在重叠的样本，一律从训练集中剔除。例如标签用未来 10 日收益，验证集起始日前 10 个交易日的训练样本必须剔除。
- **Embargo（禁运期）**：验证集结束后，额外留出等于「特征最大回看窗口 + 标签窗口」长度的禁运期，禁运期内样本不参与下一折训练，防止特征端的信息泄漏。
- **最小训练窗口**：不少于 2 年（约 500 个交易日），保证覆盖足够的市场状态多样性。

#### 7.9.4 超参数默认起点

以下为保守的默认起点，**不是最优参数**，用于第一版模型上线，后续按验证集表现小幅调整，避免直接上手做大规模网格搜索（防止过拟合验证集本身）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `objective` | `lambdarank` | 排序目标 |
| `num_leaves` | 31 | 控制树复杂度，宁小勿大 |
| `max_depth` | 5–6 | 配合 `num_leaves` 限制过拟合 |
| `learning_rate` | 0.03–0.05 | 配合 early stopping 使用 |
| `n_estimators` | 500–1000（配合 early stopping） | 不手动固定，用验证集早停 |
| `min_data_in_leaf` | 100+ | A 股/个股截面样本量有限时尤其重要，防止叶子节点过拟合个别样本 |
| `feature_fraction` | 0.7–0.8 | 每棵树随机采样特征，降低过拟合 |
| `bagging_fraction` | 0.7–0.8 | 每棵树随机采样样本 |
| `lambda_l1` / `lambda_l2` | 0.1–1.0 | 正则化，起点可以偏保守（取较大值） |
| `early_stopping_rounds` | 50 | 基于验证集 NDCG 或 IC 早停 |

#### 7.9.5 防止过拟合的强制检查

- **样本外 IC 与样本内 IC 之比**：若样本外 IC 低于样本内 IC 的 50%，视为过拟合信号，模型不允许上线，需回到特征工程阶段重新审视（呼应 Rule 8、Rule 9）。
- **单调约束（Monotonic Constraints）**：对有明确经济学方向的特征（如估值因子理论上应负向预测收益），使用 LightGBM 的 `monotone_constraints` 参数强制约束方向，防止模型学到反直觉的噪声关系。
- **不允许**仅通过增加特征数量或调高模型复杂度来提升样本内表现，任何模型复杂度的提升必须伴随样本外 IC 的同步提升，否则视为过拟合。

#### 7.9.6 再训练频率与模型版本管理

- **默认再训练频率**：月度滚动重训（Walk-Forward），训练窗口滚动前进，不做增量学习。
- 每次重训必须完整记录（写入 `BaseExperimentTracker`，见第 7.6 节）：训练窗口起止日期、特征列表版本、超参数、验证集指标、模型文件哈希、对应的 Git commit。
- **模型版本命名规则**：`{algo}_{objective}_v{major}.{minor}`，如 `lgb_lambdarank_v3.1`，与第 7.4 节 `strategy_id` 示例保持一致的命名习惯。

#### 7.9.7 可解释性与异常检查（对应 Rule 9、Rule 22）

- 每次重训后，必须输出 **Gain-based Feature Importance** 排名，人工检查是否有非预期特征（如某个应该弱相关的特征突然权重极高，往往是数据泄漏信号）。
- 对 Top 10 高权重信号，定期（建议每季度）用 SHAP 做局部解释性抽查，确认模型决策逻辑符合基本金融常识，而不是纯粹拟合噪声。
- 若某次重训的 Feature Importance 排名与上一版本发生剧烈变化（如 Top 5 特征完全不同），触发人工复核，暂缓自动上线新版本。

#### 7.9.8 模型退化判定（与第 10.3 节 Kill Switch 联动）

- 第 10.3 节的 PSI 阈值针对**特征/预测分布漂移**，本节补充**模型本身表现退化**的判定：滚动 20 日样本外 IC 若连续低于训练时验证集 IC 的 30%，标记为 Model Decay，触发降级复核（而非直接 Kill Switch，先降级到 Shadow 观察）。
- Model Decay 与 Kill Switch 的关系：Model Decay 是模型层面的早期预警，Kill Switch（第 10.3 节）是组合/策略层面的最终防线，两者独立触发，不互相替代。

#### 7.9.9 最小实现示例

```python
import lightgbm as lgb
import pandas as pd
from base_protocols import BaseModel  # 对应第 7.3 节接口

class LightGBMRankModel(BaseModel):
    """LightGBM LambdaRank 最小实现，仅作为 Walking Skeleton 阶段的参考起点"""

    def __init__(self, params: dict | None = None):
        default_params = {
            "objective": "lambdarank",
            "num_leaves": 31,
            "max_depth": 6,
            "learning_rate": 0.05,
            "min_data_in_leaf": 100,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "lambda_l1": 0.5,
            "lambda_l2": 0.5,
        }
        self.params = {**default_params, **(params or {})}
        self.model: lgb.Booster | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series, sample_weight: pd.Series | None = None) -> None:
        # group 需按截面日期切分，用于 LambdaRank 的分组排序
        train_set = lgb.Dataset(X, label=y, weight=sample_weight)
        self.model = lgb.train(
            self.params, train_set,
            num_boost_round=1000,
            callbacks=[lgb.early_stopping(stopping_rounds=50)],
        )

    def predict(self, X: pd.DataFrame) -> pd.Series:
        assert self.model is not None, "模型尚未训练"
        return pd.Series(self.model.predict(X), index=X.index)

    def save_model(self, path: str) -> None:
        assert self.model is not None
        self.model.save_model(path)

    def load_model(self, path: str) -> None:
        self.model = lgb.Booster(model_file=path)
```

---

## 8. Walking Skeleton 落地路线图

**原则**：拒绝过度设计，停止增加架构概念。用 3 周时间打造一条能真正跑通的最小策略闭环。

```
                ┌────────────────────────────────────────┐
                │         Walking Skeleton Pipeline       │
                └───────────────────┬────────────────────┘
                                    │
  [ daily_price.parquet ] ─────────┼──► Data Layer (Simple Ingestion)
                                    │
  [ momentum_20d ] ────────────────┼──► Feature Layer (Basic Momentum)
                                    │
  [ SimpleRankStrategy ] ──────────┼──► Strategy Engine (Top-N Rank)
                                    │
  [ SinglePortfolio ] ─────────────┼──► Portfolio Layer (Equal Weight)
                                    │
  [ SimpleVectorBacktest ] ────────┼──► Backtest & Execution Simulation
                                    │
  [ QuantStats / Markdown Report ] ┼──► Performance Report & Logs
                                    ▼
                        【验证整体架构连通性】
```

### 阶段一：基础设施与核心对象（Week 1）

- [ ] 初始化 Git 仓库、安装 Python 3.12+ / `uv` / `poetry`
- [ ] 部署 `platform/config/`（pydantic）与 `platform/logging/`（loguru）
- [ ] 落实 `platform/alert/`（基础 Terminal / Log / Telegram 告警通道）
- [ ] 创建 9 个 Core Domain Objects 的强类型 `dataclass` / `pydantic` 定义

### 阶段二：核心 Protocol Base Classes（Week 2）

- [ ] 落盘 `BaseDataSource`、`BaseFeature`、`BaseModel`、`BaseStrategy`、`BasePortfolio`、`BaseBroker` 等基类
- [ ] 实现轻量级 `ExperimentTracker`，支持保存参数与结果元数据（JSON / Parquet）

### 阶段三：走通 Walking Skeleton 最小闭环（Week 3）

- [ ] **Data**：接入单个行情数据源，生成 `daily_price.parquet`
- [ ] **Feature**：计算一个简单的 20 日动量因子（`momentum_20d`）
- [ ] **Strategy**：实现 `SimpleRankStrategy`，选取 Top 10 股票
- [ ] **Portfolio**：资金均分，按固定调仓日生成 Order
- [ ] **Backtest & Report**：运行端到端回测，输出一份 Markdown / HTML 绩效报告

> **重要**：第 7 节列出的大部分接口（Registry、Lineage、Risk Model、Capital Allocator 的复杂算法版本等）在这 3 周计划中**不会**被用到。这是有意为之——先用最简实现（甚至是硬编码的简化版）走通全链路，再回头对照第 6、7 节的宪法条文，逐步替换为符合规范的正式实现。不要在骨架跑通之前就把所有抽象都做满。

---

## 9. 架构完整性自查表

未来做任何架构决策或代码评审时，可以用下表快速定位"我现在动的这部分，对应保障的是哪种可信性"：

| 可信性维度 | 对应机制 |
|---|---|
| 数据可信性 | PIT、Data Contract、Cleaning、Lineage |
| 研究可信性 | IC、Neutralization、Purged CV、Experiment Tracking |
| 策略可信性 | Validation Gate、Paper Trading、Lifecycle |
| 交易可信性 | Execution Simulator、ADV、Slippage |
| 组合可信性 | Portfolio Risk、Capital Allocation |
| 长期演进能力 | Registry、Knowledge、Research Debt |
| 生产安全性 | Monitoring、Decay、Kill Switch |

如果某次改动无法归入以上任何一类，先停下来想清楚它到底解决了什么问题，再考虑是否值得写。

---

## 10. 量化判定标准与运营参数

> 前面几节的宪法条文大多是"原则性"表述（比如"通过统计显著性检验""触发严重回撤"），本节把这些原则落成具体数字，作为代码里判定函数的初始默认值。**这些数字不是永久真理，是"先用起来、后续用真实数据校准"的起点**，每次调整都应按第 12 节的流程记录变更原因。

### 10.1 因子研究阶段判定标准（对应 Rule 8）

| 指标 | 默认阈值 | 说明 |
|---|---|---|
| Rank IC 均值 | \|mean(Rank IC)\| ≥ 0.02 | 低于此值视为无显著预测力 |
| IC_IR（IC 均值 / IC 标准差） | ≥ 0.3 | 衡量 IC 的稳定性，而非仅看均值 |
| IC 显著性 t-stat | ≥ 2.0 | 对应约 95% 置信水平 |
| 最小样本区间 | ≥ 3 年（覆盖至少 1 轮牛熊） | 避免单一市场状态下的过拟合 |
| 分层测试单调性 | Top 分层与 Bottom 分层收益差 t-stat ≥ 2.0 | 检验因子分层是否单调 |

未同时满足以上条件的因子，只能进入 Research Debt Archive，不允许进入 Strategy 层。

### 10.2 策略生命周期通过条件（对应第 5.1 节状态机）

| 阶段 | 通过条件（默认值） |
|---|---|
| **Backtest Passed** | 年化 Sharpe ≥ 1.0；最大回撤 ≤ 25%；换手率在预设区间内（视策略类型设定）；剔除交易成本后仍满足以上条件 |
| **Validation Gate Passed** | 上述回测条件 + 通过行业/市值中性化检验（Rule 9）+ 代码通过 Research Code Review（Rule 10）+ 完整 Experiment 记录（Rule 6） |
| **Paper Trading Passed**（≥30 天） | 实盘信号与回测信号相关性 ≥ 0.8；实际滑点与假设滑点偏差 ≤ 50%；无因数据缺失/异常导致的信号中断 |
| **Shadow Production → Production** | Paper Trading 期间无触发 Kill Switch；至少经历一次市场波动（VIX 分位数 > 70% 或等效指标）而未出现异常回撤 |

### 10.3 Kill Switch 触发阈值（对应 Rule 25）

| 触发条件 | 默认阈值 | 动作 |
|---|---|---|
| 单策略最大回撤 | 超过历史回测最大回撤的 1.5 倍 | 暂停该策略新增信号 |
| 组合层最大回撤 | 单月回撤 ≥ 15% 或滚动 60 日回撤 ≥ 20% | 全组合减仓至风险预算下限，暂停所有买入推荐 |
| 滚动 Sharpe 衰减 | 60 日滚动 Sharpe 连续 10 个交易日 < 0 | 标记为 Warning，进入观察期 |
| 特征/预测分布漂移 | PSI（Population Stability Index） ≥ 0.25 | 标记为 Drift，暂停该策略排产 |
| 连续亏损 | 连续 15 个交易日净值创新低 | 人工复核，默认降级为 Shadow |

以上任一阈值触发后，必须在 Knowledge Layer 记录触发原因、处理动作与复盘结论（对应 Rule 12）。

### 10.4 资金配置默认参数（对应第 3 层 Capital Allocation）

- **默认分配算法**：Equal Weight 或 Risk Parity 优先于 Kelly。系统早期（Walking Skeleton 到 Shadow Production 阶段）一律使用 Equal Weight，避免过早引入需要精确概率估计的算法。
- **若启用 Kelly**：必须使用 **Fractional Kelly**，默认系数 0.25×–0.5×（即只使用理论 Kelly 仓位的 1/4 到 1/2），且需对收益分布估计误差做敏感性测试后才允许调高系数。
- **单一持仓权重上限**：单只标的 ≤ 组合总资金的 8%（默认值，可按标的流动性调整）。
- **单一行业暴露上限**：≤ 组合总资金的 25%。
- **现金缓冲**：正常状态下保留 ≥ 5% 现金，用于应对赎回/追加保证金/滑点意外。

### 10.5 组合层运营 KPI（对应 Rule 22）

| 指标 | 目标值（默认） | 评审频率 |
|---|---|---|
| 组合年化 Sharpe | ≥ 1.2 | 季度 |
| 组合最大回撤容忍度 | ≤ 20% | 实时监控，季度复盘 |
| Alpha / Beta 收益占比 | Alpha 贡献 ≥ 60% | 季度归因分析 |
| 调仓频率 | 视策略类型（默认周度） | — |
| 组合层整体复盘 | 每季度一次，产出书面复盘记录并存入 Knowledge Layer | 季度 |

### 10.6 PIT 财务数据重述（Restatement）处理原则

财务数据的重述/更正是 PIT 处理中最容易被低估的部分，需要明确以下默认规则：

- 财务数据必须记录**首次公告值（as-first-reported）**与**重述后值（as-restated）**两个版本，二者均需带时间戳。
- 回测与实盘信号生成，**默认只使用 as-first-reported 版本**，避免使用未来才可见的重述数据造成前视偏差（look-ahead bias）。
- 重述历史需保留在 Data Layer 中，供研究阶段单独分析"重述本身是否具有信号价值"（这是一个独立的研究课题，不能与常规信号混用）。

---

## 11. Walking Skeleton 之后：Phase 1 优先级

第 8 节的三周计划只解决"端到端能不能跑通"，跑通之后，不代表可以同时展开十二层里剩下的所有层。建议按以下顺序逐层补齐，每层同样遵守"先最小实现、再规范化"的原则：

1. **Validation Gate（第 5 层，最小版）** —— 把第 10.2 节的判定条件写成自动化检查脚本，哪怕只检查 Sharpe 和最大回撤两项，也要先于其他层建立，因为它是后续所有策略能否上线的唯一关卡。
2. **Monitoring / Kill Switch（第 11 层，最小版）** —— 在只有一个策略、一个组合的情况下就应该有熔断机制，成本很低，且一旦真实资金上场，这是最后一道防线。
3. **Portfolio Risk（第 7 层，最小版）** —— 当策略数量增加到 2 个以上时再启动，此前用不上真正的相关性/集中度控制。
4. **Capital Allocation（第 8 层，从 Equal Weight 升级）** —— 当组合层 KPI（10.5 节）稳定观察满 2 个季度后，再考虑引入 Risk Parity 或 Fractional Kelly。
5. **Registry & Lineage（第 4 层，正式版）** —— 当策略数量与实验数量开始让人手动追溯变得困难时（经验值：超过 10 个存活实验/策略），投入建设正式的 Registry，此前用简单的文件夹 + 命名规范代替即可。
6. **Simulation / Paper Trading Layer（第 9 层，正式版）** —— 与 Validation Gate 同步建设，但可以先用简化的固定滑点模型，不必一开始就做逐笔冲击成本建模。
7. **Knowledge Layer（第 12 层）** —— 从第一天就开始以「一个 Markdown 文件夹」的形式存在，不需要工程化，重要的是"有没有养成记录习惯"，而不是"有没有专门的系统"。

> 判断"该不该建下一层"的通用标准：**当前的手工/简化方案，是否已经开始产生真实的错误或者显著拖慢你的工作** —— 如果没有，就还不到建设该层的时候。

---

## 12. 宪法修订流程

文档过去两次自称"彻底冻结"，但实际都发生了修订，说明"冻结"更适合理解为"非正式修改的默认状态"，而非"永不能改"。为避免宪法本身变成没有约束力的口号，建立以下轻量流程：

1. **允许修订的触发条件**（满足其一即可发起修订）：
   - Walking Skeleton 或已上线的某一层，连续暴露同一类问题 2 次以上；
   - 第 10 节中的某个默认阈值，经过至少一个季度真实数据验证后被证明明显偏离实际（例如 Kill Switch 从未触发过，或触发过于频繁）；
   - 新增一层/新增一个领域对象前，已确认 Walking Skeleton 或现有架构确实无法满足需求（对应 Rule 28 的例外情形）。
2. **修订必须留痕**：任何对第 6 节（宪法）、第 7 节（接口）、第 10 节（阈值）的修改，需在文档末尾的「修订记录」中追加一行：日期、修改条目、修改前后对比、触发原因。
3. **版本号规则**：
   - 阈值/参数类调整（第 10 节） → 不升版本号，仅更新修订记录；
   - 新增/修改宪法条文（第 6 节）或接口（第 7 节） → 次版本号 +0.1（如 v4.1 → v4.2）；
   - 架构层级发生变化（第 3 节十二层结构本身改变） → 主版本号 +1，且需要重新走一遍第 9 节自查表确认七类可信性未被破坏。
4. **默认立场**：修订的默认答案是"不改"，需要修订方主动举证达到触发条件，而不是反过来要求维持现状的一方举证。这与 Rule 28 的精神一致——防止宪法本身也陷入"持续扩张"的陷阱。

### 修订记录

| 日期 | 修改条目 | 修改内容 | 触发原因 |
|---|---|---|---|
| （待填写） | — | — | — |
| 2026-07-20 | 第 7 节 | 新增 7.9「模型选择与训练规范：LightGBM 实践」，明确 LambdaRank 目标、特征规范、Purged CV 细则、默认超参数、过拟合检查、再训练频率、可解释性要求与模型退化判定 | 确认使用 LightGBM 作为默认建模算法，原文档 BaseModel 接口层面无具体训练规范，属于第 6 项文档评审中指出的薄弱点 |

---

## 13. 使用说明：如何在未来的开发中使用本文档

1. **开工前**：先看第 8 节（Walking Skeleton），确认自己当前处于哪个阶段，不要跳阶段做高层抽象。
2. **写新模块前**：对照第 3 节确认这个模块属于哪一层，对照第 4 节确认它操作的是哪个领域对象。
3. **设计接口前**：先查第 7 节是否已有对应 Base Protocol，优先复用/扩展，而不是重新发明。
4. **做设计决策犹豫不决时**：回到第 6 节找对应的宪法条文；如果某个决定违反了某条宪法，需要在代码注释或 Experiment 记录里写明原因。
5. **做架构评审 / 想加新层新对象时**：先过一遍 Rule 28（Walking Skeleton 优先）和 Rule 1（Research First），默认答案是"不加"，除非有真实需求已经把 Walking Skeleton 逼到了极限（可参考第 11 节的分层优先级判断标准）。
6. **每次为策略做上线决策时**：对照第 5.1 节生命周期状态机 + 第 10.2 节量化通过条件，确认策略处于正确阶段，不允许跳过 Paper Trading 或 Shadow Production 直接上生产。
7. **每次触发或怀疑该触发 Kill Switch 时**：对照第 10.3 节阈值表核实，触发后按 Rule 12 记录复盘。
8. **定期（建议每季度）**：重读第 9 节自查表 + 第 10.5 节组合 KPI，检查系统在七个可信性维度与运营指标上是否有明显短板；同时判断第 11 节中是否有下一层需要启动建设。
9. **想修改宪法本身时**：走第 12 节流程，不要直接改条文而不留痕。

---

*本文档版本：v4.2（整理版）。原始讨论中提出的所有层级、对象、宪法条文与接口定义均已收录，未做内容删减，仅做结构重排与去重，并新增第 10–12 节（量化判定标准、后续路线图、修订流程）以及第 7.9 节（LightGBM 模型训练规范）。后续任何修改请遵循第 12 节流程并留痕。*
