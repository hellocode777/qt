# QP (Quant Platform) 用户指南

> 个人量化研究与投资决策操作系统
> 更新日期：2026-08-10

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
| 买入时间 | 仅调仓日（每月前 5 个自然日） |
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
| **每月 1-5 号**（调仓日） | ✅ 完整调仓 | 买入新标的 + 风控退出 + 行业调整 |
| **其他日期** | ⚠️ 仅风控 | 只执行 Risk Exit / Rank Exit / 止损，不买入 |

**示例**：
- 7 月 1-5 日 → 调仓日，可能买入新股票
- 7 月 6-31 日 → 非调仓日，只检查持仓是否需要风控退出

调仓日逻辑见 `qp/pipeline/daily_pipeline.py:275`：
```python
is_rebalance_day = today.day <= 5
```

> **为什么？** 每月集中调仓一次，减少频繁交易带来的冲击成本和印花税损耗。月中只做风控止损，让 Alpha 有足够时间发酵。

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
| `--industry-neutral` | 行业中性化 | 关闭 |
| `--orthogonalize` | 因子正交化 | 关闭 |
| `--skip-gate` | 跳过验证门禁 | 关闭 |
| `--symbols <codes>` | 自定义股票池 | 全部主板 |
| `--dataset <name>` | 数据集名称 | `daily_price_main` |
| `--resume <id>` | 从快照复现实验（权重冻结） | — |
| `--score-band auto` | 自动搜索最优分位区间 | — |
| `--debug` | 启用 DEBUG 日志 | 关闭 |

### 5.3 影子模拟（Shadow Trading）

```bash
# 运行今日影子模拟
uv run qp simulation shadow run

# 查看影子组合绩效
uv run qp simulation shadow summary
```

影子模拟与实盘持仓同步，用于在不影响实盘的情况下评估策略调整。

### 5.4 验证门禁

```bash
uv run qp validate                             # 全阶段检查
uv run qp validate --stage backtest_passed      # 指定阶段
uv run qp validate --strategy-id simple_rank_v1.0  # 指定策略
uv run qp validate --json                       # 机器可读输出
```

可用阶段：`research` | `backtest_passed` | `paper_trading` | `shadow_production` | `production`

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

### 7.4 市场状态检测

```bash
uv run qp monitor regime
```

### 7.5 告警通道测试

```bash
uv run qp monitor alert-test
```

支持 6 种告警通道：Terminal / Log / Telegram / 钉钉 / 企业微信 / Email。

---

## 8. 模型管理

```bash
# 列出所有已注册模型
uv run qp model list

# 查看模型详情
uv run qp model show lgb_lambdarank_v20260722

# 模型重训（建议先用 --dry-run）
uv run qp retrain simple_rank_v1.0 --dry-run
uv run qp retrain simple_rank_v1.0
```

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
uv run qp paper start simple_rank_v1.0

# 查看进度
uv run qp paper status simple_rank_v1.0
```

输出示例：
```
═══ QP 模拟交易状态 / Paper Trading Status ═══
  策略 / Strategy:    simple_rank_v1.0
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

四个定时任务串起来，构成完整的**每日投资决策自动化闭环**：

```
08:00  data_fetch        拉取行情 + 基本面数据
         │                  ├─ AkShare/Tushare → Raw → Bronze → Silver → Gold
         │                  └─ 写入 data/dataset/
         │
09:07  monitor_check     全维度安全扫描
         │                  ├─ Market Regime (8 种状态, 含流动性危机/风格切换)
         │                  ├─ 7 个熔断触发器 (回撤/PSI/连续亏损/异常换手/模型衰减)
         │                  ├─ PSI 特征漂移
         │                  ├─ Model Decay (IC 衰减检测)
         │                  └─ Strategy Health (0-100 评分)
         │                  ├─ → system_health_log.parquet
         │                  ├─ → system_state 状态机更新
         │                  ├─ → 异常自动归档 KnowledgeArchive
         │                  └─ → 触发 retrain signal (如需重训)
         │
16:53  pre_close_check   收盘前二次确认
         │                  └─ 快速 KillSwitchPipeline (同上)
         │
17:57  daily_pipeline    策略决策
         │                  ├─ Step 0: 读取 SystemState (PAUSED+ 自动跳过)
         │                  ├─ 数据摄入 → 特征计算 → 策略发现 → 验证门禁
         │                  ├─ 策略执行 → 信号融合 → 风控过滤 → 成本估算
         │                  ├─ 资金分配 → DecisionPackage
         │                  └─ data/decisions/dp-2026-07-25-xxx.json
         │                     data/decisions/trade_decision_audit.parquet (T2)
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

```bash
# 启动
sudo systemctl start qp-scheduler

# 开机自启
sudo systemctl enable qp-scheduler

# 停止
sudo systemctl stop qp-scheduler

# 重启（代码更新后）
sudo systemctl daemon-reload
sudo systemctl restart qp-scheduler

# 查看状态
systemctl status qp-scheduler

# Scheduler 自身日志
tail -f logs/scheduler.log
journalctl -u qp-scheduler -f

# 各 Job 独立日志（按日期分目录）
tail -f logs/$(date +%F)/monitor_check.log
tail -f logs/$(date +%F)/retrain_notify.log
tail -f logs/$(date +%F)/pre_close_check.log
tail -f logs/$(date +%F)/daily_pipeline.log
tail -f logs/$(date +%F)/email_report.log
```

> 每个 Job 写入当天日期子目录，每天一个新文件，自动清理 7 天前的旧目录。

### 11.2 五任务时间表

| 时间 | Job | 执行内容 | watchdog |
|------|-----|----------|----------|
| 09:07 | `monitor_check` | KillSwitchPipeline 全扫描 + SystemState + RetrainSignal 消费 | `data/monitoring/watchdog/monitor_check.ping` |
| 09:17 | `retrain_notify` | 检查重训练信号，发邮件提醒 | `data/monitoring/watchdog/retrain_notify.ping` |
| 16:53 | `pre_close_check` | KillSwitchPipeline 收盘前二次确认 | `data/monitoring/watchdog/pre_close_check.ping` |
| 18:00 | `daily_pipeline` | DailyPipeline: 数据→特征→策略→风控→DecisionPackage | `data/monitoring/watchdog/daily_pipeline.ping` |
| 18:30 | `email_report` | 发送今日 DecisionPackage 邮件 | `data/monitoring/watchdog/email_report.ping` |

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
│   └── email_report.log             # Job 5

data/
├── monitoring/
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

QP 提供一个只读的 Web 仪表盘，用于可视化投资决策、持仓和监控状态。

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

---

## 13. 全命令速查表

### 系统

| 命令 | 说明 |
|------|------|
| `qp version` | 显示版本号 |
| `qp doctor` | 环境诊断 |
| `qp --help` | 帮助信息 |
| `qp web start [--port] [--host] [--reload]` | 启动 Web 决策中心 |
| `qp pipeline list` | 列出已注册管道 |
| `qp scheduler start` | 启动后台定时调度器 |

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

### 数据

| 命令 | 说明 |
|------|------|
| `qp data fetch [--start=] [--end=] [--batch=] [--skip-etl]` | 全量主板数据拉取 |
| `qp fundamental` | 拉取基本面数据 |
| `qp ingest [start] [end] [--demo]` | 数据摄入（支持 Demo） |
| `qp run daily [--demo]` | 端到端每日管道 |

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
| `qp model list` | 列出模型 |
| `qp model show <id>` | 模型详情 |
| `qp retrain [strategy] [--dry-run]` | 模型重训 |

### 策略生命周期

| 命令 | 说明 |
|------|------|
| `qp strategy list` | 列出所有策略 |
| `qp strategy approve <id>` | 批准策略上线 |
| `qp strategy deactivate <id>` | 下线策略 |
| `qp proposal create --strategy <id> --target <stage>` | 创建策略审批提案 |
| `qp proposal list` | 列出所有提案 |
| `qp proposal show <id>` | 查看提案详情 |
| `qp proposal approve <id>` | 批准提案 |
| `qp proposal reject <id>` | 驳回提案 |

### 组合

| 命令 | 说明 |
|------|------|
| `qp portfolio report` | KPI 仪表盘 |
| `qp portfolio risk` | 风控分析 |

### 模拟交易

| 命令 | 说明 |
|------|------|
| `qp paper start [strategy]` | 启动 30 天模拟交易 |
| `qp paper status [strategy]` | 模拟交易状态 |
| `qp simulation shadow run` | 运行影子模拟 |
| `qp simulation shadow summary` | 影子组合绩效摘要 |

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
| `systemctl start qp-scheduler` | 启动调度器 |
| `systemctl status qp-scheduler` | 查看服务状态 |
| `journalctl -u qp-scheduler -f` | 实时日志 |

---

## 14. 典型工作流

### 自动化（推荐：systemd 常驻）

```
sudo systemctl start qp-scheduler   # 启动（已配置开机自启）

  08:00 → data_fetch       自动拉取行情+基本面
  09:07 → monitor_check    KillSwitchPipeline 全扫描
  16:53 → pre_close_check  收盘前二次确认
  17:57 → daily_pipeline   产出 DecisionPackage

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
  qp validate --stage backtest_passed
  qp backtest run simple_rank_v1.0

第三步: 模拟交易
  qp paper start simple_rank_v1.0
  qp paper status           → 每天检查进度

第四步: 上线
  30 天通过后 → 策略生命周期自动流转到 Production
```

### 月度维护

```
月初:
  qp retrain simple_rank_v1.0 --dry-run   → 演习
  qp retrain simple_rank_v1.0             → 正式重训
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

### 14.1 配置文件

从模板复制：
```bash
cp config.toml.example config.toml
```

### 14.2 关键配置项

```toml
[runtime]
env = "development"                      # development | production

[storage]
backend = "duckdb"                       # duckdb | sqlite
duckdb_path = "data/quant.duckdb"

[logging]
level = "INFO"                           # DEBUG | INFO | WARNING | ERROR
format = "colored"                       # colored | json

[scheduler]
timezone = "Asia/Shanghai"

[data]
default_source = "akshare"
default_start_date = "2020-01-01"

[model]
default_model = "LightGBM"
default_objective = "lambdarank"
cv_folds = 5
purge_days = 20
embargo_days = 5

[backtest]
slippage = 0.001
commission = 0.0003
stamp_tax = 0.001

[monitoring]
psi_threshold = 0.25
max_drawdown_ratio = 11.5
model_decay_ic_ratio = 0.5

[broker]
provider = "simulated"
```

### 14.3 环境变量

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

### 15.1 十二层架构

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

### 15.2 目录结构

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

### 15.3 核心设计原则

- **决策辅助系统**，非自动交易 — 系统产出建议，人执行决策
- **混合架构** — DataFrame 管道做数据/研究，Domain Model 做组合/决策
- **一切皆管道** — `BasePipeline.run(context) → PipelineResult`
- **数据产品隔离** — 消费者不知道原始数据源
- **PurgedKFold 强制** — 所有模型必须用 Purged Walk-Forward CV
- **单入口 CLI** — 所有操作通过 `qp` 命令
- **禁止** `print()`、裸 `except:`、`utils/` 目录

### 15.4 当前策略

| 策略 | ID | 类型 |
|------|-----|------|
| SimpleRank | `simple_rank_v1.0` | 单因子排序 |
| Momentum | `momentum_v1.0` | 动量策略 |
| Value | `value_v1.0` | 价值策略 |
| Quality | `quality_v1.0` | 质量策略 |
| Momentum+Vol | `momentum_vol_full` | 5 因子反转 |
| **Alpha多因子 v1** | `alpha_multi_factor_v1` | **12 因子多因子** |
| **Alpha多因子 v2** | `alpha_multi_factor_v2` | **14 因子反转版** |

`alpha_multi_factor_v2` 是目前的主力策略，包含 5 组 14 因子：

| 组 | 权重 | 因子 |
|------|------|------|
| Short-term Reversal | 25% | Short_Term_Reversal_5D, Momentum_1M, Momentum_3M |
| Value Reversal | 25% | Earnings_Yield, PB, PCF_OCF |
| Quality | 20% | ROE, Profit_Stability, Cash_Quality |
| Low Risk | 15% | Volatility_60D, MaxDD_60D |
| Liquidity | 15% | Volume_Expansion_20_120, Amount_Momentum_20_120 |

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
