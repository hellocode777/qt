> **来源:** Obsidian `1-Projects/qt harness.md`（用户笔记，2026-08-13 归档至此）
> **状态:** ✅ 已实现（2026-08-13, commit c46715a，11 文件 +482 行；实现计划见 `.hermes/plans/2026-08-13_142351-qt-hermes-harness.md`）
> **注意:** 本文是 Harness 的**设计蓝图**（为什么这么设计），落地后的实际文件才是事实源——AGENTS.md / AI_PROJECT_CONTEXT.md / docs/ai/* / .hermes/memory/。读设计稿时对照已实现文件，设计稿中未落地的部分（如项目内 .hermes/skills/ 12 个目录、.hermes/config/、.hermes/agents/）已适配为「能力在全局 qp-project skill、导航在项目」方案，勿重复实现。

---

结合你现在的 QT 状态，我建议不要把 Hermes Harness 做成一堆零散的 prompt，而是把它设计成 **QT 的第二套工程基础设施**：

> **Code 是系统事实源，Harness 是 AI 的工作协议，Memory 是决策历史，Skills 是专业能力，Git/Test 是执行边界。**

你前面已经确定了一个很重要的原则：**AI 不应该靠一次性塞入大量 Context 来理解 QT，而应该自己 Locate → Trace → Verify → Explain。** 这应该直接成为 Harness 的核心。

---

# 一、整体架构

> **落地状态: ⚠️ 目标架构图（非现状）** — 实际已落地：`AGENTS.md` / `AI_PROJECT_CONTEXT.md` / `.hermes/memory/`（4 类目录+project-state+README）/ `docs/ai/`（四张地图 + QUANT_VERIFICATION_CHECKLIST）。**未建**：`.hermes/config/`、`.hermes/skills/`（12 个 qt-*）、`.hermes/agents/`（6 个角色）——原因见 §五/§十五 适配说明。实际源码目录是 `qp/`（12 层），docs 实际含 `constitution/ tdr/ archive/ Design_Proposal/ tracking/` 等。

我建议最终形成：

```text
QT Repository
│
├── AGENTS.md                         ← AI 总规则 / 工作协议
│
├── AI_PROJECT_CONTEXT.md             ← 项目当前状态 + 总体地图
│
├── .hermes/
│   ├── config/
│   │   ├── agent.yaml
│   │   ├── permissions.yaml
│   │   └── workflows.yaml
│   │
│   ├── skills/
│   │   ├── qt-understand/
│   │   ├── qt-investigate/
│   │   ├── qt-architecture/
│   │   ├── qt-data/
│   │   ├── qt-factor/
│   │   ├── qt-strategy/
│   │   ├── qt-validation/
│   │   ├── qt-pipeline/
│   │   ├── qt-debug/
│   │   ├── qt-test/
│   │   ├── qt-review/
│   │   └── qt-documentation/
│   │
│   ├── agents/
│   │   ├── architect.md
│   │   ├── quant-researcher.md
│   │   ├── data-engineer.md
│   │   ├── python-engineer.md
│   │   ├── test-engineer.md
│   │   └── reviewer.md
│   │
│   └── memory/
│       ├── decisions/
│       ├── discoveries/
│       ├── failures/
│       ├── workflows/
│       └── project-state.md
│
├── docs/
│   ├── ai/
│   │   ├── PROJECT_MAP.md
│   │   ├── MODULE_MAP.md
│   │   ├── COMMAND_MAP.md
│   │   └── DATA_FLOW.md
│   │
│   ├── architecture/
│   ├── operations/
│   ├── engineering/
│   ├── research/
│   └── decisions/
│
├── tests/
├── src/
├── scripts/
└── .github/
```

这里有一个很重要的区别：

### `AGENTS.md`

告诉 Hermes：

> **怎么工作。**

### `AI_PROJECT_CONTEXT.md`

告诉 Hermes：

> **QT 是什么。**

### `docs/ai/*`

告诉 Hermes：

> **去哪里找。**

### `.hermes/skills/*`

告诉 Hermes：

> **怎么完成专业任务。**

### `.hermes/memory/*`

告诉 Hermes：

> **过去发生过什么，以及为什么。**

### Code / Tests / Git

告诉 Hermes：

> **什么才是真实的。**

---

# 二、`AGENTS.md`：整个 Harness 的最高层协议

> **落地状态: ✅ 已实现** — `AGENTS.md`（项目根，22 节）。协议核心与设计稿一致：Source of Truth 优先级、Locate→Trace→Verify→Explain、证据分级（FACT/INFERENCE/HYPOTHESIS）、no-guessing、调查≠修改、最小 Context、Quant 专项验证（§20-21）、Git 纪律。

这个文件我建议放在 repository root。

它不是项目介绍，而是 **Agent Operating System**。

核心内容应该是：

```text
QT AI ENGINEERING PROTOCOL

1. Source of Truth
   Code > Tests > Runtime/CLI output > Registry/Data > Documentation > Memory

2. Investigation
   Locate → Trace → Verify → Explain

3. Modification
   Understand → Plan → Implement → Test → Review

4. No Guessing
   If evidence is insufficient, explicitly state uncertainty.

5. Investigation ≠ Modification
   Investigation tasks must not modify project files.

6. Minimal Context
   Load only context relevant to the current task.

7. Documentation
   Never trust documentation blindly.
   Verify important claims against current code.

8. Research Integrity
   Never alter historical experiment results.
   Never fabricate metrics.
   Never confuse backtest, validation, paper trading and production.

9. Quant Integrity
   Never introduce look-ahead bias.
   Never silently change factor direction.
   Never silently change universe definition.
   Never silently change rebalance assumptions.

10. Verification
    Every code change must have an explicit verification result.

11. Git Safety
    Work on a branch.
    Review diff before commit.
    Never overwrite unrelated changes.

12. Explainability
    Final response must distinguish:
    - observed facts
    - inferred conclusions
    - assumptions
    - unresolved questions
```

这套规则非常重要。

因为你不应该依赖 Hermes “聪明”。

而应该让它**在错误的时候也有边界**。

---

# 三、`AI_PROJECT_CONTEXT.md`

> **落地状态: ✅ 已实现** — `AI_PROJECT_CONTEXT.md`（项目根，导航层，<200 行）。按设计稿模板：Project Identity / 12 层架构 / Runtime Flow / Research Flow / 指向 docs/ai/ 四图 + tracking，不写实现细节。

这个文件应该非常短。

我建议控制在 **100～200 行左右**，而不是几千行。

它只做导航。

例如：

```text
# QT AI Project Context

## 1. Project Identity

QT is a personal quantitative research and investment
decision-support platform for China A-shares.

The system provides research, validation, portfolio,
risk and decision support.

Human executes trades.
QT does not autonomously execute trades.

## 2. Architecture

QT follows a 12-layer architecture:

Platform
Data
Research
Registry & Lineage
Validation Gate & Research Review
Strategy Engine
Portfolio Risk
Capital Allocation
Simulation
Decision
Monitoring
Knowledge

See:
docs/ai/PROJECT_MAP.md

## 3. Primary Runtime Flow

Data
→ Factor Calculation
→ Strategy
→ Validation
→ Portfolio/Risk
→ Decision
→ Monitoring

Daily production flow:
data_fetch
→ monitor_check
→ pre_close_check
→ daily_pipeline

## 4. Research Flow

Research
→ Experiment
→ Backtest
→ Validation Gate
→ Paper Trading
→ Shadow Production
→ Production

## 5. Factor System

Factor Library
→ Factor Calculation
→ Factor Health Monitor
→ Strategy Selection

Current factor health information:
docs/research/factor-health.md

## 6. Important Systems

Data:
...

Factors:
...

Strategies:
...

Validation:
...

Daily Pipeline:
...

WebUI:
...

## 7. Engineering Rules

See:
AGENTS.md
docs/engineering/

## 8. Current Project State

Current phase:
...

Current active work:
...

Known issues:
...

Recent decisions:
docs/decisions/

## 9. Navigation

Architecture:
docs/ai/PROJECT_MAP.md

Modules:
docs/ai/MODULE_MAP.md

Commands:
docs/ai/COMMAND_MAP.md

Data flow:
docs/ai/DATA_FLOW.md
```

注意：

**不要把具体实现细节写进这里。**

比如：

```text
factor_health.py 第 238 行……
```

绝对不要。

那是 Agent 应该自己去找的。

---

# 四、AI Navigation Maps

> **落地状态: ✅ 已实现** — `docs/ai/` 四张地图（PROJECT_MAP / MODULE_MAP / COMMAND_MAP / DATA_FLOW）+ `QUANT_VERIFICATION_CHECKLIST.md`。COMMAND_MAP 按 `qp` CLI 实测更新（2026-08-11）。更新规则：只写方法/机制，不写当前运行状态（避免过时）。

这是你这个项目特别值得做的一层。

你之前已经确定：

> retained maps are navigation only.

我非常赞成。

建立四张地图：

```text
docs/ai/

PROJECT_MAP.md
MODULE_MAP.md
COMMAND_MAP.md
DATA_FLOW.md
```

---

## 1. PROJECT_MAP

回答：

> QT 有哪些 subsystem？

```text
Platform
 ├── configuration
 ├── logging
 └── CLI

Data
 ├── ingestion
 ├── bronze
 ├── silver
 └── gold

Research
 ├── factors
 ├── experiments
 └── backtest

...

Decision
 ├── scoring
 ├── portfolio
 └── decision package
```

---

## 2. MODULE_MAP

回答：

> 某个功能对应哪些模块？

例如：

```text
Factor Health

factor_library.py
       ↓
factor_health.py
       ↓
factor_monitor.py
       ↓
factor_report.py
       ↓
factor_registry.json
```

---

## 3. COMMAND_MAP

这是你这个项目特别重要的一张。

例如：

```text
uv run qp factor update-health

Purpose:
Update full-history factor health.

Input:
Historical factor dataset

Output:
Factor health metrics

Used by:
Research / Monitoring

Do not use for:
Daily factor calculation
```

这样 Hermes 不需要每次 grep CLI。

---

## 4. DATA_FLOW

描述：

```text
AkShare
   ↓
Raw
   ↓
Bronze
   ↓
Silver
   ↓
Gold
   ↓
Dataset
   ↓
Factor
   ↓
Strategy
   ↓
Decision Package
```

并明确：

```text
historical data
latest data
experiment data
production data
```

分别在哪里。

---

# 五、Skills 体系

> **落地状态: ⚠️ 已适配（不建 12 个项目内 skill）** — 原因：Hermes 的 skills 加载自**全局** `~/.hermes/skills/`，项目内 `.hermes/skills/` 不会被自动加载；且 12 个拆分是过度工程、每次加载成本高。落地方式：职责全部并入全局 `qp-project` skill（18 个 references，已覆盖 understand/investigate/architecture/data/factor/strategy/validation/pipeline/debug/test/review/documentation）。边界：「能力在全局 skill、导航在项目」。

这里是整个 Harness 的核心。

我建议不要创建 30 个 Skill。

第一版只需要 **12 个**。

```text
.hermes/skills/

qt-understand/
qt-investigate/
qt-architecture/
qt-data/
qt-factor/
qt-strategy/
qt-validation/
qt-pipeline/
qt-debug/
qt-test/
qt-review/
qt-documentation/
```

---

# 六、Skill 之间的职责

> **落地状态: ⚠️ 已并入 qp-project / AGENTS.md** — 本节及 §七~§十四 的 12 个 skill 职责设计已落实为 qp-project skill 的工作流（如因子诊断流程「先查 direction 再判失效」、research integrity 五结果区分、validation Gatekeeper 语义、测试分层按修改范围选择）。

## `qt-understand`

用途：

> “这个模块是干什么的？”

流程：

```text
Locate
 ↓
Entry Point
 ↓
Call Graph
 ↓
Dependencies
 ↓
Data Flow
 ↓
Tests
 ↓
Explain
```

**禁止修改代码。**

---

## `qt-investigate`

用途：

> “为什么出现这个问题？”

必须产生：

```text
Observed Facts
Possible Causes
Evidence
Eliminated Causes
Root Cause
Confidence
```

而不是直接修。

---

# 七、`qt-architecture`

用于：

> “这个功能应该放在哪一层？”

它必须检查：

```text
Layer responsibility
Dependency direction
Existing abstractions
Circular dependency
Coupling
Data ownership
```

例如不能因为：

> “Daily Pipeline 需要一个功能”

就直接把代码塞进：

```text
daily_pipeline.py
```

而应该先判断这个能力属于：

```text
Data
Factor
Strategy
Decision
Monitoring
```

中的哪一层。

---

# 八、`qt-factor`

这个 Skill 要特别专业。

它应该理解你现在的：

```text
Factor Library
Factor Registry
Factor Health
IC
IC30
IC_IR
Direction
Factor Selection
Regime
```

并明确区分：

```text
Factor definition
Factor calculation
Factor evaluation
Factor health
Factor strategy usage
```

例如：

> Momentum_3M DEGRADED

不能直接回答：

> 删除 Momentum_3M。

而应该：

```text
Factor Definition
        ↓
Historical IC
        ↓
IC30
        ↓
IC IR
        ↓
Recent deterioration
        ↓
Regime behavior
        ↓
Current strategy weight
        ↓
Recommendation
```

---

# 九、`qt-strategy`

用于：

```text
strategy
experiment
backtest
ablation
feature selection
model
portfolio
```

必须严格区分：

```text
Research result
≠
Backtest result
≠
Validation result
≠
Paper trading result
≠
Production result
```

这是你的 QT 里非常重要的防错规则。

---

# 十、`qt-validation`

这个 Skill 应该成为一个 **Gatekeeper**。

例如：

```text
Research
   ↓
Backtest
   ↓
Validation Gate
   ↓
Paper Trading
   ↓
Shadow Production
   ↓
Production
```

Hermes 不能因为：

```text
Sharpe = 1.5
```

就说：

> “策略可以生产。”

必须检查整个 gate。

---

# 十一、`qt-pipeline`

专门理解：

```text
data_fetch
monitor_check
pre_close_check
daily_pipeline
```

并区分：

### Historical

```text
Full-history factor health
Experiment
Backtest
```

### Daily

```text
Yesterday's market data
        ↓
Today's factor values
        ↓
Today's score
        ↓
Today's decision package
```

这个 Skill 可以避免你之前遇到的“历史因子更新”和“Daily Pipeline 因子计算”概念混淆。

---

# 十二、`qt-debug`

这个 Skill 我建议强制：

```text
Reproduce
 ↓
Observe
 ↓
Trace
 ↓
Identify
 ↓
Fix
 ↓
Regression Test
```

禁止：

```text
Error
 ↓
猜原因
 ↓
改代码
 ↓
希望好了
```

---

# 十三、`qt-test`

必须知道：

```text
unit tests
integration tests
pipeline tests
data validation
regression tests
```

并根据修改范围选择测试，而不是每次盲目：

```text
pytest entire-project
```

---

# 十四、`qt-review`

这是非常重要的第二双眼睛。

它不应该重新实现代码。

只负责：

```text
Correctness
Architecture
Regression
Data leakage
Look-ahead bias
Performance
Tests
Documentation
Unintended changes
```

---

# 十五、Agent Roles

> **落地状态: ❌ 未建项目内 agents 目录** — 不创建 `architect.md / quant-researcher.md / data-engineer.md / python-engineer.md / test-engineer.md / reviewer.md`。角色职责由 Hermes 主 agent 直接承担；分工协作通过 `delegate_task` 子代理（§十六）实现。

Skills 和 Agents 不一样。

**Skill = 能力**

**Agent = 角色**

我建议：

```text
.hermes/agents/

architect.md
quant-researcher.md
data-engineer.md
python-engineer.md
test-engineer.md
reviewer.md
```

---

## Architect

负责：

```text
Architecture
Dependency
Design
Refactoring
Layer boundaries
```

禁止直接大规模实现。

---

## Quant Researcher

负责：

```text
Factor
IC
IC_IR
Regime
Backtest
Experiment
Strategy
```

它必须特别严格地遵守 research integrity。

---

## Data Engineer

负责：

```text
Data ingestion
Parquet
Schema
Data quality
Pipeline
Lineage
```

---

## Python Engineer

负责：

```text
Implementation
Refactoring
Performance
CLI
Libraries
```

---

## Test Engineer

负责：

```text
Test design
Regression
Integration
Edge cases
```

---

## Reviewer

负责：

> 找问题，而不是证明代码没问题。

---

# 十六、一个任务不要只让一个 Agent 做到底

> **落地状态: ⚠️ 部分落地** — Orchestrator + Specialist 模式存在：Hermes 主 agent 编排 + `delegate_task` 子代理分工（如批量调查/并行验证）。但无项目内独立 agent 定义文件（见 §十五）。

这是我最推荐你的工作方式。

例如：

> “优化 Factor Health Monitor。”

不要：

```text
Hermes
 ↓
全部完成
```

而是：

```text
Architect
    ↓
Design

Quant Researcher
    ↓
Validate research logic

Python Engineer
    ↓
Implementation

Test Engineer
    ↓
Tests

Reviewer
    ↓
Final review
```

最后由 Hermes 主 Agent 汇总。

这就是：

> **Orchestrator + Specialist Agents**

---

# 十七、Memory 体系

> **落地状态: ✅ 已实现** — `.hermes/memory/`：`decisions/ discoveries/ failures/ workflows/`（四类目录）+ `project-state.md` + `README.md`（记录四类语义 + Memory 优先级）。**注意**：正式 ADR 在 `docs/archive/adr/`（ADR-001~033），`.hermes/memory/decisions/` 只放非 ADR 级补充决策。

Memory 千万不要变成：

```text
memory.md
```

然后无限增长。

我建议：

```text
.hermes/memory/

project-state.md

decisions/
    ADR-001-xxx.md
    ADR-002-xxx.md

discoveries/
    factor-health-xxx.md
    pipeline-xxx.md

failures/
    incident-xxx.md

workflows/
    daily-pipeline.md
    research-workflow.md
```

---

# 十八、Memory 有四种东西

## 1. Decision

记录：

> 为什么这么设计。

例如：

```text
ADR-004-daily-factor-calculation.md
```

---

## 2. Discovery

记录：

> 我们发现了什么。

例如：

```text
Momentum_3M 在最近 30 日 IC 显著下降。
```

---

## 3. Failure

记录：

> 什么方法失败过。

这对 Agent 特别重要。

例如：

```text
某次修改直接改变 factor direction
导致历史实验不可比较。
```

以后 Hermes 就不会轻易重复。

---

## 4. Workflow

记录：

> 某项事情应该怎么做。

例如：

```text
Research Strategy
→ Experiment
→ Validation
→ Paper Trading
```

---

# 十九、Memory 的一个关键原则

我建议：

> **Memory 不是事实源。**

优先级：

```text
Code
 ↓
Tests
 ↓
Runtime
 ↓
Registry/Data
 ↓
Documentation
 ↓
Memory
 ↓
Agent inference
```

如果 Memory 说：

```text
Strategy 使用 5 个 factors
```

但 registry 现在是 6 个：

**相信 registry。**

然后把 drift 报告出来。

---

# 二十、任务协议

> **落地状态: ✅ 已实现** — 任务协议 Level 0-5 已写入 qp-project skill + AGENTS.md：L0 Explain / L1 Investigate / L2 Design / L3 Implement / L4 Refactor（架构分析+回归测试+diff 审查）/ L5 Production-sensitive（Plan+显式 approval+Tests+Review）。

这是 Harness 最核心的协议。

所有任务统一：

```text
REQUEST
   ↓
CLASSIFY
   ↓
LOCATE
   ↓
TRACE
   ↓
VERIFY
   ↓
PLAN
   ↓
APPROVAL
   ↓
IMPLEMENT
   ↓
TEST
   ↓
REVIEW
   ↓
REPORT
```

但是不是每个任务都需要全部步骤。

---

## Level 0 — Explain

```text
只解释。
不修改。
```

---

## Level 1 — Investigate

```text
调查问题。
不修改。
```

---

## Level 2 — Design

```text
设计方案。
不修改。
```

---

## Level 3 — Implement

```text
执行已经批准的方案。
```

---

## Level 4 — Refactor

必须：

```text
Architecture analysis
+
Regression tests
+
Diff review
```

---

## Level 5 — Production-sensitive

涉及：

```text
Strategy
Risk
Capital
Decision
Production
```

必须：

```text
Plan
+
Explicit approval
+
Tests
+
Review
```

---

# 二十一、每个任务都应该产生 Task Record

> **落地状态: ✅ 已实现** — `docs/templates/TASK_RECORD.md`（Task ID / Type / Goal / Scope / Files inspected / Evidence / Conclusion / Confidence / Changes / Tests / Follow-up），作为 `.hermes/memory/` 的来源。

例如：

```text
Task ID:
QT-2026-0813-001

Type:
Investigate

Goal:
Why Momentum_3M became DEGRADED?

Scope:
factor system

Files inspected:
...

Evidence:
...

Conclusion:
...

Confidence:
HIGH

Changes:
NONE

Tests:
N/A

Follow-up:
...
```

这样以后 Memory 又有来源了。

---

# 二十二、Git 工作流

> **落地状态: ⚠️ 已适配（方案 A，2026-08-13 确认）** — **维持 master 直推**（用户长期习惯，单人项目），未引入 feature 分支。落地为 AGENTS.md git 纪律：改动前 `git status`/`git diff` 审查、commit 前确认测试范围、GFW push 重试配置。设计稿「Hermes 不能直接改 main」未采用。

我建议：

```text
main
 │
 ├── feature/...
 ├── fix/...
 ├── research/...
 └── refactor/...
```

Hermes 默认：

> **不能直接修改 main。**

---

任务：

```text
User request
      ↓
Create branch
      ↓
Hermes investigation
      ↓
Plan
      ↓
Implementation
      ↓
Tests
      ↓
Diff
      ↓
Reviewer
      ↓
Commit
```

---

# 二十三、Git Diff 是 AI 的最后一道防线

Agent 完成任务后必须：

```text
git status
git diff
git diff --stat
```

检查：

```text
Unexpected files
Unrelated changes
Deleted files
Config changes
Generated files
Documentation drift
```

然后才能 commit。

---

# 二十四、测试分层

> **落地状态: ✅ 已落地为项目规范** — 门禁：`uvx ruff format --check` + `uvx ruff check` → `uv run pyright`（0 errors）→ 相关 pytest（先受影响模块局部测试，提交前问用户是否跑全量 1499 个 ~94s）。按修改范围选择测试，不盲目全量。

我建议 QT 的验证流程：

```text
                 Change
                   │
                   ▼
              Syntax / Import
                   │
                   ▼
                Ruff
                   │
                   ▼
              Unit Tests
                   │
                   ▼
           Targeted Integration
                   │
                   ▼
             Pipeline Test
                   │
                   ▼
          Full Regression
```

不是每个任务都跑 Full Regression。

例如：

### 改 WebUI

```text
ruff
targeted tests
web tests
```

### 改 Factor

```text
ruff
factor tests
research regression
```

### 改 Data Pipeline

```text
ruff
data tests
pipeline integration
validation gate
```

### 改 Strategy

```text
ruff
strategy tests
backtest regression
validation
```

---

# 二十五、Quant-specific Verification

> **落地状态: ✅ 已实现（设计稿最有价值部分）** — `docs/ai/QUANT_VERIFICATION_CHECKLIST.md`（11 项清单）+ AGENTS.md §20-21。量化改动自检项全部保留：look-ahead bias / future leakage / universe leakage / survivorship / factor direction / rebalance timing / transaction assumptions / missing data / corporate action / date alignment / train-test contamination。

这是普通 coding agent 没有的，但你的 Hermes 必须有。

涉及量化逻辑时自动检查：

```text
[ ] Look-ahead bias
[ ] Future data leakage
[ ] Universe leakage
[ ] Survivorship bias
[ ] Factor direction
[ ] Rebalance timing
[ ] Transaction assumptions
[ ] Missing data
[ ] Corporate action
[ ] Date alignment
[ ] Train/test contamination
```

这一层我认为是你整个 Harness **最有价值的部分之一**。

---

# 二十六、Documentation Governance

> **落地状态: ⚠️ 已适配** — Documentation Drift Check 方法论已入 qp-project skill（分层验证：路径级 / 行号级 / 命令级 / 状态级）；文档引用代码用「文件+符号名」禁行号；docs/ai/ 只写方法不写状态（去掉具体策略名/时间点后仍成立=方法）。

最后建立一个：

```text
Documentation Drift Check
```

Hermes 定期扫描：

```text
Code
   ↓
Docs
   ↓
Compare
   ↓
Drift
```

输出：

```text
Documentation Health

architecture.md       PASS
factor-system.md      WARNING
daily-pipeline.md     DEGRADED
validation-gate.md    PASS
user-guide.md         STALE
```

然后：

> **AI 修改文档必须基于当前代码，而不是反过来让代码迁就旧文档。**

这和你之前整理 QT MD 文件的方向完全一致。

---

# 二十七、最终的 Harness 工作流

最后整个系统应该变成：

```text
                       USER
                         │
                         ▼
                    HERMES
                  Orchestrator
                         │
             ┌───────────┴───────────┐
             │                       │
         Context                  Task
             │                       │
             ▼                       ▼
    AI_PROJECT_CONTEXT          Classify
    PROJECT_MAP                    │
    MODULE_MAP                     ▼
    COMMAND_MAP                  Locate
    DATA_FLOW                      │
             │                     ▼
             │                   Trace
             │                     │
             └─────────────┬───────┘
                           ▼
                       Specialist
                         Agent
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          Architect      Quant       Engineer
              │            │            │
              └────────────┼────────────┘
                           ▼
                         Plan
                           │
                      Approval
                           │
                           ▼
                      Implement
                           │
                           ▼
                         Test
                           │
                           ▼
                        Review
                           │
                           ▼
                       Git Diff
                           │
                           ▼
                        Commit
                           │
                           ▼
                         Memory
                           │
                           ▼
                      Final Report
```

---

# 二十八、我建议你最终把它收敛成这套目录

> **落地状态: ⚠️ 目标目录（非现状），与实际差异** — `src/`→实际为 `qp/`；docs 实际多出 `constitution/ tdr/ archive/ Design_Proposal/ tracking/`；无 `.hermes/config/ .hermes/skills/ .hermes/agents/`（见 §一/§五/§十五）。已实现部分：AGENTS.md / AI_PROJECT_CONTEXT.md / .hermes/memory/ / docs/ai/。

这是我认为目前最适合你 QT 的 **v1.0 Harness**：

```text
QT/
│
├── AGENTS.md
├── AI_PROJECT_CONTEXT.md
│
├── .hermes/
│   │
│   ├── config/
│   │   ├── agent.yaml
│   │   ├── permissions.yaml
│   │   └── workflows.yaml
│   │
│   ├── skills/
│   │   ├── qt-understand/
│   │   ├── qt-investigate/
│   │   ├── qt-architecture/
│   │   ├── qt-data/
│   │   ├── qt-factor/
│   │   ├── qt-strategy/
│   │   ├── qt-validation/
│   │   ├── qt-pipeline/
│   │   ├── qt-debug/
│   │   ├── qt-test/
│   │   ├── qt-review/
│   │   └── qt-documentation/
│   │
│   ├── agents/
│   │   ├── architect.md
│   │   ├── quant-researcher.md
│   │   ├── data-engineer.md
│   │   ├── python-engineer.md
│   │   ├── test-engineer.md
│   │   └── reviewer.md
│   │
│   └── memory/
│       ├── project-state.md
│       ├── decisions/
│       ├── discoveries/
│       ├── failures/
│       └── workflows/
│
├── docs/
│   ├── ai/
│   │   ├── PROJECT_MAP.md
│   │   ├── MODULE_MAP.md
│   │   ├── COMMAND_MAP.md
│   │   └── DATA_FLOW.md
│   │
│   ├── architecture/
│   ├── operations/
│   ├── engineering/
│   ├── research/
│   └── decisions/
│
├── src/
├── tests/
├── scripts/
└── .github/
```

---

# 二十九、最重要的三个设计决定

> **落地状态: ✅ 三个决定全部落地** — ① Context≠知识库（AI_PROJECT_CONTEXT 只导航）② Skill≠Prompt（qp-project 是可执行 SOP）③ Memory≠Source of Truth（`.hermes/memory/README.md` 明文 Code > Tests > Runtime > Registry > Docs > Memory）。

如果只记住三个东西，我建议记这三个。

### ① Context 不等于知识库

```text
AI_PROJECT_CONTEXT
        ↓
Navigation
        ↓
Agent自行 Locate / Trace
```

不要把整个 QT 塞进 Context。

---

### ② Skill 不等于 Prompt

Skill 应该定义：

```text
输入
↓
前置条件
↓
执行步骤
↓
验证
↓
输出格式
↓
禁止事项
```

它实际上是一个**可执行工程 SOP**。

---

### ③ Memory 不等于 Source of Truth

```text
Code / Test / Runtime
        ↓
     Truth
        ↓
Documentation
        ↓
Memory
```

这能避免 Agent “记住了一个已经过时的 QT”。

---

# 三十、最终目标

做到这个程度以后，你每天和 Hermes 的交互会从：

> “你先看看这个文件，然后看看那个文件，然后我告诉你背景……”

变成：

> **“Investigate why Momentum_3M is DEGRADED.”**

Hermes 自己：

```text
Locate
→ Trace
→ Load relevant context
→ inspect factor registry
→ inspect health history
→ inspect strategy usage
→ inspect recent experiments
→ verify data
→ consult prior decisions
→ produce evidence-based diagnosis
```

再比如：

> **“Design a fix for the Daily Pipeline factor calculation.”**

它应该自己知道：

```text
Daily Pipeline
↓
Factor calculation
↓
Factor Registry
↓
Factor Library
↓
Strategy
↓
Decision Package
```

而不是让你重新解释整个 QT。

这才是我认为 **Hermes + QT Agent Harness** 真正应该达到的状态：

> **不是让 AI 更会写代码，而是让 AI 成为一个长期、可验证、不会轻易遗忘架构与研究原则的 QT 工程师。**

而且你之前已经确定的 **Locate → Trace → Verify → Explain、evidence priority、no-guessing、investigation 不修改、maps 只做 navigation**，我建议全部保留，直接作为这个 Harness 的核心 v1.0 规范。