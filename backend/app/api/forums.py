"""
Forum endpoints — Communication module.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.forum import (
    ForumCreate,
    ForumUpdate,
    ForumResponse,
    ForumListResponse,
    ForumApprovalDecision,
    ForumApprovalRequestResponse,
    ForumJoinResponse,
    ForumParticipantListResponse,
    ForumTopicCreate,
    ForumTopicUpdate,
    ForumTopicResponse,
    ForumTopicListResponse,
    ForumReplyCreate,
    ForumReplyResponse,
    ForumReplyListResponse,
)
from app.services import forum_service as svc


router = APIRouter(tags=["Forums"])


def _err(e):
    raise HTTPException(
        status_code=getattr(e, "status_code", 400),
        detail=getattr(e, "message", str(e)),
    )


# ============================================================================
# Forums
# ============================================================================

@router.post("/forums", response_model=ForumResponse, status_code=201)
def create_forum(
    payload: ForumCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_forum(
            db, creator_id=current_user.id, data=payload,
        )
    except svc.ForumError as e:
        _err(e)


@router.get("/forums", response_model=ForumListResponse)
def list_forums(
    scope_type: str | None = Query(None),
    scope_ref_id: str | None = Query(None),
    category: str | None = Query(None),
    include_archived: bool = Query(False),
    include_pending: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = svc.list_forums(
        db, scope_type=scope_type, scope_ref_id=scope_ref_id,
        category=category, include_archived=include_archived,
        include_pending=include_pending, limit=limit,
    )
    return ForumListResponse(
        forums=[ForumResponse.model_validate(f) for f in rows],
        next_cursor=None, has_more=False,
    )


@router.get("/forums/{forum_id}", response_model=ForumResponse)
def get_forum(
    forum_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_forum(db, forum_id)
    except svc.ForumError as e:
        _err(e)


@router.get("/forums/by-slug/{slug}", response_model=ForumResponse)
def get_forum_by_slug(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_forum_by_slug(db, slug)
    except svc.ForumError as e:
        _err(e)


@router.patch("/forums/{forum_id}", response_model=ForumResponse)
def update_forum(
    forum_id: str,
    payload: ForumUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_forum(
            db, forum_id=forum_id,
            actor_id=current_user.id, data=payload,
        )
    except svc.ForumError as e:
        _err(e)


# ============================================================================
# Approval
# ============================================================================

@router.get(
    "/forums/{forum_id}/approval",
    response_model=ForumApprovalRequestResponse,
)
def get_approval_request(
    forum_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.forum import ForumApprovalRequest
    row = db.query(ForumApprovalRequest).filter(
        ForumApprovalRequest.forum_id == forum_id,
    ).first()
    if not row:
        raise HTTPException(
            status_code=404, detail="Approval request not found.",
        )
    return row


@router.post(
    "/forums/{forum_id}/approval",
    response_model=ForumResponse,
)
def decide_approval(
    forum_id: str,
    payload: ForumApprovalDecision,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Institution Admin approves or rejects an institution-scoped forum.
    The service enforces that the reviewer has appropriate authority.
    """
    try:
        return svc.decide_approval(
            db, forum_id=forum_id, reviewer_id=current_user.id,
            approve=payload.approve, notes=payload.notes,
        )
    except svc.ForumError as e:
        _err(e)


# ============================================================================
# Join / leave / participants
# ============================================================================

@router.post("/forums/{forum_id}/join", response_model=ForumJoinResponse)
def join_forum(
    forum_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.join_forum(
            db, forum_id=forum_id, user_id=current_user.id,
        )
    except svc.ForumError as e:
        _err(e)


@router.post("/forums/{forum_id}/leave", response_model=ForumJoinResponse)
def leave_forum(
    forum_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.leave_forum(
            db, forum_id=forum_id, user_id=current_user.id,
        )
    except svc.ForumError as e:
        _err(e)


@router.get(
    "/forums/{forum_id}/participants",
    response_model=ForumParticipantListResponse,
)
def list_participants(
    forum_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rows = svc.list_participants(
            db, forum_id=forum_id, actor_id=current_user.id,
        )
        return ForumParticipantListResponse(
            participants=[
                ForumJoinResponse.model_validate(r) for r in rows
            ],
            total=len(rows),
        )
    except svc.ForumError as e:
        _err(e)


# ============================================================================
# Topics
# ============================================================================

@router.post(
    "/forums/{forum_id}/topics",
    response_model=ForumTopicResponse,
    status_code=201,
)
def create_topic(
    forum_id: str,
    payload: ForumTopicCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_topic(
            db, forum_id=forum_id, author_id=current_user.id, data=payload,
        )
    except svc.ForumError as e:
        _err(e)


@router.get(
    "/forums/{forum_id}/topics",
    response_model=ForumTopicListResponse,
)
def list_topics(
    forum_id: str,
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = svc.list_topics(
            db, forum_id=forum_id,
            include_deleted=include_deleted,
            limit=limit, cursor=cursor,
        )
    except svc.ForumError as e:
        _err(e)
    return ForumTopicListResponse(**result)


@router.patch("/topics/{topic_id}", response_model=ForumTopicResponse)
def update_topic(
    topic_id: str,
    payload: ForumTopicUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_topic(
            db, topic_id=topic_id,
            actor_id=current_user.id, data=payload,
        )
    except svc.ForumError as e:
        _err(e)


@router.delete("/topics/{topic_id}", response_model=ForumTopicResponse)
def delete_topic(
    topic_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.delete_topic(
            db, topic_id=topic_id, actor_id=current_user.id,
        )
    except svc.ForumError as e:
        _err(e)


# ============================================================================
# Replies
# ============================================================================

@router.post(
    "/topics/{topic_id}/replies",
    response_model=ForumReplyResponse,
    status_code=201,
)
def create_reply(
    topic_id: str,
    payload: ForumReplyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_reply(
            db, topic_id=topic_id, author_id=current_user.id, data=payload,
        )
    except svc.ForumError as e:
        _err(e)


@router.get(
    "/topics/{topic_id}/replies",
    response_model=ForumReplyListResponse,
)
def list_replies(
    topic_id: str,
    include_deleted: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = svc.list_replies(
            db, topic_id=topic_id,
            include_deleted=include_deleted,
            limit=limit, cursor=cursor,
        )
    except svc.ForumError as e:
        _err(e)
    return ForumReplyListResponse(**result)


@router.delete("/replies/{reply_id}", response_model=ForumReplyResponse)
def delete_reply(
    reply_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.delete_reply(
            db, reply_id=reply_id, actor_id=current_user.id,
        )
    except svc.ForumError as e:
        _err(e)