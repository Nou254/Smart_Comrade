"""
Unit proposal endpoints — Module 002 completion.

The direct-creation path for units. Approval ladder (County is skipped):

    school_representative
    → institution_representative
    → regional_admin
    → super_admin

Every two hours without a response escalates one level.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.user import User
from app.schemas.unit_proposal import (
    UnitProposalCreate, UnitProposalResponse,
    UnitProposalItemResponse, UnitProposalItemModifyRequest,
    UnitProposalRejectRequest, UnitProposalWithdrawRequest,
)
from app.services.unit_proposal_service import (
    UnitProposalError,
    create_unit_proposal, list_unit_proposals, get_unit_proposal,
    modify_proposal_item, approve_unit_proposal,
    reject_unit_proposal, withdraw_unit_proposal, escalate_stale_proposals,
)
from app.services.jurisdiction_service import user_has_jurisdiction
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/unit-proposals", tags=["Unit Proposals"])


def _err(e: UnitProposalError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _guard_institution_jurisdiction(
    db: Session, user: User, institution_id: str,
) -> None:
    if not user_has_jurisdiction(db, user.id, "institution", institution_id):
        raise HTTPException(
            status_code=403,
            detail="You do not have jurisdiction over this institution.",
        )


# ============================================================================
# CREATE
# ============================================================================

@router.post("", response_model=UnitProposalResponse, status_code=201)
def post_unit_proposal(
    payload: UnitProposalCreate,
    current_user: User = Depends(require_permission("unit_proposal.create")),
    db: Session = Depends(get_db),
):
    _guard_institution_jurisdiction(db, current_user, payload.institution_id)
    try:
        result = create_unit_proposal(db, payload, user_id=current_user.id)
    except UnitProposalError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_proposal.create",
        target_type="unit_proposal", target_id=result.id,
        new_value=f"course={payload.course_id} items={len(payload.items)}",
    )
    return result


# ============================================================================
# READ
# ============================================================================

@router.get("", response_model=list[UnitProposalResponse])
def get_unit_proposals(
    institution_id: str | None = Query(None),
    course_id: str | None = Query(None),
    status: str | None = Query(None),
    mine: bool = Query(
        False,
        description="If true, return only proposals where the current user "
                    "is the current approver.",
    ),
    current_user: User = Depends(require_permission("unit_proposal.view")),
    db: Session = Depends(get_db),
):
    return list_unit_proposals(
        db,
        institution_id=institution_id,
        course_id=course_id,
        status=status,
        current_approver_id=current_user.id if mine else None,
    )


@router.get("/{proposal_id}", response_model=UnitProposalResponse)
def get_one_unit_proposal(
    proposal_id: str,
    _: User = Depends(require_permission("unit_proposal.view")),
    db: Session = Depends(get_db),
):
    try:
        return get_unit_proposal(db, proposal_id)
    except UnitProposalError as e:
        _err(e)


# ============================================================================
# ITEM MODIFICATION (approver)
# ============================================================================

@router.patch(
    "/{proposal_id}/items/{item_id}",
    response_model=UnitProposalItemResponse,
)
def patch_proposal_item(
    proposal_id: str,
    item_id: str,
    payload: UnitProposalItemModifyRequest,
    current_user: User = Depends(require_permission("unit_proposal.modify_item")),
    db: Session = Depends(get_db),
):
    try:
        proposal = get_unit_proposal(db, proposal_id)
    except UnitProposalError as e:
        _err(e)
    _guard_institution_jurisdiction(db, current_user, proposal.institution_id)
    try:
        result = modify_proposal_item(
            db, proposal_id, item_id, payload, user_id=current_user.id,
        )
    except UnitProposalError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_proposal.item.modify",
        target_type="unit_proposal_item", target_id=item_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


# ============================================================================
# APPROVE / REJECT / WITHDRAW
# ============================================================================

@router.post("/{proposal_id}/approve", response_model=UnitProposalResponse)
def post_unit_proposal_approve(
    proposal_id: str,
    current_user: User = Depends(require_permission("unit_proposal.approve")),
    db: Session = Depends(get_db),
):
    try:
        proposal = get_unit_proposal(db, proposal_id)
    except UnitProposalError as e:
        _err(e)
    _guard_institution_jurisdiction(db, current_user, proposal.institution_id)
    try:
        result = approve_unit_proposal(db, proposal_id, user_id=current_user.id)
    except UnitProposalError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_proposal.approve",
        target_type="unit_proposal", target_id=proposal_id,
    )
    return result


@router.post("/{proposal_id}/reject", response_model=UnitProposalResponse)
def post_unit_proposal_reject(
    proposal_id: str,
    payload: UnitProposalRejectRequest,
    current_user: User = Depends(require_permission("unit_proposal.approve")),
    db: Session = Depends(get_db),
):
    try:
        proposal = get_unit_proposal(db, proposal_id)
    except UnitProposalError as e:
        _err(e)
    _guard_institution_jurisdiction(db, current_user, proposal.institution_id)
    try:
        result = reject_unit_proposal(
            db, proposal_id, user_id=current_user.id, reason=payload.reason,
        )
    except UnitProposalError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_proposal.reject",
        target_type="unit_proposal", target_id=proposal_id,
        reason=payload.reason,
    )
    return result


@router.post("/{proposal_id}/withdraw", response_model=UnitProposalResponse)
def post_unit_proposal_withdraw(
    proposal_id: str,
    payload: UnitProposalWithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Withdraw a proposal. Service layer enforces that only the original
    creator may withdraw.
    """
    try:
        result = withdraw_unit_proposal(
            db, proposal_id, user_id=current_user.id, reason=payload.reason,
        )
    except UnitProposalError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_proposal.withdraw",
        target_type="unit_proposal", target_id=proposal_id,
        reason=payload.reason,
    )
    return result


# ============================================================================
# ESCALATION SWEEP (Super Admin / background trigger)
# ============================================================================

@router.post("/escalate-sweep")
def post_escalate_sweep(
    _: User = Depends(require_permission("unit_proposal.approve")),
    db: Session = Depends(get_db),
):
    """
    Manually trigger the escalation sweep. Idempotent. Returns the count
    of proposals that were escalated. In production, this is normally
    driven by a background job.
    """
    count = escalate_stale_proposals(db)
    return {"escalated": count}