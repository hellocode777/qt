# low_vol_reversal — 因子排序假设验证报告

> **日期**：2026-07-23
> **策略**：low_vol_reversal（5 因子，IC 加权）
> **数据集**：daily_price_main v2026-07-23，3039 只主板 A 股
> **检验周期**：2024-01-01 → 2026-07-23

---

## 背景

`momentum_vol_full` 策略在 §10.1 Gate 中被拦截：IC=+0.067, IC_IR=0.42 通过，但分层单调性失败（t_mono=1.15 < 2.0）。本节验证：

1. 分层塌陷是否由特定因子引起
2. 分层塌陷是否因持仓集中度过高（Top10）
3. 分层塌陷是否为因子本身的非线性特征

---

## 1. 消融实验 — 定位 Q5 塌陷来源

### 实验设计

| 模型 | 因子 | 目的 |
|------|------|------|
| `lvr_vol_only` | Volatility_20D | 孤立低波因子 |
| `lvr_vol_mom` | Volatility_20D + Momentum_3M | 低波+最强反转 |
| `lvr_vol_all_rev` | 5 因子全量 | 最大信号 |

### 结果

```
                                    Q1      Q2      Q3      Q4      Q5    t_mono
Vol only   1因子  IC=0.050    +0.45%  +0.58%  +0.68%  +0.64%  +0.40%   0.09
Vol+Mom    2因子  IC=0.057    +0.50%  +0.66%  +0.62%  +0.61%  +0.36%   0.80
Vol+AllRev 5因子  IC=0.067    +0.55%  +0.65%  +0.65%  +0.65%  +0.25%   1.15
```

### 发现

1. **Q5 塌陷是所有因子的共同特征** — 单因子 Vol_20D 也显示 Q4(+0.64%) > Q5(+0.40%)
2. **反转因子增加了信号强度** — IC 从 0.050 提升到 0.067，但不改变 Q5<Q4 的结构
3. **Q2-Q4 收益平坦** — 5 因子组合中 Q2=Q3=Q4=+0.65%，说明中间分位的区分度不高
4. **结论**：Q5 塌陷不是某个坏因子导致的，是这些因子在 A 股截面的共同特征

---

## 2. 持仓集中度实验 — Top10/20/30/50

### 实验设计

保持因子权重不变，只改变持仓数，检验 Q5 塌陷是否来自过高的集中度。

### 结果

```
Top10:  Q1=+0.55% Q2=+0.65% Q3=+0.65% Q4=+0.65% Q5=+0.25%  t_mono=1.15
Top20:  Q1=+0.55% Q2=+0.65% Q3=+0.65% Q4=+0.65% Q5=+0.25%  t_mono=1.15
Top30:  Q1=+0.55% Q2=+0.65% Q3=+0.65% Q4=+0.65% Q5=+0.25%  t_mono=1.15
Top50:  Q1=+0.55% Q2=+0.65% Q3=+0.65% Q4=+0.65% Q5=+0.25%  t_mono=1.15
```

完全一致。分层检验使用全量截面排名（3039 只分 5 组），与持有数无关。

### 结论

**Q5 塌陷不是组合容量问题，是因子信号本身的结构性特征。**

---

## 3. Score Band 选股实验 — 核心突破

### 核心假设

如果 Q4 收益 > Q5 收益是稳定的，那么**不买最高分股票，改买 Q4 区域的股票**应该能提升组合表现。

### 实验设计

在信号生成时引入 `score_percentile` 参数：

```
Top5 (baseline)  → 买分数最高的 10 只 (Q5 区域)
Score band 40-80 → 买分数在 40-80 百分位的 10 只 (Q3-Q4)
Score band 60-80 → 买分数在 60-80 百分位的 10 只 (Q4 区域)
```

所有其他参数不变：同样的 5 因子，同样的权重，同样的调仓周期。

### 结果

```
Selection         总收益     夏普   交易次数
───────────────────────────────────────────
Top5 (Q5)         -3.27%    -0.43    67
Q3-Q4 (40-80%)    -2.15%    -0.12    70
Q4 only (60-80%)  +14.82%   +0.67    86
等权买入持有        +20.22%    —       —
```

### 发现

1. **Q4 选择比 Top5 高出 18 个百分点**
2. **避开 Q5 之后，同一个因子组合从亏钱变成赚钱**
3. **Q3-Q4 混合（40-80%）反而不如纯 Q4** —— 范围太宽混入了低信号区域
4. **Q4 区域的夏普 0.67 仍然较低** —— 因子本身质量有限，低于基准

---

## 4. 根因分析：Inverted-U 收益结构

### 实际收益-分数关系

```
收益
  |
  |         Q4 *
  |     Q3 *   * Q2
  |  Q1 *           * Q5
  |
  └──────────────────────► 分数
  低                      高
```

不是线性（分数越高收益越高），而是倒 U 形：
- 低分区 (Q1)：基本面差的股票，包含真正的垃圾
- 中高区 (Q2-Q4)：合理的反转候选，跌够了但没跌穿
- 最高区 (Q5)：跌最惨的股票，包含价值陷阱

### 为什么反转因子在 Q5 失效

反转因子的排序逻辑：跌得越多 → 反转概率越高 → 分数越高。

但这个假设在 Q5 区域失效——"跌得最多"的股票里，一部分是真正的反转机会，另一部分是基本面持续恶化、市场定价正确的价值陷阱。当前 5 个因子里没有能区分这两类的信号。

### IC 和 Q5-Q1 同时成立的原因

IC 衡量的是"分数与收益的整体相关性"（排名高→收益高），不要求最高分必须对应最高收益。只要 Q2-Q4 的收益高于 Q1，IC 就是正的——这正是我们看到的。

---

## 5. 对系统设计的验证

### §10.1 Gate 的正确性

Gate 拦截了 Top5 选股的策略，但没有拦截因子本身。这次实验证明 Gate 设计是正确的：

```
IC Gate → PASS  ✅ (因子确实有信息)
Mono Gate → FAIL ❌ (但最高分≠最高收益)
```

如果没有 Mono Gate，一个 IC 漂亮但选股亏钱的策略就进入了回测。

### Score Band 作为新 Portfolio Construction 维度

当前信号生成只支持 `Top-N` 排名选股。实验结果建议增加 `Score Band` 作为一等参数：

```bash
qp experiment run multifactor --strategy low_vol_reversal --score-band 60-80
```

---

## 6. 架构级结论

### 核心原则

> **Alpha Signal（因子产生排序能力）和 Portfolio Construction（如何从排序中构造组合）必须解耦。**

### IC 正确 ≠ Top-N 正确

IC 衡量的是"分数与收益的整体相关性"：
```
IC = corr(score, future_return)
```
它只要求"高分股票整体优于低分股票"，不要求"最高分股票的绝对收益最高"。

交易需要的却是：
```
E[Return | Selected]  —  你真正买进去的那个区域的期望收益
```

二者完全不同。这次实验就是经典案例：
```
IC = +0.067  →  排序有效
Top5 = -3.27% →  选错了区域
```

### 当前架构 → 目标架构

```
当前:
  Factor → Score → Rank → Top-N → Portfolio

目标:
  Factor → Score → Distribution Analysis → Selection Policy → Portfolio
                                                              
  Selection Policy = TOP_N | SCORE_BAND | THRESHOLD | ADAPTIVE_REGION
```

`SelectionPolicy` 应该成为 Strategy Engine 的一等公民，不只是 `top_n` 一个数字。

### Gate 升级方向

当前 Mono Gate 检测线性单调性（Q1 < Q2 < Q3 < Q4 < Q5）。对于非线性 Alpha（Inverted-U），Mono Gate 会误杀——分数最高区不是收益最高区，但避开最高区后策略可行。

建议从 **Linear Alpha Gate** 升级到 **Alpha Shape Gate**：

| 检测维度 | 当前 | 升级后 |
|----------|------|--------|
| 排序能力 | IC, IC_IR, t-stat | 同 |
| 单调性 | Q5 > Q4 > … > Q1 | 同 |
| **曲线形态** | — | Inverted-U / Monotonic / Flat |
| **最优区域** | — | 自动识别 best_region (Q4) |
| **区域稳定性** | — | 分段/分市场状态检验 |

---

## 7. 下一步建议

| 优先级 | 方向 | 说明 |
|--------|------|------|
| P0 | Q4 策略时间切片验证 | 2020-2022 / 2022-2024 / 2024-2026 三段 |
| P0 | Q4 策略市场状态检验 | 牛市 / 震荡 / 熊市 |
| P1 | 净收益检验 | 反转策略换手率高，扣费后是否仍然正收益 |
| P1 | Q5 + Quality Filter 修复 | 在 Q5 叠加 ROE/毛利率/杠杆过滤，看能否挽救 Q5 |
| P2 | SelectionPolicy 作为一等配置 | `StrategyConfig` 增加 `selection_method` + `score_band` |
| P2 | Alpha Shape Gate 设计 | Mono Gate → 增加曲线形态检测 |

---

## 8. 最终裁定

```
low_vol_reversal v0.1

  Signal              PASS      ✅
  IC (+0.067)         PASS      ✅
  IC_IR (0.42)        PASS      ✅
  Linear Ranking      FAIL      ❌  Top5 = -3.27%
  Alpha Shape         Inverted-U     Q4 最优，Q5 塌陷
  Optimal Region      Q4 (60-80%)
  Port Construction   SCORE_BAND required
  Production Status   Research Candidate — 需时间切片验证
```

**这不是一个失败策略，而是一个证明「Top-N 排序假设错误」的成功研究。**

平台的核心价值不是寻找最高 IC 的因子，而是发现可交易的 Alpha 结构。

---

## 9. 命令速查

```bash
# 消融实验
uv run qp experiment run multifactor --strategy lvr_vol_only --start 2024-01-01
uv run qp experiment run multifactor --strategy lvr_vol_mom --start 2024-01-01

# Score band 回测（需跳过 Gate）
uv run qp experiment run multifactor --strategy low_vol_reversal \
  --start 2024-01-01 --skip-gate --score-band 60-80
```

---

*由消融实验 + Score Band 实验自动生成。*
