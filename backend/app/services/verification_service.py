"""
Email + phone verification and password reset services.
Uses real SMTP/SMS via app.core.notifications.
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
from app.models.auth_extension import (
    EmailVerification, PhoneVerification, PasswordReset, Session as SessionModel,
)
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
# EMAIL
# ============================================================================

def create_email_verification(db: Session, user: User, purpose: str = "registration") -> str:
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


def verify_email_otp(db: Session, email: str, otp: str, purpose: str = "registration") -> User:
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

    # Student + alumni: activate. Others: move to pending_approval.
    if user.user_type == "student" or (user.user_type == "external" and user.external_subtype == "alumni"):
        if user.account_status == "pending":
            user.account_status = "active"
    else:
        if user.account_status == "pending":
            user.account_status = "pending_approval"

    db.commit()
    db.refresh(user)

    log_auth_event(db, "email_verified", user_id=user.id, email=user.email)
    return user


# ============================================================================
# PHONE
# ============================================================================

def create_phone_verification(db: Session, user: User, phone: str | None = None,
                              purpose: str = "registration") -> str:
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

    send_sms(target, f"Your Smart Comrade verification code is {otp}. Expires in {PHONE_OTP_EXPIRY_MINUTES} min.")
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

def create_password_reset(db: Session, email: str, request_ip: str | None = None) -> str | None:
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

    log_auth_event(db, "password_reset_requested", user_id=user.id, email=user.email,
                   ip_address=request_ip)
    return token


def consume_password_reset(db: Session, token: str, new_password: str,
                           request_ip: str | None = None) -> User:
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

    log_auth_event(db, "password_reset_succeeded", user_id=user.id, email=user.email,
                   ip_address=request_ip)
    return user