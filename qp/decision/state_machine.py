"""Decision State Machine — 决策包生命周期状态机.

Defines the complete lifecycle of a DecisionPackage from generation to closure.
Ensures all state transitions are valid and auditable.

State flow:
    PENDING → APPROVED / REJECTED / MODIFIED
    APPROVED → PARTIALLY_EXECUTED / MONITORING
    MODIFIED → APPROVED
    PARTIALLY_EXECUTED → MONITORING
    MONITORING → CLOSED

Usage:
    from qp.decision.state_machine import (
        DecisionStatus, can_transition, transition, DecisionStateError,
    )

    status = DecisionStatus.PENDING
    if can_transition(status, DecisionStatus.APPROVED):
        status = transition(status, DecisionStatus.APPROVED)
    # → DecisionStatus.APPROVED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class DecisionStatus(StrEnum):
    """DecisionPackage lifecycle status.

    PENDING               — 刚生成，等待人工审核
    APPROVED              — 审核通过，等待执行
    REJECTED              — 审核驳回，本次决策作废
    MODIFIED              — 审核修改，需重新确认
    PARTIALLY_EXECUTED    — 部分交易已执行
    MONITORING            — 全部执行完成，持仓监控中
    CLOSED                — 所有仓位已平，决策包关闭
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    PARTIALLY_EXECUTED = "partially_executed"
    MONITORING = "monitoring"
    CLOSED = "closed"

    @property
    def label(self) -> str:
        """Human-readable Chinese label."""
        _labels: dict[DecisionStatus, str] = {
            DecisionStatus.PENDING: "待审核",
            DecisionStatus.APPROVED: "已批准",
            DecisionStatus.REJECTED: "已驳回",
            DecisionStatus.MODIFIED: "已修改",
            DecisionStatus.PARTIALLY_EXECUTED: "部分执行",
            DecisionStatus.MONITORING: "监控中",
            DecisionStatus.CLOSED: "已关闭",
        }
        return _labels.get(self, self.value)

    @property
    def is_terminal(self) -> bool:
        """True if this is a terminal state (no further transitions)."""
        return self in (DecisionStatus.REJECTED, DecisionStatus.CLOSED)

    @property
    def is_active(self) -> bool:
        """True if the decision is still in an active lifecycle phase."""
        return self in (
            DecisionStatus.PENDING,
            DecisionStatus.APPROVED,
            DecisionStatus.MODIFIED,
            DecisionStatus.PARTIALLY_EXECUTED,
            DecisionStatus.MONITORING,
        )

    @property
    def requires_human_action(self) -> bool:
        """True if a human must take action to advance the state."""
        return self in (DecisionStatus.PENDING, DecisionStatus.MODIFIED)


# ==================================================================
# Transition table
# ==================================================================
#
# Each key maps to a set of allowed successor states.
# A status can always transition to itself (idempotent, not listed).

TRANSITIONS: dict[DecisionStatus, set[DecisionStatus]] = {
    DecisionStatus.PENDING: {
        DecisionStatus.APPROVED,
        DecisionStatus.REJECTED,
        DecisionStatus.MODIFIED,
    },
    DecisionStatus.APPROVED: {
        DecisionStatus.PARTIALLY_EXECUTED,
        DecisionStatus.MONITORING,
    },
    DecisionStatus.REJECTED: set(),  # Terminal — no outgoing transitions
    DecisionStatus.MODIFIED: {
        DecisionStatus.APPROVED,
    },
    DecisionStatus.PARTIALLY_EXECUTED: {
        DecisionStatus.MONITORING,
    },
    DecisionStatus.MONITORING: {
        DecisionStatus.CLOSED,
    },
    DecisionStatus.CLOSED: set(),  # Terminal — no outgoing transitions
}


# ==================================================================
# Transition metadata
# ==================================================================


@dataclass
class StatusTransition:
    """Record of a single status change for the audit trail.

    Attributes:
        from_status: Previous status.
        to_status: New status.
        timestamp: ISO 8601 timestamp of the transition.
        actor: Who initiated the transition (reviewer name or "system").
        notes: Optional reason or comment.
    """

    from_status: DecisionStatus
    to_status: DecisionStatus
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    actor: str = ""
    notes: str = ""

    def __repr__(self) -> str:
        return (
            f"StatusTransition({self.from_status.value} → {self.to_status.value}"
            f"{' by ' + self.actor if self.actor else ''})"
        )


# ==================================================================
# Exception
# ==================================================================


class DecisionStateError(ValueError):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        from_status: DecisionStatus,
        to_status: DecisionStatus,
        reason: str = "",
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        msg = (
            f"Invalid transition: {from_status.value} → {to_status.value}."
            f"{' ' + reason if reason else ''}"
        )
        super().__init__(msg)


# ==================================================================
# Public API
# ==================================================================


def can_transition(
    from_status: DecisionStatus,
    to_status: DecisionStatus,
) -> bool:
    """Check if a state transition is allowed.

    Args:
        from_status: Current status.
        to_status: Desired next status.

    Returns:
        True if the transition is valid.
    """
    # Self-transition is always allowed (idempotent)
    if from_status == to_status:
        return True
    allowed = TRANSITIONS.get(from_status, set())
    return to_status in allowed


def allowed_transitions(from_status: DecisionStatus) -> set[DecisionStatus]:
    """Return the set of valid next states from a given status.

    Args:
        from_status: Current status.

    Returns:
        Set of allowed successor states (includes self).
    """
    allowed = set(TRANSITIONS.get(from_status, set()))
    allowed.add(from_status)  # Self-transition always allowed
    return allowed


def transition(
    from_status: DecisionStatus,
    to_status: DecisionStatus,
    actor: str = "",
    notes: str = "",
) -> tuple[DecisionStatus, StatusTransition]:
    """Execute a state transition, returning the new status and audit record.

    Args:
        from_status: Current status.
        to_status: Desired next status.
        actor: Who initiated the transition (reviewer name or "system").
        notes: Optional reason or comment.

    Returns:
        Tuple of (new_status, StatusTransition audit record).

    Raises:
        DecisionStateError: If the transition is not allowed.
    """
    if not can_transition(from_status, to_status):
        raise DecisionStateError(from_status, to_status)

    record = StatusTransition(
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        notes=notes,
    )

    return to_status, record


# ==================================================================
# Convenience: transition logic grouped by actor role
# ==================================================================


def approve(
    from_status: DecisionStatus,
    reviewer: str = "",
    notes: str = "",
) -> tuple[DecisionStatus, StatusTransition]:
    """Approve a pending or modified decision.

    Raises:
        DecisionStateError: If current status is not PENDING or MODIFIED.
    """
    if from_status not in (DecisionStatus.PENDING, DecisionStatus.MODIFIED):
        raise DecisionStateError(
            from_status,
            DecisionStatus.APPROVED,
            reason=f"Cannot approve from {from_status.label}",
        )
    return transition(from_status, DecisionStatus.APPROVED, actor=reviewer, notes=notes)


def reject(
    from_status: DecisionStatus,
    reviewer: str = "",
    notes: str = "",
) -> tuple[DecisionStatus, StatusTransition]:
    """Reject a pending decision.

    Raises:
        DecisionStateError: If current status is not PENDING.
    """
    if from_status != DecisionStatus.PENDING:
        raise DecisionStateError(
            from_status,
            DecisionStatus.REJECTED,
            reason=f"Cannot reject from {from_status.label}",
        )
    return transition(from_status, DecisionStatus.REJECTED, actor=reviewer, notes=notes)


def modify(
    from_status: DecisionStatus,
    reviewer: str = "",
    notes: str = "",
) -> tuple[DecisionStatus, StatusTransition]:
    """Mark a pending decision as modified.

    Raises:
        DecisionStateError: If current status is not PENDING.
    """
    if from_status != DecisionStatus.PENDING:
        raise DecisionStateError(
            from_status,
            DecisionStatus.MODIFIED,
            reason=f"Cannot modify from {from_status.label}",
        )
    return transition(from_status, DecisionStatus.MODIFIED, actor=reviewer, notes=notes)


def mark_executed(
    from_status: DecisionStatus,
    actor: str = "system",
    notes: str = "",
) -> tuple[DecisionStatus, StatusTransition]:
    """Mark trades as partially or fully executed.

    Moves APPROVED → PARTIALLY_EXECUTED or PARTIALLY_EXECUTED → MONITORING
    based on current status and whether all trades are done.

    Args:
        from_status: Current status.
        actor: Who confirmed execution.
        notes: Execution details.

    Returns:
        Tuple of (new_status, StatusTransition).

    Raises:
        DecisionStateError: If status doesn't support execution.
    """
    if from_status == DecisionStatus.APPROVED:
        return transition(from_status, DecisionStatus.PARTIALLY_EXECUTED, actor=actor, notes=notes)
    if from_status == DecisionStatus.PARTIALLY_EXECUTED:
        return transition(from_status, DecisionStatus.MONITORING, actor=actor, notes=notes)
    raise DecisionStateError(
        from_status,
        DecisionStatus.PARTIALLY_EXECUTED,
        reason=f"Cannot execute from {from_status.label}",
    )


def close(
    from_status: DecisionStatus,
    actor: str = "system",
    notes: str = "",
) -> tuple[DecisionStatus, StatusTransition]:
    """Close a monitored decision (all positions exited).

    Raises:
        DecisionStateError: If current status is not MONITORING.
    """
    if from_status != DecisionStatus.MONITORING:
        raise DecisionStateError(
            from_status,
            DecisionStatus.CLOSED,
            reason=f"Cannot close from {from_status.label}",
        )
    return transition(from_status, DecisionStatus.CLOSED, actor=actor, notes=notes)
