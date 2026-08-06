"""CLI command handlers for the "position" group.

qp position list            — Show all active positions
qp position show <id>       — Show a specific position detail
qp position close <id>      — Close a position (record exit)
qp position pnl             — Show total realized P&L
qp position history [N]     — Show recent position history
"""

from __future__ import annotations


def cmd_position_list() -> int:
    """List all active positions."""
    from qp.decision.position_ledger import PositionLedger

    ledger = PositionLedger()
    active = ledger.get_active()

    if not active:
        print("(empty) — 当前无活跃持仓")
        return 0

    total_value = ledger.total_active_value()
    print(
        f"{'ID':<10s} {'Symbol':<10s} {'Entry':<12s} {'Price':>8s} {'Shares':>8s} {'Value':>12s} {'Strategy':<20s} {'Decision'}"
    )
    print("-" * 100)
    for p in active:
        print(
            f"{p.position_id:<10s} "
            f"{p.symbol:<10s} "
            f"{p.entry_date:<12s} "
            f"¥{p.entry_price:>7.2f} "
            f"{p.shares:>8d} "
            f"¥{p.market_value:>11.0f} "
            f"{p.strategy_id:<20s} "
            f"{p.decision_id}"
        )

    print(f"\n活跃持仓: {len(active)} | 总市值: ¥{total_value:,.0f}")
    return 0


def cmd_position_show(position_id: str) -> int:
    """Show a specific position detail."""
    from qp.decision.position_ledger import PositionLedger

    ledger = PositionLedger()
    pos = ledger.get(position_id)
    if pos is None:
        print(f"❌ Position '{position_id}' not found.")
        return 1

    print("═══ 持仓详情 / Position Detail ═══")
    print(f"  ID:       {pos.position_id}")
    print(f"  标的:     {pos.symbol}")
    print(f"  状态:     {pos.status.name}")
    print(f"  入场日期: {pos.entry_date}")
    print(f"  入场价格: ¥{pos.entry_price:.2f}")
    print(f"  股数:     {pos.shares}")
    print(f"  市值:     ¥{pos.market_value:,.0f}")
    print(f"  策略:     {pos.strategy_id}")
    print(f"  决策包:   {pos.decision_id}")
    if pos.is_active:
        print(f"  未实现盈亏: ¥{pos.realized_pnl:,.0f}")
    else:
        print(f"  出场日期: {pos.exit_date}")
        print(f"  出场价格: ¥{pos.exit_price:.2f}")
        print(f"  出场原因: {pos.exit_reason}")
        print(f"  已实现盈亏: ¥{pos.pnl:,.0f} ({pos.pnl_pct:.2%})")
    if pos.notes:
        print(f"  备注:     {pos.notes}")
    return 0


def cmd_position_close(
    position_id: str, exit_price: float = 0.0, reason: str = ""
) -> int:
    """Close an active position.

    Args:
        position_id: Position to close.
        exit_price: Exit fill price (required).
        reason: Exit reason (optional).
    """
    from qp.decision.position_ledger import PositionLedger

    if exit_price <= 0:
        print("❌ 请提供出场价格: qp position close <id> --price <value>")
        print(
            "   Example: qp position close P-00001 --price 15.50 --reason target_reached"
        )
        return 1

    ledger = PositionLedger()
    closed = ledger.close(position_id, exit_price, exit_reason=reason)
    if closed is None:
        print(f"❌ 无法平仓 '{position_id}' — 未找到或已平仓")
        return 1

    print(f"✅ 已平仓: {closed.symbol} {closed.shares}股")
    print(f"   入场 ¥{closed.entry_price:.2f} → 出场 ¥{closed.exit_price:.2f}")
    print(f"   盈亏: ¥{closed.pnl:,.0f} ({closed.pnl_pct:.2%})")
    if reason:
        print(f"   原因: {reason}")
    return 0


def cmd_position_pnl() -> int:
    """Show total realized P&L summary."""
    from qp.decision.position_ledger import PositionLedger

    ledger = PositionLedger()
    active = ledger.get_active()
    total_value = ledger.total_active_value()
    total_pnl = ledger.total_realized_pnl()
    all_positions = ledger.get_history(limit=100)

    closed = [p for p in all_positions if not p.is_active]
    winning = [p for p in closed if p.pnl > 0]

    print("═══ P&L 摘要 / P&L Summary ═══")
    print(f"  活跃持仓: {len(active)} (市值 ¥{total_value:,.0f})")
    print(f"  已平仓:   {len(closed)}")
    print(
        f"  胜率:     {len(winning)}/{len(closed)} ({len(winning) / len(closed) * 100:.0f}%)"
        if closed
        else "  胜率:     N/A"
    )
    print(f"  已实现盈亏: ¥{total_pnl:,.0f}")

    if closed:
        # Show last 5 closed
        print("\n  最近平仓:")
        for p in sorted(closed, key=lambda x: x.exit_date, reverse=True)[:5]:
            sign = "+" if p.pnl >= 0 else ""
            print(
                f"    {p.symbol:<8s} {p.entry_date} → {p.exit_date} "
                f"¥{p.entry_price:.2f} → ¥{p.exit_price:.2f} "
                f"{sign}¥{p.pnl:,.0f} ({p.pnl_pct:+.2%})"
            )
    return 0


def cmd_position_history(limit: int = 30) -> int:
    """Show recent position history."""
    from qp.decision.position_ledger import PositionLedger

    ledger = PositionLedger()
    history = ledger.get_history(limit=limit)

    if not history:
        print("(empty) — 暂无持仓记录")
        return 0

    print(
        f"{'ID':<10s} {'Symbol':<10s} {'Status':<10s} {'Entry':<12s} {'Exit':<12s} {'PnL':>10s} {'Decision'}"
    )
    print("-" * 90)
    for p in history:
        status = p.status.name
        exit_date = p.exit_date if p.exit_date else "—"
        pnl_str = f"¥{p.pnl:,.0f}" if p.pnl else "—"
        print(
            f"{p.position_id:<10s} "
            f"{p.symbol:<10s} "
            f"{status:<10s} "
            f"{p.entry_date:<12s} "
            f"{exit_date:<12s} "
            f"{pnl_str:>10s} "
            f"{p.decision_id}"
        )
    print(f"\n共 {len(history)} 条记录")
    return 0
