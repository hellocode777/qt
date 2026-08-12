# DP-001: Platform Layer (L1)

> Design Proposal — 运行时基础设施
> 关联 ADR: 002, 003, 005, 006, 012

## 职责

Platform 是所有层的运行时内核。每一层都运行在 Platform 之上。

## 子模块

| 子模块 | 文件数 | 核心类/函数 | 功能 |
|--------|--------|------------|------|
| `platform/config/` | 4 | `Config`, `ProjectConfig`, `StorageConfig` | 4 层优先级（CLI > env > config.toml > defaults），启动后冻结 |
| `platform/logging/` | 3 | Loguru 集成 | 统一日志，禁止 `print()` |
| `platform/storage/` | 4 | `StorageFactory`, `DuckDBStorage`, `SQLiteStorage`, `ParquetStorage` | 多后端存储工厂（不提供业务 Repository） |
| `platform/scheduler/` | 4 | `JobRegistry` | systemd timer → CLI → APScheduler → Job |
| `platform/pipeline/` | 4 | `PipelineRunner`, `PipelineContext`, `BasePipeline` | 管道引擎（ADR-006：一切皆 Pipeline） |
| `platform/cli/` | 2 + 18 | `main()`, 20+ `cmd_*` | 单入口 CLI（ADR-002） |
| `platform/runtime/` | 5 | 状态机 | 生命周期（CREATED→INITIALIZING→READY→RUNNING→STOPPING→TERMINATED）+ 组合根 |
| `platform/metadata/` | 3 | 版本/环境 | 运行时元信息 |
| `platform/proposals/` | 2 | `StrategyProposal`, `ProposalStore` | 策略生命周期审批 |
| `platform/alert/` | 3 | `Alert`, `AlertSeverity`, `AlertChannel` | 告警协议定义（L1），monitoring 层实现通道（ADR-033） |

## 关键设计决策

- **ADR-002**: CLI 名 `qp`，无第二个入口
- **ADR-003**: 无 DI 框架，显式组合根
- **ADR-005**: Phase 0 无事件总线，层间直接调用
- **ADR-006**: 一切皆 Pipeline
- **ADR-012**: Runtime 拥有一切（`context.logger`）

## 依赖

- **无上层依赖** — Platform 是最底层
- **被所有层依赖**: L2-L10 均运行在 Platform 之上

## 组合根豁免（ADR-033）

以下目录允许跨层 import，不视为架构违规：

1. **`qp/pipeline/`** — 业务编排组合根（ADR-003）：`daily_pipeline.py`（每日信号链）、`multifactor_pipeline.py`（实验回测）等跨全部 10 层编排。与 `platform/pipeline/`（管道引擎）分工：platform 提供机制，qp/pipeline 提供业务编排。
2. **`qp/web/`** — WebUI 人类接口层：只读各层产物渲染（决策/监控/持仓/回测），不计算投资逻辑。
3. **`platform/cli/commands/*.py`** — CLI 组合根（ADR-002 唯一入口）：命令处理函数内 lazy import 豁免；但命令文件只做参数解析 + 调下层 + 输出，不定义业务逻辑。
