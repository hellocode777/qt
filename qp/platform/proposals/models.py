"""Strategy Proposal — data models for human-in-the-loop strategy lifecycle approval.

V2.1 / Phase 2: Every strategy promotion to PAPER_TRADING or above requires
an approved proposal with justification, evidence, and reviewer sign-off.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class StrategyProposal(BaseModel):
    """A proposal to change a strategy's lifecycle state.

    Attributes:
        proposal_id: Auto-generated ID (PROP-{date}-{seq}).
        strategy_id: Target strategy identifier.
        proposed_by: Person who created the proposal.
        proposed_at: ISO-8601 timestamp.
        target_lifecycle: Desired lifecycle state.
        justification: Required text explaining the rationale.
        evidence: Dict with experiment_id, sharpe, max_dd, validation_score, etc.
        status: Current workflow state.
        reviewer: Person who approved/rejected (if any).
        review_notes: Reviewer comments.
        reviewed_at: ISO-8601 timestamp of review decision.
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
    """

    proposal_id: str = ""
    strategy_id: str
    proposed_by: str = "system"
    proposed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    target_lifecycle: str  # StrategyLifecycle value
    justification: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"  # ProposalStatus value
    reviewer: str = ""
    review_notes: str = ""
    reviewed_at: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyProposal:
        return cls(**d)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    def status_label(self) -> str:
        labels = {
            "draft": "草稿 Draft",
            "pending_review": "待审核 Pending",
            "approved": "已批准 Approved",
            "rejected": "已驳回 Rejected",
            "withdrawn": "已撤回 Withdrawn",
        }
        return labels.get(self.status, self.status)

    def is_terminal(self) -> bool:
        return self.status in ("approved", "rejected", "withdrawn")
