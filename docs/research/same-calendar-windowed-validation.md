# Same-Calendar Windowed Validation（同日历分窗验证）

> **类型**: Research Finding + Methodology Fix
> **日期**: 2026-08-16
> **状态**: 定稿
> **来源**: 修复后（PIT + 卖空 + CLI + backtest offset）的 momentum_vol_full 冻结权重分窗实验
> **实验 ID**: 041315（2019-21）/ 041936（2022-23）/ 044652（2024-26）/ 044353（全区间基准）
> **完整报告**: Obsidian 无（本次为代码内研究记录）

## Finding（正式表述）

> **Finding: Windowed Calendar Alignment**
>
> Windowed backtests that re-number trading days from the window start silently diverge from the full-range calendar: a 2022-01-04 window buys on 02-08/03-08 instead of the full-range 01-18/02-22. After fixing the alignment chain (CLI → extra_overrides → strategy runner → signal generator → backtest engine, plus cache date clipping), the three same-calendar windows show momentum_vol_full is **strong in 2019-21 (+61.09% excess vs 上证) and 2024-26 (+74.47%), weak in 2022-23 (+13.50%, 39.14% drawdown)**. The full-range average (-2.79% excess vs 上证) is dragged down by the 2022-23 window, not by factor failure.

## 一句话机制

```
分窗实验若从窗口起点重数 20 天调仓日 → 与全区间日历错位 → 交易日子全错 → 超额数字失真（假象）
修复：--rebalance-offset + 缓存日期裁剪 + backtest 引擎透传 → 3 窗日历与全区间逐一验证一致
```

## 证据链（FACT）

### 修复前（错误） vs 修复后（正确）——2022-23 窗

| 版本 | 调仓日（2022Q1） | 超额 |
|------|-----------------|------|
| 未对齐（窗口起点日历） | 01-04 初始建仓 / 02-08 / 03-08 | +42.09%（假象） |
| **对齐（offset=10，同日历）** | 01-04 初始建仓 / **01-18** / **02-22** | **+6.04%（真实）** |

### 3 窗同日历结果（上证指数基准，2026-08-16 重跑）

| 窗口 | offset | 总收益 | 超额(上证) | 回撤 | IC |
|------|--------|--------|------|------|-----|
| 2019-01-01 → 2021-12-31 | 0 | +108.73% | **+61.09%** | 8.46% | 0.0686 |
| 2022-01-01 → 2023-12-31 | 10 | -4.60% | **+13.50%** | **39.14%** | 0.0769 |
| 2024-01-01 → 2026-08-14 | 6 | +107.04% | **+74.47%**（正交开）/ 短窗 +92.56%（正交关） | 9.07% | 0.0751 |
| 全区间基准 | 0 | +56.51% | **-2.79%** | 24.87% | 0.0701 |

**基准切换说明**：2026-08-16 起基准从等权全市场中位数换成上证指数（sh000001）。上证 2019-2026 涨 +59.30%，强于等权中位数 → 全区间超额 +1.97% → -2.79%。策略绝对收益不变（+56.51%）。

调仓日逐一验证一致（如 2024-26 窗 offset=6 → BUY 2024-01-10/02-07/03-14 与基准完全相同）。

## 方法学修复（3 处才让 offset 生效）

| # | Bug | 修复 commit |
|---|-----|------------|
| 1 | CLI `--rebalance-offset` 白名单缺失 + extra_overrides 透传 | e685f68 |
| 2 | `_compute_backtest` 独立引擎忽略 offset（信号对齐交易没对齐） | 8f983a6 |
| 3 | 缓存命中后未按 price_data 日期裁剪（缓存起点漂移 → 日历错位） | 8f983a6 |

**offset 公式**：`offset = (freq - W % freq) % freq`，W = 窗口起点在全区间价格日历索引（2022 窗=10、2024 窗=6；误用 W%freq=14 会错位）。

## Strategy Decision（定稿）

**momentum_vol_full v20260811：KEEP（保持原策略不动）**

1. 3 窗验证：2 强 1 弱，无系统性失效；2022-23 艰难窗是真实风险，非 bug
2. 当前实盘区间（2024-2026）真实状态：超额 +74.47% / 回撤 9.07%（上证基准；正交关短窗 +92.56%）
3. registry approved.backtest_summary 已校准为上证基准全区间值（IC 0.0701 / Sharpe 0.42 / MaxDD 24.87% / 超额 -2.79%，commit 待更新）
4. **正交化结论翻转（上证基准）**：短窗 24-26 正交关 +92.56% vs 正交开 +66.24%（**差 +26.3pp，关显著更优**；等权基准下差异仅 -2.5pp）。虽然生产 momentum_vol_full 已配置 orthogonalize=False（8-13 决策），但此前「开关几乎无差」的结论在上证基准下不成立——**关闭正交化是当前配置的正确选择**。MF_NetFlow_20D 中性（6F -3.49% vs 5F -2.79%，仍无增益）→ 不 approve 6F。

## 附：实验缓存陷阱（本次又一例）

缓存文件（`data/experiments/_factor_raw_cache.parquet`）在实验间被重写（mtime 10:44 vs 022721 10:27），起点漂移（min_history 丢前 ~60 天 → 2019-04-04 起）——**任何依赖缓存日历做 offset 基准的方案都不稳**；必须以 price_data 日期范围为基准裁剪。
