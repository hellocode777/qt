"""Proposals router — strategy lifecycle approval workflow.

GET  /proposals           — List all proposals
GET  /proposals/{id}      — Proposal detail with review form
POST /proposals/{id}/approve  — Approve a proposal
POST /proposals/{id}/reject   — Reject a proposal
POST /proposals/create        — Create a new proposal
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from loguru import logger

from qp.web.routers._templates import templates

router = APIRouter(tags=["proposals"])


@router.get("/proposals")
async def proposals_list(request: Request) -> Any:
    """List all proposals."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    all_props = store.list_all()
    # Sort by created_at descending
    all_props.sort(key=lambda p: p.created_at, reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="proposals.html",
        context={
            "proposals": [p.to_dict() for p in all_props],
            "has_proposals": len(all_props) > 0,
            "page_title": "Proposals — QP Decision Center",
        },
    )


@router.get("/proposals/{proposal_id}")
async def proposals_detail(request: Request, proposal_id: str) -> Any:
    """Show proposal detail."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.get(proposal_id)

    if prop is None:
        return templates.TemplateResponse(
            request=request,
            name="proposals.html",
            context={
                "error": f"提案 {proposal_id} 不存在 / Proposal not found",
                "proposals": [],
                "has_proposals": False,
            },
        )

    return templates.TemplateResponse(
        request=request,
        name="proposal_detail.html",
        context={
            "proposal": prop.to_dict(),
            "proposal_obj": prop,
            "page_title": f"Proposal {proposal_id} — QP Decision Center",
        },
    )


@router.post("/proposals/{proposal_id}/approve")
async def proposals_approve(
    request: Request,
    proposal_id: str,
    reviewer: str = Form(default=""),
    notes: str = Form(default=""),
) -> Any:
    """Approve a proposal."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.approve(proposal_id, reviewer=reviewer, notes=notes)

    if prop is None:
        return templates.TemplateResponse(
            request=request,
            name="proposals.html",
            context={"error": f"提案 {proposal_id} 不存在"},
        )

    logger.info("Proposal {} approved via WebUI", proposal_id)
    # Redirect back to detail
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/proposals/{proposal_id}", status_code=303)


@router.post("/proposals/{proposal_id}/reject")
async def proposals_reject(
    request: Request,
    proposal_id: str,
    reviewer: str = Form(default=""),
    notes: str = Form(default=""),
) -> Any:
    """Reject a proposal."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.reject(proposal_id, reviewer=reviewer, notes=notes)

    if prop is None:
        return templates.TemplateResponse(
            request=request,
            name="proposals.html",
            context={"error": f"提案 {proposal_id} 不存在"},
        )

    logger.info("Proposal {} rejected via WebUI", proposal_id)
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/proposals/{proposal_id}", status_code=303)


@router.post("/proposals/create")
async def proposals_create(
    request: Request,
    strategy_id: str = Form(...),
    target_lifecycle: str = Form(...),
    justification: str = Form(default=""),
) -> Any:
    """Create a new proposal."""
    from qp.platform.proposals.store import ProposalStore

    store = ProposalStore()
    prop = store.create(
        strategy_id=strategy_id,
        target_lifecycle=target_lifecycle,
        justification=justification,
        proposed_by="webui",
    )

    logger.info("Proposal {} created via WebUI", prop.proposal_id)
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/proposals/{prop.proposal_id}", status_code=303)
