"""
Pydantic schemas for discussion forums.

Rules (from the corrected spec):
  - Anyone can create a forum.
  - Institution-scoped forums require Institution Admin approval.
  - Must be created >= 3 days before starts_at.
  - Creator is the moderator.
  - Join clicks are recorded; the creator sees the participant list.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Forum
# ============================================================================

class ForumCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(None, max_length=5000)
    scope_type: str = Field(
        "public",
        description=(
            "public | group | unit | school | institution | county"
        ),
    )
    scope_ref_id: str | None = Field(None, min_length=36, max_length=36)
    visibility: str = Field(
        "public", description="public | restricted",
    )
    category: str = Field("general", max_length=32)
    starts_at: datetime
    ends_at: datetime | None = None
    google_meet_link: str | None = Field(None, max_length=500)
    location: str | None = Field(None, max_length=255)


class ForumUpdate(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = None
    visibility: str | None = None
    is_active: bool | None = None
    is_archived: bool | None = None
    google_meet_link: str | None = Field(None, max_length=500)
    location: str | None = Field(None, max_length=255)


class ForumResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None
    scope_type: str
    scope_ref_id: str | None
    visibility: str
    category: str
    starts_at: datetime
    ends_at: datetime | None
    google_meet_link: str | None
    location: str | None
    creator_id: str
    moderator_id: str
    status: str
    requires_approval: bool
    is_active: bool
    is_archived: bool
    participant_count: int
    topic_count: int
    reply_count: int
    created_at: datetime
    updated_at: datetime


class ForumListResponse(BaseModel):
    forums: list[ForumResponse]
    next_cursor: str | None
    has_more: bool


# ============================================================================
# Approval request (institution-scoped forums only)
# ============================================================================

class ForumApprovalDecision(BaseModel):
    """Institution Admin approves or rejects a scoped forum."""
    approve: bool
    notes: str | None = Field(None, max_length=2000)


class ForumApprovalRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    forum_id: str
    requester_id: str
    requested_at: datetime
    reviewer_id: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Join
# ============================================================================

class ForumJoinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    forum_id: str
    user_id: str
    joined_at: datetime
    left_at: datetime | None


class ForumParticipantListResponse(BaseModel):
    """What the forum creator sees — users who clicked join."""
    participants: list[ForumJoinResponse]
    total: int


# ============================================================================
# Topic
# ============================================================================

class ForumTopicCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    body: str = Field(..., min_length=1, max_length=50000)


class ForumTopicUpdate(BaseModel):
    """Only moderator can pin / lock."""
    is_pinned: bool | None = None
    is_locked: bool | None = None


class ForumTopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    forum_id: str
    author_id: str
    title: str
    body: str
    is_pinned: bool
    is_locked: bool
    is_deleted: bool
    reply_count: int
    last_reply_at: datetime | None
    last_reply_by_id: str | None
    created_at: datetime
    updated_at: datetime


class ForumTopicListResponse(BaseModel):
    topics: list[ForumTopicResponse]
    next_cursor: str | None
    has_more: bool


# ============================================================================
# Reply
# ============================================================================

class ForumReplyCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=50000)
    parent_id: str | None = Field(None, min_length=36, max_length=36)


class ForumReplyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_id: str
    author_id: str
    parent_id: str | None
    body: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class ForumReplyListResponse(BaseModel):
    replies: list[ForumReplyResponse]
    next_cursor: str | None
    has_more: bool