"""
Forums — Communication module.

Rules (from the corrected spec):
  - Anyone can create a forum.
  - Institution-scoped forums require Institution Admin approval.
  - Must be created >= 3 days before starts_at.
  - Creator is the moderator.
  - Join clicks are recorded; the creator sees the participant list.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.forum import (
    Forum,
    ForumApprovalRequest,
    ForumJoin,
    ForumTopic,
    ForumReply,
    VALID_SCOPE_TYPES,
)


logger = logging.getLogger(__name__)


FORUM_LEAD_TIME_DAYS = 3
SLUG_MAX = 60


class ForumError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (s or "forum")[:SLUG_MAX]


def _unique_slug(db: Session, base: str) -> str:
    slug = base
    for _ in range(20):
        if not db.query(Forum).filter(Forum.slug == slug).first():
            return slug
        slug = f"{base}-{secrets.token_hex(3)}"[:SLUG_MAX]
    return f"forum-{secrets.token_hex(6)}"


# ============================================================================
# Forum CRUD
# ============================================================================

def create_forum(
    db: Session, *, creator_id: str, data,
) -> Forum:
    if data.scope_type not in VALID_SCOPE_TYPES:
        raise ForumError(f"Invalid scope_type '{data.scope_type}'.", 400)

    if data.scope_type != "public" and not data.scope_ref_id:
        raise ForumError(
            f"scope_ref_id required for scope_type '{data.scope_type}'.", 400,
        )

    # 3-day lead time
    delta = data.starts_at - _now()
    if delta < timedelta(days=FORUM_LEAD_TIME_DAYS):
        raise ForumError(
            f"Forums must be created at least {FORUM_LEAD_TIME_DAYS} days "
            "before the start date.", 400,
        )

    if data.ends_at and data.ends_at <= data.starts_at:
        raise ForumError("ends_at must be after starts_at.", 400)

    requires_approval = data.scope_type == "institution"
    slug = _unique_slug(db, _slugify(data.name))

    forum = Forum(
        name=data.name,
        slug=slug,
        description=data.description,
        scope_type=data.scope_type,
        scope_ref_id=data.scope_ref_id,
        visibility=data.visibility,
        category=data.category,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        google_meet_link=data.google_meet_link,
        location=data.location,
        creator_id=creator_id,
        moderator_id=creator_id,
        status="pending_approval" if requires_approval else "active",
        requires_approval=requires_approval,
        is_active=True,
    )
    db.add(forum)
    db.flush()

    if requires_approval:
        db.add(ForumApprovalRequest(
            forum_id=forum.id,
            requester_id=creator_id,
            requested_at=_now(),
            status="pending",
        ))

    db.commit()
    db.refresh(forum)
    return forum


def get_forum(db: Session, forum_id: str) -> Forum:
    f = db.query(Forum).filter(Forum.id == forum_id).first()
    if not f:
        raise ForumError("Forum not found.", 404)
    return f


def get_forum_by_slug(db: Session, slug: str) -> Forum:
    f = db.query(Forum).filter(Forum.slug == slug).first()
    if not f:
        raise ForumError("Forum not found.", 404)
    return f


def list_forums(
    db: Session, *,
    scope_type: str | None = None,
    scope_ref_id: str | None = None,
    category: str | None = None,
    include_archived: bool = False,
    include_pending: bool = False,
    limit: int = 100,
) -> list[Forum]:
    q = db.query(Forum).filter(Forum.is_active.is_(True))
    if scope_type:
        q = q.filter(Forum.scope_type == scope_type)
    if scope_ref_id:
        q = q.filter(Forum.scope_ref_id == scope_ref_id)
    if category:
        q = q.filter(Forum.category == category)
    if not include_archived:
        q = q.filter(Forum.is_archived.is_(False))
    if not include_pending:
        q = q.filter(Forum.status == "active")
    return q.order_by(Forum.starts_at.asc()).limit(limit).all()


def update_forum(
    db: Session, *, forum_id: str, actor_id: str, data,
) -> Forum:
    forum = get_forum(db, forum_id)
    if forum.creator_id != actor_id:
        raise ForumError("Only the creator may update this forum.", 403)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(forum, field, value)
    db.commit()
    db.refresh(forum)
    return forum


# ============================================================================
# Approval
# ============================================================================

def decide_approval(
    db: Session, *,
    forum_id: str, reviewer_id: str, approve: bool,
    notes: str | None = None,
) -> Forum:
    """
    Institution Admin action. On approve → forum goes active.
    On reject → forum is cancelled and hidden.
    """
    forum = get_forum(db, forum_id)
    if not forum.requires_approval:
        raise ForumError("Forum does not require approval.", 409)
    if forum.status != "pending_approval":
        raise ForumError(
            f"Forum is not pending approval (status={forum.status}).", 409,
        )

    approval = db.query(ForumApprovalRequest).filter(
        ForumApprovalRequest.forum_id == forum_id,
    ).first()
    if not approval:
        raise ForumError("Approval request not found.", 404)

    now = _now()
    approval.reviewer_id = reviewer_id
    approval.reviewed_at = now
    approval.review_notes = notes

    if approve:
        approval.status = "approved"
        forum.status = "active"
    else:
        approval.status = "rejected"
        forum.status = "cancelled"
        forum.is_active = False

    db.commit()
    db.refresh(forum)
    return forum


# ============================================================================
# Join / leave
# ============================================================================

def join_forum(
    db: Session, *, forum_id: str, user_id: str,
) -> ForumJoin:
    forum = get_forum(db, forum_id)
    if forum.status != "active":
        raise ForumError("Forum is not open for joining.", 409)

    existing = db.query(ForumJoin).filter(
        ForumJoin.forum_id == forum_id,
        ForumJoin.user_id == user_id,
    ).first()
    if existing:
        if existing.left_at is not None:
            existing.left_at = None
            existing.joined_at = _now()
            forum.participant_count += 1
            db.commit()
            db.refresh(existing)
        return existing

    join = ForumJoin(
        forum_id=forum_id,
        user_id=user_id,
        joined_at=_now(),
    )
    db.add(join)
    forum.participant_count += 1
    db.commit()
    db.refresh(join)
    return join


def leave_forum(
    db: Session, *, forum_id: str, user_id: str,
) -> ForumJoin:
    join = db.query(ForumJoin).filter(
        ForumJoin.forum_id == forum_id,
        ForumJoin.user_id == user_id,
        ForumJoin.left_at.is_(None),
    ).first()
    if not join:
        raise ForumError("You have not joined this forum.", 404)
    join.left_at = _now()
    forum = get_forum(db, forum_id)
    if forum.participant_count > 0:
        forum.participant_count -= 1
    db.commit()
    db.refresh(join)
    return join


def list_participants(
    db: Session, *, forum_id: str, actor_id: str,
) -> list[ForumJoin]:
    """Creator or moderator only — this is what the creator sees."""
    forum = get_forum(db, forum_id)
    if actor_id not in (forum.creator_id, forum.moderator_id):
        raise ForumError(
            "Only the creator or moderator can view participants.", 403,
        )
    return db.query(ForumJoin).filter(
        ForumJoin.forum_id == forum_id,
        ForumJoin.left_at.is_(None),
    ).order_by(ForumJoin.joined_at.asc()).all()


# ============================================================================
# Topics
# ============================================================================

def create_topic(
    db: Session, *, forum_id: str, author_id: str, data,
) -> ForumTopic:
    forum = get_forum(db, forum_id)
    if forum.status != "active":
        raise ForumError("Forum is not open.", 409)
    if forum.is_archived:
        raise ForumError("Forum is archived.", 409)

    topic = ForumTopic(
        forum_id=forum_id,
        author_id=author_id,
        title=data.title,
        body=data.body,
    )
    db.add(topic)
    forum.topic_count += 1
    db.commit()
    db.refresh(topic)
    return topic


def get_topic(db: Session, topic_id: str) -> ForumTopic:
    t = db.query(ForumTopic).filter(ForumTopic.id == topic_id).first()
    if not t:
        raise ForumError("Topic not found.", 404)
    return t


def list_topics(
    db: Session, *, forum_id: str,
    include_deleted: bool = False,
    limit: int = 50, cursor: str | None = None,
) -> dict:
    get_forum(db, forum_id)
    q = db.query(ForumTopic).filter(ForumTopic.forum_id == forum_id)
    if not include_deleted:
        q = q.filter(ForumTopic.is_deleted.is_(False))
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(ForumTopic.created_at < cursor_dt)
        except ValueError:
            raise ForumError("Invalid cursor.", 400)

    rows = q.order_by(
        ForumTopic.is_pinned.desc(),
        ForumTopic.last_reply_at.desc().nullslast(),
        ForumTopic.created_at.desc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        rows[-1].created_at.isoformat() if rows and has_more else None
    )
    return {
        "topics": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def update_topic(
    db: Session, *, topic_id: str, actor_id: str, data,
) -> ForumTopic:
    t = get_topic(db, topic_id)
    forum = get_forum(db, t.forum_id)
    if actor_id not in (forum.moderator_id, forum.creator_id):
        raise ForumError(
            "Only the moderator may pin or lock topics.", 403,
        )
    if data.is_pinned is not None:
        t.is_pinned = data.is_pinned
    if data.is_locked is not None:
        t.is_locked = data.is_locked
    db.commit()
    db.refresh(t)
    return t


def delete_topic(
    db: Session, *, topic_id: str, actor_id: str,
    reason: str | None = None,
) -> ForumTopic:
    t = get_topic(db, topic_id)
    forum = get_forum(db, t.forum_id)
    if t.author_id != actor_id and forum.moderator_id != actor_id:
        raise ForumError("Not authorised to delete this topic.", 403)
    t.is_deleted = True
    t.deleted_at = _now()
    t.deleted_by = actor_id
    t.delete_reason = reason
    db.commit()
    db.refresh(t)
    return t


# ============================================================================
# Replies
# ============================================================================

def create_reply(
    db: Session, *, topic_id: str, author_id: str, data,
) -> ForumReply:
    t = get_topic(db, topic_id)
    if t.is_locked:
        raise ForumError("Topic is locked.", 409)
    if t.is_deleted:
        raise ForumError("Topic is deleted.", 410)

    if data.parent_id:
        parent = db.query(ForumReply).filter(
            ForumReply.id == data.parent_id,
            ForumReply.topic_id == topic_id,
        ).first()
        if not parent:
            raise ForumError("Parent reply not found.", 404)

    reply = ForumReply(
        topic_id=topic_id,
        author_id=author_id,
        parent_id=data.parent_id,
        body=data.body,
    )
    db.add(reply)

    now = _now()
    t.reply_count += 1
    t.last_reply_at = now
    t.last_reply_by_id = author_id

    forum = get_forum(db, t.forum_id)
    forum.reply_count += 1

    db.commit()
    db.refresh(reply)
    return reply


def list_replies(
    db: Session, *, topic_id: str,
    include_deleted: bool = False,
    limit: int = 200, cursor: str | None = None,
) -> dict:
    get_topic(db, topic_id)
    q = db.query(ForumReply).filter(ForumReply.topic_id == topic_id)
    if not include_deleted:
        q = q.filter(ForumReply.is_deleted.is_(False))
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(ForumReply.created_at > cursor_dt)
        except ValueError:
            raise ForumError("Invalid cursor.", 400)

    rows = q.order_by(
        ForumReply.created_at.asc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        rows[-1].created_at.isoformat() if rows and has_more else None
    )
    return {
        "replies": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def delete_reply(
    db: Session, *, reply_id: str, actor_id: str,
    reason: str | None = None,
) -> ForumReply:
    r = db.query(ForumReply).filter(ForumReply.id == reply_id).first()
    if not r:
        raise ForumError("Reply not found.", 404)
    topic = get_topic(db, r.topic_id)
    forum = get_forum(db, topic.forum_id)
    if r.author_id != actor_id and forum.moderator_id != actor_id:
        raise ForumError("Not authorised to delete this reply.", 403)
    r.is_deleted = True
    r.deleted_at = _now()
    r.deleted_by = actor_id
    r.delete_reason = reason
    db.commit()
    db.refresh(r)
    return r