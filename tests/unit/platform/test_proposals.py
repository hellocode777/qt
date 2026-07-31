"""Tests for Strategy Proposal Workflow (G-011)."""

from __future__ import annotations

from pathlib import Path

from qp.platform.proposals.models import StrategyProposal
from qp.platform.proposals.store import PROPOSALS_DIR, PROPOSALS_INDEX, ProposalStore


class TestStrategyProposal:

    def test_create_from_fields(self) -> None:
        prop = StrategyProposal(
            strategy_id="momentum_v1.0",
            target_lifecycle="paper_trading",
            justification="Backtest Sharpe 1.8",
            proposed_by="shuai",
        )
        assert prop.strategy_id == "momentum_v1.0"
        assert prop.target_lifecycle == "paper_trading"
        assert prop.status == "draft"
        assert not prop.is_terminal()

    def test_to_dict_and_from_dict(self) -> None:
        prop = StrategyProposal(
            proposal_id="PROP-2026-07-31-001",
            strategy_id="value_v1.0",
            target_lifecycle="production",
            justification="5-year live shadow, Sharpe 1.5",
            evidence={"sharpe": 1.5, "max_dd": 18.2},
            status="approved",
        )
        d = prop.to_dict()
        restored = StrategyProposal.from_dict(d)
        assert restored.proposal_id == prop.proposal_id
        assert restored.strategy_id == prop.strategy_id
        assert restored.evidence == prop.evidence
        assert restored.status == "approved"

    def test_status_labels(self) -> None:
        prop = StrategyProposal(strategy_id="x", target_lifecycle="paper_trading")
        prop.status = "draft"
        assert "草稿" in prop.status_label()
        prop.status = "pending_review"
        assert "待审核" in prop.status_label()
        prop.status = "approved"
        assert "已批准" in prop.status_label()
        prop.status = "rejected"
        assert "已驳回" in prop.status_label()

    def test_is_terminal(self) -> None:
        prop = StrategyProposal(strategy_id="x", target_lifecycle="paper_trading")
        prop.status = "draft"
        assert not prop.is_terminal()
        prop.status = "pending_review"
        assert not prop.is_terminal()
        prop.status = "approved"
        assert prop.is_terminal()
        prop.status = "rejected"
        assert prop.is_terminal()
        prop.status = "withdrawn"
        assert prop.is_terminal()


class TestProposalStore:

    def test_create_and_get(self, tmp_path: Path) -> None:
        """Create a proposal and retrieve it."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            prop = store.create(
                strategy_id="momentum_v1.0",
                target_lifecycle="paper_trading",
                justification="Test proposal",
                evidence={"sharpe": 1.8},
            )
            assert prop.proposal_id.startswith("PROP-")
            assert prop.status == "pending_review"

            loaded = store.get(prop.proposal_id)
            assert loaded is not None
            assert loaded.strategy_id == "momentum_v1.0"
            assert loaded.justification == "Test proposal"
        finally:
            _restore_store()

    def test_approve_reject_workflow(self, tmp_path: Path) -> None:
        """Full lifecycle: create → approve → can't re-approve."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            prop = store.create(
                strategy_id="quality_v1.0",
                target_lifecycle="shadow_production",
                justification="Ready for shadow",
            )

            # Approve
            approved = store.approve(prop.proposal_id, reviewer="alice", notes="LGTM")
            assert approved is not None
            assert approved.status == "approved"
            assert approved.reviewer == "alice"

            # Can't re-approve
            re_approved = store.approve(prop.proposal_id, reviewer="bob")
            assert re_approved is not None
            assert re_approved.reviewer == "alice"  # unchanged
        finally:
            _restore_store()

    def test_reject(self, tmp_path: Path) -> None:
        """Reject a proposal."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            prop = store.create(strategy_id="x", target_lifecycle="paper_trading")
            rejected = store.reject(prop.proposal_id, reviewer="bob", notes="Needs more data")
            assert rejected is not None
            assert rejected.status == "rejected"
            assert rejected.review_notes == "Needs more data"
        finally:
            _restore_store()

    def test_withdraw(self, tmp_path: Path) -> None:
        """Withdraw a proposal."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            prop = store.create(strategy_id="x", target_lifecycle="paper_trading")
            withdrawn = store.withdraw(prop.proposal_id)
            assert withdrawn is not None
            assert withdrawn.status == "withdrawn"
        finally:
            _restore_store()

    def test_list_by_status(self, tmp_path: Path) -> None:
        """Filter proposals by status."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            p1 = store.create(strategy_id="a", target_lifecycle="paper_trading")
            store.create(strategy_id="b", target_lifecycle="production")
            store.approve(p1.proposal_id, reviewer="x")

            pending = store.list_by_status("pending_review")
            approved = store.list_by_status("approved")
            assert len(pending) >= 1
            assert len(approved) >= 1
        finally:
            _restore_store()

    def test_list_by_strategy(self, tmp_path: Path) -> None:
        """Filter proposals by strategy."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            store.create(strategy_id="alpha", target_lifecycle="paper_trading")
            store.create(strategy_id="beta", target_lifecycle="production")

            alpha_props = store.list_by_strategy("alpha")
            assert all(p.strategy_id == "alpha" for p in alpha_props)
        finally:
            _restore_store()

    def test_get_active_for_strategy(self, tmp_path: Path) -> None:
        """Only returns non-terminal proposals."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            prop = store.create(strategy_id="active_test", target_lifecycle="paper_trading")

            active = store.get_active_for_strategy("active_test")
            assert active is not None
            assert active.status == "pending_review"

            store.approve(prop.proposal_id)
            active_after = store.get_active_for_strategy("active_test")
            assert active_after is None  # Approved → terminal
        finally:
            _restore_store()

    def test_get_nonexistent(self, tmp_path: Path) -> None:
        """get() returns None for missing proposals."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            assert store.get("PROP-9999-999") is None
        finally:
            _restore_store()

    def test_empty_list(self, tmp_path: Path) -> None:
        """Empty store returns empty list."""
        _redirect_store(tmp_path)
        try:
            store = ProposalStore()
            assert store.list_all() == []
        finally:
            _restore_store()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_original_dir = str(PROPOSALS_DIR)
_original_index = str(PROPOSALS_INDEX)


def _redirect_store(tmp_path: Path) -> None:
    import qp.platform.proposals.store as mod

    mod.PROPOSALS_DIR = tmp_path / "proposals"
    mod.PROPOSALS_INDEX = mod.PROPOSALS_DIR / "index.json"
    mod.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)


def _restore_store() -> None:
    import qp.platform.proposals.store as mod

    mod.PROPOSALS_DIR = Path(_original_dir)
    mod.PROPOSALS_INDEX = Path(_original_index)
