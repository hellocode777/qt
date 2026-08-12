"""CLI command handlers for the "paper" group."""

from __future__ import annotations


def cmd_paper_start(strategy_id: str = "momentum_vol_full", capital: float = 100_000) -> int:
    """Start a 30-day paper trading run."""
    from datetime import date

    from qp.simulation.paper_trading import PaperTradingTracker
    from qp.strategy.registry import StrategyRegistry

    print("═══ QP 模拟交易 / Paper Trading ═══")
    print()
    print(f"  策略 / Strategy:  {strategy_id}")
    print(f"  起始日期 / Start: {date.today().isoformat()}")
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


def cmd_paper_status(strategy_id: str = "momentum_vol_full") -> int:
    """Show current paper trading status."""
    from qp.simulation.paper_trading import PaperTradingTracker

    tracker = PaperTradingTracker()
    run = tracker.load(strategy_id)

    if run is None:
        print(f"  ⚠ 未找到 '{strategy_id}' 的模拟交易记录。请先运行 'qp paper start'。")
        print("  ⚠ No paper trading run found. Run 'qp paper start' first.")
        return 1

    st = tracker.status(run)

    print("═══ QP 模拟交易状态 / Paper Trading Status ═══")
    print()
    print(f"  策略 / Strategy:    {st['strategy_id']}")
    print(f"  运行编号 / Run ID:  {st['run_id']}")
    print(f"  起始日期 / Start:   {st['start_date']}")
    print(f"  已过天数 / Days:    {st['elapsed_days']}/30")
    print(f"  当前权益 / Equity:  ¥{st['current_equity']:,.0f}")
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
