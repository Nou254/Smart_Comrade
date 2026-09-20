"""
Pydantic schemas for UnitProposal (Module 002 completion).

A UnitProposal is the routing wrapper for units created outside the group
timetable-OCR flow. The escalation ladder is:

    School Rep -> Institution Rep -> Regional Admin -> Super Admin

County Representative is skipped and receives only reports. Every two
hours without a response escalates one level.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# ITEM (one per proposed unit)
# ============================================================================

class UnitProposalItemCreate(BaseModel):
    proposed_code: str = Field(..., min_length=1, max_length=32)
    proposed_name: str = Field(..., min_length=2, max_length=200)
    proposed_description: str | None = None
    year_level: int | None = Field(None, ge=1, le=10)
    semester_number: int | None = Field(None, ge=1, le=3)
    # OCR metadata — null for manual_creation proposals.
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    source_page: int | None = Field(None, ge=1)


class UnitProposalItemModifyRequest(BaseModel):
    """An approver's per-item modification before approving."""
    modified_code: str | None = Field(None, min_length=1, max_length=32)
    modified_name: str | None = Field(None, min_length=2, max_length=200)
    modified_description: str | None = None
    notes: str | None = Field(None, max_length=2000)


class UnitProposalItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    proposal_id: str
    existing_unit_id: str | None
    proposed_code: str
    proposed_name: str
    proposed_description: str | None
    year_level: int | None
    semester_number: int | None
    confidence: float | None
    source_page: int | None
    action: str
    item_status: str
    modified_code: str | None
    modified_name: str | None
    modified_description: str | None
    resulting_unit_id: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    notes: str | None
    created_at: datetime


# ============================================================================
# PROPOSAL
# ============================================================================

class UnitProposalCreate(BaseModel):
    """Create a proposal with its items in a single request."""
    institution_id: str
    school_id: str
    course_id: str
    academic_year_id: str
    semester_id: str
    year_level: int = Field(..., ge=1, le=10)

    proposal_type: str = Field(
        ...,
        description="ocr_extraction | manual_creation",
    )
    source_upload_id: str | None = None

    items: list[UnitProposalItemCreate] = Field(..., min_length=1)
    notes: str | None = Field(None, max_length=2000)


class UnitProposalWithdrawRequest(BaseModel):
    reason: str | None = Field(None, max_length=2000)


class UnitProposalRejectRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)


# ============================================================================
# EVENT (audit trail)
# ============================================================================

class UnitProposalEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    proposal_id: str
    event_type: str
    actor_id: str | None
    from_stage: str | None
    to_stage: str | None
    notes: str | None
    created_at: datetime


# ============================================================================
# FULL PROPOSAL RESPONSE
# ============================================================================

class UnitProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str

    institution_id: str
    school_id: str
    course_id: str
    academic_year_id: str
    semester_id: str
    year_level: int

    proposal_type: str
    source_upload_id: str | None

    created_by: str
    status: str

    current_approver_role: str | None
    current_approver_id: str | None
    current_stage_started_at: datetime
    escalation_deadline: datetime

    approved_by: str | None
    approved_at: datetime | None
    rejected_by: str | None
    rejected_at: datetime | None
    rejection_reason: str | None

    notes: str | None

    created_at: datetime
    updated_at: datetime

    items: list[UnitProposalItemResponse] = []
    events: list[UnitProposalEventResponse] = []