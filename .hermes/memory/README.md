# .hermes/memory/ — QT 项目记忆体系

> **Memory ≠ Source of Truth。**
> 优先级（从高到低）：Code → Tests → Runtime/CLI 输出 → Registry/Data → Documentation → **Memory** → Agent inference。
> Memory 说「Strategy 使用 5 个 factors」，但 registry 现在是 6 个 → **相信 registry**，然后把 drift 报告出来。

## 四类目录

| 目录 | 记录什么 | 示例 |
|---|---|---|
| `decisions/` | 为什么这么设计（决策背景） | ADR 之外的补充决策；正式 ADR 在 `docs/archive/adr/` |
| `discoveries/` | 我们发现了什么（研究/调查结论） | Momentum_3M 近 30 日 IC 显著下降 |
| `failures/` | 什么方法失败过（避免重复踩坑） | 某次修改直接改变 factor direction 导致历史实验不可比较 |
| `workflows/` | 某项事情应该怎么做（流程） | Research → Experiment → Validation → Paper Trading |

## 使用规则

1. **每次任务先查这里** — 同名问题可能已调查过（Task Record 是来源）
2. **写入用 Task Record 模板** — 见 `docs/templates/TASK_RECORD.md`
3. **发现 drift 立刻报告** — Memory 与代码不一致时，代码赢，报告差异
4. **不替代文档** — Memory 是「过去发生过什么 + 为什么」，不是「系统应该长什么样」
5. **不无限增长** — 过时条目定期清理，保留高价值的「为什么」和「失败教训」

## 当前状态

- `project-state.md` — 项目当前状态摘要（指向 docs/tracking/，不重复维护）
- 正式决策档案：`docs/archive/adr/`（ADR-001~033，权威）
- 技术选型：`docs/tdr/`（TDR-001~010）
