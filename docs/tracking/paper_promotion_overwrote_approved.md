# paper trading 自动晋级覆盖 APPROVED，导致决策包断产 / DecisionPackage outage

> 创建: 2026-10-16 | 触发: 「这两天怎么没有决策记录」
> 状态: 根因已修（A 状态恢复 + B 代码守卫，均已在工作区落盘并验证）
> 结论一句话: **管线没坏，是被门禁提前挡掉了**。10-14 晚上 18:32 的 paper trading 定时任务在
> 30 天期满评价 PASS 后，把正在生产、已 APPROVED 的 `lvr_vol_only` 无条件改写成
> `SHADOW_PRODUCTION`；而日线管线只认 APPROVED，于是 10-15 / 10-16 在策略环节提前 `return`，
> 连 DecisionPackage 都不生成。

---

## 1. 现象

| 事实 | 证据 |
|---|---|
| 最新决策包停在 10-14 | `data/decisions/` 最新 `dp-2026-10-14-b42b3ba6.json`；无 `dp-2026-10-15/16` |
| 索引未再更新 | `data/decisions/index.json` mtime = 2026-10-14 20:18，45 entries |
| 10-15 / 10-16 管线日志断在策略环节 | `logs/2026-10-1[56]/daily_pipeline.log` 最后一行都是 `run:485 Daily pipeline — loaded from Registry:`（空） |
| 10-14 正常对照 | 同文件有 `Strategy health recorded` → `Online monitor` → `DecisionPackage saved` → `Index updated (45 entries)` |

WARNING 原文（两天的 `run:472`）：

```
无 APPROVED 策略，跳过策略执行。请人工批准: qp strategy approve <strategy_id> --by <name>
```

---

## 2. 根因（证据链）

| 环节 | 证据 |
|---|---|
| 谁改了 registry | `qp/platform/cli/commands/scheduler.py` job `paper_trading`（weekdays 18:32）→ `run.is_complete` 且 `result.passed` → `registry.set_lifecycle(sid, SHADOW_PRODUCTION)`，**无任何前置状态检查** |
| 何时改的 | `data/strategy_registry.json` mtime = 2026-10-14 18:33:17；`logs/2026-10-14/paper_trading.log` 时间戳 18:32:35–18:33:12 |
| 改了什么 | `git diff`：`lvr_vol_only` approved → shadow_production；`momentum_vol_full` backtest_passed → shadow_production |
| 为什么会触发 | 两个 run 的 `daily_records` 最后一天都是 2026-10-14（各 30 条），`result.passed=true`，recommendation 原文 "Recommend promotion to SHADOW_PRODUCTION"（lvr_vol_only: ret 8.99% / sharpe 1.58） |
| 为什么决策包没了 | `qp/pipeline/daily_pipeline.py:466` 门禁 `get_lifecycle(sid) == APPROVED` → 选定集合为空 → `:471` WARNING → 注册循环不执行 → `:580-582 if not registered_ids: return result` **提前返回**，Step 7–13 全跳过（含 Step 12 退出引擎、Step 13 DecisionPackage） |
| 为什么 10-14 正常 | 10-14 决策包生成于 18:22:00，早于 18:33 的 lifecycle 覆写 |

机制冲突本质：枚举顺序上 `SHADOW_PRODUCTION` 高于 `APPROVED`，但 ADR-031 语义上 **APPROVED 才是"生产就绪的冻结快照"**，
且 daily_pipeline（刻意设计，注释 "Strict policy (A)"）只跑 APPROVED。自动晋级拿枚举序当"晋级"，
结果把一个生产策略踢出了生产的准入门槛。

---

## 3. 影响面

* **数据层没断**：10-15 / 10-16 行情抓取、因子计算、FactorHealth 正常（10-16 抓到 15127 行 / 3020 只股票 / 19 因子）
* **策略层全停**：策略评估、持仓风控退出（Step 12）、决策包（Step 13）、shadow ledger 每日推进全部未执行
* **实际敞口为零**：`NAV 2026-10-14: ¥100,413 (0 positions)` —— 当时无持仓，所以是「看不到决策」而不是「该卖没卖」
* **paper 状态机停摆**：两个 run 已 complete，`runs` 不再收集，状态不再前进（也无副作用）

---

## 4. 修复（本次改动）

**A. 状态恢复（最小侵入）**

* `data/strategy_registry.json`：`lvr_vol_only` lifecycle 改回 `approved`
* 走官方路径 `StrategyRegistry().set_lifecycle(sid, APPROVED)` 回写（APPROVED 不在
  `_LINEAGE_REQUIRED_STATES`，不触发 lineage 校验），**旧 ApprovedStrategy 快照与
  validation_report 原封不动**
* 刻意**没有**用 `qp strategy approve lvr_vol_only --by Wei` 重跑：那会用当前 meta 重冻快照，
  把原有 validation_report（PASS / score 100）冲掉
* `momentum_vol_full` 的 `shadow_production` **保留**：它的 30 天 paper run 确实 PASS，
  晋级路径合法、无生产影响（它不是被误覆盖），回退反而是篡改事实

**B. 代码守卫（防复发）**

* `qp/platform/cli/commands/scheduler.py`
  * 新增 `_PAPER_PROMOTION_PROTECTED`：`{APPROVED, SHADOW_PRODUCTION, PRODUCTION, WARNING, KILL_SWITCH}`
  * 新增 `_paper_auto_lifecycle_change_allowed(current_lifecycle)`：仅当当前状态严格低于
    SHADOW_PRODUCTION（或策略未注册）才允许自动改写
  * job `paper_trading` 评价分支改为白名单判定，**双向**保护：
    PASS 不再把 APPROVED 降成 SHADOW_PRODUCTION；FAIL 也不再把生产策略降成 RESEARCH
  * 被拦下时打印 `... PASSED but lifecycle is already 'approved' — 不自动改写，需人工决策`
* `tests/unit/test_scheduler_paper_promotion.py`（新增，7 例）
  * 5 个受保护状态 → 拒绝改写（含 2026-10-14 的 APPROVED 回归用例）
  * 3 个低阶状态 → 允许晋级；未注册策略 → 允许

---

## 5. 验证

```
uvx ruff format --check .            → 486 files already formatted
uv run pyright                       → 0 errors, 0 warnings, 0 informations
pytest (test_scheduler_paper_promotion / test_paper_trading /
        test_scheduler_rebalance)    → 29 passed
门禁等价只读检查                      → daily_pipeline 门禁将选中: ['lvr_vol_only']
```

---

## 6. 遗留待办

- [ ] 补一包今天的决策包（今天 18:00 的管线已跑完，不会再自动生成）：`qp decide --force`
- [ ] 设计层：`SHADOW_PRODUCTION` 与 `APPROVED` 的语义顺序在全仓不一致
      （枚举序：APPROVED < SHADOW_PRODUCTION；语义/门禁：只有 APPROVED 能生产）。
      建议明确 ADR：是让 daily_pipeline 接受 SHADOW_PRODUCTION，还是让自动晋级永不越过 APPROVED
      （本次选后者，为最小改动）
- [ ] 同类风险排查：`qp/monitoring/model_decay_lifecycle.py` 也调用 `set_lifecycle`，
      确认其降级路径是否同样会覆盖 APPROVED
- [ ] 断产期间（10-15 / 10-16）无决策包，`n_sells` 未评估；本次无持仓故无实际决策丢失，
      但如果将来在持仓状态下复现，退出引擎同样被跳过 —— 属结构性风险
