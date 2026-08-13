# ADR-002: CLI 名称确定为 `qp`

- **状态**：已实现
- **日期**：2026-08-01（设计）；2026-08-13 文档补全
- **决策者**：QP 项目
- **关联**：ADR-010

---

## 上下文

本决策源自 2026-08-01 设计文档（`docs/archive/dp.md` §4）。当时设计文档与实现同步演进，本文件仅为空占位；2026-08-13 从 dp.md 提取决策内容并补全为独立 ADR。

## 决策

**Decision**：统一采用 `qp` 作为所有命令入口。未来禁止新增第二套入口。

```bash
qp ingest daily-price
qp feature momentum20
qp train lgb-rank
qp validate strategy
qp backtest momentum_v1
qp report latest
qp run daily
qp scheduler start
```

**Why**：CLI First 原则。即使未来接 GUI、Web API、Telegram Bot，本质也都是调用 CLI。

---

## 实现状态

✅ 已实现。代码证据：`qp/platform/cli/main.py` 唯一入口；命令组 `commands/*.py`

## 验证

- 决策内容与当前代码一致（2026-08-13 复核）
- 质量门：ruff / pyright / pytest 全过
