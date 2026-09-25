"""CLI command handlers for the "retrain" group."""

from __future__ import annotations

from qp.shared.time import today_cn


def cmd_retrain(strategy_id: str = "", dry_run: bool = False) -> int:
    """Run monthly model retrain pipeline.

    Args:
        strategy_id: Target strategy ID. Empty → the registry's single APPROVED
            strategy (never a hardcoded name — ``simple_rank_v1.0`` was the old
            default and isn't registered anywhere).
        dry_run: Rehearsal mode — no artifacts written, no model registered.

    Returns:
        Process exit code (0 = success, 1 = unresolvable strategy or failure).
    """
    from qp.platform.pipeline.context import PipelineContext
    from qp.research.trainer.auto_retrain import MonthlyRetrainPipeline
    from qp.strategy.registry import resolve_single_approved_strategy_id

    if not strategy_id:
        resolved, why = resolve_single_approved_strategy_id()
        if resolved is None:
            print(f"❌ {why}")
            return 1
        strategy_id = resolved

    print("═══ QP 模型重训 / Model Retrain ═══")
    print()
    print(f"  策略 / Strategy:    {strategy_id}")
    print(f"  模式 / Mode:        {'演习 dry-run' if dry_run else '正式 live'}")
    print()

    context = PipelineContext(
        pipeline_name="monthly_retrain",
        parameters={
            "strategy_id": strategy_id,
            "train_end": today_cn().isoformat(),
            "dry_run": dry_run,
        },
    )

    pipeline = MonthlyRetrainPipeline()
    result = pipeline.run(context)

    if result.status.value == "failed":
        print("  ❌ 重训失败 / Retrain FAILED")
        for e in result.errors:
            print(f"     {e}")
        return 1

    print(f"  ✅ 重训完成 / Status: {result.status.value}")
    print()

    if result.metrics:
        print("  ── 指标 / Metrics ──")
        for k, v in sorted(result.metrics.items()):
            print(f"  {k}: {v:.4f}")

    if result.metadata and "retrain_result" in result.metadata:
        rr = result.metadata["retrain_result"]
        print()
        print("  ── 结果 / Result ──")
        print(f"  验证通过 / Validated: {rr.validation_passed}")
        print(f"  模型注册 / Registered: {rr.model_registered}")
        if rr.model_id:
            print(f"  模型编号 / Model ID: {rr.model_id}")
        print(f"  {rr.recommendation}")

    print()
    return 0
