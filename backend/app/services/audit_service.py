"""
Auth audit logging — record every important authentication event.
"""
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.auth_audit import AuthAuditLog

logger = logging.getLogger(__name__)


def log_auth_event(
    db: Session,
    event_type: str,
    *,
    user_id: str | None = None,
    email: str | None = None,
    event_data: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
) -> None:
    """Write an audit record. Never raises — logging must not break auth flows."""
    try:
        record = AuthAuditLog(
            user_id=user_id,
            email=email.lower() if email else None,
            event_type=event_type,
            event_data=json.dumps(event_data, default=str) if event_data else None,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
        )
        db.add(record)
        db.commit()
    except Exception as e:
        logger.exception(f"Failed to write auth audit log ({event_type}): {e}")
        try:
            db.rollback()
        except Exception:
            pass