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

Optuna 集成已规划但非默认。常规实验使用固定参数 + Purged CV。
