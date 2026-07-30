"""CLI command handlers for the "simulation shadow" group."""

from __future__ import annotations


def cmd_shadow_run(date_str: str = "") -> int:
    """Run today's shadow simulation."""
    from qp.simulation.shadow_ledger import ShadowLedger

    ledger = ShadowLedger()
    result = ledger.run_daily(date_str)

    if result.get("status") == "no_decision":
        print("❌ 今天还没有决策包。请先运行 qp run daily")
        return 1

    print("═══ Shadow Production 影子运行 ═══")
    print(f"  日期:        {result['date']}")
    print(f"  决策包:      {result['decision_id']}")
    print(f"  买入:        {result['n_buys']} | 卖出: {result['n_sells']}")
    print(f"  持仓数:      {result['n_positions']}")
    print(f"  市值:        ¥{result['market_value']:,.0f}")
    print(f"  当日盈亏:    ¥{result['unrealized_pnl']:+,.0f}")
    print(f"  累计已实现:  ¥{result['realized_pnl']:+,.0f}")
    print(f"  总权益:      ¥{result['total_equity']:,.0f}")
    return 0


def cmd_shadow_summary() -> int:
    """Show shadow portfolio performance summary."""
    from qp.simulation.shadow_ledger import ShadowLedger

    ledger = ShadowLedger()
    summary = ledger.summary()

    print("═══ Shadow Portfolio 影子组合 ═══")
    print(f"  活跃持仓:    {summary['active_count']}")
    print(f"  持仓市值:    {summary['total_value_fmt']}")
    print(f"  已平仓:      {summary['closed_count']}")
    print(f"  胜率:        {summary['win_rate']}")
    print(f"  已实现盈亏:  {summary['realized_pnl_fmt']}")
    print(f"  累计收益:    {summary['total_return_fmt']}")
    print()

    history = summary.get("history", [])
    if history:
        print("  最近5天:")
        for h in history[-5:]:
            pnl = h.get("unrealized_pnl", 0)
            sign = "+" if pnl >= 0 else ""
            print(
                f"    {h['date']} | 权益 ¥{h['total_equity']:,.0f} | "
                f"盈亏 {sign}¥{pnl:,.0f} | 持仓 {h['n_positions']}"
            )

    # Show active positions
    positions = ledger.get_positions()
    if positions:
        print(f"\n  当前持仓 ({len(positions)} 只):")
        for p in positions[:10]:
            print(f"    {p['symbol']:<8s} {p['shares']:>6d}股 @¥{p['entry_price']:.2f} | {p['strategy']}")
    return 0
