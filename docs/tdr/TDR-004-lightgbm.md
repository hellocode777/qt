# TDR-004: LightGBM

> Technology Decision Record — 默认 ML 模型

## 选择

**LightGBM** — 梯度提升决策树框架，**LambdaRank 目标函数**。

## 理由

- LambdaRank 直接优化排序质量（NDCG），天然适合截面排序策略
- 训练速度快（比 XGBoost 快 3-10x）
- 原生支持 `group` 参数（按日期截面分组）
- 支持单调约束（对估值因子强制负向，防过拟合噪声）
- Python 生态成熟，SHAP 可解释

## 使用方式

```python
from qp.research.trainer.lgb_rank import LightGBMRankModel

model = LightGBMRankModel()
model.fit(X_train, y_train)       # y = 截面 rank 百分位
model.predict(X_test)             # 排序分数
model.save_model("models/lgb_v1.txt")
```

## 训练配置（`StrategyConfig.lgb_params`）

```python
{
    "objective": "lambdarank",
    "metric": "ndcg",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "monotone_constraints": [...]  # 估值因子强制负向
}
```

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| XGBoost | 生态好 | LambdaRank 支持弱 |
| CatBoost | 类别特征好 | 排序任务无优势 |
| **LightGBM** ✅ | 快+排序原生 | — |
