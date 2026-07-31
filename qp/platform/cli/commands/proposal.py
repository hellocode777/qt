"""CLI command handlers for the "proposal" group."""

from __future__ import annotations


def cmd_proposal_list(status: str = "") -> int:
    """List all proposals, optionally filtered by status."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    proposals = store.list_by_status(status) if status else store.list_all()

    if not proposals:
        print("(empty) — 暂无提案 / No proposals found")
        return 0

    print(f"{'ID':<24s} {'策略':<24s} {'目标':<22s} {'状态':<10s} {'提议人':<12s}")
    print("-" * 92)
    for p in proposals:
        print(
            f"{p.proposal_id:<24s} {p.strategy_id:<24s} "
            f"{p.target_lifecycle:<22s} {p.status:<10s} {p.proposed_by:<12s}"
        )
    print(f"\n共 {len(proposals)} 条提案")
    return 0


def cmd_proposal_show(proposal_id: str) -> int:
    """Show full details of a proposal."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.get(proposal_id)

    if prop is None:
        print(f"提案 {proposal_id} 不存在 / Proposal not found")
        return 1

    print("=" * 60)
    print(f"  提案 {prop.proposal_id} / Proposal Detail")
    print("=" * 60)
    print(f"  策略 / Strategy:     {prop.strategy_id}")
    print(f"  目标状态 / Target:    {prop.target_lifecycle}")
    print(f"  状态 / Status:       {prop.status_label()}")
    print(f"  提议人 / Proposed by: {prop.proposed_by}")
    print(f"  创建时间 / Created:   {prop.created_at[:19]}")
    if prop.reviewer:
        print(f"  审核人 / Reviewer:    {prop.reviewer}")
        print(f"  审核备注 / Notes:     {prop.review_notes}")
        print(f"  审核时间 / Reviewed:  {prop.reviewed_at[:19]}")
    print()
    if prop.justification:
        print("  理由 / Justification:")
        print(f"    {prop.justification}")
    if prop.evidence:
        print("  证据 / Evidence:")
        for k, v in prop.evidence.items():
            print(f"    {k}: {v}")
    print()
    return 0


def cmd_proposal_create(
    strategy_id: str = "",
    target: str = "",
    justification: str = "",
    proposed_by: str = "cli",
) -> int:
    """Create a new strategy promotion proposal."""
    if not strategy_id:
        print("用法: qp proposal create --strategy <id> --target <lifecycle> [--justification ...]")
        print("Usage: qp proposal create --strategy momentum_v1.0 --target paper_trading")
        return 1

    if not target:
        print("错误: 缺少 --target 参数 (如 paper_trading, shadow_production, production)")
        return 1

    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.create(
        strategy_id=strategy_id,
        target_lifecycle=target,
        justification=justification,
        proposed_by=proposed_by,
    )

    print(f"✅ 提案已创建 / Proposal created: {prop.proposal_id}")
    print(f"   策略: {strategy_id} → {target}")
    print(f"   状态: {prop.status_label()}")
    return 0


def cmd_proposal_approve(proposal_id: str, reviewer: str = "", notes: str = "") -> int:
    """Approve a proposal."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.approve(proposal_id, reviewer=reviewer, notes=notes)

    if prop is None:
        print(f"提案 {proposal_id} 不存在 / Proposal not found")
        return 1

    print(f"✅ 提案已批准 / Proposal approved: {proposal_id}")
    print(f"   审核人: {reviewer or '(system)'}")
    return 0


def cmd_proposal_reject(proposal_id: str, reviewer: str = "", notes: str = "") -> int:
    """Reject a proposal."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.reject(proposal_id, reviewer=reviewer, notes=notes)

    if prop is None:
        print(f"提案 {proposal_id} 不存在 / Proposal not found")
        return 1

    print(f"❌ 提案已驳回 / Proposal rejected: {proposal_id}")
    print(f"   审核人: {reviewer or '(system)'}")
    return 0


def cmd_proposal_withdraw(proposal_id: str) -> int:
    """Withdraw a proposal."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.withdraw(proposal_id)

    if prop is None:
        print(f"提案 {proposal_id} 不存在 / Proposal not found")
        return 1

    print(f"提案已撤回 / Proposal withdrawn: {proposal_id}")
    return 0
