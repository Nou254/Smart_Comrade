"""
Direct messaging endpoints — Communication module.

Routes:
  /conversation-requests          create / list incoming / list outgoing
  /conversation-requests/{id}     get, accept, reject, withdraw
  /conversations                  list inbox
  /conversations/{id}             get, mark read, update state
  /conversations/{id}/messages    list, send
  /messages/{id}                  edit, delete
  /blocks                         list mine, create
  /blocks/{blocked_id}            delete (unblock)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.messaging import (
    ConversationRequestCreate,
    ConversationRequestReject,
    ConversationRequestAccept,
    ConversationRequestWithdraw,
    ConversationRequestResponse,
    ConversationRequestListResponse,
    DirectConversationResponse,
    ConversationListItem,
    ConversationListResponse,
    ConversationStateUpdate,
    ConversationReadRequest,
    MessageSendRequest,
    MessageEditRequest,
    MessageResponse,
    MessageListResponse,
    BlockCreateRequest,
    BlockResponse,
    BlockListResponse,
)
from app.services import conversation_request_service as req_svc
from app.services import direct_message_service as dm_svc
from app.services import blocking_service as block_svc


router = APIRouter(tags=["Direct Messaging"])


def _err(e):
    raise HTTPException(
        status_code=getattr(e, "status_code", 400),
        detail=getattr(e, "message", str(e)),
    )


# ============================================================================
# Conversation requests
# ============================================================================

@router.post(
    "/conversation-requests",
    response_model=ConversationRequestResponse,
    status_code=201,
)
def create_conversation_request(
    payload: ConversationRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return req_svc.create_request(
            db,
            requester_id=current_user.id,
            recipient_id=payload.recipient_id,
            context_type=payload.context_type,
            context_ref_type=payload.context_ref_type,
            context_ref_id=payload.context_ref_id,
            message=payload.message,
        )
    except req_svc.ConversationRequestError as e:
        _err(e)


@router.get(
    "/conversation-requests/incoming",
    response_model=ConversationRequestListResponse,
)
def list_incoming_requests(
    status: str | None = Query("pending"),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = req_svc.list_incoming(
            db, user_id=current_user.id,
            status=status, limit=limit, cursor=cursor,
        )
    except req_svc.ConversationRequestError as e:
        _err(e)
    return ConversationRequestListResponse(**result)


@router.get(
    "/conversation-requests/outgoing",
    response_model=ConversationRequestListResponse,
)
def list_outgoing_requests(
    status: str | None = Query("pending"),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = req_svc.list_outgoing(
            db, user_id=current_user.id,
            status=status, limit=limit, cursor=cursor,
        )
    except req_svc.ConversationRequestError as e:
        _err(e)
    return ConversationRequestListResponse(**result)


@router.get(
    "/conversation-requests/{request_id}",
    response_model=ConversationRequestResponse,
)
def get_conversation_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return req_svc.get_request(db, request_id, current_user.id)
    except req_svc.ConversationRequestError as e:
        _err(e)


@router.post(
    "/conversation-requests/{request_id}/accept",
    response_model=ConversationRequestResponse,
)
def accept_conversation_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        req, _conv = req_svc.accept_request(
            db, request_id=request_id, actor_id=current_user.id,
        )
        return req
    except req_svc.ConversationRequestError as e:
        _err(e)


@router.post(
    "/conversation-requests/{request_id}/reject",
    response_model=ConversationRequestResponse,
)
def reject_conversation_request(
    request_id: str,
    payload: ConversationRequestReject,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return req_svc.reject_request(
            db, request_id=request_id,
            actor_id=current_user.id, reason=payload.reason,
        )
    except req_svc.ConversationRequestError as e:
        _err(e)


@router.post(
    "/conversation-requests/{request_id}/withdraw",
    response_model=ConversationRequestResponse,
)
def withdraw_conversation_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return req_svc.withdraw_request(
            db, request_id=request_id, actor_id=current_user.id,
        )
    except req_svc.ConversationRequestError as e:
        _err(e)


# ============================================================================
# Conversations
# ============================================================================

@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = dm_svc.list_my_conversations(
            db, viewer_id=current_user.id,
            include_archived=include_archived,
            limit=limit, cursor=cursor,
        )
    except dm_svc.DirectMessageError as e:
        _err(e)

    items = []
    for row in result["conversations"]:
        conv = row["conversation"]
        items.append(ConversationListItem(
            id=conv.id,
            other_user_id=row["other_user_id"],
            other_user_name=None,
            status=conv.status,
            is_blocked=conv.is_blocked,
            is_muted=row["is_muted"],
            is_archived=row["is_archived"],
            last_message_at=conv.last_message_at,
            last_message_preview=conv.last_message_preview,
            unread_count=row["unread_count"],
        ))
    return ConversationListResponse(
        conversations=items,
        next_cursor=result["next_cursor"],
        has_more=result["has_more"],
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=DirectConversationResponse,
)
def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return dm_svc.get_conversation(
            db, conversation_id=conversation_id,
            viewer_id=current_user.id,
        )
    except dm_svc.DirectMessageError as e:
        _err(e)


@router.post("/conversations/{conversation_id}/read")
def mark_conversation_read(
    conversation_id: str,
    payload: ConversationReadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        dm_svc.mark_read(
            db,
            conversation_id=conversation_id,
            viewer_id=current_user.id,
            up_to_message_id=payload.up_to_message_id,
        )
        return {"ok": True}
    except dm_svc.DirectMessageError as e:
        _err(e)


@router.patch("/conversations/{conversation_id}")
def update_conversation_state(
    conversation_id: str,
    payload: ConversationStateUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        p = dm_svc.update_conversation_state(
            db,
            conversation_id=conversation_id,
            viewer_id=current_user.id,
            is_muted=payload.is_muted,
            is_archived=payload.is_archived,
        )
        return {"is_muted": p.is_muted, "is_archived": p.is_archived}
    except dm_svc.DirectMessageError as e:
        _err(e)


# ============================================================================
# Messages
# ============================================================================

@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
def list_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = dm_svc.list_messages(
            db,
            conversation_id=conversation_id,
            viewer_id=current_user.id,
            limit=limit, cursor=cursor,
        )
    except dm_svc.DirectMessageError as e:
        _err(e)
    return MessageListResponse(**result)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
)
def send_message(
    conversation_id: str,
    payload: MessageSendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return dm_svc.send_message(
            db,
            conversation_id=conversation_id,
            sender_id=current_user.id,
            content=payload.content,
            reply_to_id=payload.reply_to_id,
        )
    except dm_svc.DirectMessageError as e:
        _err(e)


@router.patch("/messages/{message_id}", response_model=MessageResponse)
def edit_message(
    message_id: str,
    payload: MessageEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return dm_svc.edit_message(
            db, message_id=message_id,
            sender_id=current_user.id,
            new_content=payload.content,
        )
    except dm_svc.DirectMessageError as e:
        _err(e)


@router.delete("/messages/{message_id}", response_model=MessageResponse)
def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return dm_svc.delete_message(
            db, message_id=message_id, actor_id=current_user.id,
        )
    except dm_svc.DirectMessageError as e:
        _err(e)


# ============================================================================
# Blocks
# ============================================================================

@router.get("/blocks", response_model=BlockListResponse)
def list_my_blocks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = block_svc.list_my_blocks(db, blocker_id=current_user.id)
    return BlockListResponse(
        blocks=[BlockResponse.model_validate(b) for b in rows],
        total=len(rows),
    )


@router.post("/blocks", response_model=BlockResponse, status_code=201)
def create_block(
    payload: BlockCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return block_svc.block_user(
            db,
            blocker_id=current_user.id,
            blocked_id=payload.blocked_id,
            reason=payload.reason,
        )
    except block_svc.BlockingError as e:
        _err(e)


@router.delete("/blocks/{blocked_id}")
def remove_block(
    blocked_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = block_svc.unblock_user(
        db, blocker_id=current_user.id, blocked_id=blocked_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Block not found.")
    return {"ok": True}