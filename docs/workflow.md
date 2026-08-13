# QP 工作流 / Workflow

> 核心工作流的端到端说明：每日运行、开发、策略上线、数据接入、实验。
> 最后更新：2026-08-13

---

## 1. 每日运行工作流（scheduler 自动）

系统通过 systemd 服务 `qp-scheduler.service` 自动运行 5 个工作日 job：

| 时间 | Job | 内容 |
|------|-----|------|
| 09:07 | monitor_check | 熔断开关检查（加载价格数据算 rolling IC，抑制假警报） |
| 09:17 | retrain_notify | 查重训信号并邮件提醒 |
| 16:53 | pre_close_check | 收盘前检查；若熔断 STOP 则跳过 daily pipeline |
| 18:00 | daily_pipeline | 拉数据 → 跑每日管道 → 产出 DecisionPackage |
| 18:30 | email_report | 发邮件「QP 每日投资决策」 |

**daily_pipeline 内部 Step 流**（概要）：

```
fetch data → update pool → factor calc → 选 APPROVED 策略（ADR-031）
  → strategy run → ensemble → portfolio/risk → DecisionPackage
  → monitoring（快照 + rolling IC）→ knowledge（归档）
```

查状态：`qp scheduler status` / `logs/{日期}/{job}.log` / `data/monitoring/watchdog/{job}.ping`

## 2. 开发工作流

### 2.1 环境与质量门

```bash
uv sync --extra dev        # 安装
uv run qp version          # 验证 CLI
uv run qp doctor           # 环境自检
```

每次提交前**必须全部通过**：

```bash
uvx ruff format --check .  # 格式化检查（CI 用最新 ruff，本地也要用 uvx）
uv run ruff check          # Lint 零错误
uv run pyright             # 类型检查零错误
uv run pytest              # 全部测试
```

> ⚠️ 教训：本地 `ruff check` 不查格式；CI 用 `uvx ruff format --check .`，本地必须同步用 uvx，否则 CI 挂。

### 2.2 新增 CLI 命令

1. 在 `qp/platform/cli/commands/<组>.py` 加 handler（`cmd_*`）
2. 在 `qp/platform/cli/parser.py` 注册 click 命令
3. 更新 `docs/ai/COMMAND_MAP.md`
4. 质量门 + 测试

### 2.3 新增策略

1. 在 `qp/strategy/strategies/` 写策略实现
2. 在 `qp/strategy/registry.py` 注册
3. 跑实验验证（见 §5）
4. 过 validation gate → APPROVED（ADR-031）→ 进 daily_pipeline

### 2.4 改代码后的验证

1. 跑质量门（§2.1）
2. **相关** pytest（不是全部，先跑改动模块对应的测试）
3. 能跑的 CLI 命令实际跑一遍验证

## 3. 策略上线工作流（验证 → 生产）

```
策略生命周期（验证"策略能不能上线"）
  Paper Trading（qp paper start，Rule 11，30 天验证）
      │  策略信号，纸面持仓，data/paper_trading/
      ▼
每日决策验证（验证"跟着系统建议做会怎样"）
  Shadow Production（影子运行，daily_pipeline Step 13.1 自动跑）
      │  决策包全自动执行，独立假钱 10 万，data/simulation/
      ▼
真实账户（人工把关的账户账本）
  Portfolio（WebUI approve 后建仓）
      │  人工审核状态机，真实现金账本，data/positions/
      ▼
人工执行交易（系统出建议，人下单）
```

## 4. 数据接入工作流

```
外部源（AkShare / QuantTrading DB）
  → qp/data/adapter/（数据源封装，只允许在这层）
  → data/raw（原始，不可变，只追加）[ADR-014]
  → data/bronze → data/silver（清洗/标准化）
  → data/dataset/*.parquet（Gold Data Product）[ADR-013/015]
  → 下游消费方（research/strategy 等，通过 Dataset 访问）
```

**接入新数据源步骤**：
1. `qp/data/adapter/` 写适配器
2. 清洗管道（`data/cleaning/`）+ 验证（`data/validation/`）
3. 构建 Dataset（`qp/data/dataset/registry.py` 注册）
4. 消费方只读 Dataset，不碰适配器

## 5. 实验工作流

### 5.1 多因子实验

```bash
qp experiment run multifactor --strategy momentum_vol_full --start 2019-01-01 --model
qp experiment compare          # 对比最近实验
qp experiment show <id>        # 查看实验详情
qp experiment validate <id>    # 跑验证门
```

### 5.2 Optuna 超参搜索（TDR-005，默认非启用）

```bash
qp experiment optuna --trials 50 --start 2019-01-01 --max-stocks 500
```

结果存 `data/optuna/lgb_optuna_{ts}.json`，含基线对比。
> ⚠️ 短样本最优参数勿直接写死进生产 — 先用完整 walk-forward 回测验证（rule.md §7.9）。

### 5.3 因子健康度检查（做研究前先看这个）

```bash
qp factor health            # 28 因子健康总览（production/weakening/degraded）
qp monitor check            # 熔断/漂移/模型衰减
qp factor report            # 生成 markdown 研究报告
```

**研究前必查**：因子是否 degraded/weakening？IC 趋势是否转负？（2026-08-13 实测：10 因子中 9 个近期失效，只有 Volatility_20D 健康——调参前先看健康度。）

## 6. 决策与监控工作流

```
daily_pipeline → DecisionPackage → data/decisions/
  → monitoring（观察：漂移/衰减/熔断）
  → 若模型衰减 → retrain_signal → 人工决定重训
  → 若熔断触发 → kill switch STOP → 跳过每日管道
```

| 动作 | 命令 |
|------|------|
| 查看今日决策 | `qp decide` |
| 监控检查 | `qp monitor check` |
| 熔断状态 | `qp monitor check`（Kill Switch 区） |
| 生成血缘图 | `qp lineage snapshot` |

## 7. 术语速查（别混）

| 术语 | 含义 |
|------|------|
| Dataset vs Data Source | Dataset=可信数据产品；Data Source=原始提供方 |
| Signal vs Prediction | Prediction=模型裸输出；Signal=可交易信号 |
| Order vs Trade | Order 可被拒；Trade 是成交确认 |
| Experiment vs Run | Experiment=容器；Run=单次执行 |
| Decision vs Order | 系统出 Decision（建议），人下单 |
