# QP (Quant Platform) 用户指南

> 个人量化研究与投资决策操作系统
> 更新日期：2026-10-08

---

## 目录

1. [快速开始](#1-快速开始)
2. [环境诊断](#2-环境诊断)
3. [数据获取](#3-数据获取)
4. [投资策略规则](#4-投资策略规则)
5. [核心工作流](#5-核心工作流)
6. [组合与风控](#6-组合与风控)
7. [监控体系](#7-监控体系)
8. [模型管理](#8-模型管理)
9. [实验追踪与知识库](#9-实验追踪与知识库)
10. [模拟交易](#10-模拟交易)
11. [自动化调度](#11-自动化调度)
12. [Web 决策中心](#12-web-决策中心)
    - [12.3 个股K线分析](#123-个股k线分析)
    - [12.4 SPA 原型界面（/proto/）](#124-spa-原型界面proto)
13. [全命令速查表](#13-全命令速查表)
14. [典型工作流](#14-典型工作流)
15. [配置说明](#15-配置说明)
16. [项目架构](#16-项目架构)
17. [开发命令](#17-开发命令)
18. [故障排查](#18-故障排查)

---

## 1. 快速开始

```bash
# 安装依赖
uv sync

# 确认 CLI 可用
uv run qp version

# 查看所有命令
uv run qp --help
```

---

## 2. 环境诊断

```bash
uv run qp doctor
```

输出示例：
```
=== QP Doctor ===
Python version: 3.12.x
Platform: Linux
CPU cores: N
Disk free: X GB
Config: OK (env=development)
Storage: OK (backend=duckdb)
=== All checks passed ===
```

---

## 3. 数据获取

> **第一步永远是拿数据。** 所有后续操作依赖 `data/dataset/` 下的 Parquet 文件。

### 3.1 全量数据拉取（生产环境）

```bash
# 从数据源拉取全量 A 股主板数据
uv run qp data fetch

# 指定日期范围
uv run qp data fetch --start=2020-01-01 --end=2026-07-01

# 每批 500 只（腾讯接口限制）
uv run qp data fetch --batch=500

# 跳过 ETL，只拉原始数据
uv run qp data fetch --skip-etl
```

数据处理流程：**Raw → Bronze（清洗）→ Silver（校验）→ Gold（数据集）**

> ⚠️ **复权策略（2026-08-14 起）**：价格表只存**不复权原始价**。
> 腾讯 adapter 使用 `kline/kline`（无复权参数）接口；复权因子独立存
> `data/dataset/adj_factor.parquet`（akshare qfq-factor），计算层按需调整。
> **腾讯 `fqkline/get` + `qfq` 接口已废弃**（负价格坏数据 bug），任何代码/脚本不得再使用。
> 详见 `docs/architecture/data/DP-002-data-layer.md`。

### 3.2 Demo 合成数据（快速体验）

```bash
uv run qp ingest --demo
uv run qp ingest 2024-01-01 2024-12-31
```

---

## 4. 投资策略规则

> 以下规则是 QP 平台的「交易宪法」(V2.1 Final)，所有买卖信号均由此派生。

### 4.1 核心原则

| 原则 | 含义 |
|------|------|
| **Model Driven** | 一切投资决策由模型驱动，Alpha 来自截面排序而非价格走势 |
| **Risk First** | 风险控制优先于 Alpha — 策略负责机会，风控负责生存 |
| **Stateless Decision** | 每次调仓都是全新评估，历史持仓/止损不影响当前决策 |
| **Human in the Loop** | 平台生成建议，最终交易由投资者确认执行 |

### 4.2 买入规则

| 项目 | 规则 |
|------|------|
| 买入标的 | 调仓日进入 Target Portfolio 的 Top N 股票 |
| 默认持仓数 | Top 10 |
| 买入时间 | 仅调仓日（每月第一个真实交易日） |
| 建仓方式 | 按目标权重一次性建仓 |

**明确不采用**：固定止盈（切断动量 Alpha）、最大持仓天数（人为规则）、Score 硬阈值（不同市场阶段不可比）。

### 4.3 卖出规则（三类，不同时间维度）

#### 第一类：Rank Exit（Alpha 消失，仅调仓日）

```
Rank ≤ Top10   →  买入 / 保持持仓
Rank 11~20     →  继续持有（Buffer 区）
Rank > 20      →  卖出
```

Buffer 机制降低换手率：排名下降不代表 Alpha 完全失效。

#### 第二类：Risk Exit（风险退出，每日必检）

| 风险 | 执行 |
|------|------|
| Stop Loss（-10%） | 次日开盘卖出 |
| ST / *ST | 次日开盘卖出 |
| 退市风险 | 次日开盘卖出 |
| 长期停牌 | 标记冻结 |
| 流动性风险 | 人工确认 |

风险不等调仓日 — 即使模型给第一名，触发风险立即退出。

#### 第三类：Portfolio Exit（组合调整，仅调仓日）

| 场景 | 处理 |
|------|------|
| 权重超限 | 减仓至目标权重 |
| 行业超配 > 40% | 降低行业仓位 |
| 基本面恶化 | 标记退出 |

### 4.4 退出信号优先级

```
CRITICAL  → ST, 退市
HIGH      → Stop Loss (-10%)
MEDIUM    → 流动性风险, 停牌
LOW       → Rank Drop, 权重调整
```

同一天多信号 → 合并为一条卖出建议（保留所有 reason tag 用于归因分析）。

### 4.5 模块职责

```
Strategy Engine (每日)    → 回答：「今天最值得持有哪些股票？」
Risk Manager    (每日)    → 回答：「哪些股票必须离开？」
Portfolio Manager (调仓日) → 回答：「今天需要如何调整组合？」
Decision Layer  (调仓日+) → 人工审核与执行
```

### 4.6 止损后又涨回来怎么办？

系统不会因为发生过止损就永久排除某只股票。每次调仓都是一次全新评估 — 如果股票重新满足 Alpha 条件，正常重新买入。**止损管理的是未知风险，不是预测未来。**

---

## 5. 核心工作流

### 5.1 端到端每日管道

一步完成：数据 → 特征 → 策略 → 报告。

```bash
uv run qp run daily                            # 正式数据
uv run qp run daily --demo                     # 合成数据
```

> ⚠️ **demo 模式仅供逻辑验证**：合成数据算出的 DecisionPackage / 信号**禁止作为交易依据**。自 2026-08-12（8/5 事故）起，demo 数据经 guard 短路，绝不写入生产数据集 `daily_price_latest.parquet`，可安全用于离线测试管道、邮件通知等逻辑。

#### 每日管道行为说明

Daily pipeline 每天运行，但**不是每天都调仓**：

| 日期 | 行为 | 说明 |
|------|------|------|
| **每月第一个真实交易日**（调仓日） | ✅ 完整调仓 | 买入新标的 + 风控退出 + 行业调整 |
| **其他日期** | ⚠️ 仅风控 | 只执行 Risk Exit / Rank Exit / 止损，不买入 |

**示例**：
- 2026-07-01（周三）→ 调仓日，可能买入新股票
- 2026-07-02 起 → 非调仓日，只检查持仓是否需要风控退出
- 若 1 号逢周末/节假日（如 2026-10-01 国庆）→ 顺延到当月首个交易日（10-08）

调仓日逻辑见 `qp/pipeline/daily_pipeline.py`：
```python
# 调仓日 = 每月第一个真实交易日（akshare 交易日历，含节假日）
first_td = TradingCalendar().first_trading_day_of_month(today.year, today.month)
is_rebalance_day = force_rebalance or (today == first_td)
```

> **为什么？** 每月集中调仓一次，减少频繁交易带来的冲击成本和印花税损耗。月中只做风控止损，让 Alpha 有足够时间发酵。
> 历史坑：旧版用 `today.day <= 5`（前 5 个自然日都算调仓日），导致每月 1-5 号连续调仓（如 9/1 建仓、9/2 又重评换股）。V2.2 改为精确到首个交易日，1 号逢假自动顺延。

### 5.2 多因子实验（核心回测命令）

```bash
# 基础回测：线性加权策略（10 因子）
uv run qp experiment run multifactor \
  --strategy momentum_vol_full \
  --start 2024-01-01 --end 2026-07-01

# ML 模式：LightGBM LambdaRank 因子合成
uv run qp experiment run multifactor \
  --strategy momentum_vol_full \
  --model --start 2024-01-01 --end 2026-07-01

# 完整参数示例
uv run qp experiment run multifactor \
  --strategy momentum_vol_full \
  --start 2024-01-01 --end 2026-07-01 \
  --top-n 10 --rebalance 20 \
  --industry-neutral --orthogonalize \
  --skip-gate
```

#### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--strategy <name>` | 策略配置名 | `momentum_vol_full` |
| `--start <YYYY-MM-DD>` | 回测起始日期 | 最近 2 年 |
| `--end <YYYY-MM-DD>` | 回测结束日期 | 今天 |
| `--model` | 启用 ML LambdaRank 模型 | 关闭（线性加权） |
| `--top-n <N>` | 持仓股票数 | 10 |
| `--rebalance <N>` | 调仓周期（天） | 20 |
| `--industry-neutral` | 行业中性化 | 开启（策略配置默认） |
| `--orthogonalize` | 因子正交化 | 关闭（momentum_vol_full 自 2026-08-13 起关闭，VIF 极端日剥离有效信号） |
| `--skip-gate` | 跳过验证门禁 | 关闭 |
| `--symbols <codes>` | 自定义股票池 | 全部主板 |
| `--dataset <name>` | 数据集名称 | `daily_price_main` |
| `--resume <id>` | 从快照复现实验（权重冻结） | — |
| `--score-band auto` | 自动搜索最优分位区间 | — |
| `--debug` | 启用 DEBUG 日志 | 关闭 |

### 5.3 影子模拟（Shadow Trading）

```bash
# 影子组合绩效摘要（无参数 = 看摘要）
uv run qp simulation shadow

# 跑指定日期的影子模拟（需该日已有决策包）
uv run qp simulation shadow 2026-09-24
```

影子模拟用假钱按当日决策包建仓，与实盘持仓解耦，用于在不影响实盘的情况下评估策略调整。`daily_pipeline` Step 13.1 每个交易日自动跑一次，无需手动。

### 5.4 验证门禁

```bash
uv run qp validate                                  # 默认校验 registry 里唯一 APPROVED 的策略
uv run qp validate --stage backtest_passed           # 指定阶段
uv run qp validate --strategy-id momentum_vol_full   # 指定策略
uv run qp validate --experiment mf_20260901_020520   # 指定提供指标的实验记录
uv run qp validate --json                            # 机器可读输出（含指标来源）
```

可用阶段：`research` | `backtest_passed` | `paper_trading` | `shadow_production` | `production`

> ✅ **指标来源全部是真的**（2026-09-25 起）：回测指标从 `ExperimentTracker`
> （`data/experiments/<id>.json`）读取，输出首部会打印实验 ID、创建时间和所用指标。
> 找不到可用实验（没跑过 / 没有回测结果）→ 直接报错退出，不再用写死的占位值。
> 默认选 `config.strategy_name == 当前策略` 的**最新**实验；用 `--experiment` 可指定。
> ⚠️ **默认策略**：不传 `--strategy-id` 时取 registry 中**唯一** `APPROVED` 的策略；
> 没有 APPROVED、或有多个 → 报错退出，不猜。
> ⚠️ **「未评估」≠ 通过**：实验记录里没有生产者的指标不会被塞占位值，对应检查项输出
> `Missing ...` / `not available`，末尾会集中列出「N 项未评估（不代表通过）」。
>
> 门禁指标 → 生产者映射（2026-09-25 起由 `multifactor_pipeline` 落盘，输出首部会回显）：
>
> | 检查项 | 指标 | 口径 / 来源 |
> |---|---|---|
> | `cost_adjusted` | `sharpe_ratio_net` / `max_drawdown_pct_net` / `total_cost_pct` | 权益曲线本身含成本（成交即扣佣金/印花税/滑点，`SimulatedBroker.get_equity = cash + 市值`）；`total_cost_pct` = 总成本 / 平均权益 |
> | `turnover` | `daily_turnover_pct` | 累计换手（总卖出 / 平均权益）÷ 交易日数 = 日均**单边**换手；阈值区间 [5%, 200%] 即按日 |
> | `overfit_ic_ratio` | `in_sample_ic` / `out_of_sample_ic` | 全期 `ic_mean` vs Purged-CV OOS `cv_oos_ic_mean`（口径会在输出里标注） |
> | `feature_importance` | `feature_importance` | 线性策略 = 归一化 `|权重|`（**不是** tree gain，仅用于集中度判断） |
> | `neutralization` | `pre/post_neutralization_ic` | **仅 legacy 因子管线路径**（`--strategy` 不在策略模式白名单时）实算 pre/post；`momentum_vol_full` 等策略模式由策略内部中性化，管线拿不到中间量 → 该项仍「未评估」 |

### 5.5 生成交易建议

人工执行前的最后一步。默认加载今天的 DecisionPackage。

```bash
uv run qp decide                               # 加载今天的决策包
uv run qp decide --force                       # 重跑每日管道，生成新决策包
uv run qp decide --review                      # 交互式人工审核（通过/拒绝+备注）
uv run qp decide --history                     # 列出历史决策
uv run qp decide --show dp-2026-07-23-xxx      # 查看指定决策包
```

DecisionPackage 包含：
- **数据血缘** — 哪个数据集版本、哪些特征版本
- **市场状态** — 当前 regime、置信度、建议敞口
- **策略执行** — 每个策略产生的信号数
- **验证门禁** — 每个策略的验证评分和失败规则
- **风控审计** — 每一条违规的阈值 vs 实际值
- **交易建议** — 具体买卖标的、数量、理由、风险警告
- **人工审核区** — 待用户填写：是否审核通过、是否执行

---

## 6. 组合与风控

### 6.1 投资组合 KPI 仪表盘

```bash
uv run qp portfolio report
```

输出内容（中英双语）：
- 基本概况：总资产、活跃策略数、候选标的数
- 风控限额：单仓上限、单行业上限、剔除标的
- 行业暴露：各行业权重分布（超过 25% 警告）
- 成本分析：印花税、佣金、预估单边/双边成本
- 资金分配：等权分配、风险平价、凯利公式三种方案对比
- 仓位优化：最大夏普比率优化结果，Top 5 持仓
- KPI 仪表盘：夏普、最大回撤、超额占比目标 vs 实际

### 6.2 风控分析

```bash
uv run qp portfolio risk
```

输出：
- 行业集中度分析
- 相关性扫描（阈值 >0.7 的配对）
- 风控限额一览

---

## 7. 监控体系

### 7.1 每日一键检查

```bash
uv run qp monitor check
```

输出示例：
```
=== QP 监控检查 / Monitor Check ===
  时间 / Time: 2026-07-25 09:07:00

── 市场状态 / Market Regime ──
  状态 / Regime:        TREND_UP
  置信度 / Confidence:  82%
  趋势强度 / ADX:       28.5
  涨跌停比 / LUD:       0.52
  行业轮动 / Rot:       0.18
  危机模式:             否

── 熔断检查 / Kill Switch ──
  ✅ 状态: 正常
  熔断级别:             NORMAL

── 特征漂移 / Drift ──
  PSI:                  0.12

── 模型衰减 / Model Decay ──
  状态:                 healthy

── 策略健康 / Strategy Health ──
  分数:                 92/100
  等级:                 HEALTHY

── 建议操作 / Action ──
  ✅ OK
```

`qp monitor check` 跑的是完整的 KillSwitchPipeline，包含：

**8 种市场状态：**
| 状态 | 含义 | 建议 |
|------|------|------|
| `TREND_UP` | 上升趋势 | Alpha 最佳发挥期 |
| `TREND_DOWN` | 下降趋势 | 减少多头敞口 |
| `RANGING` | 震荡 | 均值回归策略 |
| `HIGH_VOL` | 高波动 | 缩减仓位、扩大 Buffer |
| `LOW_VOL` | 低波动 | 正常操作 |
| `LIQUIDITY_CRUNCH` | 流动性危机 | 冻结买入 |
| `STYLE_REVERSAL` | 风格剧烈切换 | 暂停排序驱动 |
| `UNKNOWN` | 数据不足 | 等待数据 |

**7 个熔断触发器（按优先级排序）：**
| 优先级 | 触发器 | 条件 | 严重级别 |
|--------|--------|------|----------|
| 10 | AbnormalTurnover | 单日换手 > 80% 持仓 | FULL_STOP |
| 15 | WeeklyDrawdown | 周回撤 > 5% | HALT_BUY |
| 20 | Drawdown | 回撤 > 历史最大 ×1.5 | HALT_BUY |
| 25 | PortfolioDrawdown | 月回撤 > 15% 或 60日回撤 > 20% | HALT_BUY |
| 30 | ConsecutiveLoss | 连续 5 日负 PnL | WARNING |
| 40 | ModelDecay | IC 衰减至训练 IC 的 30% 以下 | WARNING |
| 50 | PSI | 特征 PSI ≥ 0.25 | WARNING |

**4 级熔断状态：**
```
NORMAL → WARNING → HALT_BUY → FULL_STOP
```

每次检查自动写入：
- `data/monitoring/system_health_log.parquet` — 每日健康快照
- `data/monitoring/system_state.parquet` — 系统状态机
- `data/monitoring/factor_health.parquet` / `factor_ic_series.parquet` — 因子健康（有 factor_daily_ics 输入时）
- `data/monitoring/retrain_signals.parquet` — 需要重训时写入信号
- `data/knowledge/failure_analysis/` — 触发 PAUSE_BUY 以上时自动归档

### 7.2 系统状态查询

```bash
# Python 一行查看当前状态
uv run python3 -c "
from qp.monitoring.system_state import SystemStateManager
mgr = SystemStateManager()
print(mgr.stats())
"
```

五种系统状态：
| 状态 | 含义 | 允许开仓 | 允许平仓 |
|------|------|----------|----------|
| NORMAL | 正常运行 | ✅ | ✅ |
| WARNING | 警告 | ✅ | ✅ |
| PAUSED | 暂停买入 | ❌ | ✅ |
| STOPPED | 全停 | ❌ | ✅ |
| RECOVERY | 恢复中 | 渐进 | ✅ |

### 7.3 查看健康历史

```bash
# 最近 90 天健康日志
uv run python3 -c "
from qp.monitoring.health_logger import SystemHealthLogger
l = SystemHealthLogger()
print(l.stats())
"

# 查看熔断触发历史
uv run python3 -c "
from qp.monitoring.retrain_signal import RetrainSignalLogger
l = RetrainSignalLogger()
for s in l.load_history(days=30).iter_rows(named=True):
    if s['action'] != 'NONE':
        print(f'{s[\"date\"]} | {s[\"trigger\"]} | {s[\"action\"]} | {s[\"message\"][:80]}')
"
```

### 7.4 因子健康监控（Factor Health）

每个因子按**生命周期状态机**持续追踪：`RESEARCH → VALIDATED → PRODUCTION → WEAKENING → DEGRADED → RETIRED → ARCHIVED`。判定基于滚动 IC（30/90/252 日）、IC_IR、IC 衰减斜率（-0.001/日 ≈ 一年 -25% IC）。

```bash
# 因子健康总览（生命周期 + 滚动 IC + 衰减斜率）
uv run qp factor list

# 单个因子详情
uv run qp factor health Volume_Concentration

# 因子研究报告（markdown）
uv run qp factor report <factor_name>

# 全量重算因子健康（约 2 分钟/因子 × 19 因子）
# 用于数据修复后重建；平时由 daily_pipeline Step 1.6 增量更新
uv run qp factor update-health

# 因子目录
uv run qp factor catalog
```

数据文件：
- `data/monitoring/factor_health.parquet` — 因子健康快照（按 factor+date 去重）
- `data/monitoring/factor_ic_series.parquet` — 日度 IC 序列（增量追加）

> **日常无需手动执行**：每日 18:00 daily_pipeline 的 Step 1.6 自动增量更新；
> 09:07 monitor_check 读取该数据做因子健康检查。`update-health` 仅在全量重建/数据修复后使用。

### 7.5 市场状态检测

```bash
uv run qp monitor regime
```

> 输出首行是「数据日期 / Data through」+ 实际读取的文件名 —— 数据不是今天的会直接看出来。
> 读文件走 `qp.shared.paths.resolve_daily_price_path()`（优先 `daily_price_latest.parquet`，
> 回退按 mtime 取最新的 `daily_price_*.parquet`）。曾经这里按文件名排序取最后一个，
> 会静默读到 `daily_price_main_2026-08-14.parquet`（2026-09-25 修复）。

### 7.6 告警通道测试

```bash
uv run qp monitor alert-test
```

支持告警通道（`monitoring/alerts.py` 共 7 个通道类：Terminal / Log / Telegram / 钉钉 DingTalk / 企业微信 WeCom / Email / File）。

> `qp monitor alert-test` 实测只注册其中 3 个：Terminal / Log / Telegram（WARNING 起）。
> 其余通道要在部署时自行 `AlertManager.add_channel(...)` 接进来 —— 别把"可用通道类"当成"已接通"。

---

## 8. 模型管理

```bash
# 列出所有已注册模型
uv run qp model list

# 查看模型详情（<model_id> 从 model list 里取）
uv run qp model show <model_id>

# 模型重训（建议先用 --dry-run）
uv run qp retrain --dry-run                     # 演习；不传策略 = registry 里唯一 APPROVED
uv run qp retrain                               # 正式重训（目标同上）
uv run qp retrain momentum_vol_full --dry-run   # 显式指定策略
```

> 实测（2026-09-25）：`qp model list` 当前为空 —— 模型在跑过实验（`--model`）或重训成功后才会注册。
> 空列表是真实状态，不是命令坏了。

---

## 9. 实验追踪与知识库

```bash
# 列出所有实验
uv run qp experiment list

# 查看实验详情
uv run qp experiment show <experiment_id>

# 知识库统计
uv run qp knowledge stats

# 全文搜索
uv run qp knowledge search "期现背离"
uv run qp knowledge search "最大回撤"
```

---

## 10. 模拟交易（Paper Trading）

新策略在真金白银之前，必须通过 30 天模拟交易验证。

```bash
# 启动 30 天模拟交易
uv run qp paper start lvr_vol_only

# 查看进度
uv run qp paper status lvr_vol_only
```

> 可用策略 ID 以 registry 为准（当前有 30 天模拟盘记录的是 `momentum_vol_full` 与 `lvr_vol_only`）；
> `qp paper start` 只接受**已注册**策略，不自动注册（否则污染 `data/strategy_registry.json`）。

输出示例：
```
═══ QP 模拟交易状态 / Paper Trading Status ═══
  策略 / Strategy:    lvr_vol_only
  已过天数 / Days:    12/30
  当前权益 / Equity:  ¥1,023,500

  ⏳ 还剩 18 天完成评估

-- or, when complete --
  ✅ 通过 / Passed:    true
  总收益 / Return:     3.2%
  夏普 / Sharpe:       1.45
  建议 / Recommendation: proceed_to_shadow
```

---

## 11. 自动化调度

六个定时任务串起来，构成完整的**每日投资决策自动化闭环**：

```
09:07  monitor_check     全维度安全扫描
         │                  ├─ Market Regime (8 种状态, 含流动性危机/风格切换)
         │                  ├─ 7 个熔断触发器 (回撤/PSI/连续亏损/异常换手/模型衰减)
         │                  ├─ PSI 特征漂移
         │                  ├─ Model Decay (IC 衰减检测)
         │                  ├─ Factor Health (因子健康，读取 factor_ic_series.parquet)
         │                  └─ Strategy Health (0-100 评分)
         │                  ├─ → system_health_log.parquet
         │                  ├─ → system_state 状态机更新
         │                  ├─ → 异常自动归档 KnowledgeArchive
         │                  └─ → 触发 retrain signal (如需重训)
         │
09:17  retrain_notify     检查重训练信号，发邮件提醒（重训需人工）
         │
16:53  pre_close_check   收盘前二次确认
         │                  └─ 快速 KillSwitchPipeline (同上，STOP 时跳过当日 daily_pipeline)
         │
18:00  daily_pipeline    策略决策
         │                  ├─ Step 0: 读取 SystemState (PAUSED+ 自动跳过)
         │                  ├─ 数据摄入 → 因子计算 → 特征计算 → 策略发现 → 验证门禁
         │                  ├─ 策略执行 → 信号融合 → 风控过滤 → 成本估算
         │                  ├─ 资金分配 → DecisionPackage
         │                  ├─ Step 1.6: 因子健康增量更新 (factor_health.parquet)
         │                  └─ data/decisions/dp-2026-07-25-xxx.json
         │                     data/decisions/trade_decision_audit.parquet (T2)
         │
18:30  email_report       发送今日 DecisionPackage 邮件
         │
18:32  paper_trading      模拟盘推进：执行当日交易，满 30 天自动评估
         │
      ┌─ 闭环反馈 ─────────────────────────────────────┐
      │  FailureArchiveLogger → ClusterAnalyzer        │
      │  → 黑名单规则 (Layer 2)                         │
      │  → 特征建议 (Layer 4)                           │
      │  → 策略参数调整 (Layer 8)                        │
      └────────────────────────────────────────────────┘
```

**你每天只需要做一件事：**

```bash
qp decide --review
```

### 11.1 启动与停止

Scheduler 是 **systemd 用户服务**（`~/.config/systemd/user/qp-scheduler.service`），
随用户登录自动启动，无需 root。安装/修复用幂等脚本（**推荐**）：

```bash
# 一键安装/修复（幂等）：删除系统级副本 → 装用户级 → 启动 → 验证单实例
bash deploy/install-systemd.sh

# 干跑：只报告状态，不改动
bash deploy/install-systemd.sh --check
```

> ⚠️ 历史教训（2026-08-18）：service 曾同时存在于 `/etc/systemd/system/`（系统级）
> 和 `~/.config/systemd/user/`（用户级），重启后两个 scheduler 同时运行，
> 导致 18:30 email_report 每天发两封邮件。现在**只允许用户级一份**，
> install-systemd.sh 会删除系统级副本并验证进程数恰为 1。

手动管理（无需 sudo）：

```bash
# 启动
systemctl --user start qp-scheduler

# 开机自启
systemctl --user enable qp-scheduler

# 停止
systemctl --user stop qp-scheduler

# 重启（代码更新后）
systemctl --user daemon-reload
systemctl --user restart qp-scheduler

# 查看状态
systemctl --user status qp-scheduler

# Scheduler 自身日志
tail -f logs/scheduler.log
journalctl --user -u qp-scheduler -f

# 各 Job 独立日志（按日期分目录）
tail -f logs/$(date +%F)/monitor_check.log
tail -f logs/$(date +%F)/retrain_notify.log
tail -f logs/$(date +%F)/pre_close_check.log
tail -f logs/$(date +%F)/daily_pipeline.log
tail -f logs/$(date +%F)/email_report.log
```

> 每个 Job 写入当天日期子目录，每天一个新文件，自动清理 7 天前的旧目录。

#### SMTP 凭据（不在仓库里）

unit 不内置任何凭据，改为读 `EnvironmentFile=~/.config/qp/smtp.env`（权限 600）：

```bash
mkdir -p ~/.config/qp
cp deploy/systemd/smtp.env.example ~/.config/qp/smtp.env   # 仅首次
$EDITOR ~/.config/qp/smtp.env        # SMTP_HOST/PORT/SENDER/PASSWORD/RECEIVER
chmod 600 ~/.config/qp/smtp.env
systemctl --user restart qp-scheduler
```

`install-systemd.sh` 在该文件缺失时会**拒绝部署**（否则调度器会带空凭据起来，
18:30 `email_report` 静默失败）。

> ⚠️ 历史（2026-10-16）：明文授权码曾写在 unit 模板里并已提交推送（私有仓）→ 该凭据
> **需轮换**。详见 `docs/tracking/scheduler_credential_and_hook.md`。

#### 自动部署钩子（post-commit）

`.git/hooks/post-commit` → `deploy/git-post-commit.sh`：commit 命中 `qp/**`（除 `qp/web/**`）
或 `deploy/` 脚本时自动跑 `install-systemd.sh`，让常驻进程与代码保持一致。三道守卫：

| 守卫 | 行为 |
|---|---|
| 暂停守卫 | unit 非 `enabled`（`systemctl --user disable qp-scheduler`）→ 跳过部署。**因此"暂停"能扛住 commit**；恢复用 `systemctl --user enable --now qp-scheduler` |
| 任务窗口守卫 | 窗口从 `qp/platform/cli/commands/scheduler.py` 的 job 注册表**派生**（非手抄），命中则跳过 —— 重启会 `shutdown(wait=False)` 掐断在跑的 job |
| sudo 守卫 | 仅当系统级副本存在且 sudo 需密码时跳过 |

当前派生窗口：monitor_check 09:05–09:12 / retrain_notify 09:15–09:22 / pre_close_check 16:51–16:58 /
daily_pipeline 17:58–18:25（实测跑 22 分钟）/ email_report 18:28–18:35 / paper_trading 18:30–18:37。

干跑验证（不动服务）：

```bash
QP_HOOK_DRY_RUN=1 QP_HOOK_VERBOSE=1 QP_HOOK_FILES="qp/x.py" QP_HOOK_NOW_MIN=1090 \
  bash deploy/git-post-commit.sh
```

### 11.2 六任务时间表

| 时间 | Job | 执行内容 | watchdog |
|------|-----|----------|----------|
| 09:07 | `monitor_check` | KillSwitchPipeline 全扫描（regime/漂移/衰减/因子健康/策略健康）+ SystemState + RetrainSignal 消费 | `data/monitoring/watchdog/monitor_check.ping` |
| 09:17 | `retrain_notify` | 检查重训练信号，发邮件提醒 | `data/monitoring/watchdog/retrain_notify.ping` |
| 16:53 | `pre_close_check` | KillSwitchPipeline 收盘前二次确认（STOP → 跳过当日 daily_pipeline） | `data/monitoring/watchdog/pre_close_check.ping` |
| 18:00 | `daily_pipeline` | DailyPipeline: 数据→因子→特征→策略→风控→DecisionPackage + 因子健康增量更新 | `data/monitoring/watchdog/daily_pipeline.ping` |
| 18:30 | `email_report` | 发送今日 DecisionPackage 邮件 | `data/monitoring/watchdog/email_report.ping` |
| 18:32 | `paper_trading` | 模拟盘推进：执行当日交易（等 daily_pipeline 拉价完成后），30 天到期自动评估 PASS/FAIL | `data/monitoring/watchdog/paper_trading.ping` |

### 11.3 监控 Scheduler 本身

```bash
# 检查各 Job 最近执行时间
ls -la data/monitoring/watchdog/

# 如果某个 ping 文件超过 24 小时未更新 → Job 可能挂了
find data/monitoring/watchdog/ -mmin +1440 -name "*.ping"
```

### 11.4 数据文件位置

```bash
logs/
├── scheduler.log                    # Scheduler 自身日志（systemd 管理）
├── 2026-07-29/
│   ├── qp.log                       # Loguru 当日汇总
│   ├── monitor_check.log            # Job 1
│   ├── retrain_notify.log           # Job 2
│   ├── pre_close_check.log          # Job 3
│   ├── daily_pipeline.log           # Job 4
│   ├── paper_trading.log            # Job 4.5
│   └── email_report.log             # Job 5

data/
├── monitoring/
│   ├── factor_health.parquet        # 因子健康快照（IC/IR/衰减/生命周期）
│   ├── factor_ic_series.parquet     # 因子日度 IC 序列（增量追加，按 factor+date 去重）
│   ├── strategy_health.parquet      # 策略健康记录
│   ├── system_health_log.parquet    # T1: 每日健康快照
│   ├── system_state.parquet         # 系统状态机
│   ├── system_state_log.parquet     # 状态转换不可变日志
│   ├── retrain_signals.parquet      # 重训信号
│   └── watchdog/                    # 各 Job 心跳文件
├── decisions/
│   ├── dp-2026-07-25-xxx.json       # 决策包
│   ├── 2026-07-25.md                # 决策报告
│   └── trade_decision_audit.parquet # T2: 交易决策审计
└── knowledge/
    ├── failure_archive.parquet      # T3: 失败事件归档
    ├── blacklist_rules.json         # 聚类分析生成的黑名单规则
    └── failure_analysis/            # 自动归档的失败分析 Markdown
```

---

## 12. Web 决策中心

QP 的 Web 端是**一个进程、一个端口（默认 8080）、两套界面**：

| 界面 | 地址 | 技术栈 |
|------|------|--------|
| 页面式（旧） | `http://localhost:8080/` | Jinja2 + HTMX |
| SPA 原型（新） | `http://localhost:8080/proto/` | Vue 3 + ECharts + Tailwind，读 `/api/v1/*` |

> ⚠️ **不是「只读」界面**：`POST /review/{id}`（旧界面）/ `POST /api/v1/decisions/{id}/review`（SPA）的 `approve` 默认 `create_positions=True` — 按决策包 SELL 平仓 + BUY 建仓，真实写入 `data/positions` 与 account。
> `/execute` 与 `/close` 只做状态流转（`APPROVED → PARTIALLY_EXECUTED → MONITORING → CLOSED`）。券商侧的真实下单仍由人工完成。

### 12.1 手动启动

```bash
uv run qp web start
```

打开浏览器访问 **http://localhost:8080**。

启动选项：

```bash
# 指定端口和绑定地址
uv run qp web start --port 9000 --host 127.0.0.1

# 开发模式（代码变更自动重载）
uv run qp web start --reload
```

> 默认绑定 `0.0.0.0:8080`（监听所有网络接口），日志中会显示 `http://localhost:8080`。

### 12.2 开机自启（systemd 用户服务）

Web 服务通过 systemd 用户服务实现开机自启，无需 root 权限。

**服务文件**：`~/.config/systemd/user/qp-web.service`

```ini
[Unit]
Description=QP Decision Center Web Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/shuai/workspace/qt
ExecStart=/home/shuai/.local/bin/uv run qp web start --reload
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure
RestartSec=5
Environment="PATH=/home/shuai/.local/bin:/usr/local/bin:/usr/bin:/bin"
StandardOutput=journal
StandardError=journal
SyslogIdentifier=qp-web

[Install]
WantedBy=default.target
```

**启用与日常管理**：

```bash
# 开启 linger（允许未登录时启动用户服务，只需执行一次）
loginctl enable-linger $USER

# 启用并启动服务
systemctl --user daemon-reload
systemctl --user enable qp-web.service
systemctl --user start qp-web.service

# 查看状态
systemctl --user status qp-web

# 重启 / 停止
systemctl --user restart qp-web
systemctl --user stop qp-web

# 查看日志
journalctl --user -u qp-web -f
```

**关键特性**：
- 开机自动启动，无需登录
- 崩溃后 5 秒自动重启（`Restart=on-failure`）
- 日志写入 systemd journal，`journalctl --user -u qp-web` 查看

### 12.3 个股K线分析

在 Web 界面中查看任意 A 股的历史 K 线图（蜡烛图），包含均线叠加和成交量。

**访问路径**：导航栏点击「个股K线 Stocks」，或直接访问 `http://localhost:8080/stocks`。

**搜索股票**：
- 在搜索框输入股票代码（如 `600519`）或股票名称（如 `茅台`）
- 支持 HTMX 实时搜索，输入即搜
- 匹配 3000+ A 股股票

**K线图表功能**：
- 专业蜡烛图（红涨绿跌），ECharts 渲染
- 均线叠加：MA5（粉）、MA10（橙）、MA20（紫）、MA60（灰）
- 成交量柱状图（红涨绿跌），位于 K 线图下方
- 时间范围切换按钮：3M / 6M / 1Y / 2Y / All
- 鼠标滚轮缩放、拖拽平移
- 底部滑块选择时间区间

**页面信息**：
- 最新价、涨跌幅
- 开盘 / 最高 / 最低 / 成交量
- 最新交易日、历史数据天数

**API 接口**：

| 路由 | 说明 |
|------|------|
| `GET /stocks` | 股票搜索页，支持 `?q=` 参数 |
| `GET /stocks/{code}` | 个股 K 线详情页 |
| `GET /api/stocks/{code}/kline?days=365` | JSON API，返回 OHLCV 数组 |

示例：`curl http://localhost:8080/api/stocks/600519/kline?days=90`

### 12.4 SPA 原型界面（/proto/）

新版界面是 Vue 3 SPA，构建产物在 `qp/web/static/spa`，由 FastAPI 挂载到 `/proto`（`qp/web/app.py:30-80`，含 history 路由 fallback + 目录穿越防护）。前端源码就在本仓库 `qp/web/spa_src/`。

**构建 / 部署**：

```bash
cd qp/web/spa_src && npm install   # 首次
bash scripts/spa_deploy.sh         # build（base=/proto/）→ 拷贝 dist → qp/web/static/spa
```

> 构建产物更新后需重启 `qp-web`（`--reload` 模式会自动重载）。

**开发模式**（Vite :5173，`/api` 反代到 127.0.0.1:8080）：

```bash
cd qp/web/spa_src && npm run dev
```

**访问**：`http://localhost:8080/proto/`（12 页路由见 §13「Web 页面」表）

**后端 JSON 端点**：`/api/v1/*`，共 27 个路由（`qp/web/routers/api_v1.py`），含 `/api/v1/industry-heat`、`/api/v1/health`、`/api/v1/positions`、`/api/v1/decisions/{id}`、`/api/v1/system-health`、`/api/v1/stocks/search`、`/api/v1/knowledge` 等；写操作只有决策包 review / execute / close 三个 POST。

---

## 13. 全命令速查表

### 系统

| 命令 | 说明 |
|------|------|
| `qp version` | 显示版本号 |
| `qp doctor` | 环境诊断 |
| `qp --help` | 帮助信息 |
| `qp web start [--port] [--host] [--reload]` | 启动 Web 决策中心（页面式 `/` + SPA `/proto/`） |
| `qp pipeline list` | 列出已注册管道（data_ingest / fundamental_ingest / feature_compute / daily） |
| `qp scheduler start` | 前台启动调度器（⚠️ 仅调试用；生产由 systemd 管理，勿起第二实例） |

### Web 页面

| 路由 | 说明 |
|------|------|
| `/` | 驾驶舱首页 |
| `/health` | 系统健康监控 |
| `/health/factors` | 因子健康详情 |
| `/health/strategies` | 策略健康列表 |
| `/strategies` | 策略管理 |
| `/portfolio` | 投资组合概览 |
| `/decisions` | 决策记录 |
| `/simulation` | 影子运行 |
| `/experiments` | 实验追踪 |
| `/models` | 模型注册 |
| `/proposals` | 审批提案 |
| `/stocks` | 个股K线分析 |
| `/stocks/{code}` | 个股K线详情 |
| `/paper` | 模拟盘状态 |
| `/api/stocks/{code}/kline?days=N` | K线 JSON API |

SPA 原型（`/proto/`，Vue 3，数据走 `/api/v1/*`）12 页路由：

| 路径 | 页面 |
|------|------|
| `/proto/` | 总览 |
| `/proto/industry` | 行业热度 |
| `/proto/paper` | 模拟盘 |
| `/proto/positions` | 持仓 |
| `/proto/chart` | 行情 |
| `/proto/strategies` | 策略 |
| `/proto/factors` | 因子 |
| `/proto/decisions` | 决策 |
| `/proto/experiments` | 回测 |
| `/proto/simulation` | 影子 |
| `/proto/monitor` | 监控 |
| `/proto/knowledge` | 复盘 |

### 数据

| 命令 | 说明 |
|------|------|
| `qp data fetch [--start=] [--end=] [--batch=] [--skip-etl]` | 全量主板数据拉取（腾讯源，不复权） |
| `qp data index` | 拉取沪深300 指数日线（市场过滤/状态检测用） |
| `qp capital-flow` | 拉取资金流数据（主力净流入/北向持股） |
| `qp fundamental` | 拉取基本面数据 |
| `qp industry heat [--date] [--window] [--granularity] [--source] [--top]` | 行业热度榜（行情口径 涨幅/成交额/上涨占比；资金流口径 主力净流入） |
| `qp ingest [start] [end] [--demo]` | 数据摄入（支持 Demo） |
| `qp run daily [--demo]` | 端到端每日管道 |
| `qp lineage snapshot` | 生成数据血缘图（写 `data/metadata/lineage_graph.json`） |

### 实验与研究

| 命令 | 说明 |
|------|------|
| `qp experiment run multifactor [选项]` | 多因子实验（线性加权 / ML） |
| `qp experiment run multifactor --resume <id>` | 从快照复现实验 |
| `qp experiment run multifactor --compare` | 批量策略对比 |
| `qp experiment list` | 列出所有实验 |
| `qp experiment show <id>` | 实验详情 |
| `qp experiment compare` | 对比最近实验 |
| `qp experiment validate <id>` | 验证指定实验 |
| `qp experiment clean --keep 20` | 清理旧实验 |
| `qp experiment optuna` | Optuna 超参搜索（LambdaRank，TDR-005） |
| `qp model list` | 列出模型 |
| `qp model show <id>` | 模型详情 |
| `qp retrain [strategy] [--dry-run]` | 模型重训 |

### 因子

| 命令 | 说明 |
|------|------|
| `qp factor list` | 因子健康总览（生命周期/IC/IR/衰减） |
| `qp factor health [name]` | 单因子健康详情或总览 |
| `qp factor report <name>` | 因子研究报告（markdown） |
| `qp factor update-health` | 全量重算因子健康（数据修复后使用） |
| `qp factor validate <name> --persist` | 单因子验证（可持久化到 factor_health.parquet） |
| `qp factor compute` | 计算每日因子值 → factor_values_daily.parquet |
| `qp factor catalog` | 因子目录（按类别分组） |
| `qp factor register` | 注册所有 BaseFeature 到因子注册表 |

### 策略生命周期

| 命令 | 说明 |
|------|------|
| `qp strategy list` | 列出所有策略 |
| `qp strategy approve <id>` | 批准策略上线（冻结不可变快照） |
| `qp strategy approved list` / `show <id>` | 已批准策略快照列表 / 详情（ADR-031） |
| `qp strategy deactivate <id>` | 下线策略 |
| `qp proposal create --strategy <id> --target <stage>` | 创建策略审批提案 |
| `qp proposal list` | 列出所有提案 |
| `qp proposal show <id>` | 查看提案详情 |
| `qp proposal approve <id>` | 批准提案 |
| `qp proposal reject <id>` | 驳回提案 |
| `qp proposal withdraw <id>` | 撤回提案 |

### 组合

| 命令 | 说明 |
|------|------|
| `qp portfolio report` | KPI 仪表盘 |
| `qp portfolio risk` | 风控分析 |

### 持仓

| 命令 | 说明 |
|------|------|
| `qp position list` | 当前持仓列表 |
| `qp position show <symbol>` | 单只持仓详情 |
| `qp position pnl` | 持仓盈亏 |
| `qp position history` | 持仓历史 |
| `qp position close <symbol>` | 平仓 |

### 模拟交易

| 命令 | 说明 |
|------|------|
| `qp paper start [strategy]` | 启动 30 天模拟交易 |
| `qp paper status [strategy]` | 模拟交易状态 |
| `qp simulation shadow` | 影子组合绩效摘要 |
| `qp simulation shadow <YYYY-MM-DD>` | 跑指定日期的影子模拟（该日需已有决策包） |

### 决策

| 命令 | 说明 |
|------|------|
| `qp decide` | 加载今天的决策包 |
| `qp decide --force` | 重跑管道生成新决策包 |
| `qp decide --review` | 交互式人工审核 |
| `qp decide --history` | 列出历史决策 |
| `qp decide --show <id>` | 查看指定决策包 |

### 监控

| 命令 | 说明 |
|------|------|
| `qp monitor check` | KillSwitchPipeline 全扫描 |
| `qp monitor regime` | 市场状态检测 |
| `qp monitor alert-test` | 告警通道测试 |

### 知识库

| 命令 | 说明 |
|------|------|
| `qp knowledge stats` | 知识库统计 |
| `qp knowledge search <query>` | 全文搜索 |

### 调度（systemd）

| 命令 | 说明 |
|------|------|
| `bash deploy/install-systemd.sh` | 一键安装/修复（幂等，推荐） |
| `bash deploy/install-systemd.sh --check` | 干跑检查状态 |
| `systemctl --user start qp-scheduler` | 启动调度器 |
| `systemctl --user status qp-scheduler` | 查看服务状态 |
| `journalctl --user -u qp-scheduler -f` | 实时日志 |

---

## 14. 典型工作流

### 自动化（推荐：systemd 常驻）

```
# 一键部署（幂等，删除系统级副本 + 装用户级 + 验证单实例）
bash deploy/install-systemd.sh

  09:07 → monitor_check    KillSwitchPipeline 全扫描
  09:17 → retrain_notify   重训信号检查
  16:53 → pre_close_check  收盘前二次确认
  18:00 → daily_pipeline   产出 DecisionPackage（含因子健康增量更新）
  18:30 → email_report     邮件日报
  18:32 → paper_trading    模拟盘推进

  → factor_health / factor_ic_series  每日自动更新
  → system_health_log  每日自动写入
  → system_state       跨 Pipeline 状态同步
  → watchdog ping      每个 Job 执行留痕
  → 异常自动归档       KnowledgeArchive
  → retrain signal     需要重训时自动生成信号

# 每天只需一次人工审核：
  qp decide --review        → 审核决策包，确认是否执行
```

### 日常操作（手动）

```
每天早上:
  qp monitor check          → 检查系统安全
  qp monitor regime         → 确认市场状态

收盘后:
  qp decide                 → 加载今天的决策包
  qp decide --review        → 人工审核决策包
  → 手动下单
```

### 策略研发

```
第一步: 因子研究
  qp data fetch --start=2020-01-01
  qp experiment run multifactor --strategy momentum_vol_full --start 2024-01-01

第二步: 验证
  qp experiment validate <id>        → 对实验跑质量 Gate
  qp validate --stage backtest_passed

第三步: 模拟交易
  qp paper start <strategy_id>   → 需已注册的策略（如 lvr_vol_only）
  qp paper status                → 每天检查进度

第四步: 上线
  30 天通过后 → 策略生命周期自动流转到 Production
```

### 月度维护

```
月初:
  qp retrain --dry-run                    → 演习（目标=registry 唯一 APPROVED）
  qp retrain                              → 正式重训
  qp portfolio report                     → 组合 KPI 报告
  qp portfolio risk                       → 风控复查
  qp knowledge stats                      → 知识库回顾
```

### 新策略上线全流程

```
1. 在 qp/strategy/strategies/ 创建策略文件
2. 在 qp/strategy/config.py 注册配置
3. qp validate --stage research            → 研究阶段验证
4. qp experiment run multifactor           → 回测验证
5. qp validate --stage backtest_passed     → 回测门禁
6. qp paper start <strategy>               → 30 天模拟交易
7. qp paper status <strategy>              → 每日检查
8. 通过后自动流转至 Shadow → Production
```

---

## 15. 配置说明

配置文件优先级：**CLI 参数 > 环境变量 > config.toml > 默认值**

### 15.1 配置文件

从模板复制：
```bash
cp config.toml.example config.toml
```

### 15.2 关键配置项

```toml
[project]
name = "qp"

[storage]
backend = "duckdb"                       # duckdb | sqlite
duckdb_path = "data/qp.duckdb"
parquet_dir = "data/parquet"
raw_dir = "data/raw"
dataset_dir = "data/dataset"

[logging]
level = "INFO"                           # DEBUG | INFO | WARNING | ERROR
format = "colored"                       # colored | json

[scheduler]
timezone = "Asia/Shanghai"

[data]
default_start_date = "2015-01-01"
default_source = "akshare"
cache_enabled = true
cache_ttl_hours = 24

[model]
default_algorithm = "lightgbm"
objective = "lambdarank"
purged_cv_folds = 5
min_training_window_days = 500

[backtest]
default_slippage_pct = 0.001
commission_pct = 0.00025
stamp_tax_pct = 0.0005
adv_limit_pct = 0.10

[monitoring]
psi_threshold = 0.25                     # PSI 熔断阈值（§7.1）
max_drawdown_strategy_ratio = 1.5        # 回撤 > 历史最大 ×1.5
monthly_drawdown_limit = 0.15            # 月回撤 15%
rolling_60d_drawdown_limit = 0.20        # 60 日回撤 20%
consecutive_loss_days = 15               # 配置项（ConsecutiveLoss 触发器实际硬编码 5 日，见 §7.1）
model_decay_ic_ratio = 0.30              # IC 衰减至训练 IC 的 30%

[broker]
provider = "simulated"

[runtime]
env = "development"                      # development | production
```

> 上面每一行都取自仓库里的 `config.toml.example` / `qp/platform/config/models.py`（2026-09-25 核对）。
> `max_drawdown_strategy_ratio` 曾在本指南里被写成不存在的 `max_drawdown_ratio`，`model_decay_ic_ratio` 曾写成 `0.5`。

### 15.3 环境变量

```bash
export QP_ENV=production
export QP_DATA_CACHE_DIR=/path/to/cache
export QP_DUCKDB_PATH=data/quant.duckdb

# 密钥类配置（只能用环境变量）
export TENCENT_API_KEY=xxx
export AKSHARE_TOKEN=xxx
export TELEGRAM_BOT_TOKEN=xxx
```

---

## 16. 项目架构

### 16.1 十二层架构

```
Layer 1:  platform/     — 运行时基础（配置、日志、CLI、调度、存储、管道）
Layer 2:  data/         — 数据产品（适配器 → 清洗 → 校验 → 数据集）
Layer 3:  research/     — 研究层（特征、因子、模型、PurgedKFold、实验追踪）
Layer 4:  validation/   — 验证门禁（IC 检查、过拟合检查、回测检查）
Layer 5:  strategy/     — 策略引擎（信号生成、多策略融合、生命周期管理）
Layer 6:  portfolio/    — 组合风控（风险模型、成本模型、资金分配、仓位优化）
Layer 7:  simulation/   — 模拟层（模拟券商、滑点模型、回测引擎）
Layer 8:  decision/     — 决策层（交易建议、决策报告、人工审计）
Layer 9:  monitoring/   — 监控层（熔断、漂移、衰减、市场状态、告警、SystemState）
Layer 10: knowledge/    — 知识库（复盘、实验总结、失败分析、闭环反哺）
Layer 11: (monitoring)  — 系统状态机、RetrainSignal、Watchdog
Layer 12: (knowledge)   — 策略版本树、失败聚类分析、黑名单规则生成
```

### 16.2 目录结构

```
qp/
├── platform/          # Layer 1: 运行时
│   ├── cli/           # CLI 入口（单入口 qp）
│   ├── config/        # 配置系统
│   ├── logging/       # 日志系统
│   ├── scheduler/     # 任务调度
│   ├── storage/       # 存储工厂
│   └── pipeline/      # 管道引擎
├── data/              # Layer 2: 数据层
│   ├── adapter/       # 数据适配器（腾讯/AKShare/Demo）
│   ├── loader/        # FullDataPipeline
│   └── universe/      # 股票池
├── research/          # Layer 3: 研究层
│   ├── split/         # PurgedKFold
│   ├── trainer/       # LightGBM、自动重训、模型注册
│   └── importance/    # 特征重要性
├── validation/        # Layer 4: 验证门禁
├── strategy/          # Layer 5: 策略引擎
│   ├── strategies/    # 具体策略实现
│   └── config.py      # 策略配置注册中心
├── portfolio/         # Layer 6: 组合风控
├── simulation/        # Layer 7: 模拟层
├── decision/          # Layer 8: 决策层
├── monitoring/        # Layer 9: 监控层
├── knowledge/         # Layer 10: 知识库
├── pipeline/          # 业务管道（DailyPipeline, MultiFactorPipeline）
└── shared/            # 共享模块（协议、类型、常量、异常）
```

### 16.3 核心设计原则

- **决策辅助系统**，非自动交易 — 系统产出建议，人执行决策
- **混合架构** — DataFrame 管道做数据/研究，Domain Model 做组合/决策
- **一切皆管道** — `BasePipeline.run(context) → PipelineResult`
- **数据产品隔离** — 消费者不知道原始数据源
- **PurgedKFold 强制** — 所有模型必须用 Purged Walk-Forward CV
- **单入口 CLI** — 所有操作通过 `qp` 命令
- **禁止** `print()`、裸 `except:`、`utils/` 目录

### 16.4 当前策略

当前 `data/strategy_registry.json` 全量（10 个，2026-10-08 实读）：

| 策略 | lifecycle | active | approved 快照 |
|------|-----------|--------|----------------|
| `momentum_vol_full` | backtest_passed | false | ✅ v20260811（2026-08-12 by Wei，保留供审计） |
| `lvr_vol_only` | approved | ✅ true | ✅ v20261008（2026-10-08 by Wei） |
| `lvr_vol_mom1m` | research | false | — |
| `momentum_v1.0` | research | false | — |
| `momentum_vol_mf` | research | false | — |
| `mvf_noorth` | research | false | — |
| `mvf_v2_amount` | research | false | — |
| `mvf_v2_expansion` | research | false | — |
| `quality_v1.0` | research | false | — |
| `value_v1.0` | research | false | — |

**生产唯一 active 策略：`lvr_vol_only`**（低波单因子）—— 2026-10-08 由 `momentum_vol_full` 换入。

生产权重取 **approved 冻结快照**（`registry.get_approved()`），不是 meta 里那套旧值 —— `daily_pipeline.py:496-512` 明确读快照，理由见 ADR-031：

| 因子 | 权重（approved 冻结快照 v20261008） |
|------|--------------------------|
| Volatility_20D | +1.00（低波异象） |

> **切换依据**（2026-10-08 同口径对照，2024-01-01→2026-07-01 / Top10 / rebalance 20d / n_days=602）：
> `lvr_vol_only` IC 0.0518 / Sharpe 1.47 / MaxDD 8.77% / 超额 +67.88%（实验 `multifactor_20261007_230557`，
> 即 v20261008 快照的指标来源）vs `momentum_vol_full` IC 0.0690 / Sharpe 0.60 / MaxDD 19.22% / 超额 -1.68%
> （实验 `multifactor_20261007_231048`，与 2026-09-26 那次逐位一致 → 基线可复现）。
> 代价：IC 更低、集中度更高（单因子）。
> `momentum_vol_full` 的 v20260811 快照保留供审计（lifecycle=backtest_passed、active=false）。
> ⚠️ 反向复归要重新 `qp strategy approve`，而 `approve()` 从 `meta.weights` 重建快照 ——
> 届时冻结的会是 v20260814 那套（-0.2331 / +0.1823 / …），**不是**原 v20260811（-0.25 / +0.22 / …）。
> 要精确回滚请用 git 恢复 `data/strategy_registry.json`。

> ⚠️ 快照里的 `parameters` 字段（`orthogonalize` / `top_n` / `rebalance` / `anti_chase`）在日线生产链路里是**惰性字段**：`daily_pipeline` 只取 `weights` + `industry_neutral`（`compute_today_scores_full()` 没有正交化入参）。所以生产日线**不做** VIF 正交化 / 防追高 / 自定义调仓周期，无论快照或 `strategy/config.py` 里怎么写 —— `lvr_vol_only`（config `orthogonalize=True`）与此前的 `momentum_vol_full`（config `orthogonalize=False`，2026-08-13 关闭）都是如此。改快照里这几个字段对生产无影响。

> 策略选择逻辑（`daily_pipeline.py:459-477`，ADR-031 Policy A）：**只跑 lifecycle==APPROVED 的策略**；没有 APPROVED 就跳过当日策略执行并报警，**不退回 research、不兜底 hardcode**。

**代码注册但未进 registry 的策略配置：** `alpha_multi_factor_v1`（12 因子）、`alpha_multi_factor_v2`（14 因子反转版），及 `alpha_ensemble_v2` / `alpha_ensemble_v3` / `lvr_vol_stable` / `low_vol_reversal` 等（`qp/strategy/strategies/`）。

---

## 17. 开发命令

```bash
# 代码格式化
uv run ruff format

# Lint 检查
uv run ruff check

# 类型检查
uv run pyright

# 运行测试
uv run pytest                              # 全部
uv run pytest tests/unit/path/to/test.py   # 单个文件
uv run pytest -x -q                        # 快速模式
```

---

## 18. 故障排查

### 已知问题与注意事项（2026-09-25）

| 现象 | 原因 | 现状 |
|------|------|------|
| 同时存在 systemd `qp-scheduler` 和手动 `qp scheduler start` → 定时 Job 跑两遍 | 两套调度器并存（2026-08-18 email_report 双发邮件的成因） | 生产只用 systemd；`install-systemd.sh` 会校验进程恰为 1 |

### 数据文件不存在

```bash
# 大多数命令依赖 data/dataset/ 下的 Parquet 文件
# 先运行数据管道：
uv run qp run daily --demo
```

### 配置文件缺失

```bash
cp config.toml.example config.toml
# 编辑 config.toml 中的路径和参数
```

### 模型列表为空

```bash
# 运行一次实验即可自动注册模型
uv run qp experiment run multifactor --model --start 2024-01-01 --end 2026-07-01
```

---

*关联文档：`docs/constitution/constitution-v4.2.md` | `CLAUDE.md`*
