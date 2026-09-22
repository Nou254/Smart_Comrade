"""
Pydantic schemas for Unit Representation — Module 004.

Design decisions:
  - Network archived when semester ends
  - Rep replacement removes rep silently
  - Shared resources AI-scanned for unit relevance
  - Educational questions answered by AI within 5 minutes
  - Reps can raise questions for anonymous students
  - Non-reps see public issue summaries and outcomes
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ═════════════════════════════════════════════════════════════════════════
# UNIT REPRESENTATIVES
# ═════════════════════════════════════════════════════════════════════════

class UnitRepresentativeAppoint(BaseModel):
    """Group Leader appoints a member as Unit Rep for a specific offering."""
    group_id: str
    unit_offering_id: str
    user_id: str
    notes: str | None = Field(None, max_length=2000)


class UnitRepresentativeEnd(BaseModel):
    """End an appointment. Reason is required."""
    reason: str = Field(..., min_length=3, max_length=500)


class UnitRepresentativeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    group_id: str
    unit_offering_id: str
    semester_id: str
    user_id: str
    appointed_by: str
    appointed_at: datetime
    status: str
    term_start: datetime
    term_end: datetime | None
    ended_reason: str | None
    replaced_by_id: str | None
    notes: str | None
    created_at: datetime


class UnitRepresentativeListResponse(BaseModel):
    """Lightweight list item."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    group_id: str
    unit_offering_id: str
    user_id: str
    status: str
    term_start: datetime
    term_end: datetime | None


# ═════════════════════════════════════════════════════════════════════════
# UNIT NETWORKS
# ═════════════════════════════════════════════════════════════════════════

class UnitNetworkMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    network_id: str
    representative_id: str | None
    user_id: str
    role_in_network: str
    is_active: bool
    joined_at: datetime
    left_at: datetime | None
    left_reason: str | None


class UnitNetworkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    semester_id: str
    supervisor_user_id: str | None
    is_active: bool
    archived_at: datetime | None
    created_at: datetime


class UnitNetworkDetailResponse(BaseModel):
    """Network + member roster in one call."""
    network: UnitNetworkResponse
    members: list[UnitNetworkMemberResponse]


# ═════════════════════════════════════════════════════════════════════════
# NETWORK COORDINATION MESSAGES
# ═════════════════════════════════════════════════════════════════════════

class UnitCoordinationMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    reply_to_id: str | None = None


class UnitCoordinationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    network_id: str
    sender_id: str
    content: str
    reply_to_id: str | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class UnitCoordinationMessageListResponse(BaseModel):
    """Paginated list of network messages."""
    messages: list[UnitCoordinationMessageResponse]
    next_cursor: str | None
    has_more: bool


# ═════════════════════════════════════════════════════════════════════════
# UNIT DISCUSSIONS
# ═════════════════════════════════════════════════════════════════════════

class UnitDiscussionCreate(BaseModel):
    title: str | None = Field(None, max_length=200)
    content: str = Field(..., min_length=1, max_length=5000)
    parent_id: str | None = None


class UnitDiscussionUpdate(BaseModel):
    is_pinned: bool | None = None
    is_locked: bool | None = None


class UnitDiscussionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    author_id: str
    parent_id: str | None
    title: str | None
    content: str
    is_pinned: bool
    is_locked: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# UNIT ANNOUNCEMENTS
# ═════════════════════════════════════════════════════════════════════════

class UnitAnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    content: str = Field(..., min_length=1, max_length=10000)
    is_pinned: bool = False


class UnitAnnouncementUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    content: str | None = Field(None, min_length=1, max_length=10000)
    is_pinned: bool | None = None
    is_archived: bool | None = None


class UnitAnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    publisher_id: str
    publisher_role: str
    title: str
    content: str
    is_pinned: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# UNIT ISSUES
# ═════════════════════════════════════════════════════════════════════════

class UnitIssueCreate(BaseModel):
    category: str = Field(
        ...,
        description=(
            "content | resource | scheduling | assessment | "
            "practical | communication | other"
        ),
    )
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=10, max_length=5000)
    is_anonymous: bool = False
    anonymous_student_reference: str | None = Field(
        None, max_length=128,
        description="Internal reference for tracking anonymous students.",
    )
    is_public: bool = True
    public_summary: str | None = Field(None, max_length=2000)


class UnitIssueEscalate(BaseModel):
    to_level: str = Field(
        ...,
        description=(
            "network | supervisor | lecturer | school | institution"
        ),
    )
    notes: str | None = Field(None, max_length=2000)


class UnitIssueResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=5, max_length=2000)


class UnitIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    raised_by_representative_id: str
    raised_by_user_id: str
    is_anonymous: bool
    anonymous_student_reference: str | None
    category: str
    title: str
    description: str
    status: str
    current_escalation_level: str
    current_escalation_target_user_id: str | None
    is_public: bool
    public_summary: str | None
    resolved_at: datetime | None
    resolution_notes: str | None
    created_at: datetime
    updated_at: datetime


class UnitIssuePublicResponse(BaseModel):
    """Non-rep view — hides sensitive fields."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    category: str
    title: str
    public_summary: str | None
    status: str
    resolved_at: datetime | None
    resolution_notes: str | None
    created_at: datetime


class UnitIssueListResponse(BaseModel):
    """List of public issue summaries."""
    issues: list[UnitIssuePublicResponse]


# ═════════════════════════════════════════════════════════════════════════
# UNIT ISSUE ESCALATIONS
# ═════════════════════════════════════════════════════════════════════════

class UnitIssueEscalationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    issue_id: str
    from_level: str
    to_level: str
    escalated_by_user_id: str
    escalated_at: datetime
    notes: str | None
    response_user_id: str | None
    response_at: datetime | None
    response_notes: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# UNIT QUESTIONS (AI-assisted educational research)
# ═════════════════════════════════════════════════════════════════════════

class UnitQuestionCreate(BaseModel):
    subject: str = Field(..., min_length=3, max_length=255)
    question_text: str = Field(..., min_length=10, max_length=5000)
    category: str = Field(
        "educational",
        description=(
            "educational | content_clarification | "
            "resource_verification | assessment_format | other_educational"
        ),
    )
    is_anonymous: bool = False
    anonymous_student_reference: str | None = Field(
        None, max_length=128,
        description=(
            "Internal reference identifying the anonymous student. "
            "Never exposed publicly."
        ),
    )


class UnitQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    raised_by_representative_id: str | None
    raised_by_user_id: str
    is_anonymous: bool
    anonymous_student_reference: str | None
    subject: str
    question_text: str
    category: str
    status: str
    posed_at: datetime
    ai_response_deadline: datetime
    ai_responded_at: datetime | None
    supervisor_notified_at: datetime | None
    resolved_at: datetime | None
    resolution_notes: str | None
    created_at: datetime


class UnitQuestionListItem(BaseModel):
    """Compact form for list views."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject: str
    category: str
    status: str
    posed_at: datetime
    ai_responded_at: datetime | None
    resolved_at: datetime | None


# ═════════════════════════════════════════════════════════════════════════
# UNIT QUESTION RESPONSES
# ═════════════════════════════════════════════════════════════════════════

class UnitQuestionSupervisorResponseCreate(BaseModel):
    """Supervisor posts a response (may supersede an earlier AI response)."""
    content: str = Field(..., min_length=5, max_length=10000)
    supersedes_response_id: str | None = Field(
        None,
        description="If set, this response overrides an earlier AI response.",
    )


class UnitQuestionResponseItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question_id: str
    responder_type: str
    responder_user_id: str | None
    content: str
    research_sources_json: list | None
    confidence_score: float | None
    superseded_by_response_id: str | None
    created_at: datetime


class UnitQuestionDetailResponse(BaseModel):
    """Question + all responses in one call."""
    question: UnitQuestionResponse
    responses: list[UnitQuestionResponseItem]


# ═════════════════════════════════════════════════════════════════════════
# UNIT SHARED RESOURCES
# ═════════════════════════════════════════════════════════════════════════

class UnitSharedResourceCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: str | None = Field(None, max_length=2000)
    resource_type: str = Field(
        "document",
        description="document | link | note | code",
    )
    file_url: str | None = Field(None, max_length=500)
    external_url: str | None = Field(None, max_length=500)
    content_text: str | None = Field(None, max_length=50000)
    visibility: str = Field(
        "network_only",
        description="network_only | all_unit_students",
    )
    source_group_id: str | None = Field(
        None,
        description=(
            "If the resource was cross-posted from an existing group "
            "resource, the source group id."
        ),
    )


class UnitSharedResourceUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = Field(None, max_length=2000)
    visibility: str | None = None


class UnitSharedResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    shared_by_user_id: str
    source_group_id: str | None
    title: str
    description: str | None
    resource_type: str
    file_url: str | None
    external_url: str | None
    content_text: str | None
    visibility: str
    ai_scan_status: str
    ai_scan_confidence: float | None
    ai_scan_notes: str | None
    ai_scanned_at: datetime | None
    is_published: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UnitSharedResourcePublicResponse(BaseModel):
    """Public view — hides AI scan internals."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_offering_id: str
    shared_by_user_id: str
    title: str
    description: str | None
    resource_type: str
    file_url: str | None
    external_url: str | None
    content_text: str | None
    visibility: str
    published_at: datetime | None
    created_at: datetime