"""
Notification store — Communication module.

Pure persistence layer for the Notification table. No email/SMS here —
that lives in notification_service. This module is called by
notification_service._persist_in_app, but can also be called directly
by any service that wants to drop a persistent in-app notification
without firing an email.

Fan-out happens at write time: one row per user per notification.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.notification import (
    Notification,
    VALID_CATEGORIES,
    VALID_PRIORITIES,
)


logger = logging.getLogger(__name__)


class NotificationStoreError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# Create (fan-out)
# ============================================================================

def create_for_users(
    db: Session, *,
    user_ids: list[str],
    category: str,
    title: str,
    body: str,
    priority: str = "normal",
    source_type: str | None = None,
    source_id: str | None = None,
    link_url: str | None = None,
    payload_json: dict | None = None,
    requires_acknowledgment: bool = False,
    expires_at: datetime | None = None,
    is_system_generated: bool = False,
    commit: bool = True,
) -> int:
    """
    Fan out one Notification row per user. Returns count created.

    Call with commit=False from inside a transaction that will commit
    shortly after, to keep multi-step operations atomic.
    """
    if category not in VALID_CATEGORIES:
        raise NotificationStoreError(f"Unknown category '{category}'.", 400)
    if priority not in VALID_PRIORITIES:
        raise NotificationStoreError(f"Unknown priority '{priority}'.", 400)
    if not user_ids:
        return 0

    # De-dup so callers who pass [a, a, b] don't create 3 rows
    unique_ids = list(dict.fromkeys(user_ids))
    now = _now()

    for uid in unique_ids:
        db.add(Notification(
            user_id=uid,
            category=category,
            priority=priority,
            title=title,
            body=body,
            source_type=source_type,
            source_id=source_id,
            link_url=link_url,
            payload_json=payload_json,
            status="delivered",
            is_system_generated=is_system_generated,
            requires_acknowledgment=requires_acknowledgment,
            delivered_at=now,
            expires_at=expires_at,
        ))

    if commit:
        db.commit()
    else:
        db.flush()
    return len(unique_ids)


# ============================================================================
# Read
# ============================================================================

def list_for_user(
    db: Session, *,
    user_id: str,
    unread_only: bool = False,
    category: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict:
    q = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        q = q.filter(Notification.status.in_(("delivered", "pending")))
    if category:
        q = q.filter(Notification.category == category)
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(Notification.created_at < cursor_dt)
        except ValueError:
            raise NotificationStoreError("Invalid cursor.", 400)

    rows = q.order_by(
        Notification.created_at.desc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        rows[-1].created_at.isoformat() if rows and has_more else None
    )

    unread = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        Notification.status.in_(("delivered", "pending")),
    ).scalar() or 0

    return {
        "notifications": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "unread_count": int(unread),
    }


def count_for_user(db: Session, *, user_id: str) -> dict:
    unread = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        Notification.status.in_(("delivered", "pending")),
    ).scalar() or 0
    pending_ack = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user_id,
        Notification.requires_acknowledgment.is_(True),
        Notification.status.notin_(("read", "dismissed", "expired")),
    ).scalar() or 0
    return {
        "unread": int(unread),
        "pending_acknowledgment": int(pending_ack),
    }


# ============================================================================
# Mutations
# ============================================================================

def mark_read(
    db: Session, *,
    user_id: str,
    notification_ids: list[str] | None = None,
) -> int:
    """
    If notification_ids is None → mark all unread for this user.
    Returns number of rows affected.
    """
    now = _now()
    q = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.status.in_(("delivered", "pending")),
    )
    if notification_ids is not None:
        if not notification_ids:
            return 0
        q = q.filter(Notification.id.in_(notification_ids))

    rows = q.all()
    for r in rows:
        r.status = "read"
        r.read_at = now
    db.commit()
    return len(rows)


def dismiss(db: Session, *, user_id: str, notification_id: str) -> bool:
    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    ).first()
    if not n:
        return False
    n.status = "dismissed"
    n.dismissed_at = _now()
    db.commit()
    return True


def acknowledge(
    db: Session, *, user_id: str, notification_id: str,
) -> bool:
    """
    Mark a requires_acknowledgment notification as read. Returns False
    if the notification doesn't belong to the user, doesn't require
    acknowledgment, or doesn't exist.
    """
    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id,
        Notification.requires_acknowledgment.is_(True),
    ).first()
    if not n:
        return False
    n.status = "read"
    n.read_at = _now()
    db.commit()
    return True


# ============================================================================
# Scheduled maintenance
# ============================================================================

def expire_stale(db: Session, *, batch_size: int = 500) -> int:
    now = _now()
    rows = db.query(Notification).filter(
        Notification.expires_at.isnot(None),
        Notification.expires_at <= now,
        Notification.status.notin_(("expired", "dismissed", "read")),
    ).limit(batch_size).all()
    for r in rows:
        r.status = "expired"
    if rows:
        db.commit()
    return len(rows)