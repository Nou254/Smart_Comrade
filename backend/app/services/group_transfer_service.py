"""
Inter-group transfer service — Module 003 Phase 8.

Admin-initiated, same-course only. Fee tiers: KSh 20 ordinary, KSh 90 elected.
Elected members' seats become vacant when they transfer.
Blocked during election period.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.group import Group, GroupMembership, GroupOfficial
from app.models.group_transfer import GroupTransfer
from app.models.user import User
from app.services.group_subscription_service import refresh_member_count


logger = logging.getLogger(__name__)


ORDINARY_FEE = 20
ELECTED_FEE = 90
ELECTION_BLOCK_STATES = {"pending_election"}


class TransferError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# REQUEST
# ============================================================================

def request_transfer(
    db: Session,
    student_id: str,
    source_group_id: str,
    target_group_id: str,
    admin_id: str,
    transfer_type: str = "ordinary",
    notes: str | None = None,
) -> GroupTransfer:
    if source_group_id == target_group_id:
        raise TransferError("Source and target groups must differ.", 400)

    if transfer_type not in ("ordinary", "elected"):
        raise TransferError("transfer_type must be 'ordinary' or 'elected'.", 400)

    source = db.query(Group).filter(Group.id == source_group_id).first()
    target = db.query(Group).filter(Group.id == target_group_id).first()
    if not source or not target:
        raise TransferError("Group not found.", 404)

    # Same course only
    if source.course_id != target.course_id:
        raise TransferError(
            "Transfers are only allowed between groups on the same course.", 409,
        )

    # Neither group in "going for elections"
    if source.status in ELECTION_BLOCK_STATES:
        raise TransferError(
            "Source group is in an election period. Transfers are blocked.", 409,
        )
    if target.status in ELECTION_BLOCK_STATES:
        raise TransferError(
            "Target group is in an election period. Transfers are blocked.", 409,
        )

    # Target capacity
    if target.member_count >= target.max_members:
        raise TransferError("Target group is full.", 409)

    # Student is active member of source
    membership = db.query(GroupMembership).filter(
        GroupMembership.group_id == source_group_id,
        GroupMembership.user_id == student_id,
        GroupMembership.status == "active",
    ).first()
    if not membership:
        raise TransferError(
            "Student is not an active member of the source group.", 409,
        )

    # Student not already in target
    already = db.query(GroupMembership).filter(
        GroupMembership.group_id == target_group_id,
        GroupMembership.user_id == student_id,
        GroupMembership.status.in_(("active", "pending")),
    ).first()
    if already:
        raise TransferError(
            "Student is already a member of the target group.", 409,
        )

    # Determine fee + elected status
    is_elected = _student_is_elected_official(db, source_group_id, student_id)
    if is_elected:
        transfer_type = "elected"

    fee = ELECTED_FEE if transfer_type == "elected" else ORDINARY_FEE

    transfer = GroupTransfer(
        student_id=student_id,
        source_group_id=source_group_id,
        target_group_id=target_group_id,
        initiated_by=admin_id,
        initiated_at=_now(),
        request_notes=notes,
        transfer_type=transfer_type,
        fee_amount=fee,
        currency="KES",
        fee_paid=False,
        status="pending",
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


def _student_is_elected_official(db: Session, group_id: str, user_id: str) -> bool:
    return db.query(GroupOfficial).filter(
        GroupOfficial.group_id == group_id,
        GroupOfficial.user_id == user_id,
        GroupOfficial.status == "active",
    ).first() is not None


# ============================================================================
# FEE
# ============================================================================

def record_fee(
    db: Session, transfer_id: str, payment_reference: str, admin_id: str,
) -> GroupTransfer:
    t = _get(db, transfer_id)
    if t.status != "pending":
        raise TransferError(f"Cannot record fee on transfer in status '{t.status}'.", 409)
    if t.fee_paid:
        return t

    t.fee_paid = True
    t.payment_reference = payment_reference
    t.fee_paid_at = _now()
    db.commit()
    db.refresh(t)
    return t


# ============================================================================
# REVIEW
# ============================================================================

def review_transfer(
    db: Session, transfer_id: str, admin_id: str, approve: bool,
    notes: str | None = None,
) -> GroupTransfer:
    t = _get(db, transfer_id)
    if t.status != "pending":
        raise TransferError(f"Transfer already {t.status}.", 409)

    if approve and not t.fee_paid:
        raise TransferError("Cannot approve a transfer whose fee is unpaid.", 409)

    t.reviewed_by = admin_id
    t.reviewed_at = _now()
    t.review_notes = notes

    if not approve:
        t.status = "rejected"
        db.commit()
        db.refresh(t)
        return t

    # --- Execute the transfer ---
    _execute_transfer(db, t)
    t.status = "completed"
    t.completed_at = _now()
    db.commit()
    db.refresh(t)
    return t


def _execute_transfer(db: Session, t: GroupTransfer) -> None:
    source = db.query(Group).filter(Group.id == t.source_group_id).first()
    target = db.query(Group).filter(Group.id == t.target_group_id).first()
    if not source or not target:
        raise TransferError("Group missing at execution time.", 500)

    # Move the source membership to 'left'
    source_m = db.query(GroupMembership).filter(
        GroupMembership.group_id == t.source_group_id,
        GroupMembership.user_id == t.student_id,
    ).first()
    if source_m:
        source_m.status = "left"
        source_m.left_at = _now()

    # Vacate elected seats if any
    if t.transfer_type == "elected":
        officials = db.query(GroupOfficial).filter(
            GroupOfficial.group_id == t.source_group_id,
            GroupOfficial.user_id == t.student_id,
            GroupOfficial.status == "active",
        ).all()
        for o in officials:
            o.status = "removed"
            o.notes = (o.notes or "") + f"\n[Transfer vacancy] {t.id}"
            t.seat_vacated = True

        # If the leader's seat became vacant, promote the Secretary to acting
        _assign_acting_leader_if_needed(db, t.source_group_id)

    # Create or reactivate the target membership
    target_m = db.query(GroupMembership).filter(
        GroupMembership.group_id == t.target_group_id,
        GroupMembership.user_id == t.student_id,
    ).first()
    if target_m:
        target_m.status = "active"
        target_m.joined_at = _now()
        target_m.left_at = None
    else:
        db.add(GroupMembership(
            group_id=t.target_group_id,
            user_id=t.student_id,
            status="active",
            joined_at=_now(),
        ))

    db.flush()
    refresh_member_count(db, source.id)
    refresh_member_count(db, target.id)


def _assign_acting_leader_if_needed(db: Session, group_id: str) -> None:
    """
    If the group now has no active leader but has an active secretary,
    promote the secretary to acting leader.
    """
    active_leader = db.query(GroupOfficial).filter(
        GroupOfficial.group_id == group_id,
        GroupOfficial.position == "leader",
        GroupOfficial.status == "active",
    ).first()
    if active_leader:
        return

    secretary = db.query(GroupOfficial).filter(
        GroupOfficial.group_id == group_id,
        GroupOfficial.position == "secretary",
        GroupOfficial.status == "active",
    ).first()
    if not secretary:
        return

    db.add(GroupOfficial(
        group_id=group_id,
        user_id=secretary.user_id,
        position="leader",
        status="active",
        term_start=_now(),
        notes=f"Acting leader (secretary elevated after transfer).",
    ))


# ============================================================================
# READ
# ============================================================================

def get_transfer(db: Session, transfer_id: str) -> GroupTransfer:
    return _get(db, transfer_id)


def list_transfers(
    db: Session,
    student_id: str | None = None,
    source_group_id: str | None = None,
    target_group_id: str | None = None,
    status: str | None = None,
) -> list[GroupTransfer]:
    q = db.query(GroupTransfer)
    if student_id:
        q = q.filter(GroupTransfer.student_id == student_id)
    if source_group_id:
        q = q.filter(GroupTransfer.source_group_id == source_group_id)
    if target_group_id:
        q = q.filter(GroupTransfer.target_group_id == target_group_id)
    if status:
        q = q.filter(GroupTransfer.status == status)
    return q.order_by(GroupTransfer.initiated_at.desc()).all()


def _get(db: Session, transfer_id: str) -> GroupTransfer:
    t = db.query(GroupTransfer).filter(GroupTransfer.id == transfer_id).first()
    if not t:
        raise TransferError("Transfer not found.", 404)
    return t