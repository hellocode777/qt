"""ProposalStore — CRUD persistence for strategy proposals.

Stores proposals as JSON files in ``data/proposals/`` with an index file
for fast listing. Follows the pattern established by ExperimentTracker.

Usage:
    store = ProposalStore()
    prop = store.create(
        strategy_id="momentum_v1.0",
        target_lifecycle="paper_trading",
        justification="Backtest Sharpe 1.8 with 5-year lookback.",
        evidence={"experiment_id": "exp-001", "sharpe": 1.8},
        proposed_by="shuai",
    )
    store.approve(prop.proposal_id, reviewer="shuai", notes="Looks good.")
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from qp.platform.proposals.models import StrategyProposal
from qp.shared.paths import PROPOSALS_DIR

PROPOSALS_INDEX = PROPOSALS_DIR / "index.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _next_id(date_str: str) -> str:
    """Generate the next proposal ID for a given date."""
    store = ProposalStore()
    existing = store.list_all()
    seq = 1
    prefix = f"PROP-{date_str}-"
    for p in existing:
        if p.proposal_id.startswith(prefix):
            try:
                n = int(p.proposal_id.rsplit("-", 1)[-1])
                seq = max(seq, n + 1)
            except (ValueError, IndexError):
                pass
    return f"{prefix}{seq:03d}"


class ProposalStore:
    """JSON-file-backed CRUD for StrategyProposal objects."""

    def __init__(self) -> None:
        PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_index()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(
        self,
        strategy_id: str,
        target_lifecycle: str,
        justification: str = "",
        evidence: dict[str, Any] | None = None,
        proposed_by: str = "system",
    ) -> StrategyProposal:
        """Create a new proposal with PENDING_REVIEW status."""
        today = datetime.now(UTC).date().isoformat()
        proposal_id = _next_id(today)

        prop = StrategyProposal(
            proposal_id=proposal_id,
            strategy_id=strategy_id,
            proposed_by=proposed_by,
            target_lifecycle=target_lifecycle,
            justification=justification,
            evidence=evidence or {},
            status="pending_review",
            created_at=_now(),
            updated_at=_now(),
        )

        self._save(prop)
        logger.info("Proposal created: {} → {}", proposal_id, target_lifecycle)
        return prop

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, proposal_id: str) -> StrategyProposal | None:
        """Load a single proposal by ID."""
        path = PROPOSALS_DIR / f"{proposal_id}.json"
        if not path.exists():
            return None
        try:
            return StrategyProposal.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load proposal {}: {}", proposal_id, exc)
            return None

    def list_all(self) -> list[StrategyProposal]:
        """List all proposals."""
        proposals: list[StrategyProposal] = []
        index = self._read_index()
        for pid in index.get("proposals", []):
            prop = self.get(pid)
            if prop is not None:
                proposals.append(prop)
        return proposals

    def list_by_status(self, status: str) -> list[StrategyProposal]:
        """List proposals filtered by status."""
        return [p for p in self.list_all() if p.status == status]

    def list_by_strategy(self, strategy_id: str) -> list[StrategyProposal]:
        """List proposals for a specific strategy."""
        return [p for p in self.list_all() if p.strategy_id == strategy_id]

    def get_active_for_strategy(self, strategy_id: str) -> StrategyProposal | None:
        """Get the current active (non-terminal) proposal for a strategy, if any."""
        for p in self.list_by_strategy(strategy_id):
            if not p.is_terminal():
                return p
        return None

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def approve(
        self,
        proposal_id: str,
        reviewer: str = "",
        notes: str = "",
    ) -> StrategyProposal | None:
        """Approve a proposal."""
        prop = self.get(proposal_id)
        if prop is None:
            return None
        if prop.is_terminal():
            logger.warning("Proposal {} is already {}", proposal_id, prop.status)
            return prop
        prop.status = "approved"
        prop.reviewer = reviewer
        prop.review_notes = notes
        prop.reviewed_at = _now()
        prop.updated_at = _now()
        self._save(prop)
        logger.info("Proposal {} approved by {}", proposal_id, reviewer or "system")
        return prop

    def reject(
        self,
        proposal_id: str,
        reviewer: str = "",
        notes: str = "",
    ) -> StrategyProposal | None:
        """Reject a proposal."""
        prop = self.get(proposal_id)
        if prop is None:
            return None
        if prop.is_terminal():
            logger.warning("Proposal {} is already {}", proposal_id, prop.status)
            return prop
        prop.status = "rejected"
        prop.reviewer = reviewer
        prop.review_notes = notes
        prop.reviewed_at = _now()
        prop.updated_at = _now()
        self._save(prop)
        logger.info("Proposal {} rejected by {}", proposal_id, reviewer or "system")
        return prop

    def withdraw(self, proposal_id: str) -> StrategyProposal | None:
        """Withdraw a proposal (by its creator)."""
        prop = self.get(proposal_id)
        if prop is None:
            return None
        if prop.is_terminal():
            return prop
        prop.status = "withdrawn"
        prop.updated_at = _now()
        self._save(prop)
        return prop

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self, prop: StrategyProposal) -> None:
        """Write proposal to disk and update index."""
        path = PROPOSALS_DIR / f"{prop.proposal_id}.json"
        path.write_text(
            json.dumps(prop.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._add_to_index(prop.proposal_id)

    def _ensure_index(self) -> None:
        """Create index file if missing."""
        if not PROPOSALS_INDEX.exists():
            PROPOSALS_INDEX.write_text(
                json.dumps({"updated_at": _now(), "proposals": []}),
                encoding="utf-8",
            )

    def _read_index(self) -> dict:
        """Read index file."""
        try:
            return json.loads(PROPOSALS_INDEX.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"proposals": []}

    def _add_to_index(self, proposal_id: str) -> None:
        """Add proposal ID to index if not already present."""
        index = self._read_index()
        proposals = index.get("proposals", [])
        if proposal_id not in proposals:
            proposals.append(proposal_id)
        index["proposals"] = proposals
        index["updated_at"] = _now()
        self._write_index(index)

    def _write_index(self, index: dict) -> None:
        """Write index to disk."""
        PROPOSALS_INDEX.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
