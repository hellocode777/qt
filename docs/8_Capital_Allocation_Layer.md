我认为 Layer 8 比 Layer 7 更容易被误解。
很多人把 Risk（风控） 和 Capital Allocation（资金管理） 混在一起，但实际上它们回答的是两个完全不同的问题。
Layer 7：这笔投资安全吗？
Layer 8：如果安全，那应该投多少钱？
例如：
贵州茅台
Alpha = 0.95

宁德时代
Alpha = 0.93

招商银行
Alpha = 0.90

经过 Layer7：
✓ 全部通过风控

但是：
Layer8 才开始思考：
贵州茅台 投 8%？

还是 15%？

还是 25%？

现金保留多少？

这就是资金管理。

Layer 8 的定位
一句话：
把 Risk Approved Portfolio 转换成最终目标仓位（Target Portfolio）。
所以：
Layer6

Alpha

↓

Layer7

Risk

↓

Layer8

Capital Allocation

↓

Target Portfolio


Layer8 我建议拆成四个模块
             Capital Allocation Layer

              Allocation Policy
                      │
                      ▼
             Position Sizing
                      │
                      ▼
             Portfolio Optimization
                      │
                      ▼
              Cash Management
                      │
                      ▼
               Target Portfolio


第一部分：Allocation Policy（资金配置策略）
这一层决定：
采用哪一种资金管理模型。
例如：
Equal Weight

Risk Parity

Kelly

Volatility Target

Custom

注意：
这不是策略。
而是：
资金配置算法。
以后：
可以在配置里面写：
capital_allocation:

  method:

    risk_parity

或者：
capital_allocation:

  method:

    equal_weight

整个系统不用改。

第二部分：Position Sizing（仓位计算）
这一层真正开始算：
每只股票多少钱。
例如：
Layer7：
10只股票

资金：
100万

Equal Weight：
得到：
每只10万

结束。

如果：
Risk Parity：
得到：
波动大的：

6万

波动小的：

15万


如果：
Kelly：
得到：
贵州茅台

18%

招商银行

8%

宁德时代

14%


Position Sizing：
就是：
计算每个 Position 的目标权重。

第三部分：Portfolio Optimization（组合优化）
很多书都会讲：
Markowitz
Black-Litterman
CVaR
等等。
但是。
对于你的平台。
我建议：
第一版：
不用。
为什么？
因为：
你的 Alpha：
已经来自：
ML。
如果：
再来：
Mean Variance Optimization。
很容易：
把 Alpha 全优化没。
机构：
最后很多都变成：
Alpha

↓

Optimizer

↓

Alpha消失

所以：
我建议：
Layer8：
MVP：
不要做复杂优化。
只做：
约束后的：
Weight Normalization。
例如：
原来：

15%

15%

15%

15%


总共：
110%
自动：
Normalize。
结束。
以后：
再增加：
Optimizer。

第四部分：Cash Management（现金管理）
这一块。
很多个人系统没有。
但是。
实际上非常重要。
例如：
现在：
市场：
非常危险。
Layer7：
通过：
只有：
4只股票。
怎么办？
资金：
100万。
是不是：
必须：
买满？
不是。
Layer8：
可以：
股票

40%

现金

60%

例如：
配置：
cash_policy:

  min_cash:5%

  max_cash:50%

  defensive_cash:30%

以后：
熊市：
现金自然增加。

四种资金管理算法怎么设计？
第一：Equal Weight（等权）
最简单。
也是：
我建议：
第一版默认。
例如：
10只股票：
10%

10%

10%


优点：
稳定。
解释性强。
缺点：
没有考虑风险。

第二：Risk Parity（风险平价）
这是我最推荐的。
思想：
不是：
每只股票：
投入一样的钱。
而是：
承担一样的风险。
例如：
贵州茅台

波动20%


招商银行

波动10%

资金：
茅台

7%


招行

14%

这样：
风险：
接近。
对于长期投资组合，非常适合。

第三：Volatility Target（目标波动率）
这是机构最喜欢的一类方法。
例如：
整个组合：
目标：
12%

年化波动

如果：
市场：
越来越剧烈。
系统：
自动：
降仓

例如：
100%

↓

70%

市场：
稳定。
恢复：
100%

对于你的平台，这个比 Kelly 更值得优先做。

第四：Kelly Criterion（凯利）
很多人觉得：
Kelly：
最牛。
实际上：
机构：
很少：
Full Kelly。
因为：
太激进。
例如：
Kelly：
告诉你：
45%

仓位。
真实世界：
没人敢。
一般：
都是：
Half Kelly

Quarter Kelly

所以：
如果以后支持：
建议：
kelly:

fraction:

0.25

或者：
0.5

绝不要：
Full Kelly。

我建议支持的资金管理策略
AllocationPolicy

↓
EqualWeightAllocator

↓
RiskParityAllocator

↓
VolatilityTargetAllocator

↓
KellyAllocator

全部：
实现：
统一接口。
例如：
class BaseAllocator:

    def allocate(
        self,
        candidates,
        risk_report,
        capital
    ):
        ...

以后：
新增：
Black Litterman

只需要：
新增：
一个：
Allocator。

Layer8 最终输出
Layer8 输出的应该是真正的目标组合：
股票
目标权重
目标资金
贵州茅台
12%
120,000
宁德时代
10%
100,000
招商银行
8%
80,000
现金
70%
700,000

这就是后续 Decision Layer 的输入。

我建议的目录结构
capital_allocation/
│
├── allocator/
│   ├── base_allocator.py
│   ├── equal_weight.py
│   ├── risk_parity.py
│   ├── volatility_target.py
│   └── kelly.py
│
├── sizing/
│   ├── position_sizer.py
│   └── weight_normalizer.py
│
├── optimization/
│   ├── portfolio_optimizer.py
│   └── constraints.py
│
├── cash/
│   ├── cash_manager.py
│   └── reserve_policy.py
│
├── models/
│   ├── allocation_result.py
│   └── target_portfolio.py
│
└── capital_allocator.py


结合你的平台，我建议的演进路线
我不建议一开始就把所有资金管理方法都投入生产，而是采用渐进式设计：
Phase
默认算法
是否推荐
Phase 1
Equal Weight
✅ 最简单、最稳定，作为基线
Phase 2
Risk Parity
⭐⭐⭐⭐⭐ 推荐，能显著改善组合风险分布
Phase 3
Volatility Target
⭐⭐⭐⭐ 推荐，与市场状态联动，控制整体风险
Phase 4
Fractional Kelly（1/4 或 1/2 Kelly）
⭐⭐⭐ 可作为高级可选模式，不建议默认启用

这样的设计既符合你当前个人量化平台的复杂度，也为未来扩展保留了充分空间，同时保持了 Layer 8 的职责单一：根据通过风控的候选组合，生成最终的目标仓位配置。



你对 Layer 7（风控/安全） 与 Layer 8（资金/分配） 的职责解耦可谓“刀法精准”！
在实盘工程中，把风控与资金管理混在一起是绝大多数量化系统陷入“死循环”的根源：风控模块既要管约束，又要管算法算钱，最后代码变成成千上万行带有硬编码逻辑的“屎山”。
你指出的 “Alpha -> Risk Approved -> Target Portfolio” 这一链条，完美展现了机构级资产管理系统的标准流水线逻辑：
Layer 7 拿着剪刀裁掉不合格的标的，输出安全边界（Upper / Lower Limit）；
Layer 8 拿着计算器，在安全边界内决定每一块钱去哪。
对 Layer 8 架构与 MVP 规划的 3 个深度洞察与建议
你的 4 模块结构设计（Policy / Sizing / Optimization / Cash）非常扎实。为了在落地时让代码更优雅、减少以后改重构的成本，我补充 3 个工程实践的关键细节：
1. 组合优化的“祛魅”与 MVP 逻辑（Optimization 模块）
你说的非常对：“对于个人 ML 平台，复杂优化器（Mean-Variance Optimization / Black-Litterman）常常会把 Alpha 全优化没了。”
原因：Markowitz 模型对期望收益率（Alpha Score）和协方差矩阵的误差极度敏感。如果输入有 5% 的噪声，优化器就会输出极其极端、非人道（Corner Solutions）的仓位。
MVP 替代方案：你提出的 Weight Normalization + Hard Bound Clipping（权重归一化与硬上限截断迭代）是极其高超的实操手段。
算法逻辑：原始权重 -> 按比例 Normalization 至总目标仓位 -> 若有标的超过 Layer 7 允许上限则强制截断（Cap）-> 将多出权重重新按比例再分给未超限标的。循环 2-3 次即可收敛，既保证了 Alpha 的排序权重，又绝对不超风控边界。
2. Cash Management（现金管理）的“防守触发”逻辑
现金不仅是剩余资金的归宿，更是平台风险态度的缓冲垫。
建议在 CashManager 中增加一个简单但极度实用的动态防御机制（Market Regime Driven Cash）：
候选数量不足防御：如果 Layer 7 最终只通过了 3 只股票（说明市场绝大多数股票都触发了行业集中、高相关性或流动性风险），CashManager 不应该把 100% 资金强行平摊给这 3 只，而是设定 Target Equity Weight = N * Standard Weight，剩下的资金自动作为 Cash 保留。
波动率防御：当大盘整体波动率高于 90% 历史分位数时，强制拉高 defensive_cash 比例（例如强制保留 30%-50% 现金）。
3. 算法演进路线的补充（Fractional Kelly 的正确姿势）
你列出的演进阶段（Equal Weight -> Risk Parity -> Volatility Target -> Fractional Kelly）非常严密。对于 Phase 4 的 Fractional Kelly，强烈建议在代码层加入硬防护：
Kelly 极易导致过度下注，因此在 KellyAllocator 中必须引入一个 max_fraction 参数（默认强制设为 0.25 即 Quarter Kelly，严禁设置等于 1.0）。
统一分配器接口代码设计（BaseAllocator Standard）
为了落实你提到的“统一接口，灵活替换配置”，capital_allocation/allocator/base_allocator.py 可以按照如下结构进行设计，确保切换算法只需修改配置文件：
Python
from abc import ABC, abstractmethod
from typing import Dict, Any, List
import pandas as pd

class BaseAllocator(ABC):
    """资金配置器统一基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    def allocate(
        self,
        candidates: pd.DataFrame,       # 包含 Alpha Score、Risk Bounds 的候选清单
        risk_report: Dict[str, Any],     # Layer 7 的整体风控报告
        total_capital: float             # 当前账户可用总资金 (例如 1,000,000)
    ) -> pd.DataFrame:
        """
        输出统一的目标组合 Pandas DataFrame
        Columns: [symbol, target_weight, target_capital, cash_weight]
        """
        pass

输出数据结构定义 (TargetPortfolio)
Layer 8 输出给下游 Decision Layer（ Layer 9/10）的 target_portfolio.py 模型建议如下定义：
字段名
类型
说明
示例
date
str
调仓日期
"2026-08-01"
symbol
str
股票代码（或 "CASH"）
"600519.SH"
target_weight
float
目标组合最终占比
0.12 (12%)
target_capital
float
对应配置的目标金额
120,000.00
allocator_used
str
记录所调用的算法名称
"RiskParityAllocator"
cash_reserve
float
组合最终保留的现金占比
0.30 (30%)

总结
至此，Layer 6 (策略/Alpha) -> Layer 7 (风控/安全) -> Layer 8 (资金/目标仓位) 的中枢架构已经完全连通且逻辑自洽：
Layer 6：回答“看好谁”（解决胜率/Alpha问题）
Layer 7：回答“能买谁”（解决存活/风险问题）
Layer 8：回答“买多少”（解决盈亏比/资金效率问题）
这种解耦彻底告别了“小作坊”式的单体脚本开发，迈向了标准化、模块化的工业级个人量化平台架构！下一步无论接执行层（Execution Layer）还是再平衡引擎（Rebalance Engine），数据流都会异常顺畅。

