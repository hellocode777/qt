# QT Hermes Harness v1.0 落地计划

> **For Hermes:** 按本计划 task-by-task 执行。纯文档/配置任务，无代码改动，不需要 TDD 循环，但每个 task 需要验证文件内容与一致性。
> **来源:** Obsidian `1-Projects/未命名.md`（1713 行设计稿）→ 用户确认落地到 `~/workspace/qt`。

**Goal:** 把设计稿中的 Hermes Harness 体系落地到 QT 仓库，让 Hermes 从「每次解释 QT」变为「自己 Locate → Trace → Verify → Explain」。

**架构原则（来自设计稿 §二十九，与现有 AGENTS.md 一致）：**
1. Context ≠ 知识库 — AI_PROJECT_CONTEXT 只做导航，Agent 自己找
2. Skill ≠ Prompt — Skill 是可执行工程 SOP
3. Memory ≠ Source of Truth — Code/Test/Runtime > Registry > Docs > Memory

**现状基线（已实测确认）：**
- ✅ `AGENTS.md` 已有（19 节，9887B，核心协议已覆盖 Locate→Trace→Verify→Explain / 证据分级 / no-guessing / 调查≠修改 / maps 只做导航）
- ✅ `docs/ai/` 四张地图已有（PROJECT_MAP 122行 / MODULE_MAP 137行 / COMMAND_MAP 93行 / DATA_FLOW 74行）
- ✅ ADR 体系已有（`docs/archive/adr/ADR-001~033`，2026-08-13 补全）
- ✅ `docs/constitution/rule.md` 宪法 + CI + tests/unit|integration|e2e + .github workflows
- ❌ 缺：`AI_PROJECT_CONTEXT.md`、`.hermes/` 目录、Task Record 模板、Quant 专项验证清单、git 分支策略

**关键适配（与设计稿不同之处）：**
- Hermes 的 skills 实际加载自 `~/.hermes/skills/`（全局），**不是**项目内 `.hermes/skills/`。qt 的 skill 已有 `qp-project`（18 个 references 的综合 skill）。因此：
  - 项目内不建 12 个 skill 目录（设计稿的目录结构是给 Claude Code 类工具的通用模板）
  - 落地方式 = 在 `qp-project` skill 上补充 Harness 特有内容（Quant 验证清单、Task Record 流程），保持「能力在全局 skill、导航在项目」的边界
- 项目内 `.hermes/` 保留设计稿中的 **memory/**（decisions/discoveries/failures/workflows + project-state.md）作为项目决策档案入口，因为这是 git 版本化的项目资产，不是 Hermes 运行时配置

---

## 任务清单

### Task 1: AI_PROJECT_CONTEXT.md（核心，设计稿 §三）

**Objective:** 建立根目录导航文件，100-200 行，只描述 QT 是什么 + 去哪里找，不含实现细节。

**Files:**
- Create: `AI_PROJECT_CONTEXT.md`（项目根）

**内容结构（按设计稿 §三模板，结合 QT 实际）：**
1. Project Identity — QP 是 A 股量化研究与投资决策支持平台，人类执行交易，QT 不自动交易
2. Architecture — 12 层架构 + 指向 docs/ai/PROJECT_MAP.md
3. Primary Runtime Flow — data_fetch → monitor_check → pre_close_check → daily_pipeline
4. Research Flow — Research → Experiment → Backtest → Validation Gate → Paper Trading → Shadow → Production
5. Factor System — Factor Library → Calculation → Health Monitor → Strategy Selection
6. Engineering Rules — 指向 AGENTS.md + docs/engineering/
7. Current Project State — 指向 docs/tracking/qt_backlog_tracker.md + Obsidian 1-Projects（不写死状态）
8. Navigation — 四张地图链接 + CLI 入口说明（qp）

**验证:** 读回文件，确认 <200 行、无实现细节（不含「factor_health.py 第 238 行」类内容）、所有链接路径真实存在。

---

### Task 2: Quant 专项验证清单（设计稿 §二十五，最有价值部分）

**Objective:** 建立量化逻辑改动前的 11 项自动检查清单，嵌入 AGENTS.md。

**Files:**
- Modify: `AGENTS.md`（追加一节，或在现有验证命令处引用）

**内容（设计稿 11 项，全部保留）：**
```
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

**方式:** 作为 AGENTS.md 新的一节（§20 Quant-Specific Verification）插入，紧跟现有验证命令；同时作为 checklist 模板存到 `docs/ai/QUANT_VERIFICATION_CHECKLIST.md`（方便复制到实验笔记）。

**验证:** grep AGENTS.md 确认新节存在；读 docs/ai/QUANT_VERIFICATION_CHECKLIST.md 确认 11 项完整。

---

### Task 3: Task Record 模板（设计稿 §二十一）

**Objective:** 让每个任务留痕，成为 memory 的来源。

**Files:**
- Create: `docs/templates/TASK_RECORD.md`

**内容:** Task ID / Type / Goal / Scope / Files inspected / Evidence / Conclusion / Confidence / Changes / Tests / Follow-up（设计稿 §二十一模板）。

**验证:** 读回文件确认字段齐全。

---

### Task 4: .hermes/memory/ 项目记忆体系（设计稿 §十七~十九）

**Objective:** 建立四类项目记忆目录 + project-state，作为「决策历史」，明确 Memory ≠ Source of Truth。

**Files:**
- Create: `.hermes/memory/README.md` — 说明四类目录语义 + Memory 优先级原则（Code > Tests > Runtime > Registry > Docs > Memory）
- Create: `.hermes/memory/project-state.md` — 当前项目状态摘要（引用 docs/tracking/ 不重复）
- Create: `.hermes/memory/decisions/.gitkeep` + 说明（ADR 实际在 docs/archive/adr/，此目录放非 ADR 级别的补充决策）
- Create: `.hermes/memory/discoveries/.gitkeep` — 研究发现（如 Momentum_3M 近 30 日 IC 下降）
- Create: `.hermes/memory/failures/.gitkeep` — 失败记录（如「某次修改改变 factor direction 导致历史实验不可比」）
- Create: `.hermes/memory/workflows/.gitkeep` — 工作流（Research → Experiment → Validation → Paper）

**验证:** 目录结构存在；README 内容符合设计稿原则。

---

### Task 5: qp-project skill 增强（Hermes 全局侧，设计稿 §五~十四）

**Objective:** 把 Harness 的 skill 职责映射到 Hermes 实际的 skill 体系（qp-project 已覆盖大部分），补 Harness 特有内容。

**Files:**
- Modify: `~/.hermes/skills/software-development/qp-project/SKILL.md`

**内容增量（不重写，只补）：**
- 新增一节「QT Agent Harness v1.0」：说明 Harness 五层结构、任务协议 Level 0-5、Task Record 用法
- 补充 Quant 验证清单引用（指向 docs/ai/QUANT_VERIFICATION_CHECKLIST.md）
- 补充 Memory 四类目录位置（.hermes/memory/）

**注意:** 不创建 12 个独立 qt-* skill（qp-project 已覆盖 understand/investigate/architecture/data/factor/strategy/validation/pipeline/debug/test/review/documentation 的职责，拆 12 个是过度工程，且 Hermes 每次加载成本高）。

**验证:** skill_view 确认新节存在；skill 语法无破坏。

---

### Task 6: 分支策略评估（设计稿 §二十二~二十三，需用户确认）

**Objective:** 评估是否引入 git 分支工作流。

**现状:** 当前 master 直改直推（用户习惯），无 feature 分支。

**方案选项（待用户定）：**
- A. 维持 master 直推，只在 AGENTS.md 增加「改动前 git status/diff 审查」纪律（轻量，推荐）
- B. 引入 feature/分支 + 合并（重，QT 单人项目收益有限）

**注意:** 设计稿说「Hermes 不能直接改 main」——但 QT 长期 master 直改，且用户偏好「命令极简」。此任务默认做 A，若用户要 B 再改。

**Files (A 方案):**
- Modify: `AGENTS.md`（在验证命令处追加 git diff 审查步骤）

**验证:** grep AGENTS.md 确认新增 git 纪律文本。

---

## 执行顺序

1. Task 1 → 2 → 3 → 4（项目内文件，独立可并行）
2. Task 5（全局 skill，依赖 2/4 的文件路径）
3. Task 6（需用户确认选项）

## 验证 / 总体验收

- 全部文件写入后：`git status` + `git diff --stat` 确认改动范围符合预期（纯文档）
- 模拟 Agent 走一遍：读 AI_PROJECT_CONTEXT.md → 问「Momentum_3M 为什么 DEGRADED」→ 应该能找到因子健康度 → factor_health_logger.py → FACTOR_DIRECTIONS 的路径
- ruff/pyright/pytest 不适用（无代码改动），跳过

## 风险 / 开放问题

1. **Hermes skills 加载路径** — 项目内 `.hermes/skills/` 不会被 Hermes 自动加载；已适配为全局 qp-project skill 增强。若未来 Hermes 支持项目级 skill 加载，可再迁移。
2. **AI_PROJECT_CONTEXT 的「Current Project State」** — 设计稿建议写当前阶段，但 qt 的 tracking 文档经常过时（skill 已记录 4 个 backlog 项 3 个早已实现）。故不写死状态，指向 tracker。
3. **分支策略** — 默认 A（轻量），等用户表态。
4. **`.hermes/` 会进 git** — 确认 .gitignore 不排除（当前无 .hermes 规则，不会排除）。

## 复盘要点（执行后）

- 计划里「缺 12 个 skill」的适配是否合理 —— 观察 qp-project 增强后 Hermes 是否真的按 Harness 工作
- AI_PROJECT_CONTEXT 是否真的减少了用户解释 QT 的次数（最终目标：用户直接说「Investigate why X is DEGRADED」）
