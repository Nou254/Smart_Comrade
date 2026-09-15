"""
Authentication business logic: registration, login, approval, admin 2FA gate.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.core.security import (
    hash_password, verify_password,
    create_2fa_pending_token, create_admin_setup_token,
)
from app.models.user import User
from app.models.academic import Institution
from app.schemas.user import StudentRegister, LecturerRegister, ExternalRegister, UserLogin
from app.services.verification_service import create_email_verification
from app.services.session_service import create_session
from app.services.audit_service import log_auth_event
from app.services.jurisdiction_service import is_admin_user
from app.services.system_config_service import is_admin_2fa_required
from app.models.role import Role, UserRole


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class TwoFactorRequired(Exception):
    def __init__(self, temp_token: str):
        self.temp_token = temp_token
        self.message = "2FA required"
        super().__init__(self.message)


class Admin2FASetupRequired(Exception):
    def __init__(self, setup_token: str):
        self.setup_token = setup_token
        self.message = "Admin 2FA setup required"
        super().__init__(self.message)


APPROVAL_REQUIRED_TYPES = {"lecturer", "external"}
AUTO_ACTIVE_EXTERNAL = {"alumni"}

# Lockout thresholds
LOCK_AFTER_ATTEMPTS = 5
LOCK_MINUTES = 15
ADMIN_LOCK_AFTER_ATTEMPTS = 3
ADMIN_LOCK_MINUTES = 60

# Session lengths (minutes)
USER_SESSION_MINUTES = 1440   # 24 hours
ADMIN_SESSION_MINUTES = 720   # 12 hours


def _email_domain_matches(email: str, institution: Institution) -> bool:
    if not email or "@" not in email:
        return False
    if not institution.website:
        return False
    domain = email.split("@", 1)[1].lower()
    site = institution.website.lower().replace("https://", "").replace("http://", "").split("/")[0]
    return domain in site or site in domain


def _create_user(db: Session, *, first_name, last_name, email, phone, password,
                 user_type, institution_id=None, external_subtype=None,
                 institutional_email=None, department=None, title=None,
                 domain_verified=False) -> User:
    if db.query(User).filter(User.email == email.lower().strip()).first():
        raise AuthError("An account with this email already exists.", 409)
    if phone and db.query(User).filter(User.phone == phone).first():
        raise AuthError("An account with this phone number already exists.", 409)

    user = User(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=email.lower().strip(),
        phone=phone.strip() if phone else None,
        password_hash=hash_password(password),
        user_type=user_type,
        external_subtype=external_subtype,
        institution_id=institution_id,
        institutional_email=institutional_email.lower().strip() if institutional_email else None,
        department=department,
        title=title,
        domain_verified=domain_verified,
        account_status="pending",
        email_verified=False,
        phone_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    base_role_code = {
        "student": "student", "lecturer": "lecturer", "external": "external_user",
    }.get(user_type)
    if base_role_code:
        role = db.query(Role).filter(Role.code == base_role_code).first()
        if role:
            role_status = "pending" if user_type in APPROVAL_REQUIRED_TYPES else "active"
            db.add(UserRole(
                user_id=user.id, role_id=role.id,
                jurisdiction_type="self", jurisdiction_id=None,
                status=role_status, start_date=datetime.now(timezone.utc),
                notes=f"Auto-assigned on {user_type} registration",
            ))
            db.commit()
    return user


def register_student(db: Session, data: StudentRegister) -> User:
    inst = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not inst:
        raise AuthError("Institution not found.", 404)
    user = _create_user(
        db, first_name=data.first_name, last_name=data.last_name,
        email=data.email, phone=data.phone, password=data.password,
        user_type="student", institution_id=inst.id,
    )
    create_email_verification(db, user, purpose="registration")
    log_auth_event(db, "register_student", user_id=user.id, email=user.email)
    return user


def register_lecturer(db: Session, data: LecturerRegister) -> User:
    inst = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not inst:
        raise AuthError("Institution not found.", 404)
    valid_titles = {"Lecturer", "Senior Lecturer", "Professor", "Assistant Lecturer"}
    if data.title not in valid_titles:
        raise AuthError(f"Invalid title. Must be one of: {sorted(valid_titles)}")
    domain_ok = _email_domain_matches(str(data.institutional_email), inst)
    user = _create_user(
        db, first_name=data.first_name, last_name=data.last_name,
        email=data.email, phone=data.phone, password=data.password,
        user_type="lecturer", institution_id=inst.id,
        institutional_email=str(data.institutional_email),
        department=data.department, title=data.title,
        domain_verified=domain_ok,
    )
    create_email_verification(db, user, purpose="registration")
    log_auth_event(db, "register_lecturer", user_id=user.id, email=user.email,
                   event_data={"domain_verified": domain_ok})
    return user


def register_external(db: Session, data: ExternalRegister) -> User:
    valid_subtypes = {"investor", "mentor", "organization", "alumni", "specialist"}
    if data.external_subtype not in valid_subtypes:
        raise AuthError(f"Invalid subtype. Must be one of: {sorted(valid_subtypes)}")
    user = _create_user(
        db, first_name=data.first_name, last_name=data.last_name,
        email=data.email, phone=data.phone, password=data.password,
        user_type="external", external_subtype=data.external_subtype,
        department=data.organization_name, title=data.profession,
    )
    create_email_verification(db, user, purpose="registration")
    log_auth_event(db, "register_external", user_id=user.id, email=user.email,
                   event_data={"subtype": data.external_subtype})
    return user


def login_user(db: Session, data: UserLogin, ip: str | None = None,
               user_agent: str | None = None) -> tuple[User, str]:
    user = db.query(User).filter(User.email == data.email.lower().strip()).first()
    if not user:
        log_auth_event(db, "login_failed", email=data.email, ip_address=ip,
                       user_agent=user_agent, success=False,
                       event_data={"reason": "user_not_found"})
        raise AuthError("Invalid email or password.", 401)

    admin = is_admin_user(db, user.id)
    lock_attempts = ADMIN_LOCK_AFTER_ATTEMPTS if admin else LOCK_AFTER_ATTEMPTS
    lock_minutes = ADMIN_LOCK_MINUTES if admin else LOCK_MINUTES

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds() // 60) + 1
        log_auth_event(db, "login_locked", user_id=user.id, email=user.email,
                       ip_address=ip, user_agent=user_agent, success=False,
                       event_data={"minutes_remaining": remaining})
        raise AuthError(f"Account locked. Try again in {remaining} minutes.", 423)

    if not verify_password(data.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= lock_attempts:
            user.locked_until = now + timedelta(minutes=lock_minutes)
            user.failed_login_attempts = 0
            db.commit()
            log_auth_event(db, "login_locked", user_id=user.id, email=user.email,
                           ip_address=ip, user_agent=user_agent, success=False,
                           event_data={"reason": "too_many_failures", "admin": admin})
            raise AuthError(
                f"Too many failed attempts. Account locked for {lock_minutes} minutes.", 423
            )
        db.commit()
        log_auth_event(db, "login_failed", user_id=user.id, email=user.email,
                       ip_address=ip, user_agent=user_agent, success=False,
                       event_data={"attempts": user.failed_login_attempts})
        raise AuthError("Invalid email or password.", 401)

    user.failed_login_attempts = 0
    user.locked_until = None

    if user.account_status == "suspended":
        log_auth_event(db, "login_blocked", user_id=user.id, email=user.email,
                       ip_address=ip, user_agent=user_agent, success=False,
                       event_data={"status": "suspended"})
        raise AuthError("This account has been suspended.", 403)
    if user.account_status == "deactivated":
        raise AuthError("This account has been deactivated.", 403)
    if user.account_status == "rejected":
        raise AuthError("Your registration was rejected.", 403)
    if user.account_status == "pending":
        raise AuthError("Please verify your email to continue.", 403)
    if user.account_status == "pending_approval":
        raise AuthError("Your account is awaiting administrative approval.", 403)

    db.commit()

    # Admin 2FA enforcement
    if admin and is_admin_2fa_required(db) and not user.two_factor_enabled:
        setup_token = create_admin_setup_token(user.id)
        log_auth_event(db, "login_admin_2fa_setup_required",
                       user_id=user.id, email=user.email,
                       ip_address=ip, user_agent=user_agent)
        raise Admin2FASetupRequired(setup_token)

    # If 2FA enabled, issue challenge
    if user.two_factor_enabled:
        from app.services.two_factor_service import issue_login_challenge
        issue_login_challenge(db, user, ip=ip, ua=user_agent)
        temp = create_2fa_pending_token(user.id)
        log_auth_event(db, "login_password_ok_2fa_pending",
                       user_id=user.id, email=user.email,
                       ip_address=ip, user_agent=user_agent,
                       event_data={"method": user.two_factor_method or "totp"})
        raise TwoFactorRequired(temp)

    # Session length depends on admin status
    expiry = ADMIN_SESSION_MINUTES if admin else USER_SESSION_MINUTES
    token, _ = create_session(
        db, user, ip_address=ip, user_agent=user_agent,
        expires_minutes=expiry,
    )
    log_auth_event(db, "login_success", user_id=user.id, email=user.email,
                   ip_address=ip, user_agent=user_agent,
                   event_data={"session_minutes": expiry, "admin": admin})
    return user, token


# --- Approval workflow (unchanged) ---

def list_pending_approvals(db: Session, institution_id: str) -> list[User]:
    return (
        db.query(User)
        .filter(User.account_status == "pending_approval",
                User.institution_id == institution_id)
        .order_by(User.created_at.asc())
        .all()
    )


def approve_user(db: Session, user_id: str, approver_id: str, approve: bool,
                 reason: str | None = None) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AuthError("User not found.", 404)
    if user.account_status != "pending_approval":
        raise AuthError("User is not awaiting approval.", 409)

    now = datetime.now(timezone.utc)
    if approve:
        user.account_status = "active"
        user.approved_by = approver_id
        user.approved_at = now
        user.rejection_reason = None
        db.query(UserRole).filter(
            UserRole.user_id == user.id, UserRole.status == "pending",
        ).update({"status": "active"})
        log_auth_event(db, "account_approved", user_id=user.id, email=user.email,
                       event_data={"approver": approver_id})
    else:
        user.account_status = "rejected"
        user.approved_by = approver_id
        user.approved_at = now
        user.rejection_reason = reason or "Rejected by administrator"
        log_auth_event(db, "account_rejected", user_id=user.id, email=user.email,
                       event_data={"approver": approver_id, "reason": reason})

    db.commit()
    db.refresh(user)

    from app.core.notifications import (
        send_account_approved_email, send_account_rejected_email,
    )
    if approve:
        send_account_approved_email(user.email, user.first_name)
    else:
        send_account_rejected_email(user.email, user.first_name, reason)
    return user