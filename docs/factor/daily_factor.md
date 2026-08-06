这是一个非常关键的问题，因为这里容易混淆 **“因子研究”** 和 **“每天使用因子生成交易信号”**。

我前面说的：

```
昨天数据
    |
    v
计算今天因子值
    |
    v
生成股票 score
    |
    v
decision package
```

里面的“计算今天因子值”不是重新研究因子，而是：

> **用最新市场数据，计算每只股票当前时点的因子暴露（factor exposure / factor score）。**

也就是：

**因子公式已经固定，每天重新代入最新数据。**

---

举你的项目例子。

你的 Factor Library 里面：

```text
Volatility_20D
Momentum_3M
Amplitude_5D
Volume_Trend_10D
Volume_Concentration
```

这些都是公式。

比如：

## 1. Volatility_20D

定义：

```
过去20个交易日收益率标准差
```

公式：

```
Volatility_20D =
std(
    daily_return[t-19],
    ...
    daily_return[t]
)
```

---

假设：

昨天收盘：

```
2026-08-06
```

数据库有：

```
600519 贵州茅台

最近20天收益:

+1%
-0.5%
+0.3%
...
```

Daily Pipeline 计算：

```
Volatility_20D = 0.018
```

意思：

> 今天这只股票最近20天波动率是1.8%

---

## 2. Momentum_3M

定义：

```
过去60交易日涨幅
```

每天计算：

例如：

昨天：

```
2026-08-05

价格:
100

60天前:
90

Momentum_3M:

100/90-1

=11.1%
```

今天：

```
2026-08-06

价格:
102

60天前:
91

Momentum_3M:

102/91-1

=12.1%
```

所以：

昨天：

```
Momentum_3M=11.1%
```

今天：

```
Momentum_3M=12.1%
```

---

注意：

这里没有计算 IC。

没有判断：

> Momentum 有没有预测能力。

只是计算：

> 当前股票 Momentum 是多少。

---

# 你的 Daily Pipeline 实际应该这样

## Step 1 数据更新

例如：

17:57

获取：

```
daily_price_latest.parquet

date:
2026-08-06

symbols:
3075
```

包含：

```
close
volume
amount
high
low
```

---

## Step 2 Factor Calculator

读取：

```
daily_price_latest.parquet
```

计算：

```
factor_values_20260806.parquet
```

结果：

| symbol | Momentum_3M | Volatility_20D | Amplitude_5D |
| ------ | ----------: | -------------: | -----------: |
| 600519 |        0.12 |          0.015 |         0.03 |
| 000001 |       -0.08 |          0.021 |         0.05 |
| 600036 |        0.06 |          0.018 |         0.02 |

这就是：

> 今天每只股票的因子状态

---

## Step 3 Factor Normalize

因为不同因子量纲不同：

例如：

Momentum:

```
0.12
```

Volatility:

```
0.018
```

不能直接相加。

所以：

变成：

```
z-score
```

或者：

```
rank percentile
```

例如：

| 股票     | Momentum Score |
| ------ | -------------: |
| 600519 |           0.85 |
| 600036 |           0.63 |
| 000001 |           0.20 |

---

## Step 4 Strategy Score

你的：

```
momentum_vol_full
```

例如：

以前：

```
score =

0.25 * Momentum_3M

+
0.25 * Volatility_20D

+
0.25 * Amplitude_5D

+
0.25 * Volume_Trend
```

每天计算：

所有股票：

```
score
```

排序：

```
rank 1
rank 2
...
```

---

## Step 5 Decision Package

生成：

例如：

```
decision_package_20260806.json
```

内容：

```json
{
"date":"2026-08-06",

"strategy":
"momentum_vol_full",

"buy_candidates":[

{
"symbol":"600519",
"score":0.86,
"rank":1
},

{
"symbol":"600036",
"score":0.82,
"rank":2
}

]

}
```

然后 WebUI 展示：

```
今日候选股票
↓
风险检查
↓
人工决策
```

---

# 所以你的系统里面有两个完全不同的动作

## A. 因子研究（低频）

回答：

> 这个因子有没有 Alpha？

例如：

```
Momentum_3M
2015-2026

IC=-0.05

weakening
```

运行：

```
qp factor update-health
```

频率：

月/季度。

---

## B. 因子计算（高频）

回答：

> 今天每只股票的因子值是多少？

例如：

```
2026-08-06


贵州茅台:

Momentum_3M=0.12

Volatility_20D=0.015

Amplitude_5D=0.03

```

运行：

每天。

---

你的 QP 现在其实已经有：

```
Factor Library        ✅
Factor Health         ✅
Factor Calculator     （应该属于 Daily Pipeline）
Strategy Engine       ✅
Decision Package      ✅
```

下一步比较重要的是把 `factor_values_daily.parquet` 正式作为一个中间层。

架构会变成：

```
Gold Data
    |
    v
Factor Calculator
    |
    v
factor_values_daily.parquet   <-- 每天产生
    |
    v
Strategy Engine
    |
    v
decision package


Factor Research
    |
    v
factor_ic_series.parquet      <-- 月/季度更新
```

这样你的研究层和生产层就完全分离了。你现在的问题，其实就是量化系统里非常典型的 **Factor Research Plane vs Factor Execution Plane 分离问题**。
