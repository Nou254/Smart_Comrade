"""
Community message service — Module 003 Phase 11.

Text-only messages, rate-limited. Auto-hide at 5 reports.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.community import (
    Community, CommunityMembership, CommunityMessage,
)
from app.services.community_service import CommunityError, get_community


logger = logging.getLogger(__name__)


RATE_LIMIT_PER_MINUTE = 10
RATE_LIMIT_PER_HOUR = 100
MAX_MESSAGE_LENGTH = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# SEND
# ============================================================================

def send_message(
    db: Session,
    community_id: str,
    user_id: str,
    content: str,
    reply_to_id: str | None = None,
) -> CommunityMessage:
    comm = get_community(db, community_id)
    if not comm.is_active:
        raise CommunityError("Community is archived.", 409)

    content = (content or "").strip()
    if not content:
        raise CommunityError("Message cannot be empty.", 400)
    if len(content) > comm.max_message_length:
        raise CommunityError(
            f"Message exceeds {comm.max_message_length} characters.", 400,
        )

    # Verify membership
    membership = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == user_id,
        CommunityMembership.is_active.is_(True),
    ).first()
    if not membership:
        raise CommunityError("You are not a member of this community.", 403)

    if membership.banned_at:
        raise CommunityError("You are banned from this community.", 403)
    if membership.muted_until and membership.muted_until > _now():
        raise CommunityError(
            f"You are muted until {membership.muted_until.isoformat()}.",
            403,
        )

    # Rate limits (per user, per community)
    _enforce_rate_limits(db, community_id, user_id)

    # Validate reply target
    if reply_to_id:
        target = db.query(CommunityMessage).filter(
            CommunityMessage.id == reply_to_id,
            CommunityMessage.community_id == community_id,
        ).first()
        if not target:
            raise CommunityError("Reply target not found in this community.", 404)

    msg = CommunityMessage(
        community_id=community_id,
        sender_id=user_id,
        content=content,
        reply_to_id=reply_to_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _enforce_rate_limits(db: Session, community_id: str, user_id: str) -> None:
    now = _now()
    minute_ago = now - timedelta(minutes=1)
    hour_ago = now - timedelta(hours=1)

    per_minute = db.query(CommunityMessage).filter(
        CommunityMessage.community_id == community_id,
        CommunityMessage.sender_id == user_id,
        CommunityMessage.created_at >= minute_ago,
        CommunityMessage.is_deleted.is_(False),
    ).count()
    if per_minute >= RATE_LIMIT_PER_MINUTE:
        raise CommunityError(
            f"Rate limit exceeded: max {RATE_LIMIT_PER_MINUTE} messages per minute.",
            429,
        )

    per_hour = db.query(CommunityMessage).filter(
        CommunityMessage.community_id == community_id,
        CommunityMessage.sender_id == user_id,
        CommunityMessage.created_at >= hour_ago,
        CommunityMessage.is_deleted.is_(False),
    ).count()
    if per_hour >= RATE_LIMIT_PER_HOUR:
        raise CommunityError(
            f"Rate limit exceeded: max {RATE_LIMIT_PER_HOUR} messages per hour.",
            429,
        )


# ============================================================================
# LIST (paginated)
# ============================================================================

def list_messages(
    db: Session,
    community_id: str,
    viewer_id: str,
    limit: int = 50,
    cursor: str | None = None,
) -> dict:
    """
    Return {messages, next_cursor, has_more}.

    Cursor is a message ID; returns messages created before that message's
    created_at. Ordering is newest-first.
    """
    get_community(db, community_id)

    # Verify viewer is a member
    membership = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == viewer_id,
        CommunityMembership.is_active.is_(True),
    ).first()
    if not membership:
        raise CommunityError("You are not a member of this community.", 403)

    q = db.query(CommunityMessage).filter(
        CommunityMessage.community_id == community_id,
        CommunityMessage.is_deleted.is_(False),
        CommunityMessage.is_hidden.is_(False),
    )

    if cursor:
        anchor = db.query(CommunityMessage).filter(
            CommunityMessage.id == cursor,
            CommunityMessage.community_id == community_id,
        ).first()
        if anchor:
            q = q.filter(CommunityMessage.created_at < anchor.created_at)

    limit = max(1, min(limit, 100))
    rows = q.order_by(CommunityMessage.created_at.desc()).limit(limit + 1).all()

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor = rows[-1].id if has_more and rows else None

    return {
        "messages": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ============================================================================
# DELETE OWN MESSAGE
# ============================================================================

def delete_own_message(db: Session, message_id: str, user_id: str) -> CommunityMessage:
    msg = db.query(CommunityMessage).filter(CommunityMessage.id == message_id).first()
    if not msg:
        raise CommunityError("Message not found.", 404)
    if msg.sender_id != user_id:
        raise CommunityError("You can only delete your own messages.", 403)
    if msg.is_deleted:
        return msg

    msg.is_deleted = True
    msg.deleted_at = _now()
    msg.deleted_by = user_id
    msg.delete_reason = "Self-deleted"
    db.commit()
    db.refresh(msg)
    return msg