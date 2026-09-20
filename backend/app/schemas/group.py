"""
Pydantic schemas for Student Groups.

Includes the security-layer additions:
  - GroupResponse carries the permanent slug
  - GroupInvitePreview carries both token and slug context
  - Join-request lifecycle schemas
  - Invite rotation schemas
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# GROUP — CREATE / UPDATE / RESPONSE
# ============================================================================

class GroupCreateWithContext(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = None

    institution_id: str
    school_id: str
    course_id: str
    academic_year_id: str
    semester_id: str
    combination_id: str | None = Field(
        None,
        description="Required only when the course has combinations defined.",
    )
    year_level: int = Field(..., ge=1, le=10)

    visibility: str = Field("invitation_only")
    max_members: int = Field(60, ge=2, le=200)


class GroupCreate(BaseModel):
    """Legacy shape kept for backward compatibility."""
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = None
    institution_id: str
    school_id: str
    course_id: str
    academic_year_id: str
    semester_id: str
    unit_id: str | None = None
    visibility: str = Field("invitation_only")
    max_members: int = Field(60, ge=2, le=200)


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=150)
    description: str | None = None
    visibility: str | None = None
    max_members: int | None = Field(None, ge=2, le=200)
    status: str | None = None


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    group_type: str
    slug: str
    institution_id: str
    school_id: str
    course_id: str
    combination_id: str | None
    academic_year_id: str
    semester_id: str
    year_level: int | None
    unit_id: str | None
    creator_id: str
    is_provisional: bool
    status: str
    visibility: str
    subscription_status: str
    invite_expires_at: datetime | None
    election_triggered_at: datetime | None
    max_members: int
    member_count: int
    trial_ends_at: datetime | None
    subscription_expires_at: datetime | None
    created_at: datetime


class GroupCreatedResponse(BaseModel):
    """Returned exactly once, when a group is created or its token rotated."""
    group: GroupResponse
    invite_token: str
    invite_expires_at: datetime
    invite_url: str
    slug_url: str


# ============================================================================
# MEMBERSHIP
# ============================================================================

class GroupJoinRequestSubmit(BaseModel):
    """Visitor's submission when arriving via token or slug link."""
    course_confirmed: bool = Field(
        ...,
        description="Visitor confirms they are on this course/semester.",
    )
    unit_confirmations: list["UnitConfirmationInput"] = Field(
        ...,
        min_length=1,
        description="One entry per unit in the group's curated list.",
    )
    message: str | None = Field(
        None,
        max_length=500,
        description="Optional short message to the group leader.",
    )


class UnitConfirmationInput(BaseModel):
    group_unit_id: str
    confirmed: bool
    flagged_as_incorrect: bool = False
    note: str | None = Field(None, max_length=500)


class GroupJoinRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    user_id: str
    status: str
    source: str
    message: str | None
    course_confirmed: bool
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    expires_at: datetime | None
    created_at: datetime


class GroupJoinRequestDecision(BaseModel):
    approve: bool = Field(
        ..., description="True to approve the request; False to reject."
    )
    notes: str | None = Field(
        None,
        max_length=500,
        description="Required when rejecting — reason goes to the visitor.",
    )

class MembershipUpdate(BaseModel):
    status: str = Field(..., description="active | suspended | removed")


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    user_id: str
    status: str
    joined_via_invite: bool
    course_confirmed_at: datetime | None
    units_confirmed_at: datetime | None
    joined_at: datetime | None
    left_at: datetime | None
    invited_by: str | None
    approved_by: str | None
    notes: str | None
    created_at: datetime


class LegacyJoinNotes(BaseModel):
    """Body for the legacy POST /groups/{id}/members/join endpoint."""
    notes: str | None = None

class GroupJoinRequestResult(BaseModel):
    request_id: str
    status: str
    membership_id: str | None
    message: str

class LegacyJoinNotes(BaseModel):
    """Body for the legacy POST /groups/{id}/members/join endpoint."""
    notes: str | None = None

# ============================================================================
# INVITE / SLUG PREVIEW
# ============================================================================

class GroupUnitPreview(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str


class GroupInvitePreview(BaseModel):
    """Preview shown before submitting a join request."""
    group_id: str
    group_name: str
    group_slug: str
    description: str | None
    institution_name: str
    school_name: str
    course_name: str
    course_code: str
    semester_name: str
    year_level: int | None
    member_count: int
    max_members: int
    status: str
    invite_valid: bool
    invite_expires_at: datetime | None
    # Source of the preview — 'invite_token' or 'slug_link'
    source: str
    units: list[GroupUnitPreview]


class InviteRotationResponse(BaseModel):
    group_id: str
    invite_token: str
    invite_expires_at: datetime
    invite_url: str
    message: str


# ============================================================================
# GROUP UNITS — CURATION
# ============================================================================

class GroupUnitCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=2, max_length=200)
    description: str | None = None
    year_level: int | None = Field(None, ge=1, le=10)
    semester_number: int | None = Field(None, ge=1, le=3)
    unit_id: str | None = None
    source: str = Field("manual")
    source_extracted_unit_id: str | None = None


class GroupUnitsCurateRequest(BaseModel):
    units: list[GroupUnitCreate] = Field(..., min_length=1)


class GroupUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    code: str
    name: str
    description: str | None
    year_level: int | None
    semester_number: int | None
    unit_id: str | None
    source: str
    created_by: str
    created_at: datetime


# ============================================================================
# SUBSCRIPTION
# ============================================================================

class GroupSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    status: str
    is_trial: bool
    member_count_at_payment: int
    amount_paid: int
    currency: str
    period_start: datetime
    period_end: datetime
    payment_reference: str | None
    paid_at: datetime | None
    notes: str | None
    created_at: datetime


class SubscriptionCalculationResponse(BaseModel):
    member_count: int
    amount: int
    currency: str
    breakdown: dict


class SubscriptionRenewRequest(BaseModel):
    payment_reference: str = Field(..., min_length=3, max_length=128)
    notes: str | None = Field(None, max_length=500)


# ============================================================================
# ELIGIBILITY
# ============================================================================

class GroupEligibilityResponse(BaseModel):
    group_id: str
    eligible: bool
    member_count: int
    required_members: int
    subscription_status: str
    subscription_current: bool
    blockers: list[str]
    notes: str | None = None


# ============================================================================
# OFFICIALS / MEETINGS / ACTIVITIES / ANNOUNCEMENTS / TIMETABLES
# (unchanged from current)
# ============================================================================

class OfficialAppoint(BaseModel):
    user_id: str
    position: str = Field(..., description="leader | secretary | treasurer | unit_representative")
    unit_id: str | None = None
    term_start: datetime | None = None
    term_end: datetime | None = None
    notes: str | None = None


class OfficialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    user_id: str
    position: str
    unit_id: str | None
    term_start: datetime | None
    term_end: datetime | None
    status: str
    appointed_by: str | None
    notes: str | None
    created_at: datetime


class MeetingCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    agenda: str | None = None
    scheduled_at: datetime
    duration_minutes: int | None = Field(None, ge=5, le=480)
    location: str | None = None
    virtual_link: str | None = None


class MeetingUpdate(BaseModel):
    title: str | None = None
    agenda: str | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = None
    location: str | None = None
    virtual_link: str | None = None
    status: str | None = None


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    title: str
    agenda: str | None
    scheduled_at: datetime
    duration_minutes: int | None
    location: str | None
    virtual_link: str | None
    status: str
    created_by: str
    created_at: datetime


class ActivityCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: str | None = None
    activity_type: str = Field(..., description="study_session|revision|project|social|event|other")
    start_time: datetime
    end_time: datetime | None = None
    location: str | None = None
    virtual_link: str | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    title: str
    description: str | None
    activity_type: str
    start_time: datetime
    end_time: datetime | None
    location: str | None
    virtual_link: str | None
    status: str
    created_by: str
    created_at: datetime


class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=1)
    priority: str = Field("normal", description="normal | important | critical")
    is_pinned: bool = False


class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    title: str
    content: str
    priority: str
    is_pinned: bool
    is_archived: bool
    published_by: str
    published_at: datetime
    created_at: datetime


class TimetableCreate(BaseModel):
    type: str = Field(..., description="official | revision")
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = None


class TimetableEntryCreate(BaseModel):
    unit_id: str | None = None
    day_of_week: int | None = Field(None, ge=0, le=6)
    start_time: str = Field(..., description="HH:MM (24-hour)")
    end_time: str = Field(..., description="HH:MM (24-hour)")
    activity_type: str | None = None
    location: str | None = None
    notes: str | None = None


class TimetableEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    timetable_id: str
    unit_id: str | None
    day_of_week: int | None
    start_time: str
    end_time: str
    activity_type: str | None
    location: str | None
    notes: str | None


class TimetableApprovalAction(BaseModel):
    approved: bool
    comments: str | None = None


class TimetableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    type: str
    name: str
    description: str | None
    created_by: str
    approval_status: str
    approved_at: datetime | None
    created_at: datetime


# Forward reference resolution
GroupJoinRequestSubmit.model_rebuild()