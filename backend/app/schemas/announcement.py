"""
Pydantic schemas for official announcements.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Create / update
# ============================================================================

class AnnouncementCreate(BaseModel):
    level: str = Field(
        ...,
        description=(
            "group | unit | school | institution | county | platform"
        ),
    )
    scope_ref_id: str | None = Field(None, min_length=36, max_length=36)
    classification: str = Field(
        ...,
        description=(
            "academic | administrative | election | assessment | "
            "event | emergency | opportunity | project | general"
        ),
    )
    priority: str = Field(
        "normal", description="normal | important | critical",
    )
    title: str = Field(..., min_length=3, max_length=255)
    content: str = Field(..., min_length=1, max_length=50000)
    is_pinned: bool = False
    scheduled_for: datetime | None = None
    expires_at: datetime | None = None


class AnnouncementUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    content: str | None = Field(None, min_length=1, max_length=50000)
    is_pinned: bool | None = None
    is_archived: bool | None = None
    priority: str | None = None
    expires_at: datetime | None = None


class AnnouncementCorrectionRequest(BaseModel):
    """Publish a correction that points back at the original."""
    correction_title: str = Field(..., min_length=3, max_length=255)
    correction_body: str = Field(..., min_length=1, max_length=50000)


# ============================================================================
# Response
# ============================================================================

class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    publisher_id: str
    publisher_role: str
    level: str
    scope_ref_id: str | None
    classification: str
    priority: str
    title: str
    content: str
    is_pinned: bool
    is_archived: bool
    correction_of_id: str | None
    status: str
    scheduled_for: datetime | None
    published_at: datetime | None
    archived_at: datetime | None
    expires_at: datetime | None
    audience_count: int
    created_at: datetime
    updated_at: datetime


class AnnouncementListItem(BaseModel):
    """Compact row for list views — folded read state for the viewer."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    level: str
    classification: str
    priority: str
    title: str
    is_pinned: bool
    is_archived: bool
    published_at: datetime | None
    is_read: bool = False


class AnnouncementListResponse(BaseModel):
    announcements: list[AnnouncementListItem]
    next_cursor: str | None
    has_more: bool


# ============================================================================
# Audience snapshot
# ============================================================================

class AnnouncementAudienceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    announcement_id: str
    user_id: str
    delivered_at: datetime
    is_read: bool
    read_at: datetime | None
    is_still_eligible: bool


class AnnouncementAudienceListResponse(BaseModel):
    audience: list[AnnouncementAudienceItem]
    next_cursor: str | None
    has_more: bool