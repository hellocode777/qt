# AGENTS.md — QT (QP) Agent Engineering Standard v1.0

> 本项目（`~/workspace/qt`，CLI 名 `qp`）的 **Agent 行为规范**。
> 职责只有一个：**规定 Coding Agent 在项目中如何调查问题**——不是告诉 Agent 答案是什么，而是告诉它如何找到答案。
> 配套导航（不是权威，只是起点）：`docs/ai/PROJECT_MAP.md`、`docs/ai/MODULE_MAP.md`、`docs/ai/COMMAND_MAP.md`、`docs/ai/DATA_FLOW.md`。
> 权威：**当前代码 + 当前运行结果 + 测试 + 配置**。宪法：`docs/constitution/rule.md`。

## 1. Purpose

This repository is a quantitative research and investment decision platform.

When answering project-specific questions, prioritize repository evidence over general knowledge.

The goal is not to maximize the amount of context consumed.
The goal is to find the minimum sufficient evidence required to produce a correct answer.

---

## 2. Core Principle

For project-specific questions:

> Locate → Trace → Verify → Explain

Do not jump directly from the user's question to an explanation.

---

## 3. Evidence Priority

Use evidence in the following order:

1. Current source code
2. Current runtime output and logs
3. Tests
4. Current configuration
5. Current architecture documentation
6. Historical documentation
7. General knowledge

Higher-priority evidence overrides lower-priority assumptions.

Do not treat historical documentation as authoritative when it contradicts current code.

---

## 4. Repository Investigation

Before answering a project-specific question:

1. Identify the exact behavior, output, error, or object mentioned.
2. Locate the code that produces or controls that behavior.
3. Trace the relevant execution path.
4. Identify the inputs used by the relevant logic.
5. Inspect configuration when configuration affects the behavior.
6. Inspect runtime output when runtime state affects the behavior.
7. Inspect tests when they define or verify the behavior.
8. Only then formulate the answer.

Do not read the entire repository unless the question genuinely requires repository-wide analysis.

---

## 5. "Why" Questions

For questions such as:

* Why did this happen?
* Why is this value different?
* Why is this factor degraded?
* Why did this pipeline produce this result?

Always identify:

1. Where the behavior is defined.
2. Which function or component makes the decision.
3. Which condition was triggered.
4. What input values caused that condition.
5. Where those input values came from.

The final explanation must connect:

actual input
→ actual logic
→ actual condition
→ actual output

---

## 6. Execution and Behavior Questions

For questions about what a command, pipeline, or feature does,
trace the actual execution path.

Prefer:

CLI/API
→ entry point
→ orchestration
→ service
→ core logic
→ data source
→ output

Do not infer execution flow solely from filenames or directory names.
Verify imports and actual calls when necessary.

For this project: CLI entry is `qp` (`.venv/bin/qp`). Command groups map to
`qp/platform/cli/commands/*.py` — see `docs/ai/COMMAND_MAP.md`.

---

## 7. Data Questions

For questions involving data, explicitly verify:

* data source
* dataset
* date range
* universe
* filtering
* missing-value handling
* transformations
* feature/factor calculation
* target/forward return definition
* output dataset

Do not assume that a variable name or filename accurately describes the underlying data.

---

## 8. Quantitative / Factor Questions

For factor, IC, backtest, and strategy questions, verify the actual implementation of:

* factor definition
* factor direction
* lookback period
* forward return
* ranking
* winsorization
* normalization
* neutralization
* universe
* missing-value handling
* time alignment
* training/validation split
* transaction assumptions when relevant

Do not explain a quantitative result using financial intuition before verifying the implementation.

---

## 9. Configuration

When behavior may depend on configuration:

1. Locate the actual configuration file.
2. Determine the effective value used at runtime.
3. Check defaults and overrides.
4. Do not assume that a configuration value is active merely because it exists in a configuration file.

---

## 10. Runtime Evidence

When the user provides logs, metrics, command output, or error messages,
treat them as first-class evidence.

Prefer reproducing or inspecting the relevant runtime path when possible.

Do not replace observed runtime behavior with theoretical behavior.

---

## 11. Tests

Use tests as behavioral evidence.

When a test conflicts with documentation:

* inspect the current implementation;
* determine whether the test reflects intended current behavior;
* clearly identify the discrepancy.

Do not assume that tests are automatically correct.

---

## 12. Documentation

Documentation describes intended behavior.

Source code and runtime behavior describe actual behavior.

When they disagree, explicitly report the discrepancy.

Do not silently choose one interpretation.

---

## 13. Evidence Classification

Clearly distinguish:

### FACT

Directly supported by source code, runtime output, tests,
configuration, or other repository evidence.

### INFERENCE

A conclusion derived from available evidence but not directly stated by the repository.

### HYPOTHESIS

A possible explanation that has not been verified.

Never present an inference or hypothesis as an established fact.

### 13.1 No-Inference Rule (user-mandated)

Do NOT infer. Answers must be based only on verified evidence:

1. If a claim was not verified against code/data/runtime/tests, do NOT state it as part of the answer.
2. Instead: either verify it first, or explicitly state "not verified / unknown" and what evidence would be needed.
3. Never fill gaps in an answer with reasoning, guesses, or plausible-sounding assumptions to make it more complete.
4. When you did infer something, it must be labeled INFERENCE/HYPOTHESIS and the user may reject it — verified facts are the only safe content.
5. Reading a fragment (grep hit, partial file, schema glimpse) is NOT verification of the full picture. Read the complete definition/flow before claiming understanding of it.

This overrides the temptation to "connect the dots" — the user explicitly prefers "I don't know / insufficient evidence" over a confident guess.

---

## 14. Uncertainty

If the available evidence is insufficient:

State explicitly:

> Insufficient evidence to determine this from the current repository/context.

Then identify what evidence is missing.

Do not invent behavior.
Do not fill gaps with assumptions merely to produce a confident answer.

---

## 15. Investigation vs Modification

When the user asks:

* why
* what
* how
* explain
* investigate
* analyze
* understand

do not modify source code unless explicitly requested.

First investigate and explain.

When the user explicitly requests an implementation change,
switch to:

Investigate → Design → Modify → Test → Verify

In this project, "verify" means: `uvx ruff format --check .` + `uv run pyright` (no args) + relevant pytest. Run them yourself after modifying code; do not wait to be told.

---

## 16. Minimal Context Principle

Do not load unrelated files merely because they are nearby.

Prefer the smallest evidence set that can establish the answer.

Start with:

1. direct implementation
2. direct caller
3. direct inputs
4. relevant configuration
5. relevant runtime evidence
6. relevant tests

Expand the investigation only when the evidence chain is incomplete.

---

## 17. Avoid Broad Speculation

Do not answer repository-specific questions using generic software
engineering or quantitative-finance assumptions when the repository can provide evidence.

For example, do not say:

"Momentum probably failed because of regime change."

Instead determine:

* how momentum is calculated;
* how its direction is defined;
* how IC is calculated;
* which data was used;
* which period was used;
* what the actual observed result was.

Only then discuss possible explanations.

---

## 18. Final Answer Requirements

For concrete project questions, the final answer should normally contain:

1. Direct answer
2. Evidence
3. Relevant file/function
4. Reasoning chain
5. Uncertainty, if any

For example:

> The factor is classified as DEGRADED because `classify_health()`
> evaluates condition X, and the current IC value is Y. The IC is
> produced by `calculate_ic()` using dataset Z over period A-B.
> Therefore condition X is triggered.

Do not provide a long repository summary when the user asked for a specific answer.

---

## 19. Repository Navigation

Use the following AI navigation documents when they help locate relevant code:

* `docs/ai/PROJECT_MAP.md`
* `docs/ai/MODULE_MAP.md`
* `docs/ai/COMMAND_MAP.md`
* `docs/ai/DATA_FLOW.md`

These documents are navigation aids, **not authoritative substitutes for source code**.

Always verify important claims against the current implementation.

If a navigation document disagrees with source code, the source code wins — and update the navigation document.

---

## 20. Final Principle

The repository is the source of truth.

The Agent's job is not to guess what the system probably does.

The Agent's job is to determine what the system actually does,
using the minimum sufficient evidence.

---

## 21. Quant-Specific Verification

Whenever a change or conclusion involves quantitative logic
(factor / IC / backtest / strategy / data pipeline / experiment),
run the 11-item checklist in `docs/ai/QUANT_VERIFICATION_CHECKLIST.md`
and report the result in the final answer.

Checklist highlights (always verify, never assume):

* Look-ahead bias — computations use only information available at time t
* Future data leakage — training/validation/backtest windows do not leak future labels
* Universe leakage — stock universe does not include future listings/delistings
* Survivorship bias — conclusions not based only on currently listed stocks
* Factor direction — a negative IC is EXPECTED for A-share momentum/price-volume
  factors with direction=-1; check `qp/research/feature/*.py` raw definitions first
* Rebalance timing — signal generation date aligned with execution date
* Transaction assumptions — fees/stamp duty/slippage consistent with cost model
* Missing data — suspensions/NaN handling not masked by `keep="last"` merges
* Corporate action — price jumps are adjustments, not raw unadjusted moves
* Date alignment — trade_date dtype (Date vs str) unified before joins
* Train/test contamination — PurgedKFold purge/embargo effective;
  never hardcode short-sample optimal parameters into production without
  full walk-forward / OOS validation

For non-quant changes (WebUI / docs), state "not quant-relevant" and skip.

---

## 22. Git Safety (master 直改纪律)

This project works on `master` directly (single developer). Discipline instead of branches:

1. Before any commit: run `git status` + `git diff` + `git diff --stat`
2. Check for: unexpected files, unrelated changes, deleted files,
   config changes, generated files, documentation drift
3. Never commit `data/` runtime artifacts unless intended
   (`data/strategy_registry.json` is tracked and can silently change lifecycle —
   verify JSON validity and diff before committing)
4. Commit message follows conventional commits (`feat/fix/docs/chore/refactor`)
5. If a change touches strategy/risk/capital/decision/production paths,
   it is production-sensitive: require explicit user approval before committing

---

## 附录 A — 提问模板（用户侧）

```
[QP QUESTION]

问题：<一句话说清现象>
目标：<解释原因 / 定位代码 / 修复 / 只诊断不改码>
相关命令：<实际跑过的 qp 命令>
相关输出：<真实输出原文>
期望：
1. 先定位（代码/数据/日志）
2. 再解释（标 FACT/INFERENCE/HYPOTHESIS）
3. <不修改代码 / 修改后自行验证>
Context：docs/ai/（四张地图）
相关文件：<候选文件清单>
```

## 附录 B — 修改边界速查

| 场景 | 动作 |
|---|---|
| 用户要求修 | 改，改完自己跑验证（ruff format --check + pyright + pytest），汇报结果 |
| 用户只要解释 | 只诊断不落盘；验证用只读方式（读 parquet、调私有方法不触发副作用） |
| 涉及架构 | 先写 ADR 再改（宪法要求） |
| 合规风险 | 先查 `docs/constitution/rule.md`（28 条宪法） |
| 数据文件 | raw 不可变只追加；改 dataset/registry 前确认消费方 |
| 维护 | 文件/命令/路径变化 → 同步更新 docs/ai/ 对应地图（导航层过时 = 违规） |

## 附录 C — 本项目其他权威文档

- 宪法（完整版）：`docs/constitution/rule.md`；精简版：`docs/constitution/constitution-v4.2.md`
- 人读指南：`docs/user_guide.md`、`docs/developer_guide.md`
- 架构决策：`docs/archive/adr/`（ADR-xxx，改架构先看）
- 技术选型：`docs/tdr/`（TDR-xxx）
- 项目导航（新 Agent 第一站）：`AI_PROJECT_CONTEXT.md`
- 量化专项验证清单：`docs/ai/QUANT_VERIFICATION_CHECKLIST.md`（§21 配套）
- 任务留痕模板：`docs/templates/TASK_RECORD.md`
- 项目记忆：`.hermes/memory/`（README 说明四类目录 + Memory ≠ Source of Truth）
