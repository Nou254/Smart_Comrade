"""
Pydantic schemas for direct messaging + blocking.

Covers:
  - ConversationRequest lifecycle (create, accept, reject, withdraw)
  - DirectConversation read/state
  - DirectMessage send / list / edit / delete
  - UserBlock
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# ConversationRequest — the DM proposal gate
# ============================================================================

class ConversationRequestCreate(BaseModel):
    """
    Start a new contact request. The recipient must accept before any
    message can be sent. Which direction is allowed depends on the
    requester's and recipient's user types — enforced by the service.
    """
    recipient_id: str = Field(..., min_length=36, max_length=36)
    context_type: str = Field(
        ...,
        description=(
            "student_to_student | student_to_external | external_to_student"
        ),
    )
    context_ref_type: str | None = Field(None, max_length=32)
    context_ref_id: str | None = Field(None, max_length=36)
    message: str | None = Field(None, max_length=2000)


class ConversationRequestAccept(BaseModel):
    """Accept the request. A DirectConversation is created."""


class ConversationRequestReject(BaseModel):
    """Reject the request. Optional short reason shown to requester."""
    reason: str | None = Field(None, max_length=500)


class ConversationRequestWithdraw(BaseModel):
    """Requester withdraws their own pending request."""


class ConversationRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    requester_id: str
    recipient_id: str
    context_type: str
    context_ref_type: str | None
    context_ref_id: str | None
    message: str | None
    status: str
    conversation_id: str | None
    resolved_at: datetime | None
    rejection_reason: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationRequestListResponse(BaseModel):
    requests: list[ConversationRequestResponse]
    next_cursor: str | None
    has_more: bool


# ============================================================================
# DirectConversation
# ============================================================================

class DirectConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_key: str
    origin_request_id: str | None
    status: str
    is_blocked: bool
    last_message_at: datetime | None
    last_message_preview: str | None
    last_message_sender_id: str | None
    created_at: datetime
    updated_at: datetime


class ConversationListItem(BaseModel):
    """Inbox row — viewer-specific state folded in."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    other_user_id: str
    other_user_name: str | None = None
    status: str
    is_blocked: bool
    is_muted: bool
    is_archived: bool
    last_message_at: datetime | None
    last_message_preview: str | None
    unread_count: int


class ConversationListResponse(BaseModel):
    conversations: list[ConversationListItem]
    next_cursor: str | None
    has_more: bool


class ConversationStateUpdate(BaseModel):
    """Mute / archive toggles for the viewer only."""
    is_muted: bool | None = None
    is_archived: bool | None = None


class ConversationReadRequest(BaseModel):
    """Mark the conversation read up to a specific message (or now)."""
    up_to_message_id: str | None = Field(None, min_length=36, max_length=36)


# ============================================================================
# DirectMessage
# ============================================================================

class MessageSendRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    reply_to_id: str | None = Field(None, min_length=36, max_length=36)


class MessageEditRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    sender_id: str
    content: str
    reply_to_id: str | None
    is_edited: bool
    edited_at: datetime | None
    is_deleted: bool
    is_reported: bool
    created_at: datetime
    updated_at: datetime


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    next_cursor: str | None
    has_more: bool


# ============================================================================
# UserBlock
# ============================================================================

class BlockCreateRequest(BaseModel):
    blocked_id: str = Field(..., min_length=36, max_length=36)
    reason: str | None = Field(None, max_length=2000)


class BlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    blocker_id: str
    blocked_id: str
    reason: str | None
    created_at: datetime


class BlockListResponse(BaseModel):
    blocks: list[BlockResponse]
    total: int