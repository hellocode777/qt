"""CLI command handlers for the "model" group."""

from __future__ import annotations

import sys


def cmd_model_list() -> int:
    """List registered models."""
    from qp.research.trainer import ModelRegistry

    registry = ModelRegistry()
    models = registry.list_models()

    if not models:
        print("(empty)")
        print("  暂无已注册模型。")
        return 0

    print(f"{'Model ID':<35s} {'Strategy':<25s} {'Stage':<16s} {'Sharpe':>8s} {'Features'}")
    print("-" * 120)
    for m in models:
        features_str = ", ".join(m.features[:3])
        if len(m.features) > 3:
            features_str += f" +{len(m.features) - 3}"
        print(
            f"{m.model_id:<35s} "
            f"{m.strategy_id:<25s} "
            f"{m.stage.value:<16s} "
            f"{m.metrics.get('sharpe_ratio', 0):>7.2f} "
            f" {features_str}"
        )
    print(f"\n共 {len(models)} 个模型 / {len(models)} models total")
    return 0


def cmd_model_show() -> int:
    """Show model details."""
    if len(sys.argv) < 3:
        print("用法: qp model show <model_id>")
        return 1

    from qp.research.trainer import ModelRegistry

    model_id = sys.argv[2]
    registry = ModelRegistry()
    meta = registry.get(model_id)

    if meta is None:
        print(f"模型 {model_id} 未找到 / Model not found")
        return 1

    print(f"=== 模型详情 / Model: {model_id} ===")
    print()
    print(f"  策略 / Strategy:       {meta.strategy_id}")
    print(f"  阶段 / Stage:          {meta.stage.value}")
    print(f"  创建时间 / Created:     {meta.created_at}")
    print(f"  文件哈希 / Hash:        {meta.file_hash}")
    print(f"  文件路径 / Path:        {meta.file_path}")
    print()
    print("  ── 训练配置 / Training Config ──")
    print(f"    特征 / Features:      {meta.features}")
    print(f"    时间窗口 / Window:     {meta.training_window}")
    print(f"    CV折数 / CV Folds:    {meta.cv_folds}")
    if meta.hyperparams:
        print("    超参数 / Hyperparams:")
        for k, v in meta.hyperparams.items():
            print(f"      {k}: {v}")
    print()
    print("  ── 评估指标 / Metrics ──")
    if meta.metrics:
        for k, v in sorted(meta.metrics.items()):
            print(f"    {k}: {v}")
    else:
        print("    (none)")

    return 0
