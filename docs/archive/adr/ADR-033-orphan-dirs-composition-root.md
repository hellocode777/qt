# ADR-033: 游离目录归属说明（pipeline 组合根 / web 人类接口层）

- **状态**：接受
- **日期**：2026-08-12
- **决策者**：QP 项目
- **关联**：ADR-003（Explicit Composition Root）、ADR-006（Everything is Pipeline）、ADR-002（CLI 唯一入口）、Rule 28（Walking Skeleton）

---

## 上下文

2026-08-11 宪法审计发现两个目录不在既定分层表内，被标记为"游离目录"：

1. **`qp/pipeline/`** —— 含 `daily_pipeline.py`、`multifactor_pipeline.py`、`factor_calc_pipeline.py`、`fundamental_pipeline.py`。文档（CLAUDE.md / DP-001）中管道引擎写的是 `platform/pipeline/`（Layer 1），但实际业务管道文件在 `qp/pipeline/`。
2. **`qp/web/`** —— WebUI（FastAPI + Jinja2 + HTMX），代码实际存在但分层文档未覆盖。

此外，CLI（`qp/platform/cli/`）有 **171 处跨层 import**，根目录 `scripts/` 有 2 个部署/测试脚本，均无正式归属说明。

## 决策

### 1. `qp/pipeline/` = 业务编排组合根（合法，非游离）

- `qp/pipeline/__init__.py` 已自述："Pipelines orchestrate across all 10 layers per ADR-003 (explicit composition root). They are the ONLY place where cross-layer imports are permitted."
- 定位：**业务管道层**（DailyPipeline 每日信号链、MultiFactorPipeline 实验回测），与 `platform/pipeline/`（管道引擎：PipelineRunner/PipelineContext/BasePipeline）**分工不同**——platform 提供机制，qp/pipeline 提供业务编排。
- 依赖统计：strategy 21 / research 13 / data 10 / portfolio 9 / platform 9 / monitoring 7 —— 跨层依赖是**设计使然**（组合根特权）。
- **结论**：保留 `qp/pipeline/` 原样，不是违规，是组合根。更新 DP-001 文档补充该层。

### 2. `qp/web/` = 人类接口层（展示层，合法）

- `qp/web/__init__.py` 已自述："Human Interface Layer… WebUI never computes investment logic — it only reads QP-produced facts."
- 定位：展示层，读各层产物渲染给人类（决策/监控/持仓/回测）。依赖 decision/strategy/portfolio/monitoring 是**向下读数据**，展示层允许跨层读。
- **结论**：保留原样。DP-001 补充该层。

### 3. CLI 组合根豁免（171 处跨层 import）

- CLI 是用户操作入口（ADR-002 唯一入口），是组合根：所有 `qp platform cli commands/*.py` 的跨层 import 豁免。
- 豁免边界：**仅命令处理函数内的 lazy import**；命令文件不得定义业务逻辑，只做参数解析 + 调下层服务 + 输出。
- 写入 DP-001 文档，防未来误判。

### 4. `scripts/` 归位

- `qp-scheduler.service` → 部署物，移至 `deploy/systemd/`（保留原路径说明，systemd 安装时用绝对路径拷贝）。
- `test_email_report.py` → 一次性验证脚本，移至 `scripts/` 保留但标注为"手工验证脚本"（不属于库代码，不参与 lint/pyright 门禁）。

## 后果

- 架构文档与实际代码目录对齐（DP-001 补 3 层：pipeline 编排 / web 展示 / CLI 豁免）。
- 审计工具不再把 qp/pipeline、qp/web、CLI 误判为违规。
- 无代码迁移（qp/pipeline、qp/web 保持原位），零运行时风险。

## 验证

- `docs/architecture/platform/DP-001-platform-layer.md` 更新后，目录与文档一一对应。
- 全量门禁：`uvx ruff format --check .` + `uv run pyright` + pytest。
