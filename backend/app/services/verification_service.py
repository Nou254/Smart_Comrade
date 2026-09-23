"""
Email + phone verification and password reset services.

Two flows:
  1. Registration -> data lives in cache, promoted to `users` on verify
  2. Other purposes -> existing users, DB-backed verification

Bootstrap admin elevation:
  Emails listed in BOOTSTRAP_ADMIN_EMAILS are elevated to Super Admin
  automatically when they complete email verification during normal
  registration. The elevation is one-time (sticky flag).

Lecturer affiliations:
  On promotion of a lecturer, a LecturerAffiliation row is created from the
  referee data captured in the cache record.

Communication module:
  Username is assigned on user promotion (see _promote_pending_to_user).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.notifications import (
    send_otp_email, send_sms, send_password_reset_email,
)
from app.core.security import (
    generate_otp, hash_otp, verify_otp,
    generate_reset_token, hash_token, hash_password,
)
from app.models.user import User
from app.models.external_profile import ExternalProfile
from app.models.role import Role, UserRole
from app.models.lecturer_affiliation import LecturerAffiliation
from app.models.auth_extension import (
    EmailVerification, PhoneVerification, PasswordReset, Session as SessionModel,
)
from app.services import registration_cache
from app.services.audit_service import log_auth_event

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 15
PHONE_OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_WINDOW_MINUTES = 10
RESET_TOKEN_EXPIRY_MINUTES = 60


class VerificationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ============================================================================
# Bootstrap admin elevation
# ============================================================================

def _try_bootstrap_admin_elevation(db: Session, user: User) -> bool:
    """
    If the user's email is in the bootstrap allowlist and they haven't
    already been elevated, grant Super Admin and return True.
    Otherwise return False.
    """
    allowlist = settings.bootstrap_admin_email_list
    if not allowlist:
        return False

    email = (user.email or "").lower().strip()
    if email not in allowlist:
        return False

    if user.is_bootstrap_admin:
        return False

    super_role = db.query(Role).filter(Role.code == "super_admin").first()
    if not super_role:
        logger.warning(
            "Bootstrap admin elevation skipped for %s: super_admin role missing.",
            email,
        )
        return False

    now = datetime.now(timezone.utc)
    user.user_type = "admin"
    user.is_bootstrap_admin = True

    db.add(UserRole(
        user_id=user.id,
        role_id=super_role.id,
        jurisdiction_type="platform",
        jurisdiction_id=None,
        status="active",
        start_date=now,
        granted_at=now,
        notes="Bootstrap admin elevation via BOOTSTRAP_ADMIN_EMAILS allowlist",
    ))

    log_auth_event(
        db,
        "bootstrap_admin_elevated",
        user_id=user.id,
        email=user.email,
        event_data={"source": "allowlist", "role": "super_admin"},
    )
    logger.info("Bootstrap admin elevated: %s", email)
    return True


# ============================================================================
# REGISTRATION - cache-based
# ============================================================================

def resend_registration_otp(email: str) -> None:
    """Generate a fresh OTP for a pending registration in cache."""
    record = registration_cache.get_pending(email)
    if not record:
        raise VerificationError("No pending registration found for this email.", 404)

    if record.get("otp_resends", 0) >= 3:
        raise VerificationError(
            "Too many OTP resends. Please wait or restart registration.", 429
        )

    otp = generate_otp()
    otp_hash_val = hash_otp(otp)
    otp_expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

    registration_cache.update_pending(
        email,
        otp_hash=otp_hash_val,
        otp_expires_at=otp_expires.isoformat(),
        otp_attempts=0,
        otp_resends=record.get("otp_resends", 0) + 1,
    )

    send_otp_email(email, otp, purpose="registration")


def verify_pending_registration(db: Session, email: str, otp: str) -> User:
    """
    Verify OTP against cache; on success, promote the pending record into
    the `users` table and clear the cache entry.
    """
    record = registration_cache.get_pending(email)
    if not record:
        raise VerificationError(
            "No pending registration found for this email. "
            "It may have expired - please register again.",
            404,
        )

    otp_expires_at = datetime.fromisoformat(record["otp_expires_at"])
    if otp_expires_at < datetime.now(timezone.utc):
        raise VerificationError("OTP has expired. Please request a new one.", 410)

    if record.get("otp_attempts", 0) >= OTP_MAX_ATTEMPTS:
        raise VerificationError("Too many failed attempts. Request a new OTP.", 429)

    if not verify_otp(otp, record["otp_hash"]):
        registration_cache.update_pending(
            email, otp_attempts=record.get("otp_attempts", 0) + 1,
        )
        remaining = OTP_MAX_ATTEMPTS - (record.get("otp_attempts", 0) + 1)
        raise VerificationError(
            f"Invalid OTP. {remaining} attempts remaining.", 400
        )

    # Uniqueness re-check (race protection)
    if db.query(User).filter(User.email == record["email"]).first():
        registration_cache.delete_pending(email)
        raise VerificationError("This email is already registered.", 409)
    if record.get("phone") and db.query(User).filter(User.phone == record["phone"]).first():
        registration_cache.delete_pending(email)
        raise VerificationError("This phone number is already registered.", 409)

    # Promotion decision
    user_type = record["user_type"]
    external_subtype = record.get("external_subtype")
    is_auto_active = (
        user_type == "student"
        or (user_type == "external" and external_subtype == "alumni")
    )

    # --- Communication module: assign username at creation ---
    from app.services.username_service import generate_unique_username
    username = generate_unique_username(
        db, first_name=record["first_name"], last_name=record["last_name"],
    )

    user = User(
        first_name=record["first_name"],
        last_name=record["last_name"],
        email=record["email"],
        phone=record.get("phone"),
        username=username,
        password_hash=record["password_hash"],
        user_type=user_type,
        external_subtype=external_subtype,
        institution_id=record.get("institution_id"),
        institutional_email=record.get("institutional_email"),
        department=record.get("department"),
        title=record.get("title"),
        domain_verified=record.get("domain_verified", False),
        account_status="active" if is_auto_active else "pending_approval",
        email_verified=True,
        phone_verified=False,
    )

    if record.get("tos_version"):
        user.tos_accepted_at = datetime.fromisoformat(record["tos_accepted_at"])
        user.tos_version = record["tos_version"]
    if record.get("privacy_version"):
        user.privacy_accepted_at = datetime.fromisoformat(record["privacy_accepted_at"])
        user.privacy_version = record["privacy_version"]

    db.add(user)
    db.flush()

    # --- Bootstrap admin elevation ---
    is_bootstrap_elevated = _try_bootstrap_admin_elevation(db, user)

    # --- Base role assignment (skipped for bootstrap admins) ---
    if not is_bootstrap_elevated:
        role_code_map = {
            "student": "student",
            "lecturer": "lecturer",
            "external": "external_user",
        }
        base_role_code = role_code_map.get(user.user_type)
        if base_role_code:
            role = db.query(Role).filter(Role.code == base_role_code).first()
            if role:
                role_status = "active" if is_auto_active else "pending"
                db.add(UserRole(
                    user_id=user.id, role_id=role.id,
                    jurisdiction_type="self", jurisdiction_id=None,
                    status=role_status,
                    start_date=datetime.now(timezone.utc),
                    notes=f"Auto-assigned on {user.user_type} registration",
                ))

    # --- External profile (only for external users) ---
    if user.user_type == "external" and external_subtype:
        profile = ExternalProfile(
            user_id=user.id,
            external_subtype=external_subtype,
            verification_status="approved" if external_subtype == "alumni" else "pending",
        )
        extra = record.get("extra") or {}
        for k, v in extra.items():
            if hasattr(profile, k):
                setattr(profile, k, v)
        db.add(profile)

    # --- Lecturer affiliation (only for lecturers) ---
    if user.user_type == "lecturer":
        extra = record.get("extra") or {}
        if extra.get("referee_name") and user.institution_id:
            db.add(LecturerAffiliation(
                user_id=user.id,
                institution_id=user.institution_id,
                institutional_email=user.institutional_email,
                department=user.department,
                title=user.title or "Lecturer",
                referee_name=extra["referee_name"],
                referee_phone=extra["referee_phone"],
                referee_relationship=extra["referee_relationship"],
                verification_status="pending",
                domain_verified=user.domain_verified,
            ))

    db.commit()
    db.refresh(user)

    registration_cache.delete_pending(email)
    log_auth_event(db, "email_verified_via_cache", user_id=user.id, email=user.email)
    return user


# ============================================================================
# DB-BACKED VERIFICATION (email_change / password_reset_confirm on existing users)
# ============================================================================

def create_email_verification(db: Session, user: User, purpose: str = "registration") -> str:
    """Used for email_change and password_reset_confirm on existing users."""
    window_start = datetime.now(timezone.utc) - timedelta(minutes=OTP_RESEND_WINDOW_MINUTES)
    recent = (
        db.query(EmailVerification)
        .filter(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == purpose,
            EmailVerification.created_at >= window_start,
            EmailVerification.is_used.is_(False),
        )
        .first()
    )
    if recent:
        raise VerificationError(
            f"An OTP was already sent. Please wait {OTP_RESEND_WINDOW_MINUTES} minutes.",
            429,
        )

    otp = generate_otp()
    record = EmailVerification(
        user_id=user.id,
        email=user.email,
        otp_hash=hash_otp(otp),
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES),
    )
    db.add(record)
    db.commit()

    send_otp_email(user.email, otp, purpose=purpose)
    return otp


def verify_email_otp(
    db: Session, email: str, otp: str, purpose: str = "registration",
) -> User:
    """DB-backed verification for email_change / password_reset_confirm."""
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user:
        raise VerificationError("No account found with this email.", 404)

    record = (
        db.query(EmailVerification)
        .filter(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == purpose,
            EmailVerification.is_used.is_(False),
        )
        .order_by(EmailVerification.created_at.desc())
        .first()
    )
    if not record:
        raise VerificationError("No pending verification found.", 404)

    if record.expires_at < datetime.now(timezone.utc):
        raise VerificationError("OTP has expired. Please request a new one.", 410)

    if record.attempts >= record.max_attempts:
        raise VerificationError("Too many failed attempts. Request a new OTP.", 429)

    if not verify_otp(otp, record.otp_hash):
        record.attempts += 1
        db.commit()
        raise VerificationError(
            f"Invalid OTP. {record.max_attempts - record.attempts} attempts remaining.", 400
        )

    now = datetime.now(timezone.utc)
    record.is_used = True
    record.consumed_at = now
    user.email_verified = True
    db.commit()
    db.refresh(user)

    log_auth_event(db, f"email_verified_{purpose}", user_id=user.id, email=user.email)
    return user


# ============================================================================
# PHONE
# ============================================================================

def create_phone_verification(
    db: Session, user: User, phone: str | None = None,
    purpose: str = "registration",
) -> str:
    target = (phone or user.phone or "").strip()
    if not target:
        raise VerificationError("No phone number on file. Provide one to verify.", 400)

    window_start = datetime.now(timezone.utc) - timedelta(minutes=OTP_RESEND_WINDOW_MINUTES)
    recent = (
        db.query(PhoneVerification)
        .filter(
            PhoneVerification.user_id == user.id,
            PhoneVerification.purpose == purpose,
            PhoneVerification.created_at >= window_start,
            PhoneVerification.is_used.is_(False),
        )
        .first()
    )
    if recent:
        raise VerificationError(
            f"An OTP was already sent. Please wait {OTP_RESEND_WINDOW_MINUTES} minutes.", 429
        )

    otp = generate_otp()
    record = PhoneVerification(
        user_id=user.id,
        phone=target,
        otp_hash=hash_otp(otp),
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=PHONE_OTP_EXPIRY_MINUTES),
    )
    db.add(record)
    db.commit()

    send_sms(
        target,
        f"Your Smart Comrade verification code is {otp}. Expires in {PHONE_OTP_EXPIRY_MINUTES} min.",
    )
    return otp


def verify_phone_otp(db: Session, user: User, otp: str, purpose: str = "registration") -> User:
    record = (
        db.query(PhoneVerification)
        .filter(
            PhoneVerification.user_id == user.id,
            PhoneVerification.purpose == purpose,
            PhoneVerification.is_used.is_(False),
        )
        .order_by(PhoneVerification.created_at.desc())
        .first()
    )
    if not record:
        raise VerificationError("No pending phone verification found.", 404)

    if record.expires_at < datetime.now(timezone.utc):
        raise VerificationError("OTP has expired. Please request a new one.", 410)

    if record.attempts >= record.max_attempts:
        raise VerificationError("Too many failed attempts. Request a new OTP.", 429)

    if not verify_otp(otp, record.otp_hash):
        record.attempts += 1
        db.commit()
        raise VerificationError(
            f"Invalid OTP. {record.max_attempts - record.attempts} attempts remaining.", 400
        )

    now = datetime.now(timezone.utc)
    record.is_used = True
    record.consumed_at = now
    user.phone_verified = True
    user.phone = record.phone
    db.commit()
    db.refresh(user)

    log_auth_event(db, "phone_verified", user_id=user.id, email=user.email)
    return user


# ============================================================================
# PASSWORD RESET
# ============================================================================

def create_password_reset(
    db: Session, email: str, request_ip: str | None = None,
) -> str | None:
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user:
        return None

    token = generate_reset_token()
    db.add(PasswordReset(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES),
        requested_ip=request_ip,
    ))
    db.commit()

    reset_url = f"https://app.smartcomrade.com/reset?token={token}"
    send_password_reset_email(user.email, reset_url)

    log_auth_event(
        db, "password_reset_requested", user_id=user.id, email=user.email,
        ip_address=request_ip,
    )
    return token


def consume_password_reset(
    db: Session, token: str, new_password: str,
    request_ip: str | None = None,
) -> User:
    th = hash_token(token)
    record = db.query(PasswordReset).filter(PasswordReset.token_hash == th).first()
    if not record:
        raise VerificationError("Invalid or expired reset token.", 400)
    if record.is_used:
        raise VerificationError("This reset token has already been used.", 400)
    if record.expires_at < datetime.now(timezone.utc):
        raise VerificationError("Reset token has expired.", 410)

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise VerificationError("User no longer exists.", 404)

    user.password_hash = hash_password(new_password)
    record.is_used = True
    record.used_at = datetime.now(timezone.utc)
    record.used_ip = request_ip

    db.query(SessionModel).filter(
        SessionModel.user_id == user.id,
        SessionModel.is_revoked.is_(False),
    ).update({"is_revoked": True, "revoked_at": datetime.now(timezone.utc)})

    db.commit()
    db.refresh(user)

    log_auth_event(
        db, "password_reset_succeeded", user_id=user.id, email=user.email,
        ip_address=request_ip,
    )
    return user