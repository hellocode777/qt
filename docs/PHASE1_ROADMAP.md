# Phase 1: Decision Support System — 实施路线图

> 目标：把"能跑的系统"变成"可信任的投资决策系统"
>
> 创建日期：2026-07-30
>
> 当前进度：25/25 tasks complete
>
> ⚡ 捷径提示：WebUI 比预期成熟（Dashboard、审核流、组件系统已就绪），P0/P4 部分任务可快速完成。

---

## 总览

```
Phase 0 ✅ → Phase 1 🔄 → Phase 2 ⏳
Walking       Decision      长期运营
Skeleton      Support       策略迭代
```

核心链路（已完成）：

```
Data → Validation → Factor → Strategy → Ensemble → Risk → Decision Package → Human Review
                                                                                   ↑
                                                                     Phase 1 加固这一环
```

---

## P0: Decision State Machine & Review Flow

**目标**：Decision Package 从"生成即结束"变成"完整生命周期"

### 当前状态

- `HumanReview` dataclass：有 `reviewed: bool` / `executed: bool`，但无显式状态枚举
- `DecisionService.mark_reviewed()` / `mark_executed()` 已存在（写入 index.json）
- WebUI 已有 `POST /review/{id}` + `POST /execute/{id}` HTMX 端点
- `human_review_panel.html` 组件已有三态 UI（unreviewed → reviewed → executed）
- **缺失**：无 `DecisionStatus` 枚举、无状态转换验证、无 MODIFIED 流程、无状态机

### 目标架构

```
                      ┌──────────────┐
                      │   PENDING    │
                      └──────┬───────┘
                             │ Human Review
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         APPROVED       REJECTED       MODIFIED
              │                            │
              ▼                            ▼
    PARTIALLY_EXECUTED               (回到 APPROVED)
              │
              ▼
         MONITORING
              │
              ▼
           CLOSED
```

### 任务列表

- [x] **Task P0.1**: 新增 `DecisionStatus` 枚举 + 状态转换验证 ✅
  - 文件：`qp/decision/state_machine.py`
  - 内容：`DecisionStatus` enum (PENDING/APPROVED/REJECTED/MODIFIED/PARTIALLY_EXECUTED/MONITORING/CLOSED) + `can_transition(from, to)` 验证函数
  - 依赖：无
  - 验证：`python -c "from qp.decision.state_machine import DecisionStatus, can_transition; assert can_transition(DecisionStatus.PENDING, DecisionStatus.APPROVED)"`

- [x] **Task P0.2**: `HumanReview` 接入 `DecisionStatus` ✅
  - 文件：`qp/decision/models.py`（扩展 HumanReview 加 status 字段）；`qp/decision/decision_package.py`（to_dict/from_dict 适配）
  - 内容：HumanReview 增加 `status: str = "PENDING"` + `status_history: list[dict]` 记录每次状态变更
  - 依赖：P0.1
  - 验证：`pytest tests/unit/decision/ -k state`

- [x] **Task P0.3**: `DecisionService` 状态流转 API 升级 ✅
  - 文件：`qp/web/services/decision_service.py`
  - 内容：`mark_reviewed()` 改名/扩展为 `transition_status(package_id, new_status, reviewer, notes)` → 验证转换合法性 → 写回 JSON + index
  - 依赖：P0.2

- [x] **Task P0.4**: 新增 CLI 审核命令 ✅
  - 文件：`qp/platform/cli/commands/decision.py`（新建）
  - 命令：`qp decision status <id>` / `qp decision review <id> --action approve|reject|modify --notes "..."` / `qp decision list`
  - 依赖：P0.3

- [x] **Task P0.5**: WebUI 审核页增加 MODIFIED 流程 ✅
  - 文件：`qp/web/routers/decisions.py` / `qp/web/templates/human_review_panel.html`
  - 内容：已有 approve/execute 按钮，需增加 reject + modify 按钮 + 修改备注输入框
  - 依赖：P0.3

---

## P1: Strategy Health Reports & Risk Gate

**目标**：策略层告诉 Decision Layer"我现在健康吗？"而不只是"我今天有股票"

### 当前状态

- `StrategyMonitor` 已存在但未接入 daily pipeline
- Validation gate 跑出 `16.67/100` 但没有结构化分析报告

### 任务列表

- [x] **Task P1.1**: `StrategyMonitor` 接入 daily pipeline ✅
  - 文件：`qp/pipeline/daily_pipeline.py`
  - 每策略执行后调用 `health_check()`，记录 health score + alerts
  - 依赖：无

- [x] **Task P1.2**: 新增 `StrategyHealthReport` 生成器 ✅
  - 文件：`qp/monitoring/strategy_health_report.py`
  - 输出：IC decay 分析 / 单调性检查 / 近期衰减趋势 / 建议（NOT_APPROVED / NEEDS_RETRAIN / HEALTHY）
  - 依赖：P1.1

- [x] **Task P1.3**: Validation Gate 失败原因结构化输出 ✅
  - 文件：`qp/validation/`（扩展）
  - 当前只输出 score，需要输出具体是哪些 rule 失败及原因
  - 依赖：无

- [x] **Task P1.4**: WebUI Strategy Health 详情页 ✅
  - 文件：`qp/web/routers/`（新增或扩展）
  - 依赖：P1.2, P1.3

---

## P2: Position Manager（Position Ledger）

**目标**：系统从"推荐买"进化到"买了以后全程跟踪"

### 当前状态

- `PositionState` 枚举**已存在**于 `qp/shared/types/__init__.py`：`IDEA → CANDIDATE → APPROVED → HOLDING → REDUCING → CLOSED → ARCHIVED`
- `Order` dataclass 已存在（`qp/portfolio/single_portfolio.py`）
- `OrderSide` / `OrderStatus` 枚举已存在
- **缺失**：Position 持久化、PositionLedger CRUD、决策→持仓自动创建

### 任务列表

- [x] **Task P2.1**: 定义 `Position` 和 `PositionLedger` 数据模型 ✅
  - 文件：`qp/decision/position_ledger.py`
  - 字段：position_id, symbol, entry_date, entry_price, shares, strategy_id, decision_id, status, exit_date, exit_price, exit_reason
  - 依赖：无

- [x] **Task P2.2**: PositionLedger 持久化（Parquet + JSON index） ✅ (已在 P2.1 完成)
  - 文件：`qp/decision/position_ledger.py`
  - 存储：`data/positions/positions.parquet` + `data/positions/index.json`
  - CRUD：open / close / get_active / get_history
  - 依赖：P2.1

- [x] **Task P2.3**: 决策批准后自动创建 Position ✅
  - 文件：`qp/decision/decision_package.py` / `qp/pipeline/daily_pipeline.py`
  - 当 `DecisionPackage.approve()` 被调用时，自动在 PositionLedger 中创建对应持仓
  - 依赖：P2.2, P0.3

- [x] **Task P2.4**: CLI 命令 `qp position` ✅
  - 文件：`qp/platform/cli/commands/position.py`
  - 子命令：`list` / `show <id>` / `close <id>` / `pnl`
  - 依赖：P2.2

- [x] **Task P2.5**: WebUI Portfolio 页面 ✅
  - 文件：`qp/web/routers/portfolio.py`
  - 显示：当前持仓表 + 盈亏 + 关联决策 + 卖出建议
  - 依赖：P2.2, P3

---

## P3: Exit Engine（卖出信号引擎）

**目标**：回答"什么时候卖"

### 当前状态

`RiskExitManager` 已存在且设计良好：
- ✅ Stop Loss（-10%）
- ✅ ST 风险检测
- ✅ 退市风险检测
- ✅ 长期停牌检测
- ❌ 未接入 daily pipeline
- ❌ 无 Alpha 衰减检测（跌出 Top-N）
- ❌ 无基本面恶化检测

### 任务列表

- [x] **Task P3.1**: Exit Engine 接入 daily pipeline ✅
  - 文件：`qp/pipeline/daily_pipeline.py`
  - 每天收盘后：加载 active positions → 跑 `RiskExitManager.evaluate_daily()` → 输出 SELL signals → 写入 DecisionPackage
  - 依赖：P2.2

- [x] **Task P3.2**: 新增 Alpha 衰减检测 ✅
  - 文件：`qp/portfolio/alpha_decay.py`（新建）
  - 规则：持仓股票跌出当日 Top-N → 生成 RANK_DROP 信号
  - 依赖：P2.2

- [x] **Task P3.3**: 新增基本面恶化检测 ✅
  - 文件：`qp/portfolio/exit_signals.py`（新建或扩展 risk_exit.py）
  - 规则：ROE 连续下降 / 营收增速转负 / 净利润下滑
  - 依赖：P2.2

- [x] **Task P3.4**: Exit signals 写入 DecisionPackage ✅ (已在 P3.1 完成) 的 sell 建议
  - 文件：`qp/decision/engine.py`（扩展）
  - 依赖：P3.1

---

## P4: WebUI（精简版）

**目标**：第一版只需三个页面，不要做大

### 当前状态

FastAPI + Jinja2 + HTMX + Alpine.js + Chart.js 已搭建，实际进展比预期多：
- ✅ `/` Dashboard：完整 Cockpit（data quality 卡片 / regime 卡片 / strategy health 仪表盘 / kill switch / BUY/SELL 表格 / risk audit / human review panel）
- ✅ `/decisions` 列表 + `/decisions/{id}` 详情
- ✅ `/health` 系统健康页
- ✅ `POST /review/{id}` + `POST /execute/{id}` HTMX 审核流
- ✅ 模板组件化：`human_review_panel.html` / `strategy_health.html` / `killswitch_card.html` / `regime_card.html` / `decision_table.html`
- ✅ `base.html` 导航栏 + 统一布局 + `cockpit.css` (381行) + `cockpit.js` (64行)
- **缺失**：Portfolio 页面、审核中的 reject/modify 操作、导航栏需要加 Portfolio 入口

### 任务列表

- [x] **Task P4.1**: Dashboard 页完善 ✅ (已在 P1.4 + P0.5 完成)（数据接入）
  - 文件：`qp/web/routers/dashboard.py` / `qp/web/services/health_service.py`
  - 内容：确保 Strategy Health 数据来自真实 pipeline 输出而非 mock（当前大部分 UI 已存在，主要补数据管道）
  - 依赖：P1.2

- [x] **Task P4.2**: Decision Review 增加 ✅ (已在 P0.5 完成) Reject/Modify 操作
  - 文件：`qp/web/templates/human_review_panel.html` / `qp/web/routers/decisions.py`
  - 内容：在已有 approve/execute 基础上增加 reject + modify 按钮 + 备注输入
  - 依赖：P0.3

- [x] **Task P4.3**: Portfolio 页面（新建） ✅
  - 文件：`qp/web/routers/portfolio.py` + `qp/web/templates/portfolio.html`
  - 内容：当前持仓表 + 累计盈亏 + 卖出建议 + 关联决策链接 + 导航栏添加入口
  - 依赖：P2.5, P3.1

- [x] **Task P4.4**: 导航栏更新 ✅
  - 文件：`qp/web/templates/base.html`
  - 内容：侧边栏/顶部导航增加 Portfolio 入口 + 调整现有链接结构
  - 依赖：P4.3

---

## 时间线建议（基于实际进度修正）

```
Week 1 (7/30 - 8/5) — P0: Decision State Machine
├── P0.1  DecisionStatus 枚举 + 状态转换验证
├── P0.2  HumanReview 接入状态机
├── P0.3  DecisionService 状态流转 API
├── P0.4  CLI qp decision 命令
└── P0.5  WebUI Reject/Modify 按钮

Week 2 (8/6 - 8/12) — P1: Strategy Health + P2 启动
├── P1.1  StrategyMonitor 接入 daily pipeline
├── P1.2  StrategyHealthReport 生成器
├── P1.3  Validation 失败原因结构化输出
├── P1.4  WebUI Health 数据接入
└── P2.1  Position + PositionLedger 数据模型

Week 3 (8/13 - 8/19) — P2: Position Manager
├── P2.2  PositionLedger 持久化 (Parquet + JSON index)
├── P2.3  决策批准后自动创建 Position
├── P2.4  CLI qp position 命令
└── P4.4  导航栏更新（Position 入口）

Week 4 (8/20 - 8/26) — P3: Exit Engine
├── P3.1  Exit Engine 接入 daily pipeline
├── P3.2  Alpha 衰减检测
├── P3.3  基本面恶化检测
└── P3.4  Exit signals → DecisionPackage SELL 建议

Week 5 (8/27 - 9/2) — P4: WebUI 收尾 + 联调
├── P4.1  Dashboard 数据接入完善
├── P4.2  Decision Review Reject/Modify 交互
├── P4.3  Portfolio 页面（持仓 + 盈亏 + 卖出建议）
├── 联调 + 端到端测试
└── 文档更新
```

---

## 不建议现在做的事

- ❌ 增加更多因子
- ❌ 调复杂模型参数
- ❌ 上深度学习
- ❌ 做自动交易（保持 Human-in-the-loop）
- ❌ 连接真实券商 API

---

## Definition of Done（每个 Task）

- [x] `ruff format` 通过
- [x] `ruff check` 零错误
- [x] `pyright` 零错误
- [x] `pytest` 全部通过
- [x] 至少一个 CLI 命令可运行验证
- [x] 更新本文档勾选对应 checkbox

---

## 相关文件索引

### 需修改的文件（Phase 1 改动范围）

| 层 | 文件 | Phase 1 改动 |
|----|------|-------------|
| Decision | `qp/decision/state_machine.py` | **新建** — DecisionStatus 枚举 + 状态转换 |
| Decision | `qp/decision/models.py` | 扩展 HumanReview 加 status 字段 |
| Decision | `qp/decision/decision_package.py` | 状态流转方法 + to_dict/from_dict 适配 |
| Decision | `qp/decision/position_ledger.py` | **新建** — Position + PositionLedger CRUD |
| Decision | `qp/decision/engine.py` | 扩展：支持 SELL 信号生成 |
| Portfolio | `qp/portfolio/risk_exit.py` | 接入 pipeline + 新检测规则 |
| Portfolio | `qp/portfolio/alpha_decay.py` | **新建** — Alpha 衰减检测 |
| Portfolio | `qp/portfolio/exit_signals.py` | **新建** — 基本面恶化检测 |
| Monitoring | `qp/monitoring/strategy_monitor.py` | 接入 daily pipeline |
| Monitoring | `qp/monitoring/strategy_health_report.py` | **新建** — 结构化健康报告 |
| Pipeline | `qp/pipeline/daily_pipeline.py` | 插入 Position Check + Exit Engine 步骤 |
| CLI | `qp/platform/cli/commands/decision.py` | **新建** — qp decision 命令 |
| CLI | `qp/platform/cli/commands/position.py` | **新建** — qp position 命令 |
| Web | `qp/web/routers/decisions.py` | 扩展：reject/modify 端点 |
| Web | `qp/web/routers/portfolio.py` | **新建** — Portfolio 页面路由 |
| Web | `qp/web/services/decision_service.py` | 扩展：状态流转 API |
| Web | `qp/web/templates/human_review_panel.html` | 扩展：reject/modify UI |
| Web | `qp/web/templates/portfolio.html` | **新建** — 持仓页面模板 |
| Web | `qp/web/templates/base.html` | 扩展：导航栏加 Portfolio 入口 |

### 已有的基础文件（只读参考）

| 层 | 文件 | 内容 |
|----|------|------|
| Types | `qp/shared/types/__init__.py` | PositionState 枚举（IDEA→...→CLOSED）、OrderSide、OrderStatus |
| Decision | `qp/decision/models.py` | TradeRecommendation, DecisionReport |
| Decision | `qp/decision/decision_package.py` | DecisionPackage, HumanReview, LineageSnapshot, RiskAudit |
| Decision | `qp/decision/engine.py` | DecisionEngine（信号→建议） |
| Portfolio | `qp/portfolio/risk_exit.py` | RiskExitManager（止损/ST/退市/停牌） |
| Portfolio | `qp/portfolio/risk_manager.py` | PortfolioRiskManager（仓位/行业/相关性风控） |
| Portfolio | `qp/portfolio/single_portfolio.py` | Order dataclass |
| Portfolio | `qp/portfolio/cost_model.py` | CostModel + MarketImpactModel |
| Portfolio | `qp/portfolio/capital_allocator.py` | CapitalAllocator → TargetPortfolio |
| Monitoring | `qp/monitoring/strategy_monitor.py` | StrategyMonitor + StrategyHealth（健康分 0-100） |
| Monitoring | `qp/monitoring/system_state.py` | SystemStateManager（系统级状态） |
| Pipeline | `qp/pipeline/daily_pipeline.py` | DailyPipeline（13步主流程） |
| Validation | `qp/validation/pipeline.py` | ValidationPipeline（6 stage, 16 checks） |
| Validation | `qp/validation/result.py` | ValidationResult, GateResult, GateDecision |
| Web | `qp/web/app.py` | FastAPI 应用工厂 |
| Web | `qp/web/routers/dashboard.py` | Dashboard Cockpit（完整版） |
| Web | `qp/web/routers/decisions.py` | 决策浏览/详情 + review/execute 端点 |
| Web | `qp/web/services/decision_service.py` | DecisionService（latest/history/get_by_id/mark_reviewed/mark_executed） |
| Web | `qp/web/services/health_service.py` | HealthService（system_state/latest_health） |
| Web | `qp/web/templates/dashboard.html` | 完整 Cockpit 页面 |
| Web | `qp/web/templates/base.html` | 导航栏 + 统一布局 |
| Web | `qp/web/templates/human_review_panel.html` | HTMX 审核面板（三态） |
| Web | `qp/web/templates/strategy_health.html` | 策略健康仪表盘组件 |
| Web | `qp/web/templates/killswitch_card.html` | Kill Switch 状态卡片 |
| Web | `qp/web/templates/regime_card.html` | 市场状态卡片 |
| Web | `qp/web/templates/decision_table.html` | BUY/SELL 表格组件 |
| Web | `qp/web/static/css/cockpit.css` | 381 行自包含 CSS |
| Web | `qp/web/static/js/cockpit.js` | 64 行 Alpine.js + Chart.js |
