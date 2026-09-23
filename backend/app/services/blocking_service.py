"""
Blocking — Communication module.

Directional block from blocker to blocked. Enforcement happens inside
direct_message_service and conversation_request_service, which call
is_blocked() at every write.

A block does NOT suppress:
  - Emergency notifications
  - Election notices
  - Assessment reminders for enrolled assessments
  - Official institutional announcements from authoritative publishers
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.messaging import UserBlock


logger = logging.getLogger(__name__)


class BlockingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def block_user(
    db: Session, *, blocker_id: str, blocked_id: str,
    reason: str | None = None,
) -> UserBlock:
    if blocker_id == blocked_id:
        raise BlockingError("You cannot block yourself.", 400)

    existing = db.query(UserBlock).filter(
        UserBlock.blocker_id == blocker_id,
        UserBlock.blocked_id == blocked_id,
    ).first()
    if existing:
        return existing

    block = UserBlock(
        blocker_id=blocker_id,
        blocked_id=blocked_id,
        reason=reason,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


def unblock_user(
    db: Session, *, blocker_id: str, blocked_id: str,
) -> bool:
    n = db.query(UserBlock).filter(
        UserBlock.blocker_id == blocker_id,
        UserBlock.blocked_id == blocked_id,
    ).delete()
    db.commit()
    return n > 0


def is_blocked(
    db: Session, *, user_a: str, user_b: str,
) -> bool:
    """True if EITHER user has blocked the other (or themselves — edge case)."""
    if user_a == user_b:
        return False
    row = db.query(UserBlock).filter(
        ((UserBlock.blocker_id == user_a) & (UserBlock.blocked_id == user_b))
        | ((UserBlock.blocker_id == user_b) & (UserBlock.blocked_id == user_a))
    ).first()
    return row is not None


def list_my_blocks(db: Session, *, blocker_id: str) -> list[UserBlock]:
    return db.query(UserBlock).filter(
        UserBlock.blocker_id == blocker_id,
    ).order_by(UserBlock.created_at.desc()).all()