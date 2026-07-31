这次实验的信息比前面的 log 更完整，可以做一个比较准确的诊断。

先给结论：

> **这个实验已经证明：因子本身具有预测能力（Alpha 存在），但当前交易策略没有把 Alpha 转换成收益。**
>
> 现在的问题已经不是 Factor Research，而是：
>
> **Score → Selection → Portfolio Construction 的转换失败。**

---

# 1. 先看因子层：非常优秀

你的因子检验：

| 指标        |     结果 | 评价     |
| --------- | -----: | ------ |
| IC Mean   | 0.0802 | ✅ 很强   |
| IC IR     |   0.70 | ✅ 稳定   |
| IC t-stat |  15.70 | ✅ 非常显著 |

这部分非常漂亮。

尤其：

```
IC t-stat = 15.70
```

意味着：

这个 IC 不是随机波动产生的。

如果只看 Factor Research：

这个因子组合应该进入下一阶段。

---

# 2. 但是策略收益非常差

你的回测：

```
总收益:
+2.49%

年化:
+1.00%

Sharpe:
0.23

MaxDD:
7.9%
```

同期：

```
Excess:
+0.00%
```

也就是说：

你的策略：

> 几乎等于买一个等权组合。

这和 IC=0.08 完全不匹配。

这里出现了一个非常典型的量化问题：

---

# 3. Alpha 被 Portfolio 消耗掉了

你的链路：

```
Factor Score
      |
      ↓
排序
      |
      ↓
Top10
      |
      ↓
组合收益
```

现在：

Factor:

✅ 有预测

但是：

Portfolio:

❌ 没有捕获

为什么？

---

# 4. 一个非常关键的指标：换手率

这里：

```
Turnover:
0.0%
```

这是最大的异常。

你的配置：

```
Top10
rebalance20d
```

正常情况下：

20天调仓策略：

换手不应该是：

```
0%
```

应该至少：

几十个百分点。

所以这里有两个可能：

---

## 情况 A：回测实际上没有调仓

例如：

第一次买入：

```
10只股票
```

之后：

20天检查：

没有交易。

那么你的策略实际上：

变成：

```
Buy & Hold
```

而不是：

```
Factor Rotation
```

这会直接解释：

为什么 IC 很高，但是收益很低。

---

## 情况 B：Position Manager 有问题

比如：

每天计算：

```
Top10
```

但是：

没有生成：

```
Sell Order
Buy Order
```

或者：

全部被：

```
buffer
risk
transaction filter
```

过滤。

---

# 5. 这个实验最大的疑点不是因子，而是 Turnover

我会把优先级排序：

---

## 第一检查：为什么 Turnover = 0

这是 P0 问题。

你需要查：

```
backtest engine
```

里面：

```python
rebalance()
```

是否真的执行。

看日志：

应该存在：

类似：

```
2024-xx-xx rebalance

old positions:
10

new candidates:
10

sell:
x

buy:
x
```

如果没有：

说明策略层根本没有运行。

---

# 6. 如果 Turnover 修复后，再看 Q 分层

你之前给出的：

```
Q1 +0.81%
Q2 +0.69%
Q3 +0.67%
Q4 +0.59%
Q5 +0.14%
```

这个非常重要。

因为：

你的排序方向仍然有问题。

虽然：

```
IC > 0
```

但是：

最高分：

```
Q5
```

收益最低。

所以：

你的 score 定义需要确认。

---

# 7. 当前策略名字可能误导

配置：

```
Strategy:
momentum_vol_full
```

但是因子：

```
Amplitude_5D
Volatility_20D
Momentum_3M
Volume_Concentration
Volume_Trend_10D
```

根据之前 IC：

大概率：

实际上是：

```
low volatility
+
short-term reversal
+
volume reversal
```

而不是：

momentum。

建议改名：

```
low_vol_reversal_v1
```

否则后面实验会混乱。

---

# 8. 现在你的 Validation Gate 需要升级

目前：

你验证：

```
IC
IC IR
IC t
Monotonicity
```

但是缺少两个生产级检查：

---

## Check 1：方向检查

增加：

```
Q5-Q1 > 0
```

否则：

直接标记：

```
Reverse Alpha
```

例如：

现在：

```
Q5-Q1=-0.67%
```

应该失败。

---

## Check 2：Portfolio Capture Test

新增：

因子通过后：

跑一个最简单组合：

```
Long top 20%
```

验证：

是否捕获 Alpha。

否则：

出现：

现在这种情况：

```
Factor:
PASS

Strategy:
FAIL
```

---

# 9. 我建议下一步实验顺序

不要继续优化因子。

按这个顺序：

---

## Experiment 1

修复：

```
Turnover=0
```

确认调仓。

---

## Experiment 2

增加：

```
Q5-Q1 Direction Gate
```

要求：

```
spread > 0
```

---

## Experiment 3

测试：

score inversion：

```
score = -score
```

看：

是否：

```
Q5 > Q1
```

如果成立：

发现反转策略。

---

## Experiment 4

Portfolio Construction：

测试：

```
Top10
Top20%
Q4
Q3+Q4
Exclude Q5
```

---

# 最终评价

这次实验其实非常有价值：

它证明：

```
Factor Layer:
★★★★★

Validation:
★★★★☆

Backtest:
★★☆☆☆

Portfolio Layer:
待修复
```

你现在遇到的是专业量化里非常常见的问题：

> **研究员发现了 Alpha，但交易系统没有正确兑现 Alpha。**

下一步重点应该从 **Factor Engine** 转向 **Portfolio Construction Layer + Backtest Execution Layer**。

尤其这个：

```
Turnover = 0.0%
```

我认为比收益数字更值得优先排查。它很可能是当前最大的问题。
