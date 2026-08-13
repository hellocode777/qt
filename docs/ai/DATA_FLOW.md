# DATA_FLOW — QP 数据流地图（数据从哪来 → 到哪去）

> 用途：给 AI 回答"某个数据/指标怎么来的、去哪了、落盘在哪"的问题。
> 核心原则：**data/ 只对外暴露 Data Product（Dataset），消费方不碰原始源**（ADR-013/015/017）。

## 数据生命周期（Raw → Bronze → Silver → Gold → 下游）

```
AkShare（数据源，封装在 qp/data/adapter/）
  │  qp data fetch / qp ingest / qp fundamental
  ▼
data/raw/        原始数据（不可变、只追加、版本化）      [ADR-014]
  ▼  cleaning（清洗/标准化，qp/data/cleaning/）
data/bronze/     青铜层（清洗后）
  ▼
data/silver/     白银层（标准化/去重/对齐交易日）
  ▼  dataset 构建（qp/data/dataset/registry.py）
data/dataset/    ★ Gold Data Product（唯一公开接口）
  │  daily_price_latest.parquet    # 3043 只主板日线（收盘价等）
  │  factor_values_daily.parquet   # 因子值
  │  momentum_20d.parquet / volatility_20d.parquet
  │  registry.json / {name}_{date}.parquet + _metadata.json
  ▼
qp/research/     因子计算（factor_calculator/processor）→ 特征 → 标签 → 模型（LightGBM，Purged KFold）
  ▼  validation gate（qp/validation/，ADR-023/025/031：只放行 APPROVED）
qp/strategy/     信号生成（compute_today_signals → generate_signals）
  ▼  ensemble 融合（等权合成 Step 6 选出的全部 APPROVED 策略信号，N=1 等效直通）
qp/portfolio/    组合构建 + 风控 + 资金分配（ADR-029：risk 归 portfolio）
  ▼
qp/decision/     DecisionPackage → data/decisions/
  ▼
qp/monitoring/   观察 + 熔断 + 健康度（只观察，不决策）[ADR：monitoring 永不 decide]
  ▼
qp/knowledge/    长期记忆（失败归档/决策审计）
```

## 数据产物落盘位置（查数据先找这些）

| 路径 | 内容 | 生产者 |
|---|---|---|
| `data/dataset/*.parquet` | Gold 数据集（消费方唯一入口） | data 层 |
| `data/strategy_registry.json` | 策略注册表（WebUI/实验也会改写！）；`strategies.<id>.approved` = APPROVED 冻结快照 | registry + `qp strategy approve` |
| `data/decisions/` | 每日决策包 | daily_pipeline |
| `data/monitoring/online_signal_history.parquet` | 信号快照（≥5 日才有 rolling_ic） | daily_pipeline Step 10.5 |
| `data/monitoring/retrain_signals.parquet` | 重训信号 | kill_switch_pipeline |
| `data/monitoring/watchdog/{job}.ping` | 任务存活心跳 | scheduler 各 job |
| `data/metadata/lineage_graph.json` | 血缘图 | `qp lineage snapshot` |
| `data/paper_trading/{id}_paper.json` | Paper 状态 | `qp paper start` |
| `data/experiments/` | 实验产物 | `qp experiment run` |
| `data/positions/` `data/portfolio/` `data/proposals/` | 持仓/组合/提案 | 各模块 |
| `logs/{日期}/{job}.log` | 任务日志（7 天清理） | scheduler |

## 外部数据接入

| 源 | 方式 | 注意 |
|---|---|---|
| AkShare | `qp/data/adapter/`（akshare 只在 data 层） | research/strategy 禁止直调 |
| QuantTrading DB | `qp/data/adapter/quant_trading_db_adapter.py` | 直接读 `~/workspace/QuantTrading/data/quant.db`（SQLite） |

## 关键口径（回答数据问题时的"证据锚点"）

- **Dataset = 可信数据产品**；**Data Source = 原始提供方**（术语别混）
- **Signal ≠ Prediction**：Prediction 是模型裸输出，Signal 才可交易
- **Order ≠ Trade**：Order 可被拒，Trade 是成交确认
- **Experiment ≠ Run**：Experiment 是容器，Run 是单次执行
- 原始数据不可变：只追加、不修改（ADR-014）
- 时间戳一律 `Asia/Shanghai`，禁止 UTC（scheduler/monitoring/approve 相关，2026-08-11 修过）

## 数据问题排查顺序（给 AI）

1. 先问：这个数据是谁生产的？（DataFlow 上找生产者）
2. 落盘在哪？（查上表）
3. 生产者读哪个 Dataset？→ DATA_FLOW 上游
4. 最后才怀疑计算逻辑（factor_health 等），用代码证据定位
