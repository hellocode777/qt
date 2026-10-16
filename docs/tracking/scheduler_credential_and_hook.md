# 调度器凭据外置 + post-commit 钩子守卫 / Scheduler Credential & Hook Hardening

> 创建: 2026-10-16 | 触发: 「qp-scheduler 不是配了开机自启吗?怎么状态还是未运行」→ 顺着追问 `.git/hooks/post-commit`
> 状态: 已改 + 已验证（本机生效）；代码变更见 §4，待提交
> 结论一句话: 明文 SMTP 授权码曾写在 `deploy/systemd/qp-scheduler.service` 里并被提交、推送到 origin（私有仓），已外置到 `~/.config/qp/smtp.env`（600）；同时 post-commit 钩子此前会在「暂停」期间把服务偷偷 `enable+start` 回来，并且只守 10 分钟窗口就敢重启要跑 22 分钟的 `daily_pipeline` —— 三处都已修。

---

## 0. 起点：为什么调度器是 inactive（FACT）

不是配置丢失，是 19:24:50 按用户要求 `stop` + `disable`（会话 `20261016_192348_bc4183`）：

| 时刻 | 事件 | 证据 |
|---|---|---|
| 19:15:53 | systemd 启动 qp-scheduler | journal `Started qp-scheduler.service` |
| 19:24:50 | `systemctl --user stop` + `disable` | journal `Stopped ...`；`default.target.wants/qp-scheduler.service` 软链被删（目录 mtime 19:24） |
| 19:28 | 机器重启 | journal `-- Boot b5e794a5... --`，用户 manager PID 2049 |
| 19:33:58 | `enable --now` 恢复 | active + enabled，NRestarts=0，实例数 1 |

unit 文件本身完好（`[Install] WantedBy=default.target` 一直在）。开机自启靠的就是
`default.target.wants/` 里的那条软链，`disable` 删掉它 = 不自启。

---

## 1. 问题一：明文 SMTP 凭据入仓（HIGH）

### 证据

| 项 | 事实 |
|---|---|
| 位置 | `deploy/systemd/qp-scheduler.service:13`（改前）`Environment="SMTP_PASSWORD=<16 位授权码>"` |
| 是否入库 | `git ls-files` 跟踪中；`git show HEAD:` 有；`git log -S <值>` → 提交 `6b3dc3a0` |
| 是否外传 | `origin = https://github.com/hellocode777/qt.git`，`gh repo view` → `isPrivate: true` |
| 扩散面 | 钩子每次部署把它 `cp` 进 `~/.config/systemd/user/qp-scheduler.service`（两份 diff 曾为空） |

### 全机残留清单（`grep -rl <值>` 实测，2026-10-16 20:0x）

| 位置 | 是否外传 | 处置 |
|---|---|---|
| `deploy/systemd/qp-scheduler.service`（qt） | **是** → 已随 `6b3dc3a0` push 到私有 GitHub | 工作区/HEAD 已清；历史残留 → **只能轮换** |
| `~/.config/systemd/user/qp-scheduler.service` | 否（本机） | 已由模板刷新，命中数 0 |
| `~/.bash_history` | 否 | 已删 2 行（无备份） |
| `~/workspace/QuantTrading/config/__init__.py:157` | 否（该仓 **无 remote**，从未 push；值在 HEAD/`0a2daa7`） | 旧仓已于 2026-10-16 **整体移入回收站**（见 §7） |
| 同仓 `config/__pycache__/__init__.cpython-314.pyc` | 否 | 同上（清 `__pycache__` 即可） |
| `~/.hermes/state.db`(+`-wal`)、`~/.hermes/sessions/request_dump_*.json`、`~/.hermes/webui/sessions/*` | 否（本机 600） | 会话记录，读 unit 文件时写入；轮换后自然失效 |
| `~/.claude/projects/-home-shuai-workspace-qt/*.jsonl` | 否（本机 600） | 同上 |
| `~/.config/qp/smtp.env` | 否（600） | 合法持有者，轮换后写入新值 |

### 修复

* 新增 `deploy/systemd/smtp.env.example`（模板，无真值）
* unit 改为 `EnvironmentFile=-/home/shuai/.config/qp/smtp.env`，删掉 5 行 `Environment=SMTP_*`
* `install-systemd.sh` 增**凭据闸门**：`~/.config/qp/smtp.env` 缺失 → 拒绝部署
  （否则调度器会带着空凭据起来，18:30 `email_report` 静默失败）
* `.gitignore` 增 `smtp.env`（防将来误拷进仓库）
* 本机新建 `~/.config/qp/smtp.env`（600），值从旧 unit 平移；`~/.bash_history` 清理残留行

### 验证（实测）

```
本机 unit 内 "SMTP_PASSWORD=" 命中数 = 0
/proc/<MainPID>/environ → SMTP_HOST/PORT/SENDER/PASSWORD/RECEIVER 共 5 个
功能验证: smtplib.SMTP_SSL(smtp.163.com:465).login(...) → LOGIN OK — NOOP 250 OK
install-systemd.sh → "smtp env: .../smtp.env present (mode 600)" + "verification: 1 scheduler process(es) running"
```

### 遗留（只能人工做）

- [ ] **轮换 163 授权码**：163 邮箱网页版 → 设置 → POP3/SMTP/IMAP → 授权码管理 → 重置；
      把新值写入 `~/.config/qp/smtp.env`，然后 `systemctl --user restart qp-scheduler`。
      理由：旧值已进 git 历史并 push 过，私有仓风险有界，但**删历史无用 —— 只能轮换**。
      轮换一次即让上表所有副本（含旧仓、会话日志）一起失效，这是最省的收口方式。
- [ ] 旧仓 `~/workspace/QuantTrading` 也有同一枚值（`config/__init__.py:157`，值已提交进 HEAD，但该仓**无 remote、从未外传**）：
      建议轮换后把该处改为读环境变量 / `.env`，并清 `config/__pycache__/`；本次未动（另一项目，等你点头）
- [ ] 是否用 `git filter-repo` 清历史：当前不必要（轮换后旧值即失效）；若将来仓库转公开，必须先做。

---

## 2. 问题二：钩子会在「暂停」期间把服务拉回来

### 证据

`deploy/install-systemd.sh` 第 3 步无条件 `enable`（未 enabled 时）+ `start`（未 active 时）；
而 post-commit 钩子只要命中 `qp/**`（除 `qp/web/**`）或 `deploy/` 脚本就跑这个脚本。
→ 暂停的实际语义是「**直到你下次动代码为止**」，任何代码提交都会让停掉的服务复活。

### 修复

钩子新增**暂停守卫**（步骤 0）：`systemctl --user is-enabled qp-scheduler` != `enabled`
→ 跳过部署并打印恢复命令。

### 验证

```
systemctl --user disable qp-scheduler → 钩子输出
  [post-commit] qp-scheduler is 'disabled' (paused) — skip auto-deploy
  [post-commit] resume with: systemctl --user enable --now qp-scheduler
恢复后 is-enabled=enabled / is-active=active
```

---

## 3. 问题三：窗口守卫是手抄的第二份时间表，且覆盖不住真实时长

### 证据

* `logs/2026-10-16/daily_pipeline.log`：18:00 起跑 → 18:21:54 结束 = **22 分钟**
* 旧钩子窗口只有 `1078-1088`（17:58–18:08，10 分钟）→ 18:10 提交代码就会重启，掐断在跑的 pipeline
* 掐断是确定性的，不是理论风险：SIGTERM → `QPScheduler.stop()` → `shutdown(wait=False)`
  （`qp/platform/scheduler/scheduler.py:79`）；`qp/platform/cli/parser.py:906` 以 `app=None`
  调 `cmd_scheduler_start()`，信号处理后主循环返回、进程退出，工作线程随之终止。
* 窗口里的分钟数与 job 定义是两份独立副本，改 job 时间不改窗口 → 守卫静默失效。

### 修复

窗口改为从 **job 注册表派生**（单一来源）：按 `scheduler.add_job(` 分块，块内取
`name="..."` 与 `CronTrigger(hour="H", minute="M")`；窗口 = `[start - 2min, start + guard(job)]`，
guard 为「启动后可能还在跑」的分钟数：`daily_pipeline = 25`（按实测 22 分钟留余量），
其余 `= 5`（实测 monitor_check / pre_close_check 均在启动后 ~30s 内结束）。
解析不到 job（<1 个）→ 打 WARNING 并回退旧静态窗口，明确提示修 parser。

派生结果（实测输出，6 个 job 全中）：

| job | 启动 | 窗口 |
|---|---|---|
| monitor_check | 09:07 | 09:05–09:12 |
| retrain_notify | 09:17 | 09:15–09:22 |
| pre_close_check | 16:53 | 16:51–16:58 |
| daily_pipeline | 18:00 | 17:58–18:25 |
| email_report | 18:30 | 18:28–18:35 |
| paper_trading | 18:32 | 18:30–18:37 |

### 验证

```
边界: 17:57 通过 / 17:58 拦 / 18:25 拦 / 18:26 通过
路径过滤: docs/*.md 跳过；qp/web/app.py 跳过；qp/monitoring/*.py 触发
fallback: registry 不存在 / 解析不到 job → WARNING + 回退窗口生效
暂停守卫: disabled 时跳过（见 §2）
```

---

## 4. 本次改动清单

| 文件 | 改动 |
|---|---|
| `deploy/systemd/qp-scheduler.service` | 删 5 行明文 `Environment=SMTP_*`；改 `EnvironmentFile=-~/.config/qp/smtp.env`；顶部加"凭据不入仓"注释 |
| `deploy/systemd/smtp.env.example` | 新增：模板 + 安装步骤 + 为什么不在仓库里 |
| `deploy/install-systemd.sh` | 新增凭据闸门（缺 env 文件即 `die`）+ 状态行打印 env 文件与权限 |
| `deploy/git-post-commit.sh` | 新增暂停守卫（步骤 0）；窗口改为从注册表派生 + guard 表；新增 `QP_HOOK_DRY_RUN` / `QP_HOOK_FILES` / `QP_HOOK_NOW_MIN` / `QP_HOOK_VERBOSE` / `QP_HOOK_REGISTRY` 测试开关；窗口表仅在 dry-run/verbose 打印 |
| `.gitignore` | 增 `smtp.env` |
| `docs/user_guide.md` | §11.1 增「SMTP 凭据」与「自动部署钩子」两节 |
| `docs/ai/COMMAND_MAP.md` | `qp scheduler` 条目补 EnvironmentFile + 钩子守卫 |
| 本机（不入库） | `~/.config/qp/smtp.env`（600）；`~/.bash_history` 清残留；`~/.config/systemd/user/qp-scheduler.service` 由模板刷新 |

非量化改动（部署/凭据/文档），不涉及因子/回测/资金路径 → 不触发 §21 量化清单。

---

## 5. 复现验证命令

```bash
# 钩子干跑（不动服务）
QP_HOOK_DRY_RUN=1 QP_HOOK_VERBOSE=1 QP_HOOK_FILES="qp/x.py" QP_HOOK_NOW_MIN=1090 bash deploy/git-post-commit.sh
# 部署（幂等，会重启调度器）
bash deploy/install-systemd.sh
# 凭据是否真的能用（只登录，不发信）
python3 - <<'PY'
import pathlib, smtplib, ssl
env = dict(l.split("=", 1) for l in pathlib.Path("~/.config/qp/smtp.env").expanduser().read_text().splitlines() if "=" in l)
with smtplib.SMTP_SSL(env["SMTP_HOST"], int(env["SMTP_PORT"]), context=ssl.create_default_context()) as s:
    s.login(env["SMTP_SENDER"], env["SMTP_PASSWORD"]); print("LOGIN OK", s.noop())
PY
```

---

## 6. 遗留 / 待决策

- [ ] 轮换 163 授权码（§1，只有人工能做）
- [x] `crontab 0 17 * * 1-5`（旧仓 pipeline）与 systemd `18:00 daily_pipeline` **语义重复** ——
      2026-10-16 随旧仓退役一并删除（§7），重复问题自然消失
- [ ] `guard_minutes`（daily_pipeline 25 / 其余 5）是人工经验值；pipeline 时长若变化需同步，
      更彻底的做法是让 job 自己上报 duration（未做）
- [ ] `deploy/systemd/qp-scheduler.service` 里的 `User=shuai` 在**用户级** unit 中被 systemd 忽略
      （`systemd-analyze verify --user` 无告警），属误导性残留，本次未动

---

## 7. 旧仓 `~/workspace/QuantTrading` 退役（2026-10-16）

用户决定：该仓不再需要 → 删除。**删前先核牵连面**（FACT）：

| 检查项 | 结果 |
|---|---|
| qt 是否消费它 | **否**。`qp/data/adapter/quant_trading_db_adapter.py` 当前代码里**不存在**（`ls` 报 No such file）；全仓 grep 只剩"从 QuantTrading 迁移"一类注释、`data/dataset/registry.json` 的历史 source 标注、`data_quality_service.py` 的展示映射 —— 均非活跃依赖 |
| crontab 引用 | 3 行：`0 17 * * 1-5` pipeline、`@reboot` 启动 webui、`*/2` 保活 webui（不摘掉 → 目录没了以后 cron 每天/每 2 分钟报错） |
| 运行中进程 | `streamlit run webui/app.py --server.port 8501`（PID 4773，旧 QT 界面） |
| systemd 单元 | 无（`~/.config/systemd/user/` 与 `/etc/systemd/system/` 均无引用） |
| 体量 / 可恢复性 | 4.6G（`quant.db` 2.5G、`.git` 294M）；**无 remote**；工作区 2893 个未提交改动 → 删掉即不可找回 |

执行的清理：

1. crontab：备份 `~/.crontab.backup.before_qt_removal.20261016_1946` → 删除那 5 行（含 2 行注释头）→
   复核 diff 仅此 5 行；现存只剩 3 条 Hermes 相关（6:00 日报 / 1 号归档 / 5:50 单词卡）
2. 停 `streamlit` PID 4773 → `:8501` 释放（旧 QT 界面**没了**，qt 自己的 UI 是 `:8080` SPA + api_v1）
3. `gio trash /home/shuai/workspace/QuantTrading` → 工作区已无此目录，内容在
   `~/.local/share/Trash/`（可恢复；`gio trash --empty` 才真正释放 4.6G）
4. 复核：进程引用 0、crontab 引用 0、`docs/ai/DATA_FLOW.md` 里那行失效导航已更新

> 注：回收站里的副本仍带着那枚旧 SMTP 授权码 —— 这正是 §1 遗留「轮换授权码」优先的原因，
> 轮换后该副本即便留着也不再构成风险；想彻底释放磁盘再执行 `gio trash --empty`。
