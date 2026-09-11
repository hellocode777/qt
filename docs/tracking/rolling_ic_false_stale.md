# 实时 IC 假 STALE 与平台死锁 / Rolling-IC False STALE

> 创建: 2026-09-11 | 触发: 「qt 今天下午 6 点的定时任务没跑吗」
> 状态: **根因已修（commit b507576，已 push）**，遗留 3 项待办（见 §6）
> 结论一句话: **模型没有衰减**；是「用 5 只股票算 IC」的度量假象把平台停了一天，并且顺带暴露了一个不会自愈的死锁。

---

## 1. 现象

2026-09-11 18:00 的 `daily_pipeline` 有触发，但在 Step 0 被系统状态拦住，等于没执行：

```
logs/2026-09-11/daily_pipeline.log
18:00:00.282 | WARNING | ⛔ 系统状态 暂停 / PAUSED — 跳过策略执行 / System paused — skipping strategies
```

* 18:30 `email_report` 有触发，但正文是占位符 `No DecisionPackage found — check logs`
* 最后一个 DecisionPackage 是 `dp-2026-09-09`；**9/10、9/11 均无产出**
* 状态来源: `data/monitoring/system_state.parquet` → `PAUSED`，自 **2026-09-10 09:07** 起
* 触发者: `KillSwitchPipeline` `action=PAUSE_BUY`，`KS=2 triggers`

```
PSI 15.529 ≥ threshold 0.25
Model STALE: rolling IC 0.0023 < absolute minimum 0.005. Retire model, retrain required.
```

---

## 2. 结论：0.0023 是噪声，不是衰减

用全横截面（~3026 只/日）重算同一批日期的 rank IC：

| 口径 | 最近 20 日 | 最近 60 日 |
|---|---|---|
| online monitor（5 只小样本） | **-0.0023** (t=-0.01) | -0.1118 (t=-0.88) |
| 全横截面（approved 权重） | **+0.0767** (t=+5.27) | +0.0829 (t=+3.79) |
| 全横截面（registry 权重） | +0.0713 (t=+4.26) | +0.0842 (t=+4.20) |

反证：从**同一批真实分数**里每天随机只取 5 只，20 日均值 IC 的 5%–95% 区间是
**[−0.130, +0.235]** —— 真 IC 是 +0.08，5 只股票根本测不出来。

---

## 3. 度量到底错在哪（三层证据）

### 3.1 精确复现（先证明读懂实现）

`OnlineSignalMonitor._compute_realized_ic` 原样重算，与落盘记录一致：

| 指标 | 复算 | `online_health_history` |
|---|---|---|
| rolling_ic(20d) @2026-09-09 | -0.002302 | -0.0023 ✓ |
| rolling_ic(60d) | -0.111796 | -0.1118 ✓ |

### 3.2 样本结构（致命细节）

```
window=20 贡献日数 = 11 天（不是 20 天）
每日子样本 n = 5 ~ 15（绝大多数就是 5）
单日 IC std = 0.545        ← 噪声量级 ±0.5
mean = -0.00230  SE = 0.164  t = -0.01
```

* 20 日窗口内 **9 个信号日被 `<5 有效样本` 闸门跳过**，其中 **9/1、9/2、9/3、9/4、9/7、9/8、9/9 全部在列**
  → 判定用的数据全部来自 **8/14–8/31**，最近两周根本没参与
* 打乱分数做 2000 次模拟（原假设 = 分数无预测力）：
  `|20日均值IC| > 0.005 的概率 = 97.3%`，实际观测 -0.0023 落在噪声分布第 **51.3** 百分位
  → **0.005 这个绝对下限比该算法的噪声底低 40 倍**，随机打分也有 97% 概率被判 STALE

### 3.3 三个具体缺陷（FACT）

1. **样本结构错**：落进 `online_signal_history` 的只有通过筛选的 3–18 只候选（分数挤在 0.001–0.05 的极窄区间），不是全横截面排序 → 拿它们算 IC 等于排序近随机数
2. **重复写入**：`_save_signal_snapshot` 同日重复追加（8/7 有 18 行但只有 **6 只唯一股票**，×3），虚增"样本量"
3. **窗口被 3 股日占领**：最近每天只有 3 条信号 → 全部触发 `<5` 闸门 → 窗口内容实际冻结在 3 周前

---

## 4. 死锁（这是比假 STALE 更严重的结构性缺陷）

```
PAUSED
  → daily_pipeline Step 0 return（跳过一切）
  → 唯一写 online_signal_history 的 Step 10.5 不执行（qp/pipeline/daily_pipeline.py:836）
  → 窗口内容不变 → rolling_ic 不变 → 一直 STALE
  → 一直 PAUSED          ← 不会自愈
```

证据：
* `online_signal_history.parquet` mtime = **9/9 18:25**，最大日期 = 2026-09-09（此后无写入）
* `OnlineSignalMonitor()` 的实例化只有三处：`online_monitor.py:95`（自身）、`kill_switch_pipeline.py:446`（只读 IC）、`daily_pipeline.py:836`（写入）
* 状态机唯一写入点是 `KillSwitchPipeline._update_system_state()` → `auto_transition()`，**没有任何 CLI/API 能手动改状态**

---

## 5. 已完成（2026-09-11，commit `b507576`）

- [x] 复现 `rolling_ic` 并做样本量/噪声验伪（§3）
- [x] 全横截面金标准重算，确认模型真实 IC +0.07~+0.08（§2）
- [x] `online_monitor`：拆出 `_realized_ic_detail()` 返回每日 IC + 对应样本量
- [x] `online_monitor`：`rolling_ic()` 增加数据充分性门槛（≥10 贡献日、每日中位样本 ≥300 只），不达标返回 `None`（= 不可测），并暴露 `last_ic_sample` 诊断字段
- [x] `_compute_realized_ic()` 保持返回 float（供日度 health score 用），行为零变化
- [x] `kill_switch_pipeline`：IC 不可测时打 WARNING 日志说明，避免静默 0.0 被读成 "healthy"
- [x] 新增 3 个回归测试（薄样本→None / 宽样本→有值 / 历史过短→诊断）
- [x] 质量门禁：`ruff format --check` 0、`ruff check` 0、`pyright`（全仓）0、`tests/unit/test_monitoring.py` 163 项全过
- [x] 端到端验证（只调内部方法，不写状态、不发邮件）：
      `_determine_action` 由 **pause_buy → watch**；
      状态机模拟 `PAUSED → auto_transition(WATCH) → WARNING`，`can_open_positions=True`
- [x] 重启 `qp-scheduler`（git hook 已自动重启，PID 575440 @ 21:01:43），修复对新任务生效

### 5.1 P1-1 落地：让信号历史变成可测量的全横截面抽样 ✅（2026-09-11）

- [x] `multifactor.compute_today_scores_full()`：拆出「全横截面打分」，返回全部 ~3020 只的 `[symbol, raw_score, rank]`；`compute_today_signals()` 变成它的 top-N 薄包装，契约与输出不变
- [x] `daily_pipeline`：每个策略只算一次全横截面，自己切 top-N 给策略，并把全量交给在线监控（不再重复计算）
- [x] `online_monitor._sample_universe()`：确定性抽样 = 分数头部 200 + 中段等距 100 + 尾部 200 = **500 只/日**（保留两端才有分数 spread）
- [x] `_save_signal_snapshot()` 改为**按 `(strategy_id, date)` 覆盖写**（幂等，顺带修掉 §3.3 的重复累加）
- [x] `check(..., score_universe_df=...)`：有全横截面就用抽样落盘，没有则回退候选信号（保持旧行为）
- [x] **新增 `kind` 列分离两种语义**（这一步是必须的，见下方"下游耦合"）
- [x] 新增 9 个测试（抽样保留两端/上限、小截面直通、幂等、回退、抽样后 IC 可测、kind 打标、IC 忽略候选行、策略计数只数候选、无 kind 的旧历史兼容）

**下游耦合（落地时才暴露，已修）**：同一个 parquet 有三个消费者，语义不同：

| 消费者 | 要的行 | 修法 |
|---|---|---|
| `online_monitor` IC | `kind="universe"`（全横截面抽样） | 只读 universe 行 |
| `strategy_monitor` 信号计数 | `kind="candidate"`（当日候选信号） | 只数 candidate 行 |
| `kill_switch_pipeline` PSI | `kind="universe"`（分数分布） | 只读 universe 行 |

不做分离的后果（真机验证过）：`strategy_monitor` 会把 500 抽样行当成 500 条信号 → `High signals: avg 505/day > max 30` 假告警 + 健康分掉到 75。旧历史没有 `kind` 列时按 `candidate` 回填，读取端各自回退，行为与今天一致。

**真机验证**（真实 `factor_values_daily`，25 个交易日，历史写 /tmp，生产文件未触碰）：

| 指标 | 修复前 | P1-1 后 |
|---|---|---|
| 每日持久化行数 | 3–18（候选信号） | **500**（rank 1 ~ 3016 抽样）+ 5 候选 |
| 贡献日 / 中位样本 | 11 日 / 5 | **19 日 / 500** |
| rolling_ic(20) | -0.0023（不可测噪声） | **+0.0502**（可测） |
| rolling_ic(60) | -0.1118 | +0.0302 |
| 全横截面金标准 | +0.077 | +0.077（口径不同，量级一致） |
| 策略健康 | score 85 / `Signal dispersion` 告警 | **score 100 / 无告警**（avg 5 条/日，未误报 High signals） |
| PSI | 15.529（小样本伪影） | **1.557**（量级回到正常区间；本次仅 25 日窗口、ref 只有 5 日，生产会随 40+ 日累积而更准） |

> PSI 由 15.5 掉到 1.6 佐证了 P2-2 的判断：原值是小样本（每天 3–18 个分数做 10 个分箱）+ epsilon 的伪影，而不是真实漂移。它仍 > 0.25，所以 PSI 触发的 WARNING 还会继续，这条留 P2-2 单独处理。

> 修复后 PSI 单独触发只到 WARNING 级 → action=WATCH → 状态自动从 PAUSED 落到
> WARNING（允许开仓）→ **下次 monitor 运行（周一 09:07）即自动解除**，无需人工改状态。

---

## 6. 待办（按优先级）

### P1-1 让 rolling_ic 变成真测量 ✅ 已完成（2026-09-11，见 §5.1）
- [x] `online_signal_history` 落全横截面抽样（头 200 + 中段 100 + 尾 200 = 500/日）
- [x] 真机验证：贡献日 19、中位样本 500、rolling_ic(20)=+0.0502（可测）

### P1-2 解开结构性死锁
- [ ] 方案：PAUSED 时仍允许「只读 + 记录」链路（数据/因子/评分/信号历史写入），只禁止开新仓
- [ ] 或：状态机加保护 —— 指标数据未更新（输入 mtime 未变）时不得重复判定/升级状态
- [ ] 补一条集成测试：PAUSED → 下一日 pipeline 仍能推进信号历史

### P1-3 阈值重标定
- [ ] `absolute_min_ic=0.005` 在任何现实样本下都不可分辨：全横截面 20 日 IC 的 SE≈0.004，已经只有 ~1.2σ
- [ ] 建议改成基于标准误的相对判定（如 `|IC| + 1σ < 阈值` 才算衰减），而不是拿点估计直接比绝对下限

### P2-1 信号历史去重 ✅ 已随 P1-1 修掉
- [x] `_save_signal_snapshot` 改为按 `(strategy_id, date)` 覆盖写（幂等），旧数据里的重复行未回溯清理
- [ ] （可选）回溯清理历史里既有的重复行

### P2-2 PSI 15.5 大概率也是假警报
- [ ] PSI 常年 13–22，而 0.25 就是「显著漂移」阈值 —— 60x 超标本身不合理，疑似空 bin + epsilon 伪影（20 日窗口内每天仅 3–18 个分数做分箱）
- [ ] 建议同样加样本充分性门槛，并复核 `_compute_signal_psi` 的 epsilon 处理

### P2-3 「不可测」不要显示成「healthy」
- [ ] IC 不可测时 `DecayStage.HEALTHY` 的语义是 "not measured"，但 WebUI/摘要显示 "healthy" —— 属「默认值伪装成测量值」
- [ ] 建议引入 `NOT_MEASURED` 展示态，或让 UI 读 `rolling_ic_available` 显式标注

---

## 7. 复现方式

```bash
cd ~/workspace/qt

# 7.1 当日是否被拦
cat logs/$(date +%Y-%m-%d)/daily_pipeline.log

# 7.2 当前系统状态与最后触发原因
.venv/bin/python -c "
import polars as pl
print(pl.read_parquet('data/monitoring/system_state.parquet').to_dicts())
print(pl.read_parquet('data/monitoring/system_state_log.parquet').sort('timestamp',descending=True).head(5).to_dicts())
"

# 7.3 rolling_ic 的样本量（修复后直接可看）
.venv/bin/python -c "
from qp.monitoring.online_monitor import OnlineSignalMonitor
from qp.pipeline.daily_pipeline import _load_price_data
prices,_=_load_price_data()
m=OnlineSignalMonitor(); print(m.rolling_ic('momentum_vol_full', prices, 20), m.last_ic_sample)
"

# 7.4 回归测试
.venv/bin/pytest tests/unit/test_monitoring.py -q -k RollingICDataSufficiency
```

---

## 8. 关联

* 索引: `docs/tracking/qt_backlog_tracker.md` #10
* 代码: `qp/monitoring/online_monitor.py` / `qp/monitoring/kill_switch_pipeline.py`
* 相关: `docs/constitution/rule.md`（默认值不得伪装成测量值）
