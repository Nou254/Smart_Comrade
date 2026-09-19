"""
Break-glass service.

Emergency account + Shamir 2-of-2 unlock.

For 2-of-2, Shamir's Secret Sharing reduces mathematically to XOR:
    share_a = random(32)
    share_b = token XOR share_a
    token   = share_a XOR share_b

Neither share alone reveals anything about the token (indistinguishable
from random). Both shares are required to reconstruct.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.break_glass import BreakGlassConfig
from app.models.user import User
from app.models.role import Role, UserRole
from app.models.auth_extension import Session as SessionModel
from app.core.security import create_access_token
from app.services.audit_service import log_auth_event
from app.services.session_service import (
    _count_active_sessions, _evict_oldest_session,
)

logger = logging.getLogger(__name__)

EMERGENCY_EMAIL = "emergency@smartcomrade.com"
TOKEN_BYTES = 32
BREAK_GLASS_SESSION_MINUTES = 30
_UNLOCK_ATTEMPTS: dict[str, list[datetime]] = {}
UNLOCK_RATE_LIMIT_PER_HOUR = 3


class BreakGlassError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ============================================================================
# Shared helpers
# ============================================================================

def _hash_token(hex_token: str) -> str:
    return hashlib.sha256(hex_token.encode("utf-8")).hexdigest()


def _get_config(db: Session) -> BreakGlassConfig | None:
    return db.query(BreakGlassConfig).order_by(BreakGlassConfig.created_at.desc()).first()


def _ensure_emergency_account(db: Session) -> User:
    """Return the singleton emergency account, creating if missing."""
    user = db.query(User).filter(User.email == EMERGENCY_EMAIL).first()
    if user:
        return user
    user = User(
        first_name="Emergency",
        last_name="Access",
        email=EMERGENCY_EMAIL,
        phone=None,
        password_hash=hash_password(secrets.token_urlsafe(48)),  # never used
        user_type="admin",
        account_status="active",
        email_verified=True,
        phone_verified=False,
        is_emergency_account=True,
    )
    db.add(user)
    db.flush()

    # Grant super_admin at platform scope
    role = db.query(Role).filter(Role.code == "super_admin").first()
    if role:
        now = datetime.now(timezone.utc)
        db.add(UserRole(
            user_id=user.id,
            role_id=role.id,
            jurisdiction_type="platform",
            jurisdiction_id=None,
            status="active",
            start_date=now,
            granted_at=now,
            notes="Emergency account (break-glass)",
        ))
    db.commit()
    db.refresh(user)
    return user


# ============================================================================
# Setup / Regenerate
# ============================================================================

def setup(db: Session, actor: User) -> dict:
    """
    One-time setup. Generates the unlock token, splits it, stores only the
    hash, and returns the two shares. The shares are NEVER stored.
    """
    existing = _get_config(db)
    if existing:
        raise BreakGlassError(
            "Break-glass is already configured. Use /regenerate to rotate.",
            409,
        )

    _ensure_emergency_account(db)

    token = secrets.token_bytes(TOKEN_BYTES)
    share_a = secrets.token_bytes(TOKEN_BYTES)
    share_b = bytes(a ^ b for a, b in zip(token, share_a))

    import base64
    cfg = BreakGlassConfig(
        unlock_token_hash=_hash_token(token.hex()),
        created_by_user_id=actor.id,
    )
    db.add(cfg)
    db.commit()

    log_auth_event(
        db, "break_glass_configured",
        user_id=actor.id, email=actor.email,
        event_data={"created_by": actor.id},
    )

    return {
        "share_a": base64.b64encode(share_a).decode("ascii"),
        "share_b": base64.b64encode(share_b).decode("ascii"),
        "message": (
            "Save each share separately. Neither share alone can unlock. "
            "Both must be presented together to break glass."
        ),
    }


def regenerate(db: Session, actor: User) -> dict:
    """Rotate the unlock token and produce a new pair of shares."""
    cfg = _get_config(db)
    if not cfg:
        raise BreakGlassError("Break-glass is not configured yet.", 404)

    token = secrets.token_bytes(TOKEN_BYTES)
    share_a = secrets.token_bytes(TOKEN_BYTES)
    share_b = bytes(a ^ b for a, b in zip(token, share_a))

    import base64
    cfg.unlock_token_hash = _hash_token(token.hex())
    cfg.created_by_user_id = actor.id
    db.commit()

    log_auth_event(
        db, "break_glass_shares_regenerated",
        user_id=actor.id, email=actor.email,
    )

    return {
        "share_a": base64.b64encode(share_a).decode("ascii"),
        "share_b": base64.b64encode(share_b).decode("ascii"),
        "message": "Old shares are now invalid. Save the new pair separately.",
    }


# ============================================================================
# Status
# ============================================================================

def status(db: Session) -> dict:
    cfg = _get_config(db)
    if not cfg:
        return {"configured": False, "use_count": 0, "last_used_at": None}
    return {
        "configured": True,
        "use_count": cfg.use_count,
        "last_used_at": cfg.last_used_at.isoformat() if cfg.last_used_at else None,
        "created_at": cfg.created_at.isoformat(),
    }


# ============================================================================
# Unlock
# ============================================================================

def _rate_limit_ok(ip: str) -> bool:
    now = datetime.now(timezone.utc)
    window = now - timedelta(hours=1)
    attempts = [t for t in _UNLOCK_ATTEMPTS.get(ip, []) if t > window]
    _UNLOCK_ATTEMPTS[ip] = attempts
    return len(attempts) < UNLOCK_RATE_LIMIT_PER_HOUR


def _record_attempt(ip: str) -> None:
    _UNLOCK_ATTEMPTS.setdefault(ip, []).append(datetime.now(timezone.utc))


def unlock(db: Session, share_a_b64: str, share_b_b64: str, reason: str,
           ip: str | None, ua: str | None) -> dict:
    import base64

    if ip and not _rate_limit_ok(ip):
        raise BreakGlassError(
            f"Too many break-glass attempts from this IP. Try again later.", 429,
        )
    if ip:
        _record_attempt(ip)

    cfg = _get_config(db)
    if not cfg:
        raise BreakGlassError("Break-glass is not configured.", 404)

    try:
        share_a = base64.b64decode(share_a_b64)
        share_b = base64.b64decode(share_b_b64)
    except Exception:
        raise BreakGlassError("Invalid share encoding.", 400)

    if len(share_a) != TOKEN_BYTES or len(share_b) != TOKEN_BYTES:
        raise BreakGlassError("Shares must be 32 bytes each.", 400)

    token = bytes(a ^ b for a, b in zip(share_a, share_b))
    if _hash_token(token.hex()) != cfg.unlock_token_hash:
        log_auth_event(
            db, "break_glass_failed",
            event_data={"reason": "hash_mismatch"},
            ip_address=ip, user_agent=ua, success=False,
        )
        raise BreakGlassError("Invalid shares.", 401)

    emergency = _ensure_emergency_account(db)

    # Revoke any prior break-glass session before issuing a new one
    db.query(SessionModel).filter(
        SessionModel.user_id == emergency.id,
        SessionModel.is_break_glass.is_(True),
        SessionModel.is_revoked.is_(False),
    ).update({"is_revoked": True, "revoked_at": datetime.now(timezone.utc)})

    # Enforce concurrent session limit (regular path)
    if _count_active_sessions(db, emergency.id) >= 5:
        _evict_oldest_session(db, emergency.id)

    token_str = create_access_token(
        subject=emergency.id, expires_minutes=BREAK_GLASS_SESSION_MINUTES,
    )
    now = datetime.now(timezone.utc)
    session = SessionModel(
        user_id=emergency.id,
        token_hash=hashlib.sha256(token_str.encode("utf-8")).hexdigest(),
        ip_address=ip,
        user_agent=ua,
        device_label="Emergency break-glass session",
        expires_at=now + timedelta(minutes=BREAK_GLASS_SESSION_MINUTES),
        last_seen_at=now,
        is_break_glass=True,
    )
    db.add(session)

    cfg.last_used_at = now
    cfg.use_count = (cfg.use_count or 0) + 1
    db.commit()

    log_auth_event(
        db, "break_glass_unlocked",
        user_id=emergency.id, email=emergency.email,
        event_data={"reason": reason, "use_count": cfg.use_count},
        ip_address=ip, user_agent=ua,
    )

    return {
        "access_token": token_str,
        "token_type": "bearer",
        "expires_in_minutes": BREAK_GLASS_SESSION_MINUTES,
        "message": "Break-glass session active. Every action is audited.",
    }


# ============================================================================
# Revoke active break-glass session
# ============================================================================

def revoke_active_session(db: Session, actor: User) -> dict:
    count = (
        db.query(SessionModel)
        .filter(
            SessionModel.is_break_glass.is_(True),
            SessionModel.is_revoked.is_(False),
        )
        .update({"is_revoked": True, "revoked_at": datetime.now(timezone.utc)})
    )
    db.commit()
    log_auth_event(
        db, "break_glass_session_revoked",
        user_id=actor.id, email=actor.email,
        event_data={"revoked_count": count},
    )
    return {"revoked_count": count}