我认为 Layer 7 是整个量化平台真正体现专业性的地方。
很多个人量化系统都是：
Alpha 很强，组合很差。
最后不是输给市场，而是输给风险管理。
对于我们的平台，我建议牢记一句设计哲学：
Layer 7 不负责赚钱，它负责让你活下来。
也就是说：
Layer 6 的目标：找出最好的股票（Alpha）
Layer 7 的目标：不要把钱都押在同一种风险上
这是两个完全不同的问题。

Layer 7 的定位
输入：
Layer 6 Alpha Signal

贵州茅台   0.95
五粮液     0.94
泸州老窖   0.93
山西汾酒   0.92

Layer6 会觉得：
太好了，前四名全买。
但是 Layer7 会说：
等等。
这四个都是白酒。
本质上是一笔交易。
所以：
Layer7 的职责就是：
把 Alpha 转换成一个风险可接受的候选组合。
注意：
还不是最终仓位。

我建议 Layer 7 只有四个模块
               Portfolio Risk Layer

                Exposure Analysis
                        │
                        ▼
             Correlation Analysis
                        │
                        ▼
                Risk Constraints
                        │
                        ▼
                 Risk Budgeting
                        │
                        ▼
              Risk Approved Portfolio


第一部分：Exposure Analysis（暴露分析）
这是第一道风控。
分析组合到底暴露在什么风险上。
不是股票。
而是风险因子。
例如：
行业

市值

风格

Beta

流动性

成长

价值


例如：
Layer6 输出：
贵州茅台
五粮液
泸州老窖
山西汾酒

Exposure：
食品饮料

82%

立即报警。

再例如：
宁德时代
亿纬锂能
天赐材料
容百科技

全部：
新能源。
虽然不是同一家公司。
但是：
同一种风险。

所以：
第一个模块就是：
计算各种 Exposure。
例如：
Sector Exposure

MarketCap Exposure

Factor Exposure

Beta Exposure

Liquidity Exposure


第二部分：Correlation Analysis（相关性分析）
这是很多人忽略的。
实际上：
行业限制解决不了很多问题。
例如：
中国平安

招商银行

兴业银行


行业不同？
不是。
金融。
但是：
有时候：
贵州茅台

伊利股份

海天味业


行业：
食品。
相关性：
0.92
还是一样危险。
所以：
应该计算：
Correlation Matrix

例如：
        茅台 五粮液 宁德 招行

茅台      1

五粮液    0.93

宁德      0.42

招行      0.25

然后：
发现：
>0.85

禁止同时大量持有。

以后：
甚至可以：
Cluster。
例如：
Cluster A

白酒

Cluster B

新能源

Cluster C

金融

风险预算：
按 Cluster。
而不是行业。

第三部分：Risk Constraints（风险约束）
这是最重要的一层。
所有规则。
全部集中。
例如：
单只股票

<=15%

单行业

<=30%

Top3

<=45%

小市值

<=20%

ST

0%

停牌

0%

Beta

<1.2

等等。
以后：
所有风控：
统一。
不要散落在策略里面。

例如：
Layer6：
推荐：
贵州茅台

20%

Layer7：
发现：
超过15%

自动：
Cut

↓

15%


第四部分：Risk Budget
这是工业系统真正开始高级的地方。
不是资金预算。
是：
风险预算。
例如：
整个组合：
允许：
100%

风险

分配：
白酒

20%

新能源

25%

银行

15%

医药

20%

现金

20%

以后：
Layer8：
才把：
这些风险预算：
变成：
资金。

Risk Budget 可以来源很多。
例如：
波动率

VaR

CVaR

Tracking Error

Max Drawdown


个人平台前期：
其实：
Inverse Volatility
已经够用了。

Layer 7 最终输出
Layer7 不输出：
买卖

不输出：
Order

输出：
Risk Approved Candidates

例如：
股票
Alpha
Risk Score
是否通过
贵州茅台
0.95
0.18
✅
五粮液
0.94
0.41
❌（行业过度集中）
宁德时代
0.92
0.22
✅
招商银行
0.90
0.15
✅

Layer8 再根据这些通过风控的候选股票进行资金配置。

我建议的目录结构
portfolio_risk/
│
├── exposure/
│   ├── sector_exposure.py
│   ├── factor_exposure.py
│   ├── marketcap_exposure.py
│   └── beta_exposure.py
│
├── correlation/
│   ├── correlation_matrix.py
│   ├── clustering.py
│   └── diversification.py
│
├── constraints/
│   ├── position_limits.py
│   ├── sector_limits.py
│   ├── liquidity_limits.py
│   └── rule_engine.py
│
├── budget/
│   ├── risk_budget.py
│   ├── volatility_budget.py
│   └── var_budget.py
│
├── models/
│   ├── risk_report.py
│   └── portfolio_snapshot.py
│
└── portfolio_risk_engine.py


结合你的平台定位，我建议 Layer 7 的 MVP（第一版）先做四项核心能力即可：
行业集中度控制（Sector Concentration）：限制单一行业的权重，避免“全仓白酒”“全仓新能源”等情况。
个股权重限制（Position Limits）：限制单只股票的最大权重，避免单一股票风险。
相关性分析（Correlation Analysis）：识别高度相关的持仓，提升组合分散度，而不仅仅依赖行业分类。
风险预算（Risk Budget）：基于波动率等简单指标，为后续 Layer 8 的资金配置提供风险约束。
这四项已经能够覆盖绝大多数个人量化平台的组合风险需求，而且与后续的 Capital Allocation Layer 可以自然衔接，不会造成职责重叠。



这句话直接点破了绝大多数 Quant 策略从“回测表现惊艳”走向“实盘快速腰斩”的根本原因：
“Layer 6 不负责赚钱，Layer 7 负责让你活下来。”
如果把 Layer 6（Strategy Engine）比作选拔最优秀赛车手的过程，那 Layer 7（Portfolio Risk Layer）就是赛车的防滚架、刹车系统与风洞验证。只看 Alpha 的组合本质上是在无套利风险、无对冲暴露的环境下裸奔。
你对 Layer 7 的拆解极其地道，完全抓住了机构级投资组合构建（Portfolio Construction）的核心逻辑。
针对 MVP 版 Layer 7 的 3 个精细化建议
在你规划的 4 个核心模块基础上，结合个人平台的工程落地（MVP 阶段），我建议在细节上做如下“微创优化”，避免过度复杂化的同时，极大地提升组合的鲁棒性：
               Layer 6: Alpha Signal (0~1 Score)
                                │
                                ▼
         ┌──────────────────────────────────────────────┐
         │          Layer 7: Portfolio Risk             │
         │                                              │
         │  1. Exposure Analysis (Sector / Beta / Cap)  │
         │                       │                      │
         │                       ▼                      │
         │  2. Dynamic Clustering (Correlation Matrix)  │
         │                       │                      │
         │                       ▼                      │
         │  3. Hard Constraints Engine (Trim & Filter)  │
         │                       │                      │
         │                       ▼                      │
         │  4. Volatility-Based Risk Budgeting          │
         └──────────────────────┬───────────────────────┘
                                │
                                ▼
             Layer 7 Output: Risk-Approved Candidates
                      (Weights & Risk Bounds)

1. 行业 vs Correlation：用“聚类 (Clustering)”取代硬性行业分类
正如你举的例子：茅台、伊利、海天 在申万宏源行业分类里可能分别属于“白酒、乳业、调味品”，但它们的走势相关性可能高达 0.85+（本质都是“大消费/外资重仓/高 ROE 资产”）。
MVP 落地方案：不要只依赖传统的行业划分（申万/中信），建议直接对候选股票计算 近 60 日收益率的相关系数矩阵（Correlation Matrix），并使用简单的 层次聚类（Hierarchical Clustering / Agglomerative Clustering） 划分出 3~5 个动态 Risk Clusters。
风控规则：限制单个 Cluster 的总体权重，而不仅仅是限制单一“行业”。
2. 约束引擎的处理逻辑：是 Cut 还是 Filter？
在 Risk Constraints 模块中，Layer 6 传上来的高 Alpha 股票被触发风控时，存在两种处理方式：
截断（Trim/Hard Cap）：如果茅台推荐权重超出 15%，直接截断为 15%，释放出的额度分配给其他股票。
剔除（Filter/Reject）：如果整个组合白酒集中度>30%，直接剔除排名靠后、但相关性极高的一只（如五粮液），换成排名第 5 但所属 Sector 不同的股票。
推荐方案：采用 “先截断、后补位” 机制。硬限制（如 ST、停牌、单股上限）直接 Cut/Reject；集中度限制（行业/Cluster）采用“梯度截断，将多余额度向 Alpha 排序靠后且低相关性的股票轮换”。
3. MVP 阶段的 Risk Budget：波动率倒数（Inverse Volatility）
在第一版 MVP 中，不要一开始就上复杂且对协方差矩阵极度敏感的 Risk Parity（风险平摊） 或 CVaR 优化（非常容易因为协方差矩阵估计误差导致组合产生奇怪的边角仓位）。
MVP 实施路径：直接采用 Inverse Volatility（波动率倒数重加权）。
高波动股票（如小盘成长、高 Beta）：给予较小的风险预算（上限较低）。
低波动股票（如大盘红利、低 Beta）：给予相对宽裕的风险预算。
结合 Layer 6 的 Alpha 排序进行加权调整，输出最终的 Risk Approved Candidates。
推荐的 Layer 7 数据结构定义
为了方便 Layer 7 与 Layer 8（Capital Allocation Layer）无缝对接，Layer 7 最终输出的 RiskApprovedPortfolio 建议包含以下字段：
候选清单与风险约束输出 (RiskApprovedCandidate)
字段名
类型
说明
示例
symbol
str
股票代码
"600519.SH"
alpha_score
float
来自 Layer 6 的原始得分
0.95
risk_cluster
int / str
相关性聚类编号/主暴露标签
"Cluster_Consumer_A"
max_weight_limit
float
Layer 7 风控允许的最大权重上限
0.15
risk_volatility
float
近 20/60 日年化波动率（供 Layer 8 算资金）
0.22
pass_status
bool
是否通过风控筛选
True
rejection_reason
str
若未通过，记录具体违规项
"Exceeded Cluster Risk Budget"

总结
你规划的目录结构（portfolio_risk/ 下拆分 exposure、correlation、constraints、budget）非常符合高内聚设计。
Layer 7 搭建完成后：
Layer 6 负责放飞想象力，寻找市场超额收益。
Layer 7 扮演冷酷的风险裁判，把所有危险的暴露、高相关性泡沫和黑天鹅隐患挡在门外。
这种职责划分，才是一个长期稳定的个人量化投资系统应有的工程硬实力。我们可以随时根据这个 Blueprint 开始定义具体的风控规则类或相关性计算模块！

