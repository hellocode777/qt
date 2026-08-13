# ADR-003: Explicit Composition Root（不引入 DI Framework）

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-012, ADR-011

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

**Decision**：不引入 Dependency Injection Framework。所有对象在应用启动时显式构造。

```python
config = Config.load()
logger = Logger(config)
scheduler = Scheduler(logger)
storage = DuckDBStorage(config)
experiment = ExperimentTracker(storage)
app = Application(
    config=config,
    logger=logger,
    scheduler=scheduler,
    experiment=experiment,
)
```

**Why**：符合 Research First、Walking Skeleton First 原则，避免隐藏依赖。

---

## 实现状态

✅ 已实现。代码证据：`qp/platform/runtime/`（RuntimeContext / build_runtime 显式构造）

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
