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
> Windowed backtests that re-number trading days from the window start silently diverge from the full-range calendar: a 2022-01-04 window buys on 02-08/03-08 instead of the full-range 01-18/02-22. After fixing the alignment chain (CLI → extra_overrides → strategy runner → signal generator → backtest engine, plus cache date clipping), the three same-calendar windows show momentum_vol_full is **strong in 2019-21 (+44.11% excess) and 2024-26 (+87.67%), weak in 2022-23 (+6.04%, 39.14% drawdown)**. The full-range average (+1.97% excess) is dragged down by the 2022-23 window, not by factor failure.

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

### 3 窗同日历结果（全部对齐全区间基准 044353）

| 窗口 | offset | 总收益 | 超额 | 回撤 | IC |
|------|--------|--------|------|------|-----|
| 2019-01-01 → 2021-12-31 | 0 | +108.73% | **+44.11%** | 8.46% | 0.0686 |
| 2022-01-01 → 2023-12-31 | 10 | -4.60% | **+6.04%** | **39.14%** | 0.0769 |
| 2024-01-01 → 2026-08-14 | 6 | +107.04% | **+87.67%** | 9.07% | 0.0751 |
| 全区间基准 | 0 | +56.51% | +1.97% | 24.87% | 0.0701 |

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
2. 当前实盘区间（2024-2026）真实状态：超额 +87.67% / 回撤 9.07%（远好于此前短窗估计 +58%）
3. registry approved.backtest_summary 已校准为修复后全区间真实值（IC 0.0701 / Sharpe 0.42 / MaxDD 24.87% / 超额 +1.97%，commit c414c66）
4. MF_NetFlow_20D 中性、正交化开关无差 → 均不 approve

## 附：实验缓存陷阱（本次又一例）

缓存文件（`data/experiments/_factor_raw_cache.parquet`）在实验间被重写（mtime 10:44 vs 022721 10:27），起点漂移（min_history 丢前 ~60 天 → 2019-04-04 起）——**任何依赖缓存日历做 offset 基准的方案都不稳**；必须以 price_data 日期范围为基准裁剪。
