# Alpha 传导泄漏调查

> 创建：2026-07-31
> 状态：调查中
> 关联：`docs/test.md`（诊断分析）、`docs/strategy_research.md`（策略记录）

## 问题陈述

**因子层优秀，策略层失败。** Alpha 在 Score → Portfolio 的传导链中几乎全部损失。

| 层 | 指标 | 值 | 判定 |
|----|------|-----|------|
| Factor | IC Mean | +0.080 | ✅ |
| Factor | IC IR | 0.70 | ✅ |
| Factor | IC t-stat | 15.70 | ✅ |
| Factor | Q5-Q1 spread | +0.0067 | ✅ dir=↑ |
| Gate | direction_correct | True | ✅ |
| **Portfolio** | **Turnover** | **0.0%** | ❌ **P0** |
| **Portfolio** | **总收益** | **+2.49%** | ❌ |
| **Portfolio** | **超额 vs 基准** | **-16.43%** | ❌ |
| **Portfolio** | **Sharpe** | **0.23** | ❌ |

---

## 调查步骤

### P0 — Turnover = 0%：为什么没有调仓？

**现象**：20天调仓 + Top-10 策略，WebUI 显示 turnover_pct = 0.0%。正常应该有几十%换手。

**假设**：

| # | 假设 | 验证方法 |
|---|------|---------|
| H1 | 回测引擎 `rebalance()` 只执行了初始建仓，后续调仓日未触发 | 在 `rebalance()` 加日志，或 grep 现有日志中是否有第2次调仓 |
| H2 | 信号生成了但全部被 buffer/filter 过滤掉 | 对比 `buy_signals=34` / `sell_signals=164` 的日志 vs 实际执行的 trade |
| H3 | `turnover_pct` 计算逻辑有 bug（实际有交易但算成 0） | 跟踪 `turnover_pct` 的计算路径，确认公式 |
| H4 | 策略只在第一次调仓日买入，之后 score 无变化导致无新信号 | 检查 score 是否在后续调仓日变化 |
| H5 | 大盘过滤（bear market）阻止了所有买入 | 检查大盘过滤的触发频率 |

**调查步骤**：

1. **定位 turnover_pct 计算位置**
   - `grep -rn "turnover_pct" qp/` — 找到谁写入这个 metric
   - 跟踪从 backtest result → metrics dict 的数据流

2. **检查信号 → 交易转换**
   - 日志显示 `买入信号: 34 条 | 卖出信号: 164 条 | 调仓日: 25 天`
   - 但 `n_trades = 76`
   - 确认 34 + 164 = 198 个信号，只有 76 个实际成交？被什么过滤了？

3. **检查回测引擎 rebalance 逻辑**
   - `qp/simulation/` 或 `qp/pipeline/multifactor_pipeline.py` 中回测部分
   - 确认调仓是否在后续日期被调用
   - 检查 `SimulatedBroker` 的 `execute_signals` 或等效方法

4. **手动算一次 turnover**
   - 取实验记录的 25 个调仓日
   - 对比相邻调仓日的持仓变化
   - 如果持仓有变但 turnover=0，则是计算 bug
   - 如果持仓无变，则是信号/执行问题

---

### P1 — 信号到持仓的传导路径

**已知**：
```
因子: 5 个 (Amplitude_5D, Volatility_20D, Momentum_3M, Volume_Concentration, Volume_Trend_10D)
质量过滤: 1037/3043 合格 (34%)
OLS 中性化: 波动率 + 成交额
Top-10: 每月调仓 (20天)
```

**需要验证的链路**：

```
Score 计算
  → 质量过滤 ×
  → OLS 正交化 ×
  → 行业中性 ×
  → 防追高 ×
  → 大盘过滤 ×
  → Top-N 排序
  → Signal 生成 (buy/sell)
  → Position Manager
  → Broker 执行
  → 持仓
```

对每个环节，需要确认：
- 输入是什么？
- 过滤掉了什么？
- 输出是什么？

---

### P2 — 基准对比异常

**现象**：等权买入持有 +18.92%，策略 +2.49%

**问题**：基准是「全部 3043 只股票等权持有」，策略是「从 1037 只质量合格股票中选 10 只」。两者的 universe 完全不同。这是一个公平对比吗？

**建议**：
- 增加一个「质量过滤后等权持有」的基准
- 或者用「1037 只中随机选 10 只 × N 次」做 Monte Carlo 基准

---

## 已完成修复

- [x] Gate 方向检查 (`direction_correct`) — 2026-07-31
- [x] Q 编号翻转 (Q1=最低分, Q5=最高分) — 2026-07-31

---

## 调查结果

### ✅ 修复 #1 — Turnover 计算缺失 (P0)

**根因**：`_broker_backtest()` 返回 dict 没有 `turnover_pct` 字段。`ExperimentMetrics.turnover_pct` 取默认值 0.0。

**修复**：回测循环中累加 `total_buy_value` / `total_sell_value`，公式 `turnover_pct = total_sell_value / avg_equity * 100`。

**验证**：累计换手 329%（2.5 年，25 次调仓，对应每次平均 ~13% 单边换手）。

### ✅ 修复 #2 — BUY 订单被现金检查拒绝 (P0)

**根因**：`multifactor_pipeline.py` 回测循环中，先 `submit_order(SELL)` 清仓，再 `submit_order(BUY)` 建仓，但两次提交之间没有执行。`submit_order(BUY)` 检查 `self._cash >= est_cost` 时，卖出款尚未到账（`execute_pending()` 尚未调用），导致买单因"现金不足"被拒。

**修复**：在 SELL 和 BUY 提交之间插入 `broker.execute_pending()`，先让卖出款到账。

### ❌ 新发现 #1 — 信号生成才是真正的瓶颈 (P1)

Debug log 揭示：

```
2024-08-02  0持仓→0卖出→0买入候选   ← 第一笔调仓延迟8个月
2024-08-30  0持仓→0卖出→0买入候选   ← 继续空仓
2025-06-05  0持仓→0卖出→6买入候选   ← 首次买入，已过整年
2025-07-03  6持仓→6卖出→6买入候选   ← 只买 6 只，不是 10
```

25 个调仓日仅生成 **34 条买入信号**（Top-10 策略应有 ~250 条）。大部分调仓日买入候选为 0，策略长时间空仓。

**下一步**：调查 `momentum_vol_full` 策略的信号生成逻辑，确认为什么买入候选如此之少。

### ❌ 新发现 #2 — 仓位累积不轮换

持仓数逐渐增加（6→12→18→23→28），说明每次调仓不是"全清→全买"，而是"部分清→部分买"。卖出数始终 ≤ 买入数，仓位只增不减。

---

## 实验记录

| 日期 | 实验 ID | 改动 | 结果 |
|------|---------|------|------|
| 2026-07-31 | multifactor_20260731_085209 | Gate 方向检查修复后 | Turnover 0%, 收益 +2.49% |
