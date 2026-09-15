"""
Admin provisioning, suspend/reactivate, invitation lifecycle.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.security import (
    generate_reset_token, hash_token, hash_password, verify_password,
)
from app.models.user import User
from app.models.role import Role, UserRole
from app.models.admin_invitation import AdminInvitation
from app.services.admin_audit_service import log_admin_action
from app.services.session_service import revoke_all_other_sessions


class AdminError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


INVITATION_EXPIRY_DAYS = 7


# ============================================================================
# Invitation lifecycle
# ============================================================================

def create_invitation(
    db: Session, *,
    invited_by: str,
    email: str,
    role_code: str,
    jurisdiction_type: str,
    jurisdiction_id: str | None,
    notes: str | None = None,
) -> tuple[AdminInvitation, str]:
    """Returns (invitation_row, plaintext_token)."""
    role = db.query(Role).filter(Role.code == role_code).first()
    if not role:
        raise AdminError(f"Role '{role_code}' not found.", 404)

    valid_jt = {"platform", "region", "county", "institution", "school", "group"}
    if jurisdiction_type not in valid_jt:
        raise AdminError(f"Invalid jurisdiction_type. Must be one of {sorted(valid_jt)}")

    if jurisdiction_type != "platform" and not jurisdiction_id:
        raise AdminError("jurisdiction_id is required for non-platform roles.")

    existing = db.query(User).filter(User.email == email.lower().strip()).first()
    if existing:
        raise AdminError("A user with this email already exists.", 409)

    pending = (
        db.query(AdminInvitation)
        .filter(AdminInvitation.email == email.lower().strip(), AdminInvitation.is_used.is_(False))
        .first()
    )
    if pending and pending.expires_at > datetime.now(timezone.utc):
        raise AdminError("An active invitation already exists for this email.", 409)

    token = generate_reset_token()
    inv = AdminInvitation(
        email=email.lower().strip(),
        role_code=role_code,
        jurisdiction_type=jurisdiction_type,
        jurisdiction_id=jurisdiction_id,
        token_hash=hash_token(token),
        invited_by=invited_by,
        notes=notes,
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRY_DAYS),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    log_admin_action(
        db, actor_id=invited_by, action="invitation.create",
        target_type="admin_invitation", target_id=inv.id,
        new_value=f"{email} as {role_code} @ {jurisdiction_type}:{jurisdiction_id}",
        reason=notes,
    )
    return inv, token


def accept_invitation(
    db: Session, *,
    token: str,
    first_name: str,
    last_name: str,
    password: str,
    phone: str | None = None,
) -> User:
    th = hash_token(token)
    inv = db.query(AdminInvitation).filter(AdminInvitation.token_hash == th).first()
    if not inv:
        raise AdminError("Invalid invitation token.", 400)
    if inv.is_used:
        raise AdminError("This invitation has already been used.", 409)
    if inv.expires_at < datetime.now(timezone.utc):
        raise AdminError("This invitation has expired.", 410)

    if db.query(User).filter(User.email == inv.email).first():
        raise AdminError("A user with this email already exists.", 409)

    role = db.query(Role).filter(Role.code == inv.role_code).first()
    if not role:
        raise AdminError("Invitation role no longer exists.", 404)

    user = User(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=inv.email,
        phone=phone.strip() if phone else None,
        password_hash=hash_password(password),
        user_type="lecturer",  # placeholder user_type for admins
        account_status="active",
        email_verified=True,
        phone_verified=False,
        two_factor_enabled=False,  # must set up on first login
    )
    db.add(user)
    db.flush()

    db.add(UserRole(
        user_id=user.id,
        role_id=role.id,
        jurisdiction_type=inv.jurisdiction_type,
        jurisdiction_id=inv.jurisdiction_id,
        status="active",
        start_date=datetime.now(timezone.utc),
        granted_by=inv.invited_by,
        granted_at=datetime.now(timezone.utc),
        notes=f"Via invitation {inv.id}",
    ))

    inv.is_used = True
    inv.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    log_admin_action(
        db, actor_id=inv.invited_by, action="invitation.accept",
        target_type="user", target_id=user.id,
        new_value=f"User accepted invitation for {inv.role_code}",
    )
    return user


# ============================================================================
# Suspend / reactivate
# ============================================================================

def suspend_user(db: Session, *, target_user_id: str, actor_id: str,
                 reason: str | None, ip: str | None = None, ua: str | None = None) -> User:
    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise AdminError("User not found.", 404)
    if user.id == actor_id:
        raise AdminError("You cannot suspend your own account.", 409)

    old_status = user.account_status
    user.account_status = "suspended"
    db.commit()

    revoke_all_other_sessions(db, user.id, keep_token=None)

    log_admin_action(
        db, actor_id=actor_id, action="user.suspend",
        target_type="user", target_id=user.id,
        old_value=old_status, new_value="suspended", reason=reason,
        ip_address=ip, user_agent=ua,
    )
    db.refresh(user)
    return user


def reactivate_user(db: Session, *, target_user_id: str, actor_id: str,
                    reason: str | None, ip: str | None = None, ua: str | None = None) -> User:
    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise AdminError("User not found.", 404)

    old_status = user.account_status
    user.account_status = "active"
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    log_admin_action(
        db, actor_id=actor_id, action="user.reactivate",
        target_type="user", target_id=user.id,
        old_value=old_status, new_value="active", reason=reason,
        ip_address=ip, user_agent=ua,
    )
    db.refresh(user)
    return user