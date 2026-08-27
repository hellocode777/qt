"""CLI command handlers for the "strategy" group.

ADR-031 Step 4: Strategy approval workflow — promote experiment-validated
strategies to frozen ApprovedStrategy snapshots that Daily Pipeline consumes.
"""

from __future__ import annotations

from qp.shared.json_io import json_load
from qp.shared.paths import EXPERIMENTS_DIR


def cmd_strategy_approve(
    strategy_id: str,
    approved_by: str = "",
    version: str | None = None,
    from_experiment: str | None = None,
) -> int:
    """Freeze a registered strategy as an ApprovedStrategy snapshot.

    Args:
        strategy_id: Strategy to approve.
        approved_by: Name of the approver.
        version: Optional version string override.
        from_experiment: If set, load weights + backtest metrics from
            this experiment_id instead of the current Registry metadata.

    The strategy must already be registered with weights, parameters,
    and backtest metrics in its StrategyMeta (unless --from-experiment
    is used, in which case those are loaded from the experiment record).
    """
    from pathlib import Path

    from qp.shared.types import StrategyLifecycle
    from qp.strategy.registry import StrategyMeta, StrategyRegistry

    registry = StrategyRegistry()

    # ── Load weights & metrics from experiment if specified ──
    if from_experiment:
        exp_path = Path(EXPERIMENTS_DIR) / f"{from_experiment}.json"
        if not exp_path.exists():
            print(f"❌ 实验 '{from_experiment}' 不存在 / Experiment not found")
            print(f"   {exp_path}")
            return 1

        exp_data = json_load(exp_path)

        exp_cfg = exp_data.get("config", {})
        exp_met = exp_data.get("metrics", {})
        exp_weights = exp_cfg.get("model_params", {})

        if not exp_weights:
            print(f"❌ 实验 '{from_experiment}' 没有 model_params / No weights in experiment")
            return 1

        exp_strategy = exp_cfg.get("strategy_name", strategy_id)
        if exp_strategy != strategy_id:
            print(f"⚠️  实验策略 '{exp_strategy}' ≠ 目标策略 '{strategy_id}'")
            print("   继续使用实验权重, 但请确认这是你想要的")

        # Build/update StrategyMeta from experiment data
        try:
            meta = registry.get_meta(strategy_id)
        except KeyError:
            meta = StrategyMeta()
        meta.weights = dict(exp_weights)
        meta.backtest_ic = float(exp_met.get("ic_mean", 0))
        meta.backtest_sharpe = float(exp_met.get("sharpe_ratio", 0))
        meta.backtest_max_dd = float(exp_met.get("max_drawdown_pct", 0))
        meta.backtest_excess_return = float(exp_met.get("excess_return_pct", 0))
        meta.strategy_version = version or from_experiment
        meta.owner = approved_by or meta.owner

        # Ensure strategy is registered in the in-memory registry
        if strategy_id not in registry.list_strategies():
            registry._lifecycles[strategy_id] = StrategyLifecycle.RESEARCH

        # Write updated meta to registry before approve
        registry.set_meta(strategy_id, meta)
        registry._save()

        print(f"📋 从实验加载: {from_experiment}")
        print(f"   权重: {len(exp_weights)} 因子")
        print(f"   IC: {meta.backtest_ic:.4f}  Sharpe: {meta.backtest_sharpe:.2f}")
    else:
        # Check that the strategy exists
        try:
            registry.get_lifecycle(strategy_id)
        except KeyError:
            print(f"❌ 策略 '{strategy_id}' 未注册 / Strategy not registered")
            print("   先运行 qp run daily 注册策略，或 qp experiment run 验证策略")
            return 1

        meta = registry.get_meta(strategy_id)

    # Check that it has weights
    if not meta.weights:
        print(f"❌ 策略 '{strategy_id}' 没有因子权重 / Strategy has no weights")
        print("   设置 meta.weights 后再 approve")
        return 1

    # Approve
    try:
        approved = registry.approve(
            strategy_id=strategy_id,
            approved_by=approved_by,
            version=version,
        )
    except ValueError as exc:
        print(f"❌ 审批失败 / Approval failed: {exc}")
        return 1

    print("✅ 策略已冻结 / Strategy approved")
    print(approved.describe())  # type: ignore[union-attr]
    return 0


def cmd_strategy_approved_list() -> int:
    """List all approved (frozen) strategy snapshots."""
    from qp.strategy.registry import StrategyRegistry

    registry = StrategyRegistry()
    active = registry.load_active()

    if not active:
        print("(empty) — 暂无已批准策略 / No approved strategies")
        return 0

    print(
        f"{'Strategy ID':<28s} {'Version':<14s} {'Approved By':<16s} {'Factors':<8s} {'Sharpe':<8s}"
    )
    print("-" * 80)
    for s in active:
        from qp.strategy.approved import ApprovedStrategy

        if isinstance(s, ApprovedStrategy):
            sharpe = s.backtest_summary.get("sharpe", 0.0)
            print(
                f"{s.strategy_id:<28s} {s.version:<14s} "
                f"{s.approved_by:<16s} {s.factor_count:<8d} "
                f"{float(str(sharpe)):<8.2f}"
            )
    print(f"\n共 {len(active)} 只已批准策略 / {len(active)} approved strategies")
    return 0


def cmd_strategy_approved_show(strategy_id: str) -> int:
    """Show details of an approved strategy snapshot."""
    from qp.strategy.registry import StrategyRegistry

    registry = StrategyRegistry()
    approved = registry.get_approved(strategy_id)

    if approved is None:
        print(f"❌ 策略 '{strategy_id}' 未批准 / Strategy not approved")
        return 1

    from qp.strategy.approved import ApprovedStrategy

    if isinstance(approved, ApprovedStrategy):
        print(approved.describe())
    return 0


def cmd_strategy_deactivate(strategy_id: str) -> int:
    """Deactivate an approved strategy (revert to BACKTEST_PASSED)."""
    from qp.strategy.registry import StrategyRegistry

    registry = StrategyRegistry()
    try:
        registry.deactivate(strategy_id)
    except KeyError:
        print(f"❌ 策略 '{strategy_id}' 未注册 / Strategy not registered")
        return 1

    print(f"✅ 策略 '{strategy_id}' 已下线 / Strategy deactivated")
    print("   快照保留供审计 / Snapshot preserved for audit")
    return 0


def cmd_strategy_list() -> int:
    """List all registered strategies with lifecycle state."""
    from qp.strategy.registry import StrategyRegistry

    registry = StrategyRegistry()
    sids = registry.list_strategies()

    if not sids:
        print("(empty) — 暂无已注册策略 / No registered strategies")
        print("   运行 qp run daily 后策略将自动注册")
        return 0

    print(f"{'Strategy ID':<28s} {'Lifecycle':<20s} {'Version':<12s} {'Owner':<12s}")
    print("-" * 76)
    for sid in sids:
        try:
            lifecycle = registry.get_lifecycle(sid).value
        except KeyError:
            lifecycle = "unknown"
        try:
            meta = registry.get_meta(sid)
            version = meta.strategy_version
            owner = meta.owner
        except KeyError:
            version = "?"
            owner = "?"
        print(f"{sid:<28s} {lifecycle:<20s} {version:<12s} {owner:<12s}")
    print(f"\n共 {len(sids)} 只策略 / {len(sids)} strategies")
    return 0
