# Task Record — 任务留痕模板

> 每个 QT 任务（调查/设计/实现/修复/实验）完成后复制本模板填写，存入 `.hermes/memory/` 对应目录
> （discoveries/、failures/、workflows/）或附在实验/修复文档末尾。
> 目的：让 Memory 有来源，让未来 Agent 不必重新调查。

```text
Task ID:        QT-YYYY-MMDD-NNN        # 如 QT-2026-0813-001
Type:           Explain / Investigate / Design / Implement / Refactor / Production-sensitive
Goal:           <一句话：要回答/解决什么问题>
Scope:          <涉及的系统/层/模块，如 factor system / daily pipeline / webui>
Status:         DONE / BLOCKED / PARTIAL

Files inspected:
  - <路径/函数> — <发现>

Evidence:
  - <FACT: 代码/运行输出/测试直接支持的观察>
  - <INFERENCE: 由证据推出的结论>
  - <HYPOTHESIS: 未验证的假设>

Conclusion:
  <结论正文，区分 observed facts / inferred conclusions / assumptions / unresolved questions>

Confidence:     HIGH / MEDIUM / LOW
Changes:        <NONE 或列出 git 提交/文件改动>
Tests:          <跑了哪些测试、结果；N/A if 纯调查>
Follow-up:
  - <遗留问题 / 下一步>
```

## 示例

```text
Task ID:        QT-2026-0813-001
Type:           Investigate
Goal:           Why Momentum_3M became DEGRADED?
Scope:          factor system
Files inspected:
  - qp/monitoring/factor_health_logger.py — classify_health() 判定条件
  - data/monitoring/factor_health.parquet — 滚动 IC 分布
Evidence:
  - FACT: classify_health() 在 ic_30d < 阈值时输出 DEGRADED
  - FACT: Momentum_3M direction=-1，IC 负是预期语义
  - INFERENCE: 近 30d IC 变弱与 regime 变化一致
Conclusion:
  Momentum_3M DEGRADED 源于 ...（附推理链）
Confidence:     HIGH
Changes:        NONE
Tests:          N/A
Follow-up:
  - 若持续 60 天再评估是否调权重（先诊断后调参）
```

## 存储位置

- 研究发现 → `.hermes/memory/discoveries/`
- 失败记录 → `.hermes/memory/failures/`
- 流程沉淀 → `.hermes/memory/workflows/`
- 架构决策 → `docs/archive/adr/`（ADR-xxx，正式决策走这里）
