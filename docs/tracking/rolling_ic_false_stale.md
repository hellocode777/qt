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

### 3.4 PSI 15.529 也是假的（P2-2，2026-09-11 实测）

`_compute_signal_psi()` 的值由 `DriftMonitor.compute_psi()` 算出。两个独立缺陷叠加：

**① epsilon 尺度错了（FACT，可复现）**：`epsilon=1e-6` 被用在 **0..1 的比例**上。
某个 bin 一侧计数为 0 时，`max(pct, 1e-6)` → 该项贡献 `(1e-6 − 0.25)·ln(1e-6/0.25) ≈ +1.0`。
用同一份真实数据实测：

```
修复前 (epsilon=1e-6):  PSI = 15.529   ← 与事故值完全一致
修复后 (1/(2n) 平滑):   PSI =  5.395
```

**② 更根本：抽样对象就不对**。历史里只有候选尾部信号，逐日候选数从 3 到 18 不等
（8/7=18，8/13=12，8/16=15…9/1 起只有 3），而且 9 月的候选分数全挤在
`−0.15 ~ −0.12` 的窄带里 → 分箱后 4 个 bin 一侧为空，各贡献 +0.5：

```
bin0: exp=0.254 act=0.000 contrib=+0.999
bin6: exp=0.000 act=0.165 contrib=+0.499
bin7: exp=0.000 act=0.165 contrib=+0.499
bin8: exp=0.000 act=0.165 contrib=+0.499
bin9: exp=0.000 act=0.165 contrib=+0.499
```

**结论**：候选尾部（策略筛选出来的一个子集）的形状随筛选口径变化，**不能用来衡量
分数分布的稳定性** —— 与 P1-1 同源。修复三件事：

1. `DriftMonitor.compute_psi()` 默认平滑改为 `1/(2n)`（各样本各自 n），显式传 epsilon 的行为保留；
   `PSITrigger.compute_psi()` 删掉重复实现，改为委托（两处曾在同一天各犯一次同样的错）
2. 新增 `psi_sample_is_sufficient()`：10 箱 × ≥5 样本/箱 = 每侧 ≥50，不足即判「不可测」
3. `_compute_signal_psi()` 只在 `kind="universe"` 抽样上计算 PSI；旧格式（无 kind 列，仅候选信号）
   直接返回 `available=False` 并打日志 —— 宁可说"测不了"，不给一个假数字

> 过渡期内 PSI 会一直是"不可测"（需要 ≥4 个 universe 抽样日），这正是预期行为。

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

## 4.1 附带发现：状态机 fail-open + 单测污染生产状态（2026-09-11 21:59 实测）

修完度量、跑完 `qp monitor check` 把状态置为 WARNING（21:14）之后，21:59:13 状态被**自动清成 NORMAL**：

```
2026-09-11T13:59:13.370838+00:00 | 1 -> 0 | KillSwitchPipeline | 监控正常，未发现风险事件
details: action=ok regime=UNKNOWN psi=0.000
```

来源查明：`tests/unit/test_pipeline_critical_path.py::TestKillSwitchPipelineIntegration::test_full_pipeline_runs_all_steps`
直接 `KillSwitchPipeline().run(ctx)`（裸 context、无价格数据、无 tmp 隔离），而 `run()` 末尾无条件调
`_update_system_state()` → 写**生产** `data/monitoring/system_state.parquet`。

**两个缺陷（均已实测复现，不只是推断）**：

1. **fail-open：读不到任何数据 = 判定"无风险"** ✅ **已修（P1-4）**
   沙盒复刻（把状态目录重定向到 /tmp，再 `chdir` 离开仓库根，等价于单测 `monkeypatch.chdir(tmp_path)` 之后的同进程调用）：

   ```
   修复前：沙盒初始 WARNING → pipeline action: ok → 沙盒结束 NORMAL（监控正常，未发现风险事件）
   修复后：沙盒初始 WARNING → pipeline action: ok → 沙盒结束 WARNING | sandbox seed
           （并打出 WARNING 日志：监控输入不可用 → 保持系统状态不变）
   ```
   → 相对路径 `data/...` 读不到时，PSI=0、rolling_ic 不可用，全部"没有触发"，于是 `action=OK` →**把风险状态降级**。
   这与"默认值不得伪装成测量值"是同一类问题：**"测不到" 被当成 "没问题"**。

   修法：`_update_system_state()` 加 fail-safe 守卫 —— `action=OK` 且 `_measurements_present(report)` 为假时**不改状态**。
   `_measurements_present` = 有 regime（说明价格数据真的进来了）**且**（PSI 或 rolling_ic 至少一个可算）。
   只有 OK 被拦；WATCH / PAUSE_BUY / STOP 等保守方向照常写入（真的测到了风险就该升级）。

2. **测试污染生产状态**
   `tests/unit/test_pipeline_critical_path.py` 的 `KillSwitchPipeline` 集成测试没有隔离目录，直接写生产状态文件；
   另有 `tests/unit/pipeline/test_multifactor_fundamental.py` 等用 `monkeypatch.chdir(tmp_path)`，同进程后续测试的相对路径读者都会失准。

   影响：任何一次 `pytest` 都可能悄悄改写生产风险状态，**审计链失真**（功能上本次无损失，NORMAL/WARNING 都允许开仓）。
   当前状态已在 21:59 被清成 NORMAL；周一 09:07 的 monitor_check 会重新算。

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

**⚠️ 过渡期（新历史累积期）**：抽样历史从下一个交易日 18:00 起逐日累积，
- PSI 需要 ≥4 个信号日 → 约 **4 个交易日**恢复可算
- realized IC 需要 ≥10 个贡献日 → 约 **2 周**恢复可测

这段时间里两类测量都不可用。配合 P1-4 的 fail-safe 守卫，系统**不会**用 `action=OK`
去覆盖状态（什么都不写），也不会误报警；但反过来说，**这两周模型衰减与漂移检查实际上是休眠的**。
`rolling_ic` 恢复后即可验证真实值（本次用 25 日回填测到 +0.05 量级）。

> 修复后 PSI 单独触发只到 WARNING 级 → action=WATCH → 状态自动从 PAUSED 落到
> WARNING（允许开仓）→ **下次 monitor 运行（周一 09:07）即自动解除**，无需人工改状态。

---

### 5.2 P1-2 解开结构性死锁 ✅（2026-09-11）

- Step 0 不再 `return`：改为 `record_only = True`，继续跑数据/因子/打分/策略执行（内存中）到
  **Step 10.5（线上信号监控）之后**才早退 —— 这正是 kill switch 依赖的两类测量（PSI / realized IC）的输入
- **交易行为不变**：仍然不开新仓（也不生成 SELL），只多了"记录"；订单与 DecisionPackage 都不产出
- 兼容：保留 `metadata["skip_reason"]`（WebUI/日志读取），新增 `record_only` / `record_only_completed`
- 回归测试：`test_system_state_paused_runs_record_only`（断言 DataPipeline 被调用 = 真的越过 Step 0）
- 从 PAUSED 出来的路径也随之可达：测量恢复 → `action=OK` → `auto_transition` → RECOVERY → NORMAL

### 5.3 P1-3 IC 衰减判定改为标准误感知 ✅（2026-09-11）

- 新增 `model_decay.ic_below_boundary(abs_ic, se, boundary, z=1.0)`：**点估计 + 1σ 仍低于边界**才算"确定低于"
- `ModelDecayDetector.check(rolling_ic, rolling_ic_se=None)`：STALE / DECAYING 需可分辨，否则 `NOT_MEASURED`
  （不传 se 的旧调用保持原行为，向后兼容）
- `ModelDecayTrigger` 读 `metrics["rolling_ic_se"]`；不可分辨时 `fired=False` / `level="NOT_MEASURED"`
- SE 从哪来：`rolling_ic()` 在给出均值的同时算 `SE = std(每日IC)/√n`（`last_ic_sample["se"]`），
  经 `_check_online_signal_health → MonitorReport.rolling_ic_se → _check_kill_switch` 传到触发器
- **事故数字回归**：IC=0.0023 / SE=0.16 → `NOT_MEASURED`（原来 STALE）；SE=0.0005 → 仍 `STALE`
  （真衰减不会被这套门禁掩盖）

### 5.4 P2-3 「不可测」不再伪装成 healthy ✅（2026-09-11）

- 新增 `DecayStage.NOT_MEASURED`，`model_decay_lifecycle` 映射为"不变更"（`None`）
- `_check_model_decay()` 在 IC 缺失时返回 `NOT_MEASURED`（原来返回 HEALTHY）
- 所有兜底默认值改掉：`MonitorReport.model_decay_stage`、`HealthLog`、`RetrainSignal.model_decay_stage`、
  `health_logger` 里的 `getattr(..., "HEALTHY")` —— 未设置的阶段不再自称健康
- WebUI：新增 `health_service.decay_stage_label()`（缺失/未知 → **不可测**），
  `health.html` 与 `components/strategy_health.html` 去掉 `| default("HEALTHY")`

---

## 6. 待办（按优先级）

### P1-1 让 rolling_ic 变成真测量 ✅ 已完成（2026-09-11，见 §5.1）
- [x] `online_signal_history` 落全横截面抽样（头 200 + 中段 100 + 尾 200 = 500/日）
- [x] 真机验证：贡献日 19、中位样本 500、rolling_ic(20)=+0.0502（可测）

### P1-2 解开结构性死锁 ✅ 已完成（2026-09-11，见 §5.2）
- [x] PAUSED 时仍运行"记录链路"（数据/因子/打分/信号历史），只禁止开新仓
- [x] 回归测试：`test_system_state_paused_runs_record_only`
- [x] 沙盒 e2e：状态=PAUSED + 真实数据 → 记录链路跑通、生产 `data/decisions` 零变动

### P1-3 阈值重标定 ✅ 已完成（2026-09-11，见 §5.3）
- [x] `ic_below_boundary()`：点估计 + 1σ 仍低于边界才判 STALE / DECAYING
- [x] `ModelDecayDetector.check(ic, se)` + `ModelDecayTrigger` 读 `rolling_ic_se`
- [x] SE 由 `rolling_ic()` 计算并一路传到 kill switch
- [x] 事故数字回归：0.0023/SE=0.16 → NOT_MEASURED；0.0023/SE=0.0005 → 仍 STALE

### P1-4 状态机 fail-open 改 fail-safe ✅ 已完成（2026-09-11，见 §4.1）
- [x] 数据不可用时 `action=OK` 不再改状态（`_measurements_present` 守卫）
- [x] 判定依据改为「关键输入是否真的读到」（regime + PSI/IC 的 available 标志），不再依赖默认值 0.0
- [x] 守卫只拦 OK；WATCH / PAUSE_BUY / STOP 照常写入
- [x] 4 个单测（无测量值保持状态 / 有 regime 无测量值也保持 / 有测量值仍能迁移 / 保守方向不受影响）
- [x] 沙盒复刻验证：原先把 WARNING 清成 NORMAL 的那次调用，现在保持 WARNING 并打出 fail-safe 日志

### P1-5 测试隔离：禁写生产状态（见 §4.1）
- [ ] `tests/conftest.py` 加 autouse fixture：把 `MONITORING_DIR` / 状态文件 / 信号历史重定向到 tmp（或至少禁止写生产路径）
- [ ] 给 `test_pipeline_critical_path.py` 的 KillSwitchPipeline 集成测试加 tmp 状态目录
- [ ] 复查 `monkeypatch.chdir` 的测试：同进程后续的**相对路径**读者（`data/...`）会失准

### P2-1 信号历史去重 ✅ 已随 P1-1 修掉
- [x] `_save_signal_snapshot` 改为按 `(strategy_id, date)` 覆盖写（幂等），旧数据里的重复行未回溯清理
- [ ] （可选）回溯清理历史里既有的重复行

### P2-2 PSI 假警报 ✅ 已完成（2026-09-11，见 §3.4）
- [x] `compute_psi()` epsilon 尺度修正（1/(2n) 平滑）：实测 15.529 → 5.395
- [x] 样本充分性门禁 `psi_sample_is_sufficient()`（≥10 箱 × 5 样本/侧）
- [x] PSI 只在 `kind="universe"` 抽样上计算；旧格式历史显式判「不可测」
- [x] `PSITrigger.compute_psi()` 重复实现删除，委托给唯一实现

### P2-3 「不可测」不要显示成「healthy」✅ 已完成（2026-09-11，见 §5.4）
- [x] `DecayStage.NOT_MEASURED` + 生命周期映射
- [x] 兜底默认值全部改为 NOT_MEASURED（MonitorReport / HealthLog / RetrainSignal / health_logger）
- [x] WebUI `decay_stage_label()`（缺失/未知 → 不可测）+ 模板去掉 `| default("HEALTHY")`

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
