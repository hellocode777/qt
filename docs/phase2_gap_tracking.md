# Phase 2 Gap Closure — 进度追踪

> 最后更新：2026-07-31
> 基线：1375 tests | ruff 0 | pyright 0

## 总体进度

| 状态 | 数量 |
|------|------|
| ✅ 已完成 | 6 / 6 |
| 🔄 进行中 | 0 / 6 |
| ⏳ 待开始 | 0 / 6 |

---

## G-016：估值数据 PIT 对齐（Lookahead Bias 修复）

| 属性 | 值 |
|------|-----|
| 优先级 | 🔴 高 |
| 状态 | ✅ 已完成 |
| 复杂度 | 低 |
| 预估工时 | 1 天 |

**问题**：`_build_valuation_data()` 取最新季报 EPS/NAV 套到所有历史交易日，造成未来信息泄漏。

**修复方向**：对每个 trade_date 取 `report_date <= trade_date` 的最新报告，实现 PIT 对齐。

### 文件清单

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/pipeline/daily_pipeline.py` `_build_valuation_data()` | 重写 | ⏳ |
| `tests/unit/pipeline/test_valuation.py` | 新建 | ⏳ |

### 验证项

- [ ] PIT 对齐：2024-06-15 的 PE 用 2024Q1 EPS，不是 2026Q1
- [ ] 无报告日期 PE/PB = None
- [ ] ruff check = 0
- [ ] pyright = 0
- [ ] pytest 全部通过

---

## G-012：组合 KPI 报表

| 属性 | 值 |
|------|-----|
| 优先级 | 🔴 高 |
| 状态 | ✅ 已完成 |
| 复杂度 | 中 |
| 预估工时 | 3-4 天 |

**问题**：`qp portfolio report` Sharpe/MaxDD/Alpha 显示"待回测"占位符，WebUI 无组合绩效指标。

**修复方向**：新建 NAVLedger + PortfolioMetrics，替换假数据为真实计算值。

### 子任务

#### 2a：NAVLedger 净值账本

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/portfolio/nav_ledger.py` | 新建 | ⏳ |
| `tests/unit/portfolio/test_nav_ledger.py` | 新建 | ⏳ |

#### 2b：PortfolioMetrics 指标计算

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/portfolio/metrics.py` | 新建 | ⏳ |
| `tests/unit/portfolio/test_portfolio_metrics.py` | 新建 | ⏳ |

#### 2c：CLI 报表替换假数据

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/platform/cli/commands/portfolio.py` | 修改 | ⏳ |

#### 2d：WebUI 绩效展示

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/web/routers/portfolio.py` | 修改 | ⏳ |
| `qp/web/templates/portfolio.html` | 修改 | ⏳ |

#### 2e：流水线接入

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/pipeline/daily_pipeline.py` | 修改（加 NAV 录制步骤） | ⏳ |
| `qp/portfolio/__init__.py` | 修改（导出新类） | ⏳ |

### 待计算指标

- [ ] Sharpe Ratio（年化）
- [ ] Max Drawdown（%）
- [ ] 年化收益率
- [ ] 年化波动率
- [ ] Calmar Ratio
- [ ] Alpha（vs 基准）
- [ ] 最佳/最差月份
- [ ] 月度胜率

---

## G-003：CLI 解析器基础设施

| 属性 | 值 |
|------|-----|
| 优先级 | 🟡 中高 |
| 状态 | ⏳ 待开始 |
| 复杂度 | 高 |
| 预估工时 | 5-7 天 |

**问题**：`parser.py` 0 字节，19 个命令全用手工 `sys.argv` 解析，无 `--help`。

**修复方向**：Click 框架重写，逐步迁移，保持向后兼容。

### 文件清单

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/platform/cli/parser.py` | 重写 (~400 行 Click 定义) | ⏳ |
| `qp/platform/cli/main.py` | 重写 (~15 行入口) | ⏳ |
| `qp/platform/cli/commands/*.py` | 签名调整（sys.argv → kwargs） | ⏳ |
| `pyproject.toml` | 加 `click>=8.0` 依赖 | ⏳ |
| `tests/unit/platform/test_cli_parser.py` | 新建 | ⏳ |

### 命令迁移清单（共 19 个命令组）

| 命令组 | 子命令 | 迁移状态 |
|--------|--------|---------|
| `version` | — | ⏳ |
| `doctor` | — | ⏳ |
| `ingest` | — | ⏳ |
| `run` | `daily` | ⏳ |
| `fundamental` | — | ⏳ |
| `pipeline` | `list` | ⏳ |
| `validate` | — | ⏳ |
| `portfolio` | `report`, `risk` | ⏳ |
| `position` | `list`, `show`, `close`, `pnl`, `history` | ⏳ |
| `simulation` | `shadow` | ⏳ |
| `experiment` | `list`, `show`, `run`, `compare`, `validate`, `clean` | ⏳ |
| `model` | `list`, `show` | ⏳ |
| `data` | `fetch` | ⏳ |
| `backtest` | `run` | ⏳ |
| `monitor` | `check`, `regime`, `alert-test` | ⏳ |
| `knowledge` | `stats`, `search` | ⏳ |
| `decide` | — | ⏳ |
| `paper` | `start`, `status` | ⏳ |
| `web` | `start` | ⏳ |
| `retrain` | — | ⏳ |
| `scheduler` | `start` | ⏳ |

---

## G-011：策略提案审批流程

| 属性 | 值 |
|------|-----|
| 优先级 | 🟡 中 |
| 状态 | ⏳ 待开始 |
| 复杂度 | 中高 |
| 预估工时 | 4-5 天 |

**问题**：策略生命周期转换（RESEARCH→PRODUCTION）无人工审批环节，无审计跟踪。

**修复方向**：新建 Proposal 数据模型 + 存储 + CLI + WebUI + StrategyRegistry 门禁。

### 子任务

#### 4a：Proposal 数据模型

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/platform/proposals/__init__.py` | 新建 | ⏳ |
| `qp/platform/proposals/models.py` | 新建 | ⏳ |
| `qp/shared/types/__init__.py` | 修改（加 ProposalStatus） | ⏳ |

#### 4b：Proposal 存储

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/platform/proposals/store.py` | 新建 | ⏳ |

#### 4c：CLI 命令

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/platform/cli/commands/proposal.py` | 新建 | ⏳ |

#### 4d：WebUI 审批页

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/web/routers/proposals.py` | 新建 | ⏳ |
| `qp/web/templates/proposals.html` | 新建 | ⏳ |
| `qp/web/app.py` | 修改（注册路由） | ⏳ |
| `qp/web/templates/base.html` | 修改（加导航链接） | ⏳ |

#### 4e：StrategyRegistry 门禁

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/strategy/registry.py` | 修改（加审批检查） | ⏳ |

#### 测试

| 文件 | 操作 | 状态 |
|------|------|------|
| `tests/unit/platform/test_proposals.py` | 新建 | ⏳ |

---

## G-002：告警模块桥接

| 属性 | 值 |
|------|-----|
| 优先级 | 🟢 低 |
| 状态 | ⏳ 待开始 |
| 复杂度 | 极低 |
| 预估工时 | 15 分钟 |

**问题**：`qp/platform/alert/` 目录缺失，告警代码在 `qp/monitoring/alerts.py`。

**修复方向**：创建 re-export 桥接模块。

### 文件清单

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/platform/alert/__init__.py` | 新建 (~25 行) | ⏳ |

---

## G-020：类型标注修复

| 属性 | 值 |
|------|-----|
| 优先级 | 🟢 低 |
| 状态 | ⏳ 待开始 |
| 复杂度 | 极低 |
| 预估工时 | 5 分钟 |

**问题**：`BaseCorporateAction` ABC 参数用 `object` 而非 `pd.DataFrame`。

### 文件清单

| 文件 | 操作 | 状态 |
|------|------|------|
| `qp/shared/protocols/base_corporate_action.py` | 修改（1 行） | ⏳ |

---

## 质量门（每个 gap 完成后检查）

```
[ ] uv run ruff check — 0 errors
[ ] uv run pyright  — 0 errors
[ ] uv run pytest   — all pass
[ ] 新代码有对应测试
[ ] 无跨层导入
[ ] 无 print() — 全部用 loguru
```
