"""CLI command handlers for the "paper" group."""

from __future__ import annotations

import sys


def cmd_paper_start() -> int:
    """Start a 30-day paper trading run."""
    from datetime import date

    from qp.strategy.paper_trading import PaperTradingTracker
    from qp.strategy.registry import StrategyRegistry

    strategy_id = "simple_rank_v1.0"
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        strategy_id = sys.argv[3]

    print("═══ QP 模拟交易 / Paper Trading ═══")
    print()
    print(f"  策略 / Strategy:  {strategy_id}")
    print(f"  起始日期 / Start: {date.today().isoformat()}")

    # Verify strategy exists
    try:
        registry = StrategyRegistry()
        from qp.strategy.simple_rank import SimpleRankStrategy

        registry.register(SimpleRankStrategy(top_n=10))
        registry.get(strategy_id)
    except KeyError:
        print(f"  ❌ 策略 '{strategy_id}' 未注册")
        return 1

    tracker = PaperTradingTracker()
    run = tracker.start(strategy_id, capital=1_000_000)
    print(f"  运行编号 / Run ID: {run.run_id}")
    print(f"  状态文件 / State:   {run.state_file}")
    print()
    print("  ✅ 模拟交易已启动。每天运行 'qp paper status' 查看进度。")
    print("  ✅ Paper trading started. Run 'qp paper status' for daily updates.")
    return 0


def cmd_paper_status() -> int:
    """Show current paper trading status."""
    from qp.strategy.paper_trading import PaperTradingTracker

    strategy_id = "simple_rank_v1.0"
    if len(sys.argv) > 3 and not sys.argv[3].startswith("--"):
        strategy_id = sys.argv[3]

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
