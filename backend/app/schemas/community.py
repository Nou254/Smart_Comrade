"""
Pydantic schemas for Communication Communities — Module 003 Phase 11.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# COMMUNITY
# ============================================================================

class CommunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_type: str
    institution_id: str
    school_id: str | None
    course_id: str | None
    year_level: int | None
    combination_id: str | None
    academic_year_id: str | None
    name: str
    description: str | None
    max_message_length: int
    is_active: bool
    member_count: int
    created_at: datetime


class CommunityMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_id: str
    user_id: str
    role: str
    is_active: bool
    joined_at: datetime
    left_at: datetime | None
    muted_until: datetime | None
    banned_at: datetime | None
    ban_reason: str | None


class CommunityDetailResponse(BaseModel):
    """Community + viewer's membership in one call."""
    community: CommunityResponse
    viewer_membership: CommunityMembershipResponse | None
    is_moderator: bool


# ============================================================================
# MESSAGES
# ============================================================================

class CommunityMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    reply_to_id: str | None = None


class CommunityMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_id: str
    sender_id: str
    content: str
    reply_to_id: str | None
    is_deleted: bool
    is_hidden: bool
    created_at: datetime
    updated_at: datetime


class CommunityMessageListResponse(BaseModel):
    """Paginated list of messages."""
    messages: list[CommunityMessageResponse]
    next_cursor: str | None
    has_more: bool


# ============================================================================
# MODERATION
# ============================================================================

class CommunityReportRequest(BaseModel):
    reason: str = Field(
        ...,
        description=(
            "spam | harassment | hate_speech | misinformation | "
            "off_topic | academic_integrity | other"
        ),
    )
    notes: str | None = Field(None, max_length=1000)


class CommunityReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    reporter_id: str
    reason: str
    notes: str | None
    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime


class CommunityReportReviewRequest(BaseModel):
    """Moderator decision on a report."""
    status: str = Field(
        ..., description="resolved | dismissed",
    )
    review_notes: str | None = Field(None, max_length=1000)
    # Optional actions to apply alongside the decision
    delete_message: bool = False
    hide_message: bool = False


class CommunityMuteRequest(BaseModel):
    until_at: datetime
    reason: str = Field(..., min_length=3, max_length=500)


class CommunityBanRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class CommunityModerationActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_id: str
    moderator_id: str
    target_user_id: str | None
    target_message_id: str | None
    action_type: str
    reason: str | None
    until_at: datetime | None
    created_at: datetime


# ============================================================================
# ADMIN VIEWS
# ============================================================================

class CommunityStatsResponse(BaseModel):
    community_id: str
    member_count: int
    active_member_count: int
    message_count_total: int
    message_count_last_24h: int
    message_count_last_7d: int
    reports_pending: int
    muted_members: int
    banned_members: int


class CommunityListResponse(BaseModel):
    """Lightweight list item for the communities list page."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_type: str
    name: str
    description: str | None
    member_count: int
    is_active: bool