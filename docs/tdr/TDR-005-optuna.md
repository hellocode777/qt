# TDR-005: Optuna

> Technology Decision Record — 超参数优化

## 选择

**Optuna** — 超参数优化框架。

## 理由

- 基于 Tree-structured Parzen Estimator (TPE)，比网格搜索高效 10x+
- 原生支持剪枝（pruning），提前终止差试验
- Pythonic API，与 LightGBM 集成良好
- 试验可恢复、可并行

## 使用方式

```python
import optuna

def objective(trial):
    params = {
        "num_leaves": trial.suggest_int("num_leaves", 15, 127),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1),
    }
    model = LightGBMRankModel(**params)
    model.fit(X_train, y_train)
    return model.evaluate(X_val, y_val)

study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=50)
```

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| GridSearchCV | 简单 | 维度灾难，太慢 |
| Hyperopt | 经典 | 维护不活跃 |
| **Optuna** ✅ | 高效+活跃 | — |

## 当前状态

✅ **Optuna 集成已实现（2026-08-13）**，默认非启用。常规实验仍使用固定参数 + Purged CV。

### 实现方式

- **模块**: `qp/research/trainer/optuna_search.py` — `OptunaSearch` 类
- **CLI**: `qp experiment optuna [--trials N] [--start] [--end] [--train-window] [--timeout] [--seed]`
- **目标函数**: PurgedKFold OOS IC 均值（最大化），每折独立截面 z-score 标准化（防前视偏差）
- **搜索空间**: num_leaves / max_depth / learning_rate / min_data_in_leaf / feature_fraction / bagging_fraction / lambda_l1 / lambda_l2（TPE 采样）
- **基线对比**: 自动计算 DEFAULT_LGB_PARAMS 的 OOS IC，结果含 ΔIC
- **结果保存**: `data/optuna/lgb_optuna_{ts}.json`（study_name + best_params + baseline）

### 验证

- 单元测试: `tests/unit/research/test_optuna_search.py`（合成数据端到端，5 用例）
- 质量门: ruff format/check + pyright 0 errors + pytest 全过

> ⚠️ 短样本最优参数勿直接写死进生产 — 先用完整 walk-forward 回测验证（rule.md §7.9）。
