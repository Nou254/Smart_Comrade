"""
Conversation requests — Communication module.

A request is required before any DM can start.

Direction rules:
  student  → student    : recipient must accept
  student  → external   : allowed to initiate
  external → student    : allowed to send, student must accept

On accept, a DirectConversation is created. The request becomes its
origin.

Unaccepted requests auto-expire (14 days). A rejected request triggers
a 30-day cooldown before the same requester can try again.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.messaging import (
    ConversationRequest,
    DirectConversation,
    DirectConversationParticipant,
    VALID_REQUEST_CONTEXT_TYPES,
)
from app.models.user import User
from app.services.blocking_service import is_blocked


logger = logging.getLogger(__name__)


REQUEST_EXPIRY_DAYS = 14
REJECTION_COOLDOWN_DAYS = 30


class ConversationRequestError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation_key(a: str, b: str) -> str:
    return f"{min(a, b)}:{max(a, b)}"


# ============================================================================
# Create
# ============================================================================

def create_request(
    db: Session, *,
    requester_id: str,
    recipient_id: str,
    context_type: str,
    context_ref_type: str | None = None,
    context_ref_id: str | None = None,
    message: str | None = None,
) -> ConversationRequest:
    if requester_id == recipient_id:
        raise ConversationRequestError(
            "You cannot send a contact request to yourself.", 400,
        )
    if context_type not in VALID_REQUEST_CONTEXT_TYPES:
        raise ConversationRequestError(
            f"Unknown context_type '{context_type}'.", 400,
        )

    requester = db.query(User).filter(User.id == requester_id).first()
    recipient = db.query(User).filter(User.id == recipient_id).first()
    if not requester or not recipient:
        raise ConversationRequestError("User not found.", 404)

    if is_blocked(db, user_a=requester_id, user_b=recipient_id):
        raise ConversationRequestError(
            "Contact is not possible with this user.", 403,
        )

    # Cooldown after rejection
    cooldown_cutoff = _now() - timedelta(days=REJECTION_COOLDOWN_DAYS)
    recent_rejection = db.query(ConversationRequest).filter(
        ConversationRequest.requester_id == requester_id,
        ConversationRequest.recipient_id == recipient_id,
        ConversationRequest.status == "rejected",
        ConversationRequest.resolved_at > cooldown_cutoff,
    ).first()
    if recent_rejection:
        raise ConversationRequestError(
            "A recent request was rejected. You may try again after "
            f"{REJECTION_COOLDOWN_DAYS} days.", 429,
        )

    # Pending request already in flight from this direction
    pending = db.query(ConversationRequest).filter(
        ConversationRequest.requester_id == requester_id,
        ConversationRequest.recipient_id == recipient_id,
        ConversationRequest.status == "pending",
    ).first()
    if pending:
        return pending

    # Reverse pending → auto-accept (mutual interest)
    reverse = db.query(ConversationRequest).filter(
        ConversationRequest.requester_id == recipient_id,
        ConversationRequest.recipient_id == requester_id,
        ConversationRequest.status == "pending",
    ).first()
    if reverse:
        req, _conv = accept_request(
            db, request_id=reverse.id, actor_id=requester_id,
        )
        return req

    expires = _now() + timedelta(days=REQUEST_EXPIRY_DAYS)
    req = ConversationRequest(
        requester_id=requester_id,
        recipient_id=recipient_id,
        context_type=context_type,
        context_ref_type=context_ref_type,
        context_ref_id=context_ref_id,
        message=message,
        status="pending",
        expires_at=expires,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


# ============================================================================
# Accept
# ============================================================================

def accept_request(
    db: Session, *, request_id: str, actor_id: str,
) -> tuple[ConversationRequest, DirectConversation]:
    req = db.query(ConversationRequest).filter(
        ConversationRequest.id == request_id,
    ).first()
    if not req:
        raise ConversationRequestError("Request not found.", 404)
    if req.recipient_id != actor_id:
        raise ConversationRequestError(
            "Only the recipient can accept this request.", 403,
        )
    if req.status != "pending":
        raise ConversationRequestError(
            f"Cannot accept a request in status '{req.status}'.", 409,
        )
    if req.expires_at and req.expires_at < _now():
        req.status = "expired"
        db.commit()
        raise ConversationRequestError("Request has expired.", 410)

    if is_blocked(db, user_a=req.requester_id, user_b=req.recipient_id):
        raise ConversationRequestError(
            "Contact is not possible with this user.", 403,
        )

    key = _conversation_key(req.requester_id, req.recipient_id)
    conv = db.query(DirectConversation).filter(
        DirectConversation.conversation_key == key,
    ).first()

    if not conv:
        conv = DirectConversation(
            conversation_key=key,
            origin_request_id=req.id,
            status="active",
        )
        db.add(conv)
        db.flush()
        db.add_all([
            DirectConversationParticipant(
                conversation_id=conv.id, user_id=req.requester_id,
            ),
            DirectConversationParticipant(
                conversation_id=conv.id, user_id=req.recipient_id,
            ),
        ])
    else:
        # Reopen: un-archive both sides, clear block state
        for p in conv.participants:
            p.is_archived = False
            p.left_at = None
        if conv.status == "blocked":
            conv.status = "active"
            conv.is_blocked = False

    req.status = "accepted"
    req.resolved_at = _now()
    req.conversation_id = conv.id

    db.commit()
    db.refresh(req)
    db.refresh(conv)
    return req, conv


# ============================================================================
# Reject / withdraw / expire
# ============================================================================

def reject_request(
    db: Session, *, request_id: str, actor_id: str,
    reason: str | None = None,
) -> ConversationRequest:
    req = db.query(ConversationRequest).filter(
        ConversationRequest.id == request_id,
    ).first()
    if not req:
        raise ConversationRequestError("Request not found.", 404)
    if req.recipient_id != actor_id:
        raise ConversationRequestError(
            "Only the recipient can reject this request.", 403,
        )
    if req.status != "pending":
        raise ConversationRequestError(
            f"Cannot reject a request in status '{req.status}'.", 409,
        )
    req.status = "rejected"
    req.resolved_at = _now()
    req.rejection_reason = reason
    db.commit()
    db.refresh(req)
    return req


def withdraw_request(
    db: Session, *, request_id: str, actor_id: str,
) -> ConversationRequest:
    req = db.query(ConversationRequest).filter(
        ConversationRequest.id == request_id,
    ).first()
    if not req:
        raise ConversationRequestError("Request not found.", 404)
    if req.requester_id != actor_id:
        raise ConversationRequestError(
            "Only the requester can withdraw this request.", 403,
        )
    if req.status != "pending":
        raise ConversationRequestError(
            f"Cannot withdraw a request in status '{req.status}'.", 409,
        )
    req.status = "withdrawn"
    req.resolved_at = _now()
    db.commit()
    db.refresh(req)
    return req


def expire_stale(db: Session, *, batch_size: int = 200) -> int:
    now = _now()
    rows = db.query(ConversationRequest).filter(
        ConversationRequest.status == "pending",
        ConversationRequest.expires_at.isnot(None),
        ConversationRequest.expires_at <= now,
    ).limit(batch_size).all()
    for r in rows:
        r.status = "expired"
        r.resolved_at = now
    if rows:
        db.commit()
    return len(rows)


# ============================================================================
# Read
# ============================================================================

def get_request(
    db: Session, request_id: str, viewer_id: str,
) -> ConversationRequest:
    req = db.query(ConversationRequest).filter(
        ConversationRequest.id == request_id,
    ).first()
    if not req:
        raise ConversationRequestError("Request not found.", 404)
    if viewer_id not in (req.requester_id, req.recipient_id):
        raise ConversationRequestError("Not your request.", 403)
    return req


def list_incoming(
    db: Session, *, user_id: str,
    status: str | None = "pending",
    limit: int = 50, cursor: str | None = None,
) -> dict:
    return _list(
        db,
        filter_col=ConversationRequest.recipient_id,
        user_id=user_id, status=status, limit=limit, cursor=cursor,
    )


def list_outgoing(
    db: Session, *, user_id: str,
    status: str | None = "pending",
    limit: int = 50, cursor: str | None = None,
) -> dict:
    return _list(
        db,
        filter_col=ConversationRequest.requester_id,
        user_id=user_id, status=status, limit=limit, cursor=cursor,
    )


def _list(
    db: Session, *, filter_col, user_id: str,
    status: str | None, limit: int, cursor: str | None,
) -> dict:
    q = db.query(ConversationRequest).filter(filter_col == user_id)
    if status:
        q = q.filter(ConversationRequest.status == status)
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(ConversationRequest.created_at < cursor_dt)
        except ValueError:
            raise ConversationRequestError("Invalid cursor.", 400)

    rows = q.order_by(
        ConversationRequest.created_at.desc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        rows[-1].created_at.isoformat() if rows and has_more else None
    )
    return {
        "requests": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }