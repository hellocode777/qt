"""CLI command handlers for the "paper" group."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qp.shared.time import today_cn

if TYPE_CHECKING:
    from qp.simulation.paper_trading import PaperTradingRun, PaperTradingTracker


def cmd_paper_start(strategy_id: str = "momentum_vol_full", capital: float = 100_000) -> int:
    """Start a 30-day paper trading run."""

    from qp.simulation.paper_trading import PaperTradingTracker
    from qp.strategy.registry import StrategyRegistry

    print("═══ QP 模拟交易 / Paper Trading ═══")
    print()
    print(f"  策略 / Strategy:  {strategy_id}")
    print(f"  起始日期 / Start: {today_cn().isoformat()}")
    print(f"  初始资金 / Capital: ¥{capital:,.0f}")

    # Verify strategy exists in the registry (no auto-registration —
    # paper trading validates an already-registered strategy, Rule 11)
    try:
        registry = StrategyRegistry()
        if strategy_id not in registry.list_strategies():
            print(f"  ❌ 策略 '{strategy_id}' 未注册")
            print(f"     已注册策略: {registry.list_strategies()}")
            return 1
    except Exception as e:
        print(f"  ⚠ 注册表读取失败: {e}")
        return 1

    tracker = PaperTradingTracker()
    run = tracker.start(strategy_id, capital=capital)
    print(f"  运行编号 / Run ID: {run.run_id}")
    print(f"  状态文件 / State:   {run.state_file}")
    print()
    print("  ✅ 模拟交易已启动。每天运行 'qp paper status' 查看进度。")
    print("  ✅ Paper trading started. Run 'qp paper status' for daily updates.")
    return 0


def _paper_status_label(run: PaperTradingRun) -> str:
    """One-line lifecycle label for a paper run (never fakes a measurement)."""
    if run.result is not None:
        return "✅ PASS · 已完成" if run.result.passed else "❌ FAIL · 已完成"
    if run.is_complete:
        return "已完成（未评估）"
    return f"进行中 {run.elapsed_days}/30"


def _print_paper_overview(tracker: PaperTradingTracker) -> int:
    """Print one row per run on disk, separating active from completed."""
    runs = tracker.list_runs()
    print("═══ QP 模拟交易状态 / Paper Trading Status ═══")
    print()
    if not runs:
        print("  ℹ 没有任何模拟交易运行。启动一只: qp paper start <strategy_id>")
        print()
        return 0

    print("  ── 全部运行 / All runs ──")
    for run in runs:
        ret = f"{run.result.total_return_pct:+.2f}%" if run.result else "N/A"
        print(
            f"  {run.strategy_id:<24} {run.run_id:<14} {run.start_date!s:<12} "
            f"{run.elapsed_days:>2}/30  ¥{run.current_equity:>10,.0f}  "
            f"收益 {ret:<9} {_paper_status_label(run)}"
        )
    active = sum(1 for r in runs if not r.is_complete)
    print()
    print(f"  活跃 / Active: {active} ｜ 已完成 / Completed: {len(runs) - active}")
    print("  ℹ 已完成运行保留在 data/paper_trading/（WebUI 净值曲线 + 审计用）；")
    print("    scheduler 18:32 的 job 只推进未完成的 run，不会重复推进。")
    print("  查看单条详情: qp paper status <strategy_id>")
    print()
    return 0


def cmd_paper_status(strategy_id: str | None = None) -> int:
    """Show paper trading status.

    With no strategy id: one row per run on disk, marking which runs are still
    active (the scheduler advances those) and which are completed history.
    """
    from qp.simulation.paper_trading import PaperTradingTracker

    tracker = PaperTradingTracker()
    if not strategy_id:
        return _print_paper_overview(tracker)

    run = tracker.load(strategy_id)

    if run is None:
        print(f"  ⚠ 未找到 '{strategy_id}' 的模拟交易记录。请先运行 'qp paper start'。")
        print("  ⚠ No paper trading run found. Run 'qp paper start' first.")
        print("  ℹ 查看全部运行: qp paper status")
        return 1

    st = tracker.status(run)

    print("═══ QP 模拟交易状态 / Paper Trading Status ═══")
    print()
    print(f"  策略 / Strategy:    {st['strategy_id']}")
    print(f"  运行编号 / Run ID:  {st['run_id']}")
    print(f"  起始日期 / Start:   {st['start_date']}")
    print(f"  已过天数 / Days:    {st['elapsed_days']}/30")
    print(f"  当前权益 / Equity:  ¥{st['current_equity']:,.0f}")
    print(f"  状态 / Status:      {_paper_status_label(run)}")
    print()

    if st["is_complete"] and "result" in st:
        r = st["result"]
        icon = "✅" if r["passed"] else "❌"
        print("  ── 评估结果 / Evaluation ──")
        print(f"  {icon} 通过 / Passed:    {r['passed']}")
        print(f"  总收益 / Return:         {r['total_return']:.1f}%")
        print(f"  夏普 / Sharpe:           {r['sharpe']:.2f}")
        print(f"  最大回撤 / Max DD:       {r['max_drawdown']:.1f}%")
        print(f"  建议 / Recommendation:   {r['recommendation']}")
    else:
        remaining = 30 - st["elapsed_days"]
        print(f"  ⏳ 还剩 {remaining} 天完成评估 / {remaining} days remaining.")
    print()
    return 0
