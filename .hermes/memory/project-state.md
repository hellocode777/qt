# Project State — QT 当前状态摘要

> ⚠️ 本文件是**摘要指针**，不是权威状态。详细追踪以版本化文件为准。
> 本文件过时 = 正常现象；回答「当前在做什么」先看下方链接，别信本文件缓存。

## 权威状态源

- 版本化 backlog：`docs/tracking/qt_backlog_tracker.md`
- 用户侧待办（双镜像）：Obsidian `1-Projects/qt项目待办.md`
- 策略注册表（运行事实）：`data/strategy_registry.json`
- 近期决策：`docs/archive/adr/`（ADR-001~033）

## 当前活跃工作（截至 2026-10-08）

- **唯一 APPROVED 策略**：`lvr_vol_only`（v20261008，低波单因子 `Volatility_20D +1.0`）
  —— 2026-10-08 由 `momentum_vol_full` 换入；mvF 降为 backtest_passed（v20260811 快照保留供审计），依据见 `docs/tracking/qt_backlog_tracker.md` #6
- **Paper Trading**：`lvr_vol_only`（pt-8a24c686，起始 2026-08-21）跑到 30/30 中
  —— 切换先行，未等模拟盘满 30 天（已知取舍，非 bug）
- 见 `docs/tracking/qt_backlog_tracker.md` 的最新条目

## 已知未完成

- 参见 backlog tracker 的 OPEN 项；**动手前先验证代码现状**（tracker 标记可能过时）
