# LLM 判断点清点 — Jev 适用性评估

> 创建: 2026-09-26 | 状态: ✅ 清点完成（结论：Jev 候选位 = 0）
> 来源: Hermes 讨论「Jev 对当前系统作用大吗」→ 摊开清点所有「调 LLM 做判断」的位置
> 姊妹篇: `industry_heat_ai_feasibility.md`（那篇回答「AI 该用在哪」，本篇回答「判断点在哪、Jev 有没有位置」）
> 范围: **跨项目** —— `~/workspace/qt`（qp）+ `~/.hermes`（cron + scripts）
> ⚠️ 本文数据核实于 **2026-09-26**，路径/脚本/任务会变，复用时先重跑 §1 的复核命令

---

## 结论摘要

1. **Jev 候选位 = 0。**
   不是「量还不够」，而是**手上根本没有「该用模型做判断」的位置** —— 现有判断要么是确定性数学（qt），要么是纯规则（cron 的算术 / 时间戳比较 / 枚举分派）。
2. **qt 代码里 LLM 调用数为零**（2026-09-26 复核，与 2026-09-10 的结论一致）。
3. **清点反而暴露了 3 个真实问题**：3 个 Hermes cron 任务正在用 LLM 做**纯规则/算术**判断 —— 既烧 token，又违反「可核实」铁律。**这是本次清点的真正产出**。
4. **Jev 不改变既有硬约束。** Jev 不是确定性组件（详见 §4）。`industry_heat_ai_feasibility.md` §3「AI 不进信号管线」的结论**不变**，Jev 只是「更快更便宜更结构化的 LLM 判断节点」，不是「确定性组件」。

---

## §1 清点方法（可复核）

```bash
# 1. qt 代码里有没有 LLM 调用（2026-09-26 实测 → 零命中）
rg -il --glob '!**/.venv/**' --glob '!**/node_modules/**' \
   -e 'openai|anthropic|deepseek|zhipu|dashscope|chat\.completions|messages\.create' \
   ~/workspace/qt

# 2. Hermes 脚本里的 LLM 调用
rg -n --glob '*.py' -e 'def .*llm|bigmodel|ZHIPU|DEEPSEEK|openai' ~/.hermes/scripts/

# 3. Hermes cron 任务的 prompt（判断逻辑藏在 prompt 里，不在代码里）
python3 -c "import json;d=json.load(open('/home/shuai/.hermes/cron/jobs.json'));..."
```

**关键方法论点**：Hermes 系里「判断逻辑」藏在 **cron job 的 prompt** 里，不在 `.py` 文件里。只 grep 代码会**漏掉全部 cron 任务** —— 这是本次清点最容易踩的坑。

---

## §2 全量清点表（FACT）

| # | 位置 | 触发频率 | 实际在做什么 | 分类 | Jev 候选位 |
|---|---|---|---|---|---|
| 1 | `qt/qp/**/*.py` + `qt/scripts/*.py` | — | **零 LLM 调用**（rg 复核） | 确定性系统 | — |
| 2 | `~/.hermes/scripts/hermes_daily_mail.py:448` `llm_summarize_news()`（zhipu） | 每日邮件 | 新闻原文 → 中文摘要 | **生成 / 摘要** | ❌ 不是判断 |
| 3 | cron `qp-paper-trading-daily-reminder`（工作日 18:35） | 工作日 1 次 | Agent 读 2 个 JSON → **算**总收益率% / 剩余天数 → 2 条 if 分支汇报 | **纯规则伪装成 LLM** | ❌ 该用 Python |
| 4 | cron `qt-monthly-retrain`（每月 1 日 10:00） | 月 1 次 | 跑脚本 → 读候选快照 → **verdict 四选一分派**（UPGRADE/HOLD/DECAY/FACTORS_FAILED） | **枚举判断，且 verdict 已由脚本算出** | ❌ 名义上是 Choice 型，但该用 if/elif |
| 5 | cron `skill-health-check-report`（每月 1 日 09:00） | 月 1 次 | 统计 skill 数 + **时间戳比较**找 >30 天未使用 | **纯规则** | ❌ 该用 Python |
| 6 | cron `daily-native-word-card`（每日 05:50） | 日 1 次 | 生成 native-lab 英语教学卡 | **纯生成** | ❌ 不是判断 |
| 7 | `~/.hermes/scripts/*.sh`（NCE 下载 / hindsight） | 手动 / 常驻 | HTTP 下载、健康检查 | 不是 LLM | — |

**唯一真正的「LLM 判断」候选位：#4 的 verdict 分派** —— 但它的四个选项**已经由 `retrain_monthly.py` 算出来了**，LLM 只是把结果翻译成中文句子。判断本身不在 LLM 手上。

---

## §3 三个反模式：该脚本化，不该用 LLM

> 这三条是本次清点的**真正产出**。它们不是「Jev 的候选位」，而是「该从 LLM 手里拿走」的东西。

### 反模式 1：让 LLM 做算术（#3）

`qp-paper-trading-daily-reminder` 的 prompt 要求：

```
计算：
- 总收益率% = (最新equity / capital - 1) * 100
- 剩余天数 = 30 - elapsed_days
```

**问题**：把两个确定性的算术，交给一个逐 token 生成的模型做。
**风险**：算错没有护栏，且**违反「真实可核实」铁律**（用户 profile 明写：默认值/测量值不得混淆）。
**正确姿势**：写成 `qp paper status --brief` 子命令或独立脚本，输出 markdown，cron 只负责投递。

### 反模式 2：让 LLM 比较时间戳（#5）

`skill-health-check-report` 要求 Agent 读 `.usage.json` → 筛 `last_used_at` 超过 30 天且 `created_at` 超过 14 天。

**问题**：这是 `datetime` 比较，不是判断。
**正确姿势**：一个 30 行的 Python 脚本。

### 反模式 3：让 LLM 做「已算好结果的搬运」（#4）

`qt-monthly-retrain` 的 verdict 由 `retrain_monthly.py` 输出到 JSON。Agent 的角色是「读 JSON → 按 verdict 挑一段文案」。

**问题**：判断已经发生过了（在 Python 里），LLM 只做文案。用 LLM 搬运 = 引入不确定性 + 每次烧 token。
**正确姿势**：脚本直接渲染中文报告；只有**真的需要解释「为什么 DECAY」**时才调模型。

> **共性**：三者的判断**都可以被写成一个 `if`**。凡是一个 `if` 能写清楚的，都不该调模型 —— 这一点和 `industry_heat_ai_feasibility.md` §2「不该用 AI 的两处」是同一条原则的延伸：**「拿大炮打蚊子，还引入不可复现性」**。

---

## §4 Jev 事实核查（FACT）

| 项 | 事实 | 来源 | 核实日期 |
|---|---|---|---|
| 是什么 | TypeSafe AI 首个「System One Model」，不生成文本，输入 `state` + 类型化 `questions`，输出带概率的类型化答案 | typesafe.ai / Cloudflare 文档 | 2026-09-26 |
| 三种问题类型 | `Noul`（是非 → 概率）/ `Choice`（多选 → 选项+概率）/ `Score`（量表 → 分数+分布） | Cloudflare / LangChain 文档 | 2026-09-26 |
| 上下文 | **32,000 tokens**（Cloudflare 文档口径）；另有第三方称 64k，**以官方 32k 为准** | Cloudflare Workers AI 模型页 | 2026-09-26 |
| 价格 | 输入 $0.042/百万 token，**输出免费** | 官方 / dev.to | 2026-09-26 |
| 性能 | 官方口径 193.6x 快 / 444.6x 便宜（**TypeSafe 自测、无第三方复现**） | typesafe.ai（明确标注 "self-run and unreproduced"） | 2026-09-26 |
| **采样参数** | **无** —— `temperature` / `top_p` 被忽略（"Jev has no sampling knobs"） | Pydantic AI 官方文档 | 2026-09-26 |
| **confidence 语义** | **是 margin，不是「答案正确的概率」**。是非题 = 概率距 0.5 的距离 ×2（p=0.01 报 0.98） | Pydantic AI 官方文档 | 2026-09-26 |
| **对抗性文本** | Jev 把 state 当数据，但**注入指令 / 误导性框架 / 自我辩护的论证能动摇它**；官方建议护栏「与确定性检查并用，而非替代」 | Pydantic AI 官方文档 | 2026-09-26 |
| OpenRouter 可用性 | ❌ **不可用**。API 实测 458 个模型中只有 `typesafe/jev-router`（定价 `-1`，未开放），**没有 `jev-1.13`** | `curl https://openrouter.ai/api/v1/models` 实测 | 2026-09-26 |
| 获取方式 | TypeSafe console（early access，有 waitlist）/ Vercel AI gateway / Cloudflare Workers AI / LangChain | dev.to / Cloudflare | 2026-09-26 |
| 确定性 | ⚠️ **未核实** —— 官网 FAQ 有此问题（"Is Jev deterministic?"）但答案在折叠组件里，静态 HTML 抓不到；未做浏览器渲染 | typesafe.ai（仅见问题文本） | 2026-09-26 |

### §4.1 对硬约束的影响（INFERENCE）

`industry_heat_ai_feasibility.md` §3 拒绝 LLM 进信号管线的第①条理由是「**同输入不同输出，不可复现**」。

Jev 的已核实事实**不解除这条约束**：
- ✅ 无采样参数 → 减少了采样噪声（比 LLM 好）
- ❌ 但 **confidence 不是正确率**（是 margin）→ 不能拿它当「这个判断有多可信」的度量
- ❌ 且**对对抗性文本敏感** → 输入被污染时会漂移
- ⚠️ **确定性未核实** → 不能声称「同输入同输出」

**结论：Jev 不能进信号管线/回测。** 它是「更便宜更快更结构化的 LLM 判断节点」，不是确定性组件。若哪天要重新引入 AI 解读层（见 §5），Jev 是该层的**优先候选**，但仍受 §3 硬约束管辖。

---

## §5 Jev 什么时候才会真的有位置

`industry_heat_ai_feasibility.md` §2 已指出 AI 唯一不可替代之处：**「非结构化 → 结构化：新闻/公告 → 行业催化判断」**。

**那正是 Jev 的理论位置** —— 语义分类、输出可枚举、带可校准概率。但该篇已决策「暂不做」（对选股无直接作用，且不能进因子）。

**触发器（满足任一才重新评估）：**

- [ ] AI 解读层解禁（即 §2「非结构化 → 结构化」重新启动）
- [ ] 出现日判断量 ≥ 万级的场景（这时 444x 便宜才开始有意义）
- [ ] 要做**对外**的 Agent 工具护栏（工具放行 / 命令风险），而非自用

---

## §6 决策记录

| 日期 | 决策 |
|---|---|
| 2026-09-26 | **不引入 Jev** —— 候选位为零，无场景可落 |
| 2026-09-26 | **Jev 不解除「AI 不进信号管线」约束** —— 非确定性组件 |
| 2026-09-26 | 清点暴露的 3 个反模式（#3/#4/#5）转为待办，**方向是脚本化减 token**，不是换模型 |

---

## §7 待办

- [ ] **#3** `qp-paper-trading-daily-reminder` 算术部分下沉到脚本 / `qp paper status --brief`；cron 只投递
- [ ] **#4** `qt-monthly-retrain` 的 verdict 渲染下沉到 `retrain_monthly.py`；仅「为什么 DECAY」保留模型解释
- [ ] **#5** `skill-health-check-report` 改为独立 Python 脚本
- [ ] 核实 Jev 确定性（需浏览器渲染 typesafe.ai FAQ，静态抓取拿不到）

---

## §8 变更日志

| 日期 | 变更 |
|---|---|
| 2026-09-26 | 创建。完成跨项目 LLM 判断点清点、Jev 事实核查、3 个反模式识别、硬约束复验 |

---

## 相关文件

- `~/workspace/qt/docs/tracking/industry_heat_ai_feasibility.md` — 姊妹篇，AI 该用在哪 + §3 硬约束
- `~/workspace/qt/AGENTS.md` — Harness 最高层协议（含 No-Inference Rule）
- `~/workspace/qt/docs/Design_Proposal/QT_Hermes_Harness_Design.md` — AI 工作协议设计蓝图
- `~/.hermes/cron/jobs.json` — cron 任务定义（判断逻辑所在）
- `~/workspace/qt/docs/tracking/qt_backlog_tracker.md` — 项目级待办
