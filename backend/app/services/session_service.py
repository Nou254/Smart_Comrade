"""
Session management: create on login, revoke on logout, list active sessions.
Supports per-call session length overrides (admin vs user).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from app.core.security import create_access_token, hash_token
from app.models.user import User
from app.models.auth_extension import Session as SessionModel


# Default session lengths in minutes
DEFAULT_SESSION_MINUTES = 1440   # 24 hours (regular users)
ADMIN_SESSION_MINUTES = 720      # 12 hours (admins)


def create_session(
    db: DBSession,
    user: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
    device_label: str | None = None,
    expires_minutes: int | None = None,
) -> tuple[str, SessionModel]:
    """
    Create a JWT + session record.
    Returns (plain_token, session_record).
    If expires_minutes is None, uses DEFAULT_SESSION_MINUTES.
    """
    minutes = expires_minutes if expires_minutes is not None else DEFAULT_SESSION_MINUTES

    token = create_access_token(subject=user.id, expires_minutes=minutes)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    session = SessionModel(
        user_id=user.id,
        token_hash=hash_token(token),
        ip_address=ip_address,
        user_agent=user_agent,
        device_label=device_label,
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


def revoke_all_other_sessions(db: DBSession, user_id: str,
                              keep_token: str | None = None) -> int:
    th = hash_token(keep_token) if keep_token else None
    q = db.query(SessionModel).filter(
        SessionModel.user_id == user_id,
        SessionModel.is_revoked.is_(False),
    )
    if th:
        q = q.filter(SessionModel.token_hash != th)
    count = q.update({"is_revoked": True, "revoked_at": datetime.now(timezone.utc)})
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