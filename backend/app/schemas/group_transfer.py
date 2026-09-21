"""
Pydantic schemas for Inter-Group Transfers — Module 003 Phase 8.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# CREATE
# ============================================================================

class GroupTransferCreate(BaseModel):
    """
    Admin-initiated transfer request. The service validates:
      - same course
      - neither group is in "going for elections" state
      - target group has capacity
      - student is an active member of source
    """
    student_id: str
    source_group_id: str
    target_group_id: str
    transfer_type: str = Field(
        "ordinary",
        description="ordinary | elected",
    )
    request_notes: str | None = Field(None, max_length=2000)


class GroupTransferFeeRecord(BaseModel):
    payment_reference: str = Field(..., min_length=3, max_length=128)


class GroupTransferReviewRequest(BaseModel):
    approve: bool
    review_notes: str | None = Field(None, max_length=2000)


# ============================================================================
# RESPONSE
# ============================================================================

class GroupTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    source_group_id: str
    target_group_id: str
    initiated_by: str
    initiated_at: datetime
    request_notes: str | None

    transfer_type: str
    fee_amount: int
    currency: str
    fee_paid: bool
    payment_reference: str | None
    fee_paid_at: datetime | None

    seat_vacated: bool

    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    completed_at: datetime | None

    created_at: datetime


class GroupTransferListResponse(BaseModel):
    """Lightweight list item."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    source_group_id: str
    target_group_id: str
    transfer_type: str
    fee_amount: int
    status: str
    initiated_at: datetime
    completed_at: datetime | None