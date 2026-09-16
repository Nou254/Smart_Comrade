"""
Session management: create on login, revoke on logout, list active sessions.
Adds device metadata, concurrent session limit, and last-seen tracking.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from app.core.security import create_access_token, hash_token
from app.core.config import settings
from app.core.user_agent_parser import parse as parse_ua
from app.models.user import User
from app.models.auth_extension import Session as SessionModel


DEFAULT_SESSION_MINUTES = 1440   # 24 hours (regular users)
ADMIN_SESSION_MINUTES = 720      # 12 hours (admins)
MAX_CONCURRENT_SESSIONS = 5      # per spec §11.2


class SessionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _count_active_sessions(db: DBSession, user_id: str) -> int:
    now = datetime.now(timezone.utc)
    return (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user_id,
            SessionModel.is_revoked.is_(False),
            SessionModel.expires_at > now,
        )
        .count()
    )


def _evict_oldest_session(db: DBSession, user_id: str) -> None:
    oldest = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user_id,
            SessionModel.is_revoked.is_(False),
        )
        .order_by(SessionModel.created_at.asc())
        .first()
    )
    if oldest:
        oldest.is_revoked = True
        oldest.revoked_at = datetime.now(timezone.utc)


def create_session(
    db: DBSession,
    user: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
    device_label: str | None = None,
    expires_minutes: int | None = None,
) -> tuple[str, SessionModel]:
    """
    Create a JWT + session record with device metadata.
    Enforces max concurrent sessions per user.
    Returns (plain_token, session_record).
    """
    # Enforce concurrent session limit
    active_count = _count_active_sessions(db, user.id)
    if active_count >= MAX_CONCURRENT_SESSIONS:
        # Evict oldest to make room
        _evict_oldest_session(db, user.id)

    minutes = expires_minutes if expires_minutes is not None else DEFAULT_SESSION_MINUTES

    token = create_access_token(subject=user.id, expires_minutes=minutes)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    # Parse device metadata
    parsed = parse_ua(user_agent)
    device_type = parsed.device_type
    device_os = parsed.os
    device_browser = parsed.browser

    # Best-effort geo lookup (fails silently)
    location = None
    if ip_address and settings.RATE_LIMIT_ENABLED:  # only if we have networking
        try:
            from app.services.geo_service import lookup as geo_lookup
            location = geo_lookup(ip_address)
        except Exception:
            pass

    session = SessionModel(
        user_id=user.id,
        token_hash=hash_token(token),
        ip_address=ip_address,
        user_agent=user_agent,
        device_label=device_label or parsed.friendly,
        device_type=device_type,
        device_os=device_os,
        device_browser=device_browser,
        location=location,
        expires_at=expires_at,
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return token, session


def is_session_valid(db: DBSession, token: str) -> bool:
    th = hash_token(token)
    s = db.query(SessionModel).filter(SessionModel.token_hash == th).first()
    if not s:
        return False
    if s.is_revoked:
        return False
    if s.expires_at < datetime.now(timezone.utc):
        return False
    return True


def touch_session(db: DBSession, token: str) -> None:
    th = hash_token(token)
    s = db.query(SessionModel).filter(SessionModel.token_hash == th).first()
    if s:
        s.last_seen_at = datetime.now(timezone.utc)
        db.commit()


def revoke_session(db: DBSession, token: str) -> None:
    th = hash_token(token)
    s = db.query(SessionModel).filter(SessionModel.token_hash == th).first()
    if s and not s.is_revoked:
        s.is_revoked = True
        s.revoked_at = datetime.now(timezone.utc)
        db.commit()


def revoke_all_other_sessions(
    db: DBSession, user_id: str, keep_token: str | None = None,
) -> int:
    th = hash_token(keep_token) if keep_token else None
    q = db.query(SessionModel).filter(
        SessionModel.user_id == user_id,
        SessionModel.is_revoked.is_(False),
    )
    if th:
        q = q.filter(SessionModel.token_hash != th)
    count = q.update({
        "is_revoked": True,
        "revoked_at": datetime.now(timezone.utc),
    })
    db.commit()
    return count


def list_sessions(db: DBSession, user_id: str) -> list[SessionModel]:
    return (
        db.query(SessionModel)
        .filter(SessionModel.user_id == user_id)
        .order_by(SessionModel.created_at.desc())
        .all()
    )


def revoke_session_by_id(db: DBSession, user_id: str, session_id: str) -> bool:
    s = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id, SessionModel.user_id == user_id)
        .first()
    )
    if not s:
        return False
    if not s.is_revoked:
        s.is_revoked = True
        s.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return True