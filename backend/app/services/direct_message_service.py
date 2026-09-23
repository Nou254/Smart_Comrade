"""
Direct messaging — Communication module.

Assumes the caller has already established the conversation via an
accepted ConversationRequest. This module does not create conversations
from scratch — that's conversation_request_service.accept_request().

Blocking is enforced at every send.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.messaging import (
    DirectConversation,
    DirectConversationParticipant,
    DirectMessage,
)
from app.services.blocking_service import is_blocked


logger = logging.getLogger(__name__)


class DirectMessageError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# Access
# ============================================================================

def get_conversation(
    db: Session, *, conversation_id: str, viewer_id: str,
) -> DirectConversation:
    conv = db.query(DirectConversation).filter(
        DirectConversation.id == conversation_id,
    ).first()
    if not conv:
        raise DirectMessageError("Conversation not found.", 404)

    is_participant = db.query(DirectConversationParticipant).filter(
        DirectConversationParticipant.conversation_id == conversation_id,
        DirectConversationParticipant.user_id == viewer_id,
    ).first()
    if not is_participant:
        raise DirectMessageError(
            "You are not a participant in this conversation.", 403,
        )
    return conv


def _other_participant_id(
    db: Session, *, conversation_id: str, viewer_id: str,
) -> str | None:
    row = db.query(DirectConversationParticipant).filter(
        DirectConversationParticipant.conversation_id == conversation_id,
        DirectConversationParticipant.user_id != viewer_id,
    ).first()
    return row.user_id if row else None


# ============================================================================
# Inbox
# ============================================================================

def list_my_conversations(
    db: Session, *, viewer_id: str,
    include_archived: bool = False,
    limit: int = 50, cursor: str | None = None,
) -> dict:
    q = db.query(DirectConversation).join(
        DirectConversationParticipant,
        DirectConversationParticipant.conversation_id == DirectConversation.id,
    ).filter(DirectConversationParticipant.user_id == viewer_id)

    if not include_archived:
        q = q.filter(DirectConversationParticipant.is_archived.is_(False))

    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(
                or_(
                    DirectConversation.last_message_at < cursor_dt,
                    DirectConversation.last_message_at.is_(None),
                )
            )
        except ValueError:
            raise DirectMessageError("Invalid cursor.", 400)

    convs = q.order_by(
        DirectConversation.last_message_at.desc().nullslast(),
        DirectConversation.created_at.desc(),
    ).limit(limit + 1).all()

    has_more = len(convs) > limit
    convs = convs[:limit]
    next_cursor = (
        convs[-1].last_message_at.isoformat()
        if convs and has_more and convs[-1].last_message_at
        else None
    )

    out = []
    for conv in convs:
        viewer_p = db.query(DirectConversationParticipant).filter(
            DirectConversationParticipant.conversation_id == conv.id,
            DirectConversationParticipant.user_id == viewer_id,
        ).first()
        other_p = db.query(DirectConversationParticipant).filter(
            DirectConversationParticipant.conversation_id == conv.id,
            DirectConversationParticipant.user_id != viewer_id,
        ).first()
        if not viewer_p or not other_p:
            continue

        unread_q = db.query(func.count(DirectMessage.id)).filter(
            DirectMessage.conversation_id == conv.id,
            DirectMessage.sender_id != viewer_id,
            DirectMessage.is_deleted.is_(False),
        )
        if viewer_p.last_read_at:
            unread_q = unread_q.filter(
                DirectMessage.created_at > viewer_p.last_read_at,
            )
        unread_count = unread_q.scalar() or 0

        out.append({
            "conversation": conv,
            "other_user_id": other_p.user_id,
            "is_muted": viewer_p.is_muted,
            "is_archived": viewer_p.is_archived,
            "unread_count": int(unread_count),
        })

    return {
        "conversations": out,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ============================================================================
# Send
# ============================================================================

def send_message(
    db: Session, *,
    conversation_id: str,
    sender_id: str,
    content: str,
    reply_to_id: str | None = None,
) -> DirectMessage:
    conv = get_conversation(
        db, conversation_id=conversation_id, viewer_id=sender_id,
    )
    if conv.status == "blocked":
        raise DirectMessageError("This conversation is blocked.", 403)

    other_id = _other_participant_id(
        db, conversation_id=conversation_id, viewer_id=sender_id,
    )
    if other_id and is_blocked(db, user_a=sender_id, user_b=other_id):
        conv.is_blocked = True
        conv.status = "blocked"
        db.commit()
        raise DirectMessageError("This conversation is blocked.", 403)

    if reply_to_id:
        parent = db.query(DirectMessage).filter(
            DirectMessage.id == reply_to_id,
            DirectMessage.conversation_id == conversation_id,
        ).first()
        if not parent:
            raise DirectMessageError("Parent message not found.", 404)

    now = _now()
    msg = DirectMessage(
        conversation_id=conversation_id,
        sender_id=sender_id,
        content=content,
        reply_to_id=reply_to_id,
    )
    db.add(msg)

    conv.last_message_at = now
    conv.last_message_preview = content[:200]
    conv.last_message_sender_id = sender_id

    sender_p = db.query(DirectConversationParticipant).filter(
        DirectConversationParticipant.conversation_id == conversation_id,
        DirectConversationParticipant.user_id == sender_id,
    ).first()
    if sender_p:
        sender_p.last_read_at = now

    db.commit()
    db.refresh(msg)
    return msg


# ============================================================================
# Read
# ============================================================================

def list_messages(
    db: Session, *,
    conversation_id: str, viewer_id: str,
    limit: int = 50, cursor: str | None = None,
) -> dict:
    get_conversation(db, conversation_id=conversation_id, viewer_id=viewer_id)

    q = db.query(DirectMessage).filter(
        DirectMessage.conversation_id == conversation_id,
    )
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(DirectMessage.created_at < cursor_dt)
        except ValueError:
            raise DirectMessageError("Invalid cursor.", 400)

    rows = q.order_by(
        DirectMessage.created_at.desc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        rows[-1].created_at.isoformat() if rows and has_more else None
    )
    return {
        "messages": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def mark_read(
    db: Session, *,
    conversation_id: str, viewer_id: str,
    up_to_message_id: str | None = None,
) -> None:
    p = db.query(DirectConversationParticipant).filter(
        DirectConversationParticipant.conversation_id == conversation_id,
        DirectConversationParticipant.user_id == viewer_id,
    ).first()
    if not p:
        raise DirectMessageError("Not a participant.", 403)

    if up_to_message_id:
        msg = db.query(DirectMessage).filter(
            DirectMessage.id == up_to_message_id,
            DirectMessage.conversation_id == conversation_id,
        ).first()
        p.last_read_at = msg.created_at if msg else _now()
    else:
        p.last_read_at = _now()
    db.commit()


# ============================================================================
# Conversation state
# ============================================================================

def update_conversation_state(
    db: Session, *,
    conversation_id: str, viewer_id: str,
    is_muted: bool | None = None,
    is_archived: bool | None = None,
) -> DirectConversationParticipant:
    p = db.query(DirectConversationParticipant).filter(
        DirectConversationParticipant.conversation_id == conversation_id,
        DirectConversationParticipant.user_id == viewer_id,
    ).first()
    if not p:
        raise DirectMessageError("Not a participant.", 403)

    if is_muted is not None:
        p.is_muted = is_muted
    if is_archived is not None:
        p.is_archived = is_archived
    db.commit()
    db.refresh(p)
    return p


# ============================================================================
# Edit / delete
# ============================================================================

def edit_message(
    db: Session, *,
    message_id: str, sender_id: str, new_content: str,
) -> DirectMessage:
    msg = db.query(DirectMessage).filter(
        DirectMessage.id == message_id,
        DirectMessage.sender_id == sender_id,
    ).first()
    if not msg:
        raise DirectMessageError("Message not found or not yours.", 404)
    if msg.is_deleted:
        raise DirectMessageError("Cannot edit a deleted message.", 409)

    msg.content = new_content
    msg.is_edited = True
    msg.edited_at = _now()
    db.commit()
    db.refresh(msg)
    return msg


def delete_message(
    db: Session, *,
    message_id: str, actor_id: str, reason: str | None = None,
) -> DirectMessage:
    msg = db.query(DirectMessage).filter(
        DirectMessage.id == message_id,
    ).first()
    if not msg:
        raise DirectMessageError("Message not found.", 404)
    if msg.sender_id != actor_id:
        raise DirectMessageError(
            "You can only delete your own messages.", 403,
        )
    msg.is_deleted = True
    msg.deleted_at = _now()
    msg.deleted_by = actor_id
    msg.delete_reason = reason
    db.commit()
    db.refresh(msg)
    return msg