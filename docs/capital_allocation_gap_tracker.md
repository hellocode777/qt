# Capital Allocation Layer 差距追踪文档

> 对照 `docs/8_Capital_Allocation_Layer.md`，逐项追踪 Layer 8（Capital Allocation）的待实现项。
> 最后更新：2026-07-22（全部完成 ✅）

---

## 状态说明

- ⬜ `[ ]` 待实现
- 🟡 `[~]` 部分实现，有缺陷
- ✅ `[x]` 已完成

---

## 一、模块一：Allocation Policy（资金配置策略）

### 1.1 BaseAllocator 统一接口

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `BaseCapitalAllocator.allocate(candidates, risk_report, total_capital) -> pd.DataFrame[symbol, target_weight, target_capital]`
- **改动**: 新增 `allocate()` 抽象方法；旧 `allocate_capital()` 转为委托方法
- **涉及文件**: `qp/shared/protocols/base_capital_allocator.py`

### 1.2 EqualWeightAllocator（等权）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 新增 `allocate()` 方法实现（返回 `target_capital` 列）；旧 `allocate_capital()` 委托到 `allocate()`
- **涉及文件**: `qp/portfolio/allocator/equal_weight.py`

### 1.3 RiskParityAllocator（风险平价）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 新增 `allocate()` — 优先使用 `risk_volatility` 列（Layer 7 提供），无波动率时自动退化为等权 + max_weight_limit 截断
- **涉及文件**: `qp/portfolio/allocator/risk_parity.py`

### 1.4 VolatilityTargetAllocator（目标波动率）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: target_vol / current_vol → scale ∈ [min_exposure, max_exposure]；默认 12% 年化目标；高波动自动降仓，低波动恢复满仓；`get_recommended_exposure()`
- **涉及文件**: `qp/portfolio/allocator/volatility_target.py`

### 1.5 KellyAllocator（凯利）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 新增 `allocate()` 方法 — alpha_score × fraction × (1-cash_buffer)，受 max_single 和 max_weight_limit 双重上限约束；__init__ 强制 max(fraction, 0.5)
- **涉及文件**: `qp/portfolio/allocator/kelly.py`

### 1.6 AllocationFactory（工厂）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 注册 4 种方法 — equal_weight / risk_parity / volatility_target / kelly
- **涉及文件**: `qp/portfolio/allocator/factory.py`

---

## 二、模块二：Position Sizing（仓位计算）

### 2.1 PositionSizer（仓位数计算器）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `PositionSizer` 封装 BaseAllocator，传入 candidates → 输出含 risk_cluster/max_weight_limit/allocator_used 的 enriched positions
- **涉及文件**: `qp/portfolio/sizing/position_sizer.py`

### 2.2 WeightNormalizer（权重归一化器）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 迭代 clip+redistribute 算法 — 比例归一化 → cap 截断 → freed_weight 按比例重新分配给 uncapped 仓位 → 循环至收敛（默认 5 次迭代）
- **涉及文件**: `qp/portfolio/sizing/weight_normalizer.py`

---

## 三、模块三：Portfolio Optimization（组合优化）

### 3.1 PortfolioOptimizer（优化器）

- **状态**: `[~]` 已有但文档建议 MVP 暂缓
- **已实现**: `MeanVarianceOptimizer` + `OptimizationResult` — Max Sharpe + Ledoit-Wolf + SLSQP
- **不足**: 文档建议 MVP 不做复杂优化，仅做权重归一化；可保留但默认不启用
- **涉及文件**: `qp/portfolio/optimizer.py`

### 3.2 Optimization Constraints（优化约束）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `ConstraintSet` dataclass（10 种约束类型）+ `OptimizationConstraintsBuilder` — 从 candidates + risk_report 构建结构化约束；blacklist/frozen 自动识别；空 cluster 名过滤
- **涉及文件**: `qp/portfolio/optimization/constraints.py`

---

## 四、模块四：Cash Management（现金管理）

### 4.1 CashManager（现金管理器）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: 3 个防御触发器 — 候选不足（N < scarcity_threshold → target equity = N × standard_weight）、波动率防御（vol_percentile ≥ 阈 值 → defensive_cash）、风控告警（violations → cash 提升 80% defensive）；`evaluate()` + `apply_to_positions()`
- **涉及文件**: `qp/portfolio/cash/cash_manager.py`

### 4.2 ReservePolicy（现金储备策略）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: min_cash / max_cash / defensive_cash 三级 + scarcity_threshold / volatility_percentile 阈值 + `aggressive()`/`conservative()`/`default()` 预设
- **涉及文件**: `qp/portfolio/cash/reserve_policy.py`

---

## 五、数据模型

### 5.1 AllocationResult（分配结果）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **涉及文件**: `qp/portfolio/models/allocation_result.py`

### 5.2 TargetPortfolio（目标组合）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **要求**: 6 字段 — date / symbol / target_weight / target_capital / allocator_used / cash_reserve + from_allocator_output() 工厂 + validate() + to_dataframe()/to_polars()
- **涉及文件**: `qp/portfolio/models/target_portfolio.py`

---

## 六、编排引擎

### 6.1 CapitalAllocator（资金配置编排器）

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **已实现**: `CapitalAllocator` + `CapitalAllocatorConfig` — 4 步流水线（CreatePolicy → PositionSizer → WeightNormalizer → TargetPortfolio）+ pass_status 过滤 + 验证
- **涉及文件**: `qp/portfolio/capital_allocator.py`

---

## 七、已有的部分实现（不在文档中但已存在）

| 模块 | 文件 | 说明 |
|---|---|---|
| EqualWeightAllocator | `allocator/equal_weight.py` | 1/N + cash_buffer |
| RiskParityAllocator | `allocator/risk_parity.py` | 逆波动率 + fallback |
| KellyAllocator | `allocator/kelly.py` | 1/4 Kelly + max_single 硬帽 |
| AllocationFactory | `allocator/factory.py` | 按名分配器工厂 |
| MeanVarianceOptimizer | `optimizer.py` | Max Sharpe + Ledoit-Wolf |
| BaseCapitalAllocator | `shared/protocols/base_capital_allocator.py` | 抽象基类壳 |

---

## 八、实现顺序建议

```
Week 1 — P0 数据模型 + 接口升级（5 项）
  ├── 5.2  TargetPortfolio 数据模型
  ├── 5.1  AllocationResult 数据模型
  ├── 1.1  BaseAllocator 接口升级（统一 allocate() 签名）
  ├── 1.2  EqualWeightAllocator 接口对齐
  └── 1.5  KellyAllocator 接口对齐

Week 2 — P0 核心引擎 + 新算法（5 项）
  ├── 6.1  CapitalAllocator 编排器
  ├── 2.1  PositionSizer
  ├── 2.2  WeightNormalizer（迭代裁剪归一化）
  ├── 1.4  VolatilityTargetAllocator
  └── 1.3/1.6 RiskParity + Factory 升级

Week 3 — P1 现金管理（3 项）
  ├── 4.2  ReservePolicy 数据模型
  ├── 4.1  CashManager（含防御触发逻辑）
  └── 1.4  VolatilityTarget 集成到 CapitalAllocator

Week 4 — P2 优化约束 + 收尾（2 项）
  ├── 3.2  Optimization Constraints
  └── 配套测试 + 回归验证
```

---

## 九、完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 5.2 TargetPortfolio | 新增 `TargetPortfolio` dataclass（6 字段 + from_allocator_output + validate + to_dataframe/to_polars + format_table） |
| 2026-07-22 | 5.1 AllocationResult | 新增 `AllocationResult` dataclass（to/from_dict + summary + to_dataframe） |
| 2026-07-22 | 1.1 BaseAllocator | 新增 `allocate(candidates, risk_report, total_capital)` 抽象方法；`allocate_capital` 转为委托 |
| 2026-07-22 | 1.2 EqualWeightAllocator | 新增 `allocate()` 实现，返回 `target_capital`（替代 `target_amount`） |
| 2026-07-22 | 1.5 KellyAllocator | 新增 `allocate()` — alpha_score × fraction，受 max_single + max_weight_limit 双重约束 |
| 2026-07-22 | 1.3 RiskParityAllocator | 新增 `allocate()` — 优先使用 Layer 7 risk_volatility，无数据自动退化等权 + cap |
| 2026-07-22 | 1.6 工厂 | 更新 `__init__.py` 导出 `AllocationResult` + `TargetPortfolio` |
| 2026-07-22 | 配套 | 测试 809→822（+13 项）：TestAllocators +5, TestTargetPortfolio +5, TestAllocationResult +3 |

### Week 2 完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 2.1 PositionSizer | 新增 `PositionSizer` — 封装 BaseAllocator，enrich 输出含 risk_cluster/max_weight_limit/allocator_used；支持 size_batch 按 cluster 分组 |
| 2026-07-22 | 2.2 WeightNormalizer | 新增 `WeightNormalizer` — 迭代 clip+redistribute 算法（proportional scale → cap → redistribute → loop）；`NormalizationResult` dataclass |
| 2026-07-22 | 1.4 VolatilityTargetAllocator | 新增 `VolatilityTargetAllocator` — target_vol/current_vol scale ∈ [min,max]；12% 年化目标；低波动满仓、高波动降仓 |
| 2026-07-22 | 6.1 CapitalAllocator | 新增 `CapitalAllocator` + `CapitalAllocatorConfig` — 4 步流水线（Policy → Sizing → Normalizer → TargetPortfolio）；pass_status 过滤 + 验证 |
| 2026-07-22 | 1.6 Factory | 注册 VolatilityTargetAllocator 到工厂（4 种方法）；更新 `__init__.py` 导出 36 个符号 |
| 2026-07-22 | 配套 | 测试 822→839（+17 项）：TestPositionSizer +3, TestWeightNormalizer +5, TestVolatilityTargetAllocator +4, TestCapitalAllocator +5 |

### Week 3 完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 4.2 ReservePolicy | 新增 `ReservePolicy` dataclass — min/max/defensive_cash 三级 + scarcity_threshold + volatility_percentile + `aggressive()`/`conservative()`/`default()` 预设 |
| 2026-07-22 | 4.1 CashManager | 新增 `CashManager` — 3 触发器（候选不足/波动率防御/风控告警）+ `evaluate()` → `CashDecision` + `apply_to_positions()` |
| 2026-07-22 | 集成 | `CapitalAllocator.run()` 新增 Step 4 CashManager；`market_vol`/`vol_percentile` 参数；cash_mode 写入 AllocationResult.metadata |
| 2026-07-22 | 配套 | 测试 839→852（+13 项）：TestReservePolicy +4, TestCashManager +6, TestCapitalAllocatorWithCash +3 |

### Week 4 完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-22 | 3.2 OptimizationConstraints | 新增 `ConstraintSet` dataclass（10 约束类型）+ `OptimizationConstraintsBuilder` — per_position/sector/cluster bounds + blacklist/frozen + beta/liquidity/leverage + cardinality；跳过空 cluster 名 |
| 2026-07-22 | 配套 | 测试 852→857（+5 项）：TestOptimizationConstraints +5 |
