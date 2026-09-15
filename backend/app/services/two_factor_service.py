"""
Two-factor authentication:
- TOTP (authenticator app) — uses user.two_factor_secret
- Email OTP — challenge sent via SMTP
- SMS OTP — challenge sent via SMS provider
- Backup codes — universal recovery
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.notifications import send_sms, send_email
from app.core.security import (
    generate_totp_secret, build_totp_uri, qr_code_data_uri,
    verify_totp, generate_backup_codes, hash_backup_code, verify_backup_code,
    generate_otp, hash_otp, verify_otp,
)
from app.models.user import User
from app.models.auth_extension import BackupCode
from app.models.two_factor import TwoFactorChallenge
from app.services.audit_service import log_auth_event

logger = logging.getLogger(__name__)


class TwoFactorError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


BACKUP_CODE_COUNT = 10
CHALLENGE_EXPIRY_MINUTES = 10
CHALLENGE_MAX_ATTEMPTS = 5
CHALLENGE_RESEND_WINDOW_MINUTES = 2


# ============================================================================
# TOTP — Setup
# ============================================================================

def start_setup_totp(db: Session, user: User) -> dict:
    secret = generate_totp_secret()
    uri = build_totp_uri(secret, user.email)
    qr = qr_code_data_uri(uri)
    codes = generate_backup_codes(BACKUP_CODE_COUNT)

    user.two_factor_secret = secret
    user.two_factor_method = "totp"
    user.two_factor_enabled = False

    db.query(BackupCode).filter(BackupCode.user_id == user.id).delete()
    for code in codes:
        db.add(BackupCode(user_id=user.id, code_hash=hash_backup_code(code)))
    db.commit()

    return {
        "secret": secret,
        "provisioning_uri": uri,
        "qr_code_data_uri": qr,
        "backup_codes": codes,
        "message": "Scan or enter the secret in your authenticator, then POST /auth/2fa/verify-setup.",
    }


def verify_setup_totp(db: Session, user: User, code: str) -> None:
    if not user.two_factor_secret:
        raise TwoFactorError("Call /auth/2fa/setup first.", 400)
    if not verify_totp(user.two_factor_secret, code):
        raise TwoFactorError("Invalid code. Try the next one from your authenticator.", 400)
    user.two_factor_enabled = True
    user.two_factor_method = "totp"
    db.commit()
    log_auth_event(db, "2fa_enabled", user_id=user.id, email=user.email,
                   event_data={"method": "totp"})


# ============================================================================
# Email / SMS — Enable
# ============================================================================

def enable_email_2fa(db: Session, user: User) -> dict:
    if not user.email_verified:
        raise TwoFactorError("Verify your email before enabling email 2FA.", 409)
    user.two_factor_enabled = True
    user.two_factor_method = "email"
    user.two_factor_secret = None
    db.commit()
    log_auth_event(db, "2fa_enabled", user_id=user.id, email=user.email,
                   event_data={"method": "email"})
    return {"message": "Email 2FA enabled.", "method": "email"}


def enable_sms_2fa(db: Session, user: User) -> dict:
    if not user.phone_verified or not user.phone:
        raise TwoFactorError("Verify your phone before enabling SMS 2FA.", 409)
    user.two_factor_enabled = True
    user.two_factor_method = "sms"
    user.two_factor_secret = None
    db.commit()
    log_auth_event(db, "2fa_enabled", user_id=user.id, email=user.email,
                   event_data={"method": "sms"})
    return {"message": "SMS 2FA enabled.", "method": "sms"}


# ============================================================================
# Challenge issue + verify (email / sms)
# ============================================================================

def _issue_challenge(db: Session, user: User, method: str,
                     ip: str | None = None, ua: str | None = None) -> None:
    destination = user.email if method == "email" else (user.phone or "")
    if not destination:
        raise TwoFactorError(f"No {method} destination on file.", 400)

    window_start = datetime.now(timezone.utc) - timedelta(minutes=CHALLENGE_RESEND_WINDOW_MINUTES)
    recent = (
        db.query(TwoFactorChallenge)
        .filter(
            TwoFactorChallenge.user_id == user.id,
            TwoFactorChallenge.method == method,
            TwoFactorChallenge.created_at >= window_start,
            TwoFactorChallenge.is_used.is_(False),
        )
        .first()
    )
    if recent:
        raise TwoFactorError(
            f"A code was already sent. Please wait {CHALLENGE_RESEND_WINDOW_MINUTES} minutes.",
            429,
        )

    otp = generate_otp()
    db.add(TwoFactorChallenge(
        user_id=user.id,
        method=method,
        destination=destination,
        otp_hash=hash_otp(otp),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=CHALLENGE_EXPIRY_MINUTES),
        ip_address=ip,
        user_agent=ua,
    ))
    db.commit()

    if method == "email":
        subject = "Your Smart Comrade login code"
        text = f"Your 2FA code is: {otp}\n\nExpires in {CHALLENGE_EXPIRY_MINUTES} minutes."
        html = f"""
        <html><body style="font-family: Arial, sans-serif;">
          <div style="max-width: 480px; margin: 0 auto; padding: 24px;">
            <h2 style="color:#00d4c8;">Smart Comrade 2FA</h2>
            <p>Your one-time login code is:</p>
            <div style="font-size: 32px; font-weight: 700; letter-spacing: 4px;
                        background: #f3f4f6; padding: 16px; text-align: center;
                        border-radius: 8px; margin: 16px 0;">
              {otp}
            </div>
            <p style="color:#6b7280;font-size:13px;">
              Expires in {CHALLENGE_EXPIRY_MINUTES} minutes. If you didn't request this, ignore this email.
            </p>
          </div>
        </body></html>
        """
        send_email(destination, subject, html, text)
    else:
        send_sms(destination,
                 f"Your Smart Comrade login code is {otp}. Expires in {CHALLENGE_EXPIRY_MINUTES} min.")


def issue_login_challenge(db: Session, user: User,
                          ip: str | None = None, ua: str | None = None) -> None:
    if not user.two_factor_enabled:
        return
    method = user.two_factor_method or "totp"
    if method in ("email", "sms"):
        try:
            _issue_challenge(db, user, method, ip=ip, ua=ua)
        except TwoFactorError as e:
            logger.warning(f"Could not issue 2FA challenge: {e.message}")


def resend_login_challenge(db: Session, user: User,
                           ip: str | None = None, ua: str | None = None) -> dict:
    if not user.two_factor_enabled:
        raise TwoFactorError("2FA is not enabled.", 400)
    method = user.two_factor_method or "totp"
    if method not in ("email", "sms"):
        raise TwoFactorError("This 2FA method does not support resend.", 400)
    _issue_challenge(db, user, method, ip=ip, ua=ua)
    return {"message": f"New {method} code sent.", "method": method}


def _verify_challenge(db: Session, user: User, code: str, method: str) -> bool:
    record = (
        db.query(TwoFactorChallenge)
        .filter(
            TwoFactorChallenge.user_id == user.id,
            TwoFactorChallenge.method == method,
            TwoFactorChallenge.is_used.is_(False),
        )
        .order_by(TwoFactorChallenge.created_at.desc())
        .first()
    )
    if not record:
        return False
    if record.expires_at < datetime.now(timezone.utc):
        return False
    if record.attempts >= record.max_attempts:
        return False
    if not verify_otp(code, record.otp_hash):
        record.attempts += 1
        db.commit()
        return False
    record.is_used = True
    record.consumed_at = datetime.now(timezone.utc)
    db.commit()
    return True


# ============================================================================
# Unified verify-login
# ============================================================================

def verify_login_challenge(db: Session, user: User, code: str) -> bool:
    if not user.two_factor_enabled:
        raise TwoFactorError("2FA is not enabled for this account.", 400)

    code = code.strip().upper()
    method = user.two_factor_method or "totp"

    # Backup codes (length 8-16)
    if 8 <= len(code) <= 16:
        candidates = db.query(BackupCode).filter(
            BackupCode.user_id == user.id,
            BackupCode.is_used.is_(False),
        ).all()
        for bc in candidates:
            if verify_backup_code(code, bc.code_hash):
                bc.is_used = True
                bc.used_at = datetime.now(timezone.utc)
                db.commit()
                log_auth_event(db, "2fa_success", user_id=user.id, email=user.email,
                               event_data={"method": "backup_code"})
                return True

    # Method-specific (6 digits)
    if len(code) == 6 and code.isdigit():
        ok = False
        if method == "totp" and user.two_factor_secret:
            ok = verify_totp(user.two_factor_secret, code)
        elif method == "email":
            ok = _verify_challenge(db, user, code, "email")
        elif method == "sms":
            ok = _verify_challenge(db, user, code, "sms")

        if ok:
            log_auth_event(db, "2fa_success", user_id=user.id, email=user.email,
                           event_data={"method": method})
            return True

    log_auth_event(db, "2fa_failed", user_id=user.id, email=user.email,
                   success=False, event_data={"method": method})
    return False


# ============================================================================
# Disable
# ============================================================================

def disable(db: Session, user: User, password: str, code: str) -> None:
    from app.core.security import verify_password
    if not verify_password(password, user.password_hash):
        raise TwoFactorError("Password is incorrect.", 400)

    old_method = user.two_factor_method
    if not verify_login_challenge(db, user, code):
        raise TwoFactorError("Invalid 2FA code.", 400)

    user.two_factor_enabled = False
    user.two_factor_secret = None
    user.two_factor_method = None
    db.query(BackupCode).filter(BackupCode.user_id == user.id).delete()
    db.commit()

    log_auth_event(db, "2fa_disabled", user_id=user.id, email=user.email,
                   event_data={"previous_method": old_method})


def backup_codes_remaining(db: Session, user: User) -> int:
    return (
        db.query(BackupCode)
        .filter(BackupCode.user_id == user.id, BackupCode.is_used.is_(False))
        .count()
    )