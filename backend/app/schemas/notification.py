"""
Pydantic schemas for persistent notifications.

NotificationCreate is internal — other services call notification_store
directly with the same field set. Kept here so the shape is documented
in one place.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Create (internal)
# ============================================================================

class NotificationCreate(BaseModel):
    user_ids: list[str] = Field(..., min_length=1)
    category: str = Field(
        ...,
        description=(
            "academic | assessment | election | impeachment | event | "
            "administrative | opportunity | project | announcement | "
            "emergency | system | security"
        ),
    )
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=10000)
    priority: str = Field(
        "normal", description="normal | important | critical",
    )
    source_type: str | None = Field(None, max_length=32)
    source_id: str | None = Field(None, max_length=36)
    link_url: str | None = Field(None, max_length=500)
    payload_json: dict | None = None
    requires_acknowledgment: bool = False
    expires_at: datetime | None = None
    is_system_generated: bool = False


# ============================================================================
# Response
# ============================================================================

class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    category: str
    priority: str
    title: str
    body: str
    source_type: str | None
    source_id: str | None
    link_url: str | None
    payload_json: dict | None
    status: str
    is_system_generated: bool
    requires_acknowledgment: bool
    delivered_at: datetime | None
    read_at: datetime | None
    dismissed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    next_cursor: str | None
    has_more: bool
    unread_count: int


class NotificationCountResponse(BaseModel):
    unread: int
    pending_acknowledgment: int


# ============================================================================
# Mutations
# ============================================================================

class NotificationMarkReadRequest(BaseModel):
    """
    If notification_ids is omitted → marks all the viewer's unread
    notifications as read.
    """
    notification_ids: list[str] | None = None


class NotificationMarkReadResponse(BaseModel):
    marked_read: int


class NotificationDismissResponse(BaseModel):
    dismissed: bool