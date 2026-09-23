"""
Business logic for UnitProposals — Module 002 completion.

The direct-creation path for units: a School Rep (or higher) submits a
batch of units to add to a course. The proposal routes up an approval
ladder with two-hour escalation windows.

Ladder (County is skipped):
    group_leader → school_representative → institution_representative
                 → regional_admin → super_admin
    super_admin → auto-approve

Every two hours without a response the proposal escalates one level.
Assistants at each level are notified in parallel. Once approved, items
create real Unit rows and auto-create UnitOffering rows for the target
semester.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.academic import (
    AcademicStructureAudit,
    AcademicYear, Course, Institution, School, Unit,
)
from app.models.role import Role, UserRole
from app.models.unit_proposal import (
    UnitProposal, UnitProposalEvent, UnitProposalItem,
)
from app.services.unit_offering_service import ensure_offering_for_unit

logger = logging.getLogger(__name__)


# ============================================================================
# Approval ladder
# ============================================================================

# Ordered lowest → highest. County is deliberately absent.
_APPROVAL_LADDER: list[str] = [
    "group_leader",
    "school_representative",
    "institution_representative",
    "regional_admin",
    "super_admin",
]

# Maps each ladder position to the next one. The value is the role code
# that is expected to act at that stage.
_STAGE_TO_STATUS: dict[str, str] = {
    "school_representative": "pending_school_rep",
    "institution_representative": "pending_institution_rep",
    "regional_admin": "pending_regional_admin",
    "super_admin": "pending_super_admin",
}


class UnitProposalError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(
    db: Session, user_id: str | None, entity_type: str, entity_id: str,
    action: str, old_value: str | None = None, new_value: str | None = None,
    reason: str | None = None,
) -> None:
    db.add(AcademicStructureAudit(
        user_id=user_id, entity_type=entity_type, entity_id=entity_id,
        action=action, old_value=old_value, new_value=new_value, reason=reason,
    ))


def _log_event(
    db: Session, proposal_id: str, event_type: str,
    actor_id: str | None = None,
    from_stage: str | None = None, to_stage: str | None = None,
    notes: str | None = None,
) -> UnitProposalEvent:
    ev = UnitProposalEvent(
        proposal_id=proposal_id,
        event_type=event_type,
        actor_id=actor_id,
        from_stage=from_stage,
        to_stage=to_stage,
        notes=notes,
    )
    db.add(ev)
    return ev


def _escalation_deadline(now: datetime) -> datetime:
    return now + timedelta(minutes=settings.UNIT_PROPOSAL_ESCALATION_MINUTES)


def _next_role(current: str | None) -> str | None:
    """Return the next role code in the ladder, or None if terminal."""
    if current not in _APPROVAL_LADDER:
        return _APPROVAL_LADDER[1]  # default to school_rep if unknown
    idx = _APPROVAL_LADDER.index(current)
    if idx + 1 >= len(_APPROVAL_LADDER):
        return None  # already at super_admin
    return _APPROVAL_LADDER[idx + 1]


def _resolve_creator_ladder_role(db: Session, user_id: str) -> str:
    """
    Return the highest ladder-relevant role the creator currently holds.
    Falls back to 'group_leader' if none match, so routing defaults to
    starting at school_representative.
    """
    now = _now()
    rows = (
        db.query(UserRole)
        .join(Role, UserRole.role_id == Role.id)
        .filter(
            UserRole.user_id == user_id,
            UserRole.status == "active",
        )
        .all()
    )
    active = [r for r in rows if r.end_date is None or r.end_date > now]
    codes = {r.role.code for r in active if r.role}
    # Pick the highest-priority ladder role the user holds.
    for role in reversed(_APPROVAL_LADDER):
        if role in codes:
            return role
    return "group_leader"


def _notify_approver_and_assistant(
    db: Session, proposal: UnitProposal, role_code: str, assistant_role_code: str | None = None,
) -> None:
    """
    Notify the principal approver for this stage and, in parallel, the
    assistant role where one exists. Pins the proposal to a concrete
    approver so it can be filtered out of that user's inbox.
    """
    from app.services.notification_service import (
        notify_user, users_with_roles,
    )

    role_codes: list[str] = [role_code]
    if assistant_role_code:
        role_codes.append(assistant_role_code)
    recipients = users_with_roles(db, tuple(role_codes))

    principal_ids = users_with_roles(db, (role_code,))
    if principal_ids and proposal.current_approver_id not in principal_ids:
        proposal.current_approver_id = principal_ids[0]

    deadline = (
        proposal.escalation_deadline.isoformat()
        if proposal.escalation_deadline else "n/a"
    )
    subject = "Unit proposal awaiting your review"
    body = (
        f"Unit proposal {proposal.id} is at stage '{role_code}'"
        + (f" (assistant: {assistant_role_code})" if assistant_role_code else "")
        + f". Escalation deadline: {deadline}."
    )

    for uid in recipients:
        notify_user(
            db,
            user_id=uid,
            subject=subject,
            text_body=body,
            html_body=f"<p>{body}</p>",
            event_key="unit.proposal.pending",
            source_type="unit_proposal",
            source_id=proposal.id,
        )

    try:
        db.commit()
    except Exception:
        logger.exception(
            "[unit_proposal.notify] commit failed for %s", proposal.id,
        )


_ASSISTANT_FOR: dict[str, str] = {
    "school_representative": "assistant_school_rep",
    "institution_representative": "assistant_institution_rep",
    "county_representative": "assistant_county_rep",
}


# ============================================================================
# CREATE
# ============================================================================

def create_unit_proposal(
    db: Session, data, user_id: str,
) -> UnitProposal:
    # Validate academic chain.
    institution = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not institution:
        raise UnitProposalError("Institution not found.", 404)

    school = db.query(School).filter(School.id == data.school_id).first()
    if not school or school.institution_id != institution.id:
        raise UnitProposalError(
            "School not found in the given institution.", 404,
        )

    course = db.query(Course).filter(Course.id == data.course_id).first()
    if not course or course.school_id != school.id:
        raise UnitProposalError(
            "Course not found in the given school.", 404,
        )

    ay = db.query(AcademicYear).filter(AcademicYear.id == data.academic_year_id).first()
    if not ay or ay.institution_id != institution.id:
        raise UnitProposalError(
            "Academic year not found in the given institution.", 404,
        )

    if data.proposal_type not in ("ocr_extraction", "manual_creation"):
        raise UnitProposalError(
            "proposal_type must be 'ocr_extraction' or 'manual_creation'.", 400,
        )

    # Determine first approver.
    creator_role = _resolve_creator_ladder_role(db, user_id)
    first_approver = _next_role(creator_role)

    if first_approver is None:
        raise UnitProposalError(
            "Super Admin actions do not require a proposal; create units directly.",
            400,
        )

    now = _now()

    proposal = UnitProposal(
        institution_id=institution.id,
        school_id=school.id,
        course_id=course.id,
        academic_year_id=ay.id,
        semester_id=data.semester_id,
        year_level=data.year_level,
        proposal_type=data.proposal_type,
        source_upload_id=data.source_upload_id,
        created_by=user_id,
        status=_STAGE_TO_STATUS.get(first_approver, "pending_school_rep"),
        current_approver_role=first_approver,
        current_approver_id=None,  # populated by the notification layer
        current_stage_started_at=now,
        escalation_deadline=_escalation_deadline(now),
        notes=data.notes,
    )
    db.add(proposal)
    db.flush()

    for item_data in data.items:
        code = item_data.proposed_code.strip().upper()
        name = item_data.proposed_name.strip()

        # Pre-match existing unit for this course + code.
        existing = db.query(Unit).filter(
            Unit.course_id == course.id,
            Unit.code == code,
        ).first()

        item = UnitProposalItem(
            proposal_id=proposal.id,
            existing_unit_id=existing.id if existing else None,
            proposed_code=code,
            proposed_name=name,
            proposed_description=item_data.proposed_description,
            year_level=item_data.year_level or proposal.year_level,
            semester_number=item_data.semester_number,
            confidence=item_data.confidence,
            source_page=item_data.source_page,
            action="update" if existing else "create",
            item_status="pending",
        )
        db.add(item)

    _log_event(
        db, proposal.id, "created",
        actor_id=user_id,
        to_stage=first_approver,
        notes=f"Proposal created by role '{creator_role}'",
    )
    _audit(
        db, user_id, "UnitProposal", proposal.id, "CREATE",
        new_value=f"course={course.code} items={len(data.items)}",
    )
    db.commit()
    db.refresh(proposal)

    _notify_approver_and_assistant(
        db, proposal,
        role_code=first_approver,
        assistant_role_code=_ASSISTANT_FOR.get(first_approver),
    )
    return proposal


# ============================================================================
# READ
# ============================================================================

def _refresh_escalations(db: Session) -> None:
    """Bulk-escalate any proposals past their deadline."""
    escalate_stale_proposals(db)


def list_unit_proposals(
    db: Session,
    institution_id: str | None = None,
    course_id: str | None = None,
    status: str | None = None,
    current_approver_id: str | None = None,
) -> list[UnitProposal]:
    _refresh_escalations(db)
    q = db.query(UnitProposal)
    if institution_id:
        q = q.filter(UnitProposal.institution_id == institution_id)
    if course_id:
        q = q.filter(UnitProposal.course_id == course_id)
    if status:
        q = q.filter(UnitProposal.status == status)
    if current_approver_id:
        q = q.filter(UnitProposal.current_approver_id == current_approver_id)
    return q.order_by(UnitProposal.created_at.desc()).all()


def get_unit_proposal(db: Session, proposal_id: str) -> UnitProposal:
    _refresh_escalations(db)
    proposal = db.query(UnitProposal).filter(UnitProposal.id == proposal_id).first()
    if not proposal:
        raise UnitProposalError("Unit proposal not found.", 404)
    return proposal


# ============================================================================
# ITEM MODIFICATION
# ============================================================================

def modify_proposal_item(
    db: Session, proposal_id: str, item_id: str, data, user_id: str,
) -> UnitProposalItem:
    proposal = get_unit_proposal(db, proposal_id)
    if proposal.status in ("approved", "rejected", "withdrawn"):
        raise UnitProposalError(
            f"Cannot modify items on a proposal in status '{proposal.status}'.", 409,
        )

    item = (
        db.query(UnitProposalItem)
        .filter(
            UnitProposalItem.id == item_id,
            UnitProposalItem.proposal_id == proposal.id,
        )
        .first()
    )
    if not item:
        raise UnitProposalError("Proposal item not found.", 404)

    changes = data.model_dump(exclude_unset=True)
    if "modified_code" in changes and changes["modified_code"]:
        item.modified_code = changes["modified_code"].strip().upper()
    if "modified_name" in changes and changes["modified_name"]:
        item.modified_name = changes["modified_name"].strip()
    if "modified_description" in changes:
        item.modified_description = changes["modified_description"]
    if "notes" in changes and changes["notes"]:
        item.notes = changes["notes"]

    item.item_status = "modified"
    item.reviewed_by = user_id
    item.reviewed_at = _now()

    _log_event(
        db, proposal.id, "modified",
        actor_id=user_id,
        from_stage=proposal.current_approver_role,
        to_stage=proposal.current_approver_role,
        notes=f"Item {item_id} modified",
    )
    _audit(
        db, user_id, "UnitProposalItem", item.id, "MODIFY",
        new_value=str(changes),
    )
    db.commit()
    db.refresh(item)
    return item


# ============================================================================
# APPROVE
# ============================================================================

def approve_unit_proposal(
    db: Session, proposal_id: str, user_id: str,
) -> UnitProposal:
    proposal = get_unit_proposal(db, proposal_id)
    if proposal.status in ("approved", "rejected", "withdrawn"):
        raise UnitProposalError(
            f"Cannot approve proposal in status '{proposal.status}'.", 409,
        )

    now = _now()

    # Apply each item: create or update the underlying Unit, then ensure
    # a UnitOffering exists for the target semester.
    for item in proposal.items:
        if item.item_status == "rejected":
            continue

        code = (item.modified_code or item.proposed_code).strip().upper()
        name = (item.modified_name or item.proposed_name).strip()
        description = (
            item.modified_description
            if item.modified_description is not None
            else item.proposed_description
        )

        if item.existing_unit_id:
            unit = db.query(Unit).filter(Unit.id == item.existing_unit_id).first()
            if unit:
                unit.name = name
                unit.description = description or unit.description
                if item.year_level is not None:
                    unit.year_level = item.year_level
                if item.semester_number is not None:
                    unit.semester_number = item.semester_number
                action = "update"
            else:
                # Stale link — fall through to create.
                unit = _create_unit_from_item(
                    db, proposal, code, name, description, item,
                )
                action = "create"
        else:
            unit = _create_unit_from_item(
                db, proposal, code, name, description, item,
            )
            action = "create"

        item.resulting_unit_id = unit.id
        item.action = action
        item.item_status = "approved"
        item.reviewed_by = user_id
        item.reviewed_at = now

        # Auto-create the offering for the target semester.
        ensure_offering_for_unit(
            db,
            unit_id=unit.id,
            academic_year_id=proposal.academic_year_id,
            semester_id=proposal.semester_id,
        )

    proposal.status = "approved"
    proposal.approved_by = user_id
    proposal.approved_at = now
    proposal.current_approver_role = None
    proposal.current_approver_id = None

    _log_event(
        db, proposal.id, "approved",
        actor_id=user_id,
        from_stage=proposal.current_approver_role,
        to_stage=None,
        notes="Final approval",
    )
    _audit(
        db, user_id, "UnitProposal", proposal.id, "APPROVE",
        old_value=proposal.status, new_value="approved",
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def _create_unit_from_item(
    db: Session, proposal: UnitProposal, code: str, name: str,
    description: str | None, item: UnitProposalItem,
) -> Unit:
    # Guard against unique constraint if the same code appeared twice.
    existing = db.query(Unit).filter(
        Unit.course_id == proposal.course_id,
        Unit.code == code,
    ).first()
    if existing:
        return existing

    unit = Unit(
        course_id=proposal.course_id,
        code=code,
        name=name,
        description=description,
        year_level=item.year_level or proposal.year_level,
        semester_number=item.semester_number,
        status="active",
    )
    db.add(unit)
    db.flush()
    return unit


# ============================================================================
# REJECT / WITHDRAW
# ============================================================================

def reject_unit_proposal(
    db: Session, proposal_id: str, user_id: str, reason: str,
) -> UnitProposal:
    proposal = get_unit_proposal(db, proposal_id)
    if proposal.status in ("approved", "rejected", "withdrawn"):
        raise UnitProposalError(
            f"Cannot reject proposal in status '{proposal.status}'.", 409,
        )
    if not reason or len(reason.strip()) < 3:
        raise UnitProposalError("A reason is required.", 400)

    old = proposal.status
    proposal.status = "rejected"
    proposal.rejected_by = user_id
    proposal.rejected_at = _now()
    proposal.rejection_reason = reason.strip()

    for item in proposal.items:
        if item.item_status == "pending":
            item.item_status = "rejected"
            item.reviewed_by = user_id
            item.reviewed_at = _now()

    _log_event(
        db, proposal.id, "rejected",
        actor_id=user_id,
        from_stage=proposal.current_approver_role,
        to_stage=None,
        notes=reason,
    )
    _audit(
        db, user_id, "UnitProposal", proposal.id, "REJECT",
        old_value=old, new_value="rejected", reason=reason,
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def withdraw_unit_proposal(
    db: Session, proposal_id: str, user_id: str, reason: str | None = None,
) -> UnitProposal:
    proposal = get_unit_proposal(db, proposal_id)
    if proposal.created_by != user_id:
        raise UnitProposalError("Only the original creator may withdraw.", 403)
    if proposal.status in ("approved", "rejected", "withdrawn"):
        raise UnitProposalError(
            f"Cannot withdraw proposal in status '{proposal.status}'.", 409,
        )

    old = proposal.status
    proposal.status = "withdrawn"
    proposal.current_approver_role = None
    proposal.current_approver_id = None

    _log_event(
        db, proposal.id, "withdrawn",
        actor_id=user_id,
        from_stage=old,
        to_stage=None,
        notes=reason,
    )
    _audit(
        db, user_id, "UnitProposal", proposal.id, "WITHDRAW",
        old_value=old, new_value="withdrawn", reason=reason,
    )
    db.commit()
    db.refresh(proposal)
    return proposal


# ============================================================================
# ESCALATION SWEEP
# ============================================================================

def escalate_stale_proposals(db: Session) -> int:
    """
    Find proposals whose escalation_deadline has passed and move them one
    step up the ladder. Idempotent, safe to call frequently.

    Returns the number of proposals that were escalated.
    """
    now = _now()
    stale = (
        db.query(UnitProposal)
        .filter(
            UnitProposal.escalation_deadline <= now,
            UnitProposal.status.notin_(("approved", "rejected", "withdrawn")),
            UnitProposal.current_approver_role.isnot(None),
        )
        .all()
    )

    escalated = 0
    for p in stale:
        current = p.current_approver_role
        nxt = _next_role(current)
        if nxt is None:
            # Terminal stage reached (super_admin). Do nothing.
            continue
        new_status = _STAGE_TO_STATUS.get(nxt)
        if new_status is None:
            continue

        old_status = p.status
        p.status = new_status
        p.current_approver_role = nxt
        p.current_approver_id = None
        p.current_stage_started_at = now
        p.escalation_deadline = _escalation_deadline(now)

        _log_event(
            db, p.id, "escalated",
            actor_id=None,
            from_stage=current,
            to_stage=nxt,
            notes="Auto-escalated after timeout",
        )
        _audit(
            db, None, "UnitProposal", p.id, "ESCALATE",
            old_value=old_status, new_value=new_status,
            reason="Auto-escalation after escalation_deadline",
        )

        _notify_approver_and_assistant(
            db, p, role_code=nxt,
            assistant_role_code=_ASSISTANT_FOR.get(nxt),
        )
        escalated += 1

    if escalated:
        db.commit()
    return escalated