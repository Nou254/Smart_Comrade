"""
Inter-group transfer endpoints — Module 003 Phase 8.

Admin-initiated. Same-course only. Fee: KSh 20 ordinary / KSh 90 elected.
Elected members' seats are vacated on transfer.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.group_transfer import (
    GroupTransferCreate, GroupTransferResponse, GroupTransferReviewRequest,
    GroupTransferFeeRecord, GroupTransferListResponse,
)
from app.services.group_transfer_service import (
    TransferError,
    request_transfer, record_fee, review_transfer,
    get_transfer, list_transfers,
)
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/group-transfers", tags=["Group Transfers"])


def _err(e: TransferError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


# ============================================================================
# REQUEST
# ============================================================================

@router.post("", response_model=GroupTransferResponse, status_code=201)
def post_transfer(
    payload: GroupTransferCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = request_transfer(
            db,
            student_id=payload.student_id,
            source_group_id=payload.source_group_id,
            target_group_id=payload.target_group_id,
            admin_id=current_user.id,
            transfer_type=payload.transfer_type,
            notes=payload.request_notes,
        )
    except TransferError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="group_transfer.request",
        target_type="group_transfer", target_id=result.id,
        new_value=f"{payload.source_group_id}->{payload.target_group_id}",
    )
    return result


# ============================================================================
# LIST / READ
# ============================================================================

@router.get("", response_model=list[GroupTransferListResponse])
def get_transfers(
    student_id: str | None = Query(None),
    source_group_id: str | None = Query(None),
    target_group_id: str | None = Query(None),
    status: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_transfers(
        db,
        student_id=student_id,
        source_group_id=source_group_id,
        target_group_id=target_group_id,
        status=status,
    )


@router.get("/{transfer_id}", response_model=GroupTransferResponse)
def get_one_transfer(
    transfer_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_transfer(db, transfer_id)
    except TransferError as e:
        _err(e)


# ============================================================================
# FEE
# ============================================================================

@router.post("/{transfer_id}/fee", response_model=GroupTransferResponse)
def post_transfer_fee(
    transfer_id: str,
    payload: GroupTransferFeeRecord,
    provider: str = Query(
        "mpesa", description="Payment provider that took the transfer fee.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Record a transfer fee payment after the provider confirms it.

    The fee is only recorded once the payment provider verifies that the
    supplied reference is a successful payment for the correct amount.
    """
    from app.services.fee_service import (
        FeeError, transfer_fee_amount, verify_payment_reference,
    )
    try:
        transfer = get_transfer(db, transfer_id)
        if not transfer.fee_paid:
            verify_payment_reference(
                provider_name=provider,
                reference=payload.payment_reference,
                amount=transfer_fee_amount(
                    getattr(transfer, "transfer_type", "ordinary"),
                ),
            )
        result = record_fee(
            db, transfer_id,
            payment_reference=payload.payment_reference,
            admin_id=current_user.id,
        )
    except (TransferError, FeeError) as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="group_transfer.fee_recorded",
        target_type="group_transfer", target_id=transfer_id,
        new_value=payload.payment_reference,
    )
    return result


# ============================================================================
# REVIEW
# ============================================================================

@router.post("/{transfer_id}/review", response_model=GroupTransferResponse)
def post_transfer_review(
    transfer_id: str,
    payload: GroupTransferReviewRequest,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Approve or reject a transfer. Super Admin only for now — the migration
    will seed a dedicated `group_transfer.manage` permission for admin
    roles so this can be relaxed.
    """
    try:
        result = review_transfer(
            db, transfer_id, current_user.id,
            approve=payload.approve, notes=payload.review_notes,
        )
    except TransferError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id,
        action=("group_transfer.approve" if payload.approve else "group_transfer.reject"),
        target_type="group_transfer", target_id=transfer_id,
        reason=payload.review_notes,
    )
    return result