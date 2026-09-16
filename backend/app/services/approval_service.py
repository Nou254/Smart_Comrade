"""
External user approval workflow.

Routes pending external registrations to the correct approver and
applies the approve/reject state transitions.

Routing rules (spec §9.3):
  - Lecturer:     institution_admin of the specified institution
  - Investor:     institution_admin + super_admin
  - Organization: institution_admin + super_admin
  - Mentor:       institution_admin + super_admin
  - Specialist:   institution_admin + super_admin
  - Alumni:       no approval needed
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.role import UserRole
from app.models.user import User
from app.services.admin_audit_service import log_admin_action
from app.services.notification_service import notify_user
from app.core.templates import email_templates

logger = logging.getLogger(__name__)


class ApprovalError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


EXTERNAL_APPROVAL_REQUIRED = {
    "lecturer",
    "investor",
    "organization",
    "mentor",
    "specialist",
}


def requires_approval(external_subtype: str | None) -> bool:
    if not external_subtype:
        return False
    return external_subtype.lower() in EXTERNAL_APPROVAL_REQUIRED


def list_pending_for_admin(db: Session, admin_user: User) -> list[User]:
    """Return all pending external users this admin can approve."""
    q = (
        db.query(User)
        .filter(
            User.account_status == "pending_approval",
        )
        .order_by(User.created_at.desc())
    )

    # Super Admin sees everything
    roles, _ = _resolve_admin_roles(db, admin_user.id)
    if "super_admin" in roles:
        return q.all()

    # Institution Admin sees their institution only
    if "institution_admin" in roles and admin_user.institution_id:
        return [
            u for u in q.all()
            if u.institution_id == admin_user.institution_id
        ]

    return []


def approve(db: Session, *, target_user_id: str, actor: User,
            notes: str | None = None) -> User:
    target = _get_pending_user(db, target_user_id)
    _check_authority(db, actor, target)

    target.account_status = "active"
    target.approved_at = datetime.now(timezone.utc)
    target.approved_by = actor.id
    db.commit()
    db.refresh(target)

    log_admin_action(
        db, actor_id=actor.id, action="external.approve",
        target_type="user", target_id=target.id,
        old_value="pending_approval", new_value="active",
        reason=notes,
    )

    subject, html, text = email_templates.account_approved(
        name=target.first_name or "there"
    )
    try:
        notify_user(
            db, user_id=target.id,
            subject=subject, html_body=html, text_body=text,
            event_key="account.approved",
        )
    except Exception:
        logger.exception("Failed to notify approved user")

    return target


def reject(db: Session, *, target_user_id: str, actor: User,
           reason: str) -> User:
    if not reason or len(reason.strip()) < 5:
        raise ApprovalError("Rejection reason is required (min 5 chars).", 400)

    target = _get_pending_user(db, target_user_id)
    _check_authority(db, actor, target)

    target.account_status = "rejected"
    target.rejected_at = datetime.now(timezone.utc)
    target.rejected_by = actor.id
    target.rejection_reason = reason.strip()
    db.commit()
    db.refresh(target)

    log_admin_action(
        db, actor_id=actor.id, action="external.reject",
        target_type="user", target_id=target.id,
        old_value="pending_approval", new_value="rejected",
        reason=reason,
    )

    subject, html, text = email_templates.account_rejected(
        name=target.first_name or "there", reason=reason
    )
    try:
        notify_user(
            db, user_id=target.id,
            subject=subject, html_body=html, text_body=text,
            event_key="account.rejected",
        )
    except Exception:
        logger.exception("Failed to notify rejected user")

    return target


# ── Helpers ────────────────────────────────────────────────

def _get_pending_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ApprovalError("User not found.", 404)
    if user.account_status != "pending_approval":
        raise ApprovalError(
            f"User is not pending approval (current: {user.account_status}).", 409
        )
    return user


def _check_authority(db: Session, actor: User, target: User) -> None:
    roles, _ = _resolve_admin_roles(db, actor.id)

    if "super_admin" in roles:
        return

    if "institution_admin" in roles:
        if actor.institution_id and actor.institution_id == target.institution_id:
            return
        raise ApprovalError("You can only approve users in your institution.", 403)

    raise ApprovalError("You do not have approval authority.", 403)


def _resolve_admin_roles(db: Session, user_id: str) -> tuple[set[str], set[str]]:
    rows = (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.status == "active")
        .all()
    )
    roles = set()
    perms: set[str] = set()
    for r in rows:
        if r.role:
            roles.add(r.role.code)
            # permission resolution is handled elsewhere; we only need roles here
    return roles, perms