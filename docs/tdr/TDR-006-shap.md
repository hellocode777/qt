# TDR-006: SHAP

> Technology Decision Record — 模型可解释性

## 选择

**SHAP (SHapley Additive exPlanations)** — 博弈论驱动的特征归因。

## 理由

- 基于 Shapley 值，理论严格（非启发式方法）
- 支持 Tree SHAP，对 LightGBM 精确且快速
- 可视化丰富：summary plot, waterfall, dependence plot
- 满足 ADR-008 要求的特征重要性稳定性检查

## 使用方式

```python
import shap

model = LightGBMRankModel()
model.fit(X_train, y_train)

explainer = shap.TreeExplainer(model._model)
shap_values = explainer.shap_values(X_test)

# 可视化
shap.summary_plot(shap_values, X_test)
```

## 在 QP 中的角色

```python
# qp/research/importance/feature_importance.py
# 集成 SHAP 用于：
# 1. 特征重要性排名（替代 gain/split）
# 2. 稳定性检查：Top 5 特征排名 vs 上一版 → 剧烈变化触发人工复核
# 3. 方向验证：SHAP 方向是否与因子方向一致
```

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| Gain/Split Importance | 简单 | 有偏，不稳定 |
| Permutation Importance | 无模型依赖 | 慢 |
| LIME | 局部近似 | 不是全局归因 |
| **SHAP** ✅ | 理论严格 | Tree 模型专用 |
