"""
Password hashing, JWT, OTP, TOTP, step-up tokens, admin setup tokens.
"""
import base64
import hashlib
import io
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import pyotp
import qrcode
from jose import JWTError, jwt

from app.core.config import settings

_BCRYPT_MAX_BYTES = 72


# ============================================================================
# Passwords
# ============================================================================

def _normalize_password(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(_normalize_password(password), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_normalize_password(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ============================================================================
# JWT - Access tokens
# ============================================================================

def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    if expires_minutes is None:
        expires_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


# Backwards-compat alias (existing imports use this name)
decode_access_token = decode_token


# ============================================================================
# JWT - Purpose-scoped tokens
# ============================================================================

def _create_scoped_token(subject: str, purpose: str, expires_minutes: int,
                         extra: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "purpose": purpose,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_scoped_token(token: str, purpose: str) -> dict | None:
    payload = decode_token(token)
    if not payload or payload.get("purpose") != purpose:
        return None
    return payload


# 2FA pending (issued after correct password, before 2FA verification)
def create_2fa_pending_token(subject: str, expires_minutes: int = 5) -> str:
    return _create_scoped_token(subject, "2fa_pending", expires_minutes)


def decode_2fa_pending_token(token: str) -> str | None:
    payload = _decode_scoped_token(token, "2fa_pending")
    return payload.get("sub") if payload else None


# Admin 2FA setup (issued when an admin tries to log in without 2FA enabled)
def create_admin_setup_token(subject: str, expires_minutes: int = 15) -> str:
    return _create_scoped_token(subject, "admin_2fa_setup", expires_minutes)


def decode_admin_setup_token(token: str) -> str | None:
    payload = _decode_scoped_token(token, "admin_2fa_setup")
    return payload.get("sub") if payload else None


# ============================================================================
# Step-up (short-lived proof of recent re-authentication)
#
# Context binding: tokens are bound to the IP address and User-Agent of the
# request that issued them. A stolen token cannot be used from a different
# context. Tokens without context claims are accepted for backward compat.
# ============================================================================

_CONTEXT_HASH_LENGTH = 16  # hex chars; 64 bits is ample for a 10-min token


def hash_context(value: str | None) -> str | None:
    """One-way fingerprint of a context value (IP or User-Agent).

    Returns None if the input is None, so callers can skip binding a
    context dimension that is genuinely absent.
    """
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_CONTEXT_HASH_LENGTH]


def create_step_up_token(
    user_id: str,
    scope: str,
    expires_minutes: int = 10,
    ip_hash: str | None = None,
    ua_hash: str | None = None,
) -> str:
    extra: dict[str, Any] = {"scope": scope}
    if ip_hash is not None:
        extra["ip_hash"] = ip_hash
    if ua_hash is not None:
        extra["ua_hash"] = ua_hash
    return _create_scoped_token(user_id, "step_up", expires_minutes, extra=extra)


def decode_step_up_token(token: str) -> dict | None:
    return _decode_scoped_token(token, "step_up")


# ============================================================================
# OTP / Reset tokens
# ============================================================================

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    return bcrypt.hashpw(otp.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_otp(plain_otp: str, hashed_otp: str) -> bool:
    try:
        return bcrypt.checkpw(plain_otp.encode("utf-8"), hashed_otp.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_reset_token() -> str:
    return secrets.token_urlsafe(48)


# ============================================================================
# TOTP (2FA)
# ============================================================================

def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_totp_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name=settings.APP_NAME,
    )


def qr_code_data_uri(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=valid_window)
    except Exception:
        return False


def generate_backup_codes(count: int = 10) -> list[str]:
    return [secrets.token_hex(5).upper() for _ in range(count)]


def hash_backup_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_backup_code(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.upper().encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False