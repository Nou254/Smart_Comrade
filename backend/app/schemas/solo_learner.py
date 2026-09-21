"""
Pydantic schemas for Solo Learner path — Module 003.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# SUBSCRIPTION
# ============================================================================

class SoloSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    status: str
    amount_paid: int
    currency: str
    period_start: datetime
    period_end: datetime
    payment_reference: str | None
    paid_at: datetime | None
    cancelled_at: datetime | None
    cancelled_reason: str | None
    created_at: datetime


class SoloSubscribeRequest(BaseModel):
    payment_reference: str = Field(..., min_length=3, max_length=128)


# ============================================================================
# DISCOVERY
# ============================================================================

class SoloLearnerCard(BaseModel):
    """Compact representation used in discovery lists."""
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    first_name: str
    last_name: str
    institution_id: str | None
    course_id: str | None
    year_level: int | None
    interests: list[str] | None = None


class SoloLearnerListResponse(BaseModel):
    learners: list[SoloLearnerCard]
    next_cursor: str | None
    has_more: bool


class SoloDiscoverFilters(BaseModel):
    course_id: str | None = None
    year_level: int | None = None
    interest: str | None = None


# ============================================================================
# LEARNING SESSIONS
# ============================================================================

class SoloSessionCreate(BaseModel):
    partner_id: str
    title: str = Field(..., min_length=2, max_length=200)
    description: str | None = Field(None, max_length=2000)
    scheduled_at: datetime
    duration_minutes: int = Field(60, ge=15, le=480)


class SoloSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    initiator_id: str
    partner_id: str
    title: str
    description: str | None
    scheduled_at: datetime
    duration_minutes: int
    status: str
    accepted_at: datetime | None
    declined_at: datetime | None
    declined_reason: str | None
    completed_at: datetime | None
    created_at: datetime


class SoloSessionDecision(BaseModel):
    accept: bool
    decline_reason: str | None = Field(None, max_length=500)