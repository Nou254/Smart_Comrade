"""
Lecturer affiliation management.

Self-service CRUD for the lecturer, plus admin verification queue.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.notifications import send_email
from app.models.user import User
from app.models.academic import Institution
from app.models.lecturer_affiliation import LecturerAffiliation
from app.schemas.lecturer import LecturerAffiliationCreate
from app.services.audit_service import log_auth_event


logger = logging.getLogger(__name__)


class LecturerError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


VALID_TITLES = {"Lecturer", "Senior Lecturer", "Professor", "Assistant Lecturer"}


# ============================================================================
# Self-service
# ============================================================================

def list_my_affiliations(db: Session, user_id: str) -> list[LecturerAffiliation]:
    """All affiliations for the current user, newest first."""
    return (
        db.query(LecturerAffiliation)
        .filter(LecturerAffiliation.user_id == user_id)
        .order_by(LecturerAffiliation.created_at.desc())
        .all()
    )


def get_affiliation(
    db: Session, affiliation_id: str, user_id: str | None = None,
) -> LecturerAffiliation:
    q = db.query(LecturerAffiliation).filter(LecturerAffiliation.id == affiliation_id)
    if user_id is not None:
        q = q.filter(LecturerAffiliation.user_id == user_id)
    aff = q.first()
    if not aff:
        raise LecturerError("Affiliation not found.", 404)
    return aff


def add_affiliation(
    db: Session, user: User, data: LecturerAffiliationCreate,
) -> LecturerAffiliation:
    """Add a new affiliation for the current lecturer. Status = pending."""
    if user.user_type != "lecturer":
        raise LecturerError("Only lecturers can add affiliations.", 403)

    if data.title not in VALID_TITLES:
        raise LecturerError(
            f"Invalid title. Must be one of: {sorted(VALID_TITLES)}"
        )

    inst = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not inst:
        raise LecturerError("Institution not found.", 404)

    # Duplicate check (user cannot have two affiliations at the same institution)
    existing = (
        db.query(LecturerAffiliation)
        .filter(
            LecturerAffiliation.user_id == user.id,
            LecturerAffiliation.institution_id == inst.id,
            LecturerAffiliation.verification_status.in_(["pending", "verified"]),
        )
        .first()
    )
    if existing:
        raise LecturerError(
            "You already have an active affiliation with this institution.", 409,
        )

    aff = LecturerAffiliation(
        user_id=user.id,
        institution_id=inst.id,
        institutional_email=(
            str(data.institutional_email) if data.institutional_email else None
        ),
        department=data.department,
        title=data.title,
        referee_name=data.referee_name,
        referee_phone=data.referee_phone,
        referee_relationship=data.referee_relationship,
        verification_status="pending",
        domain_verified=False,  # admin will confirm
    )
    db.add(aff)
    db.commit()
    db.refresh(aff)

    log_auth_event(
        db, "lecturer_affiliation_added",
        user_id=user.id, email=user.email,
        event_data={
            "affiliation_id": aff.id,
            "institution_id": inst.id,
            "title": aff.title,
        },
    )

    # Notify admins (best-effort, no crash if it fails)
    try:
        _notify_admins_pending_affiliation(db, aff, user)
    except Exception:
        pass

    return aff


def end_affiliation(
    db: Session, user: User, affiliation_id: str, reason: str | None = None,
) -> LecturerAffiliation:
    """Self-service: mark one of my affiliations as ended."""
    aff = get_affiliation(db, affiliation_id, user_id=user.id)
    if aff.verification_status == "ended":
        raise LecturerError("This affiliation is already ended.", 409)

    now = datetime.now(timezone.utc)
    old_status = aff.verification_status
    aff.verification_status = "ended"
    aff.end_date = now
    if reason:
        aff.verification_notes = reason
    db.commit()
    db.refresh(aff)

    log_auth_event(
        db, "lecturer_affiliation_ended",
        user_id=user.id, email=user.email,
        event_data={
            "affiliation_id": aff.id,
            "previous_status": old_status,
            "reason": reason,
        },
    )
    return aff


# ============================================================================
# Admin verification
# ============================================================================

def list_pending_for_institution(
    db: Session, institution_id: str,
) -> list[LecturerAffiliation]:
    return (
        db.query(LecturerAffiliation)
        .filter(
            LecturerAffiliation.institution_id == institution_id,
            LecturerAffiliation.verification_status == "pending",
        )
        .order_by(LecturerAffiliation.created_at.asc())
        .all()
    )


def verify_affiliation(
    db: Session, affiliation_id: str, actor_id: str,
    approve: bool, notes: str | None = None,
) -> LecturerAffiliation:
    aff = get_affiliation(db, affiliation_id)
    if aff.verification_status != "pending":
        raise LecturerError(
            f"Affiliation is not pending (current: {aff.verification_status}).", 409,
        )

    now = datetime.now(timezone.utc)
    if approve:
        aff.verification_status = "verified"
        aff.approved_by = actor_id
        aff.approved_at = now
    else:
        aff.verification_status = "rejected"
        aff.approved_by = actor_id
        aff.approved_at = now
    if notes:
        aff.verification_notes = notes
    db.commit()
    db.refresh(aff)

    log_auth_event(
        db, "lecturer_affiliation_verified" if approve else "lecturer_affiliation_rejected",
        user_id=actor_id,
        event_data={
            "affiliation_id": aff.id,
            "lecturer_user_id": aff.user_id,
            "institution_id": aff.institution_id,
            "notes": notes,
        },
    )

    # Notify the lecturer
    try:
        lecturer = db.query(User).filter(User.id == aff.user_id).first()
        if lecturer:
            verb = "approved" if approve else "rejected"
            send_email(
                to=lecturer.email,
                subject=f"Your affiliation with an institution was {verb}",
                html_body=f"<p>Your lecturer affiliation has been {verb}.</p>",
                text_body=f"Your lecturer affiliation has been {verb}.",
            )
    except Exception:
        pass

    return aff


# ============================================================================
# Internal helpers
# ============================================================================

def _notify_admins_pending_affiliation(
    db: Session, aff: LecturerAffiliation, lecturer: User,
) -> None:
    """Best-effort notification to Super Admins about a pending affiliation."""
    try:
        from app.services.notification_service import (
            notify_user, users_with_roles,
        )

        name = f"{lecturer.first_name} {lecturer.last_name}".strip()
        subject = "Lecturer affiliation pending verification"
        body = (
            f"{name or lecturer.email} requested lecturer affiliation with "
            f"institution {aff.institution_id}. Please review and verify it."
        )
        for uid in users_with_roles(db, ("super_admin",)):
            notify_user(
                db,
                user_id=uid,
                subject=subject,
                text_body=body,
                html_body=f"<p>{body}</p>",
                event_key="account.lecturer_affiliation_pending",
                source_type="lecturer_affiliation",
                source_id=aff.id,
            )
    except Exception:
        logger.exception(
            "[lecturer.notify] admin notification failed for %s", aff.id,
        )