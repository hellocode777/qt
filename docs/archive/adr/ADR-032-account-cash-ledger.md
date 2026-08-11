# ADR-032: 账户现金账本（Account Cash Ledger）

- **状态**：提议
- **日期**：2026-08-11
- **决策者**：QP 项目
- **关联**：ADR-006（Everything is Pipeline）、ADR-029（Risk 归 Portfolio）、Rule 24（Same Input Same Output）

---

## 上下文

用户使用 WebUI 模拟真实交易场景：投入 10 万本金，调仓日买入后现金几乎耗尽，之后某日卖出部分股票，现金应当回流。但当前系统存在**现金流断裂**：

1. **PositionLedger**（`qp/decision/position_ledger.py`）只记录持仓（position），**没有现金账本**。
   - `open()` 建仓时**不扣现金**（positions.parquet 无 cash 字段）
   - `close()` 平仓时只记 `pnl`（已实现盈亏），**卖出所得不回流**
2. **DecisionEngine**（`qp/decision/engine.py`）每次从 `total_capital`（默认 100,000）**重新计算**建议，不知道账户已有持仓与已投入资金。
   - 因此非调仓日 WebUI 显示"已用 ¥0 / 剩余 ¥100,000"——这是"当天建议口径"，不是账户真实状态
3. 三个资金相关组件各自独立：`SimulatedBroker`（有真实现金流但仅模拟层）、`ShadowLedger`（影子盘独立记账）、`PositionLedger`（无现金）——**没有一个"生产账户账本"**。

目标场景（用户期望）：

```
初始：现金 ¥100,000
调仓日买入 6 只（¥98,941）→ 现金 ¥1,059
某日卖出 1 只（¥16,470）→ 现金 ¥17,529
```

## 决策

### 1. PositionLedger 增加现金账本（Account Cash Ledger）

在 `PositionLedger` 内新增持久化现金状态：

- 存储：`data/positions/account.json`（与 positions.parquet 同目录）
  ```json
  {
    "initial_capital": 100000.0,
    "cash": 17529.0,
    "updated_at": "2026-08-11T18:00:00+08:00"
  }
  ```
- 首次使用：`initial_capital` 默认取 `qp run daily --capital` 传入值（缺省 100,000），或从现有 DecisionPackage 的 `report.total_capital` 引导；**现金 = initial_capital − Σ活跃持仓成本**（兼容已有持仓，无需重建历史）。

### 2. 买卖联动

| 操作 | 现金变化 |
|---|---|
| `open()` / `open_from_decision()` | `cash -= entry_price × shares`；现金不足 → 拒绝开仓并告警（不静默） |
| `close()` | `cash += exit_price × shares`（卖出回流） |

- `open()` 增加可选参数 `check_cash: bool = True`，`open_from_decision()` 批量校验总额后再逐个建仓（避免部分成功）。
- 交易成本（佣金/印花税/滑点）**暂不计入现金**——ADR 后续版本引入（保持与 CostModel 分离，避免双重计算）。

### 3. 账户视图 API

PositionLedger 新增只读查询（供 WebUI/CLI）：

- `get_account_summary() -> {initial_capital, cash, positions_value, total_equity, realized_pnl, available}`
- `total_equity = cash + Σ(active market_value)` —— 这就是"真实账户状态"

### 4. WebUI 显示真实账户状态

- `/portfolio` 路由：`已用 ¥X / 剩余 ¥Y` 改为读 `get_account_summary()`（账户口径），不再读当日 DecisionPackage 的 `report`（建议口径）。
- 保留 DecisionPackage 历史列表展示（那是"决策记录"，不是账户）。

### 5. 不改变的内容

- DecisionPackage / DecisionEngine 的**建议生成逻辑不动**——它仍然回答"今天建议交易什么"。
- PositionLedger 的 CRUD API 向后兼容（新增字段默认值，老 parquet 可读）。
- 影子盘（ShadowLedger）、模拟盘（SimulatedBroker）保持独立——它们本来就有现金账，**不合并**；本 ADR 只补生产账户账本。

## 后果

**正面**：
- 生产链路具备真实现金流闭环（买扣钱、卖回钱），WebUI 显示真实账户状态
- 用户可模拟"10 万 → 买入 → 卖出回流"完整场景
- 与 SimulatedBroker/ShadowLedger 形成对照：三者现金口径一致（initial_capital + realized − cost_basis）

**负面/代价**：
- PositionLedger 增加一个持久化文件与少量状态；需要迁移已存在的 positions.parquet（首次运行时自动推导现金）
- 已有测试需补充现金断言；`open()` 默认 `check_cash=True` 可能影响无账户上下文的调用方（测试/脚本），需逐个确认

## 验证

1. 单元测试：open 扣现金、close 回流、现金不足拒绝、账户摘要计算
2. 真实回放：用现有 08-07 决策包（6 BUY，¥98,941）→ 账户现金应推导为 ¥1,059 → 模拟卖出 1 只 → 现金回补
3. WebUI `/portfolio` 显示 `已用 ¥98,941 / 剩余 ¥1,059`（真实），而非 `¥0 / ¥100,000`
4. 质量门禁：ruff = 0、pyright = 0、pytest 全过
