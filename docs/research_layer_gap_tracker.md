# Research Layer 差距追踪文档

> 对照 `docs/research_layer.md` 与 `docs/rule.md` §7.9，逐项追踪 `qp/research/` 的待实现项。
> 最后更新：2026-07-21

---

## 状态说明

- ⬜ `[ ]` 待实现
- 🟡 `[~]` 部分实现，有缺陷
- ✅ `[x]` 已完成

---

## 一、P0 — 影响回测可信度，须最先修复

### 1.1 因子计算缺少 shift(1) 防未来信息泄露

- **状态**: `[x]` ✅ 已完成 (2026-07-21)
- **文档出处**: research_layer.md §1 "强约束：所有计算出的原始特征，必须在逻辑出口统一 shift(1) 才能交由下一环"
- **当前情况**: `research/feature/momentum.py` 等因子直接使用 `pct_change(period)` 返回结果，没有 `.shift(1)`
- **影响**: 回测时因子值包含了同期价格信息，导致未来信息泄露，回测结果虚高
- **涉及文件**:
  - `qp/research/feature/momentum.py`
  - `qp/research/feature/volatility.py`
  - `qp/research/feature/volume.py`
  - `qp/research/feature/money_flow.py`
- **方案**: 在每个因子的 `compute()` 返回前，对 `feature_value` 列加 `shift(1)`（或在 `BaseFeature.compute()` 中统一处理）

---

### 1.2 OLS 截面中性化（含市值剥离）

- **状态**: `[x]` ✅ 已完成 (2026-07-21)
- **文档出处**: research_layer.md §2 "截面中性化的数学本质，就是剥离风险因子暴露后的残差"
- **当前情况**: `research/factor_processor.py` 中的 `industry_neutralize()` 只做行业中位数减法，没有市值（Size）风险因子剥离，也没有使用 OLS 回归
- **文档公式**:
  ```
  f_raw,i = α + β₁·Size_i + Σ γₖ·Industry_i,k + ε_i
  残差 ε̂_i = 纯净 Alpha 因子
  ```
- **当前 vs 要求**:

| 能力 | 文档要求 | 当前实现 | 状态 |
|---|---|---|---|
| 行业剥离 | ✅ | ✅（行业中位数减法） | 有但方法不同 |
| 市值剥离 | ✅ | ❌ 无 | 缺失 |
| OLS 回归 | ✅（statsmodels） | ❌ 无 | 缺失 |
| 残差提取 | ✅ | ❌ 无 | 缺失 |

- **方案**:
  1. 在 `factor_processor.py` 中新增 `neutralize_cross_section_ols()` 函数
  2. 输入：单日因子 Series + 风险矩阵 DataFrame（市值 + 行业 one-hot）
  3. 使用 statsmodels OLS 回归，提取 `model.resid`
  4. 重新对齐原 Index 输出
  5. 在有 `risk_matrix` 数据时优先走 OLS 路径，否则 fallback 到当前行业中位数方法

---

## 二、P1 — 研究流程完整性

### 2.1 evaluation/ 目录 — 因子评估指标

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §10.1、research_layer.md §3
- **已实现**:
  - `rank_ic.py`: `compute_rank_ic()`, `evaluate_factor_ic()`, `compute_daily_ic_series()`, `compute_ic_decay()`, `ICRecord`
  - `layered_test.py`: `compute_layered_returns()`, `compute_quantile_spread_series()`, `LayeredTestResult`
  - ICRecord 内置 rule.md §10.1 阈值自动检测（`ic_mean_pass`, `ic_ir_pass`, `ic_t_stat_pass`, `all_pass`）
- **rule.md §10.1 阈值**:

| 指标 | 阈值 |
|---|---|
| Rank IC 均值 | abs ≥ 0.02 |
| IC_IR | ≥ 0.3 |
| IC t-stat | ≥ 2.0 |
| 最小样本区间 | ≥ 3 年 |
| 分层单调性 t-stat | ≥ 2.0 |

---

### 2.2 label/ 目录 — 标签构建

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §7.9.1、research_layer.md §3
- **已实现**:
  - `forward_returns.py`: `build_forward_returns()`, `build_industry_neutral_labels()`, `build_labels()`
  - `label_utils.py`: `detect_label_overlap()`, `validate_label_rebalance_consistency()`, `check_label_coverage()`
  - 行业中性化标签：日内行业 rank-normalize to [0,1]（rule.md §7.9.1）

---

### 2.3 importance/ 目录 — 特征重要性分析

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §7.9.7
- **已实现**:
  - `feature_importance.py`: `compute_shap_importance()`, `compute_gain_importance()`, `compare_importance_versions()`, `ImportanceRecord`, `ImportanceDriftReport`
  - SHAP TreeExplainer 集成 + gain fallback
  - Importance 版本变化对比 + drift severity 分级（none/moderate/severe）
  - Top 5 特征变化 >50% 自动告警 + 单特征权重突增（surge）检测

---

### 2.4 dataset/ 目录 — 研究用数据集管理

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: research_layer.md §1
- **已实现**:
  - `research_dataset.py`: `ResearchDataset` 类
  - `split_train_test()`, `split_train_val_test()`, `split_by_date()` — 时间顺序切分
  - `check_integrity()` — 数据完整性检查（缺失列、重复、负价格、极端涨跌）
  - `filter_pit()` — PIT 视角过滤（上市/退市日期）
  - 自动缓存到 `data/cache/research/`

---

### 2.5 artifact/ 目录 — 实验产物管理

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: 对应 Experiment 生命周期
- **已实现**:
  - `artifact_manager.py`: `ArtifactManager` 类
  - `save_model()` / `load_model_metadata()` / `load_importance()` — 模型版本归档
  - `save_factor_snapshot()` / `load_factor_snapshot()` — 因子快照
  - `archive_experiment()` — 实验记录归档
  - `cleanup_old_models()` / `cleanup_old_snapshots()` — 按数量和年龄清理

---

### 2.6 experiment/multifactor_pipeline.py — 多因子实验编排

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **当前情况**: 已完整串接到 `factor_processor.py` 的因子管线（winsorize → normalize → neutralize → combine），Stage 2 改为直接调用 `factor_pipeline()`；Stage 3 IC 分析使用 `evaluation/` 模块 + 分层单调性测试；新增 `_flatten_price_data()` 和 `_build_industry_map()` 辅助函数

---

## 三、P2 — 工程规范化

### 3.1 PurgedKFold sklearn 兼容接口

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: research_layer.md §3（`PurgedGroupTimeSeriesSplit(_BaseKFold)`）
- **已实现**:
  - `PurgedGroupTimeSeriesSplit` — sklearn-compatible splitter with `split(X, y, groups)` interface
  - `PurgedKFoldSklearn` — 完全继承 `sklearn.model_selection._BaseKFold`，自动兼容 `cross_val_score`、`GridSearchCV`、`RandomizedSearchCV`
  - 保留原有 `PurgedKFold` @dataclass 不变，新增两个类作为补充
  
---

### 3.2 LightGBM 单调约束集成

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §7.9.5
- **已实现**:
  - `build_monotone_constraints(feature_names, directions)` — 从因子方向映射生成约束列表
  - `build_monotone_constraints_dict(feature_names, directions)` — 生成 dict 格式约束
  - `LightGBMRankModel.fit()` 接受 `monotone_constraints` kwarg（list 或 dict）
  - `save_model()` / `load_model()` 持久化和恢复约束配置
  - `monotone_constraints` 属性暴露当前约束
  
---

### 3.3 Feature Importance 剧烈变化自动复核

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §7.9.7
- **已实现**:
  - `auto_retrain.py` `_check_feature_importance_drift()` 重写为使用 `importance/` 模块的 `compare_importance_versions()`
  - severe drift → 阻断 promote（`validation_passed = False`）
  - moderate drift → 允许上线但发出 warning
  - 返回详细 drift report（overlap_count, new_entrants, departed, surge_alerts, rank_shifts）
  
---

### 3.4 Model Decay 与 Kill Switch 联动

- **状态**: `[x]` ✅ 已完成 (2026-07-22)
- **文档出处**: rule.md §7.9.8
- **已实现**:
  - `kill_switch.py`: 新增 `ModelDecayTrigger`（继承 `_BaseTrigger`），可加入 `KillSwitch` 触发器列表
  - `model_decay_lifecycle.py`: 新增 `ModelDecayLifecycle` 桥接层
    - DECAYING → 自动降级到 `SHADOW_PRODUCTION`
    - STALE → 自动触发 `KILL_SWITCH`
    - 通过 `StrategyRegistry.set_lifecycle()` 实际修改策略状态
  - `kill_switch_pipeline.py`: `_check_kill_switch()` 已集成 `ModelDecayTrigger`
  - `ModelDecayDetector.check_series()` 支持连续 N 天阈值检查，防止单日误报
  
---

## 四、P3 — Ray 并行引擎（中长期目标）

### 4.1 Ray 运行时初始化

- **状态**: `[ ]`
- **文档出处**: research_layer.md §Ray 工业级引擎
- **当前情况**: 项目无 Ray 依赖，无 `ray.init()` 代码
- **方案**: 在 `pyproject.toml` 添加 `ray` 依赖，创建 `research/engine/` 目录

---

### 4.2 Ray Remote Tasks

- **状态**: `[ ]`
- **涉及组件**:

| Task | 函数名 | 用途 |
|---|---|---|
| 因子计算 | `_compute_factor_task` | 并行计算多个因子类型 |
| 截面中性化 | `_neutralize_date_task` | 按交易日并发 OLS 中性化 |
| Fold 评估 | `_eval_fold_task` | 并行计算各 Fold 的 Rank IC |

---

### 4.3 Plasma 共享内存

- **状态**: `[ ]`
- **功能**: `ray.put(market_data)` 将大数据集放入共享内存，后续 Task 零拷贝读取
- **对应文档代码**: `market_ref = ray.put(market_data)`

---

### 4.4 RayResearchEngine 门面类

- **状态**: `[ ]`
- **文档代码**: `class RayResearchEngine` with `run_pipeline()` method
- **应包含**:
  - Step 1: 共享内存广播
  - Step 2: 并行批量因子计算
  - Step 3: 并行截面中性化
  - Step 4: 并行 Purged CV 评估

---

### 4.5 性能优化配套

- **状态**: `[ ]`

| 优化项 | 说明 |
|---|---|
| 显式内存回收 | `ray.internal.free([ref])` 防止 Plasma 泄漏 |
| Chunking 批量调度 | 3000+ 交易日时按月/周分组提交，防止 Task Overhead |
| Ray Dashboard | `ray.init(dashboard_host="0.0.0.0", dashboard_port=8265)` |

---

## 五、实现顺序建议

```
Week 1 ─ P0
  ├── 1.1  shift(1) 防未来信息泄露     ← 改因子 compute() 返回值
  └── 1.2  OLS 截面中性化（含市值剥离） ← 新增 neutralize_cross_section_ols()

Week 2 ─ P1（填充空目录）
  ├── 2.2  label/   标签构建
  ├── 2.1  evaluation/  因子评估指标（IC/IC_IR/t-stat/分层测试）
  ├── 2.4  dataset/  研究数据集管理
  └── 2.3  importance/  SHAP + 特征重要性分析

Week 3 ─ P1 收尾 + P2
  ├── 2.5  artifact/  实验产物管理
  ├── 2.6  multifactor_pipeline 完整串联
  ├── 3.1  PurgedKFold sklearn 兼容
  └── 3.2  LightGBM monotone_constraints

Week 4+ ─ P2 收尾 + P3（视数据规模决定）
  ├── 3.3  Feature Importance 自动复核串联
  ├── 3.4  Model Decay ↔ Kill Switch 联动
  └── 4.x  Ray 并行引擎（数据量 < 1000 只股票时可暂缓）
```

---

## 六、完成记录

| 日期 | 项目 | 改动摘要 |
|---|---|---|
| 2026-07-21 | 1.1 shift(1) | 所有 12 个因子类的 `compute()` 方法和 4 个 batch 函数添加 `.shift(1).over("symbol")`，防止未来信息泄露 | P0 Week 1 |
| 2026-07-21 | 1.2 OLS 截面中性化 | 新增 `neutralize_cross_section_ols()`、`neutralize_factors_ols()`、`_build_risk_matrix()`、`_one_hot_encode_industries()` 四个函数，集成到 `factor_pipeline()` 支持 `neutralize_method="ols"`，可同时剥离市值+行业风险暴露 | P0 Week 1 |
| 2026-07-22 | 2.1 evaluation/ | 新增 `rank_ic.py`（Rank IC/IC_IR/t-stat/IC decay）+ `layered_test.py`（分层单调性/spread t-stat），ICRecord 内置 rule.md §10.1 阈值自动检测 | P1 Week 2 |
| 2026-07-22 | 2.2 label/ | 新增 `forward_returns.py`（原始/行业中性化标签）+ `label_utils.py`（重叠检测/调仓一致性校验/覆盖率检查） | P1 Week 2 |
| 2026-07-22 | 2.3 importance/ | 新增 `feature_importance.py`（SHAP TreeExplainer + gain 排名 + 版本对比 + drift severity + surge 告警） | P1 Week 2 |
| 2026-07-22 | 2.4 dataset/ | 新增 `research_dataset.py`（ResearchDataset: PIT 过滤/时间顺序切分/完整性检查/缓存） | P1 Week 2 |
| 2026-07-22 | 2.5 artifact/ | 新增 `artifact_manager.py`（ArtifactManager: 模型归档/因子快照/实验记录/按年龄数量清理） | P1 Week 2 |
| 2026-07-22 | 2.6 multifactor_pipeline | 重构 Stage 2 使用 `factor_pipeline()` 直接驱动 winsorize→normalize→neutralize→combine；Stage 3 IC 评估改用 `evaluation/` 模块 + 分层单调性测试 | P1 Week 2 |
| 2026-07-22 | 3.1 PurgedKFold sklearn | 新增 `PurgedGroupTimeSeriesSplit`（标准 sklearn splitter）+ `PurgedKFoldSklearn`（完整 _BaseKFold 子类），GridSearchCV 测试通过 | P2 Week 3 |
| 2026-07-22 | 3.2 LightGBM monotone | 新增 `build_monotone_constraints()` / `build_monotone_constraints_dict()`，`LightGBMRankModel.fit()` 接受 `monotone_constraints` kwarg，save/load 持久化 | P2 Week 3 |
| 2026-07-22 | 3.3 Importance auto-review | 重写 `_check_feature_importance_drift()` 使用 `compare_importance_versions()`；severe drift 阻断 promote；moderate drift 告警放行 | P2 Week 4 |
| 2026-07-22 | 3.4 Model Decay ↔ Kill Switch | 新增 `ModelDecayTrigger`（KillSwitch 集成）+ `ModelDecayLifecycle`（DECAYING→Shadow, STALE→KILL_SWITCH 自动降级）+ `KillSwitchPipeline` 已集成 | P2 Week 4 |
