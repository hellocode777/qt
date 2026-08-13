# Reversal Alpha Capacity Compression（反转 Alpha 容量压缩）

> **类型**: Research Finding + Strategy Decision
> **日期**: 2026-08-13
> **状态**: 定稿
> **来源**: R1-R5 研究 + 跌停博弈微观结构研究（`scripts/research/limit_down_microstructure_s1~s4.py`）
> **完整报告**: Obsidian `技术深挖/跌停博弈微观结构研究-20260813.md`

## Finding（正式表述）

> **Finding: Reversal Alpha Capacity Compression**
>
> Historical A-share reversal alpha was materially supported by sentiment-driven overshooting. Since ~2022, the frequency and subsequent reversal profitability of limit-down / lottery-tail events have declined substantially, while the fundamental deterioration of extreme losers has increased relative to the market. This indicates a structural reduction in mispricing capacity rather than a failure of the reversal mechanism itself. Therefore momentum_vol_full v20260811 is retained unchanged; historical reversal alpha should not be extrapolated into future expected returns.

## 一句话机制

```
过去：坏消息/恐慌 → 价格过度下跌 → 跌停/高波动 → 情绪性错杀 → 随后反弹 → 反转 Alpha
现在：坏消息/基本面恶化 → 价格快速下跌 → 跌停/高波动 → 更多信息被及时反映 → 并非错误定价 → 继续下跌/反弹减弱
```

## 证据链（FACT，720 万行）

| 证据 | 数值 |
|------|------|
| 同样恐慌环境下跌停频率 | -72%（627→178/千股月） |
| 跌停后 1 日收益 | +3.97% → -1.65%（由正转负） |
| 跌停后 20 日彩票尾部（P99） | +468% → +81%（-83%） |
| 跌停股亏损比例相对全市场 | +1.8pp → +4.8pp（恶化扩大） |
| 连续跌停（3+） | -87% |

共同指向：**市场中可套利错误定价容量下降**，而非某个因子 IC 下降。

## 关键区分：机制失效 vs Alpha 容量收缩

看到因子 IC 从 0.08 ↓ 0.03，**不能立即判断 DEGRADED → 降权**。必须先区分：

| 类别 | 含义 | 例子 | 策略动作 |
|------|------|------|---------|
| **A. 因子机制失效** | 数据错误 / 定义错误 / 经济逻辑消失 | 数据源污染、因子方向反转是逻辑 bug | 修复 / REMOVE |
| **B. Alpha Capacity 收缩** | 市场越来越有效 → 错误定价机会减少，但机制仍成立 | 本次反转因子 | **KEEP，降低对历史 Alpha 的预期** |

对本次反转因子的健康判定：

```
Factor Health
├── Economic Mechanism: 仍成立（均值回归逻辑未变）
├── Data Quality: 正常
├── IC: 下降（0.08→0.03 级别）
└── Alpha Capacity: STRUCTURALLY COMPRESSED
→ 结论：不是 DEGRADED → REMOVE
→ 而是：KEEP，但降低对历史 Alpha 的预期
```

这使 Factor Health Monitor 从「统计监控」升级为「因子生命周期管理」。

## Strategy Decision（定稿）

**momentum_vol_full v20260811：KEEP（保持原策略不动）**

**不做**：
- ❌ 强化超跌高波权重
- ❌ 加入 crash-reversal factor
- ❌ 加入跌停反转 factor
- ❌ 用历史 2015-2021 的 Alpha 重新训练以追回历史收益
- ❌ 修改当前权重

**原因**：不是「我们没找到优化办法」，而是「我们找到了为什么不能这么优化的证据」——这是两种完全不同的结论。

## 后续动作（Research 侧，不碰 Production）

```
mvF v20260811（Production 正常运行）
        │
        ▼
记录 Alpha Capacity（Research 持续观察）
        │
        ├── 是否继续收缩？ → 降低预期
        └── 是否重新恢复？ → 重新研究机制
```

## 研究链条（完整 Research Story）

```
Q5 Collapse
  → 发现极端超跌
  → 发现超跌×低波不佳
  → 发现超跌×高波历史很强
  → 发现 2022 后高波反转衰减
  → Regime 无法解释
  → 研究跌停 / 尾部 / 基本面
  → 发现情绪性错杀机会减少
  → 市场效率提升
  → Reversal Alpha Capacity Compression
```

**停止继续「修 Q5」**——Cap 2%/4%/6%、新 reversal factor、新 crash filter 都容易重新进入过拟合。本轮研究已足够深入。

## 长期价值

以后研究任何新反转策略时，可直接继承本结论，不必重新花几天证明「A 股以前的极端反转 Alpha 为什么没有以前那么强了」。

## 关联

- R1-R5 研究: `~/.hermes/skills/.../alpha-decay-r1-r5-study.md`（R6 节）
- 微观结构报告: Obsidian `技术深挖/跌停博弈微观结构研究-20260813.md`
- 脚本: `scripts/research/limit_down_microstructure_s1~s4.py`
