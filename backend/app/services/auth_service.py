"""
Authentication business logic: registration, login, approval, admin 2FA gate.
Registration stages data in cache until email verification succeeds.

Supports 13 user types including 5 distinct external subtypes.

Phone requirements:
  - students and alumni: phone optional
  - lecturers and other external subtypes: phone required (PWA users)
  - elevated students (alumni, pre-assessed mentors): phone optional (inherited)
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.core.security import (
    hash_password, verify_password,
    create_2fa_pending_token, create_admin_setup_token,
    generate_otp, hash_otp,
)
from app.core import captcha as captcha_module
from app.core.notifications import send_otp_email
from app.models.user import User
from app.models.academic import Institution
from app.models.external_profile import ExternalProfile
from app.schemas.user import (
    StudentRegister, LecturerRegister, ExternalRegister,
    InvestorRegister, OrganizationRegister, AlumniRegister,
    MentorRegister, SpecialistRegister, UserLogin,
)
from app.services import registration_cache
from app.services.session_service import create_session
from app.services.audit_service import log_auth_event
from app.services.jurisdiction_service import is_admin_user
from app.services.system_config_service import is_admin_2fa_required
from app.services.hub_router import resolve_hub
from app.services.environment_service import analyze as analyze_env
from app.services import security_alert_service
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


class CaptchaRequired(Exception):
    def __init__(self, reason: str = "CAPTCHA required"):
        self.message = reason
        super().__init__(self.message)


# ── Constants ───────────────────────────────────────────────────────────────

APPROVAL_REQUIRED_TYPES = {"lecturer", "external"}
AUTO_ACTIVE_EXTERNAL = {"alumni"}

APPROVAL_REQUIRED_SUBTYPES = {
    "investor", "organization", "mentor", "specialist",
}

LOCK_AFTER_ATTEMPTS = 5
LOCK_MINUTES = 15
ADMIN_LOCK_AFTER_ATTEMPTS = 3
ADMIN_LOCK_MINUTES = 60

USER_SESSION_MINUTES = 1440
ADMIN_SESSION_MINUTES = 720

CURRENT_TOS_VERSION = "1.0"
CURRENT_PRIVACY_VERSION = "1.0"

OTP_EXPIRY_MINUTES = 15


# ── Helpers ─────────────────────────────────────────────────────────────────

def _email_domain_matches(email: str, institution: Institution) -> bool:
    if not email or "@" not in email:
        return False
    if not institution.website:
        return False
    domain = email.split("@", 1)[1].lower()
    site = (
        institution.website.lower()
        .replace("https://", "").replace("http://", "")
        .split("/")[0]
    )
    return domain in site or site in domain


def _require_tos_privacy(tos: bool, privacy: bool) -> None:
    if not tos:
        raise AuthError("You must accept the Terms of Service.", 400)
    if not privacy:
        raise AuthError("You must accept the Privacy Policy.", 400)


def _check_uniqueness(db: Session, email: str, phone: str | None) -> None:
    """Reject if email/phone already taken in DB or pending in cache."""
    if db.query(User).filter(User.email == email.lower().strip()).first():
        raise AuthError("An account with this email already exists.", 409)
    if phone and db.query(User).filter(User.phone == phone).first():
        raise AuthError("An account with this phone number already exists.", 409)

    if registration_cache.get_pending(email):
        raise AuthError(
            "A registration is already pending for this email. "
            "If you did not receive the OTP, use the resend endpoint.",
            409,
        )
    if phone and registration_cache.is_phone_pending(phone):
        raise AuthError(
            "A registration is already pending for this phone number. "
            "If you did not receive the OTP, use the resend endpoint.",
            409,
        )


def _stage_registration(
    db: Session, *,
    first_name, last_name, email, phone, password,
    user_type,
    external_subtype=None,
    institution_id=None,
    institutional_email=None,
    department=None,
    title=None,
    domain_verified=False,
    tos_version=None,
    privacy_version=None,
    extra: dict | None = None,
) -> dict:
    """
    Stage a pending registration in cache.
    Returns a dict suitable for LoginResponse.user.
    No DB row is created.
    """
    _check_uniqueness(db, email, phone)

    otp = generate_otp()
    otp_hash_val = hash_otp(otp)
    otp_expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

    registration_cache.store_pending(
        email=email,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
        password_hash=hash_password(password),
        user_type=user_type,
        external_subtype=external_subtype,
        institution_id=institution_id,
        institutional_email=institutional_email,
        department=department,
        title=title,
        domain_verified=domain_verified,
        tos_version=tos_version,
        privacy_version=privacy_version,
        otp_hash=otp_hash_val,
        otp_expires_at=otp_expires,
        purpose="registration",
        extra=extra,
    )

    send_otp_email(email, otp, purpose="registration")

    log_auth_event(
        db, "register_staged", email=email.lower().strip(),
        event_data={"user_type": user_type, "external_subtype": external_subtype},
    )

    return {
        "email": email.lower().strip(),
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "user_type": user_type,
        "external_subtype": external_subtype,
        "account_status": "pending",
        "email_verified": False,
    }


def _stage_external(
    db: Session, *, subtype: str,
    first_name, last_name, email, phone, password,
    tos_version, privacy_version,
    extra: dict | None = None,
) -> dict:
    return _stage_registration(
        db,
        first_name=first_name, last_name=last_name,
        email=email, phone=phone, password=password,
        user_type="external", external_subtype=subtype,
        tos_version=tos_version, privacy_version=privacy_version,
        extra=extra,
    )


# ============================================================================
# REGISTRATION — Core types (all return pending dict)
# ============================================================================

def register_student(db: Session, data: StudentRegister) -> dict:
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)
    inst = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not inst:
        raise AuthError("Institution not found.", 404)

    return _stage_registration(
        db,
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        user_type="student", institution_id=inst.id,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
    )


def register_lecturer(db: Session, data: LecturerRegister) -> dict:
    """Lecturer registration — first affiliation + referee stored in cache."""
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)

    inst = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not inst:
        raise AuthError("Institution not found.", 404)

    valid_titles = {"Lecturer", "Senior Lecturer", "Professor", "Assistant Lecturer"}
    if data.title not in valid_titles:
        raise AuthError(f"Invalid title. Must be one of: {sorted(valid_titles)}")

    domain_ok = _email_domain_matches(str(data.institutional_email), inst)

    # Referee is per-affiliation. For the first affiliation, we capture the
    # referee in the cache record's `extra` dict, and the promotion step
    # (verify_pending_registration) creates the LecturerAffiliation row.
    return _stage_registration(
        db,
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        user_type="lecturer", institution_id=inst.id,
        institutional_email=str(data.institutional_email),
        department=data.department, title=data.title,
        domain_verified=domain_ok,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
        extra={
            "referee_name": data.referee_name,
            "referee_phone": data.referee_phone,
            "referee_relationship": data.referee_relationship,
        },
    )


def register_external(db: Session, data: ExternalRegister) -> dict:
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)
    valid_subtypes = {"investor", "mentor", "organization", "alumni", "specialist"}
    if data.external_subtype not in valid_subtypes:
        raise AuthError(f"Invalid subtype. Must be one of: {sorted(valid_subtypes)}")

    return _stage_external(
        db, subtype=data.external_subtype,
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
        extra={
            "organization_name": data.organization_name,
            "mentor_profession": data.profession,
            "mentor_expertise": data.expertise,
        },
    )


# ============================================================================
# REGISTRATION — External subtypes
# ============================================================================

def register_investor(db: Session, data: InvestorRegister) -> dict:
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)
    return _stage_external(
        db, subtype="investor",
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
        extra={
            "investor_org_name": data.organization_name,
            "investor_role": data.role_in_organization,
            "investment_focus": data.investment_focus,
        },
    )


def register_organization(db: Session, data: OrganizationRegister) -> dict:
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)

    org_name = data.organization_name.strip()
    if db.query(ExternalProfile).filter(
        ExternalProfile.organization_name == org_name,
    ).first():
        raise AuthError("An organization with this name already exists.", 409)

    return _stage_external(
        db, subtype="organization",
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
        extra={
            "organization_name": org_name,
            "organization_type": data.organization_type,
            "industry": data.industry,
            "registration_number": data.registration_number,
            "contact_name": data.contact_name,
            "contact_email": str(data.contact_email) if data.contact_email else None,
            "contact_phone": data.contact_phone,
        },
    )


def register_alumni(db: Session, data: AlumniRegister) -> dict:
    """Alumni registration — phone optional (elevated-student exception)."""
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)
    return _stage_external(
        db, subtype="alumni",
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
        extra={
            "former_institution": data.former_institution,
            "graduation_year": data.graduation_year,
            "current_profession": data.current_profession,
            "alumni_expertise": data.expertise,
        },
    )


def register_mentor(db: Session, data: MentorRegister) -> dict:
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)
    if len(data.areas_of_expertise) < 1:
        raise AuthError("At least one area of expertise is required.", 400)

    valid_availability = {"Weekdays", "Weekends", "Evenings", "Flexible"}
    if data.availability not in valid_availability:
        raise AuthError(
            f"Invalid availability. Must be one of: {sorted(valid_availability)}"
        )

    return _stage_external(
        db, subtype="mentor",
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
        extra={
            "mentor_profession": data.profession,
            "mentor_expertise": ", ".join(data.areas_of_expertise),
            "mentor_experience_summary": data.experience_summary,
            "mentor_availability": data.availability,
        },
    )


def register_specialist(db: Session, data: SpecialistRegister) -> dict:
    _require_tos_privacy(data.tos_accepted, data.privacy_accepted)
    return _stage_external(
        db, subtype="specialist",
        first_name=data.first_name, last_name=data.last_name,
        email=str(data.email), phone=data.phone, password=data.password,
        tos_version=data.tos_version, privacy_version=data.privacy_version,
        extra={
            "expertise_field": data.field_of_expertise,
            "affiliation": data.affiliated_organization,
        },
    )


# ============================================================================
# LOGIN
# ============================================================================

def login_user(
    db: Session, data: UserLogin,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    request=None,
) -> tuple[User, str, dict]:
    user = db.query(User).filter(User.email == data.email.lower().strip()).first()
    if not user:
        pending = registration_cache.get_pending(str(data.email))
        if pending:
            log_auth_event(
                db, "login_pending_registration", email=str(data.email),
                ip_address=ip, user_agent=user_agent, success=False,
            )
            raise AuthError(
                "Please verify your email to continue. "
                "Check your inbox for the verification code.",
                403,
            )
        log_auth_event(
            db, "login_failed", email=data.email,
            ip_address=ip, user_agent=user_agent, success=False,
            event_data={"reason": "user_not_found"},
        )
        raise AuthError("Invalid email or password.", 401)

    admin = is_admin_user(db, user.id)
    lock_attempts = ADMIN_LOCK_AFTER_ATTEMPTS if admin else LOCK_AFTER_ATTEMPTS
    lock_minutes = ADMIN_LOCK_MINUTES if admin else LOCK_MINUTES

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds() // 60) + 1
        log_auth_event(
            db, "login_locked", user_id=user.id, email=user.email,
            ip_address=ip, user_agent=user_agent, success=False,
            event_data={"minutes_remaining": remaining},
        )
        raise AuthError(f"Account locked. Try again in {remaining} minutes.", 423)

    if captcha_module.captcha_required(user.failed_login_attempts):
        if not data.captcha_token:
            raise CaptchaRequired("CAPTCHA verification required.")
        try:
            import asyncio
            asyncio.run(captcha_module.verify_captcha(data.captcha_token, remote_ip=ip))
        except captcha_module.CaptchaError as e:
            raise AuthError(e.message, e.status_code)

    if not verify_password(data.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= lock_attempts:
            user.locked_until = now + timedelta(minutes=lock_minutes)
            user.failed_login_attempts = 0
            db.commit()
            log_auth_event(
                db, "login_locked", user_id=user.id, email=user.email,
                ip_address=ip, user_agent=user_agent, success=False,
                event_data={"reason": "too_many_failures", "admin": admin},
            )
            raise AuthError(
                f"Too many failed attempts. Account locked for {lock_minutes} minutes.",
                423,
            )
        db.commit()
        log_auth_event(
            db, "login_failed", user_id=user.id, email=user.email,
            ip_address=ip, user_agent=user_agent, success=False,
            event_data={"attempts": user.failed_login_attempts},
        )
        raise AuthError("Invalid email or password.", 401)

    user.failed_login_attempts = 0
    user.locked_until = None

    if user.account_status == "suspended":
        log_auth_event(
            db, "login_blocked", user_id=user.id, email=user.email,
            ip_address=ip, user_agent=user_agent, success=False,
            event_data={"status": "suspended"},
        )
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

    if admin and is_admin_2fa_required(db) and not user.two_factor_enabled:
        setup_token = create_admin_setup_token(user.id)
        log_auth_event(
            db, "login_admin_2fa_setup_required",
            user_id=user.id, email=user.email,
            ip_address=ip, user_agent=user_agent,
        )
        raise Admin2FASetupRequired(setup_token)

    if user.two_factor_enabled:
        from app.services.two_factor_service import issue_login_challenge
        issue_login_challenge(db, user, ip=ip, ua=user_agent)
        temp = create_2fa_pending_token(user.id)
        log_auth_event(
            db, "login_password_ok_2fa_pending",
            user_id=user.id, email=user.email,
            ip_address=ip, user_agent=user_agent,
            event_data={"method": user.two_factor_method or "totp"},
        )
        raise TwoFactorRequired(temp)

    expiry = ADMIN_SESSION_MINUTES if admin else USER_SESSION_MINUTES
    token, _ = create_session(
        db, user, ip_address=ip, user_agent=user_agent,
        expires_minutes=expiry,
    )

    log_auth_event(
        db, "login_success", user_id=user.id, email=user.email,
        ip_address=ip, user_agent=user_agent,
        event_data={"session_minutes": expiry, "admin": admin},
    )

    is_new_device = security_alert_service.detect_new_device(db, user, user_agent, ip)
    if is_new_device:
        security_alert_service.emit_new_device_alert(db, user, user_agent, ip)
    security_alert_service.remember_device(db, user, user_agent)

    hub_target = resolve_hub(db, user.id, user.user_type)
    extras = {
        "redirect_to": hub_target.redirect_to,
        "hub": hub_target.hub,
    }

    if request is not None:
        try:
            env_info = analyze_env(user.user_type, request)
            extras["environment"] = env_info.environment.value
            if env_info.warning:
                extras["environment_warning"] = env_info.warning
        except Exception:
            pass

    return user, token, extras


# ============================================================================
# APPROVAL WORKFLOW
# ============================================================================

def list_pending_approvals(db: Session, institution_id: str) -> list[User]:
    return (
        db.query(User)
        .filter(
            User.account_status == "pending_approval",
            User.institution_id == institution_id,
        )
        .order_by(User.created_at.asc())
        .all()
    )


def approve_user(
    db: Session, user_id: str, approver_id: str,
    approve: bool, reason: str | None = None,
) -> User:
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

        profile = db.query(ExternalProfile).filter(
            ExternalProfile.user_id == user.id,
        ).first()
        if profile:
            profile.verification_status = "approved"

        # If this is a lecturer, also mark the primary affiliation as verified.
        if user.user_type == "lecturer":
            from app.models.lecturer_affiliation import LecturerAffiliation
            affs = (
                db.query(LecturerAffiliation)
                .filter(
                    LecturerAffiliation.user_id == user.id,
                    LecturerAffiliation.verification_status == "pending",
                )
                .all()
            )
            for aff in affs:
                aff.verification_status = "verified"
                aff.approved_by = approver_id
                aff.approved_at = now

        log_auth_event(
            db, "account_approved", user_id=user.id, email=user.email,
            event_data={"approver": approver_id},
        )
    else:
        user.account_status = "rejected"
        user.rejected_by = approver_id
        user.rejected_at = now
        user.rejection_reason = reason or "Rejected by administrator"

        profile = db.query(ExternalProfile).filter(
            ExternalProfile.user_id == user.id,
        ).first()
        if profile:
            profile.verification_status = "rejected"
            profile.verification_notes = reason

        # Reject any pending lecturer affiliations too
        if user.user_type == "lecturer":
            from app.models.lecturer_affiliation import LecturerAffiliation
            affs = (
                db.query(LecturerAffiliation)
                .filter(
                    LecturerAffiliation.user_id == user.id,
                    LecturerAffiliation.verification_status == "pending",
                )
                .all()
            )
            for aff in affs:
                aff.verification_status = "rejected"
                aff.verification_notes = reason

        log_auth_event(
            db, "account_rejected", user_id=user.id, email=user.email,
            event_data={"approver": approver_id, "reason": reason},
        )

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