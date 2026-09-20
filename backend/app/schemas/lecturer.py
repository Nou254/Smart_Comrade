"""
Schemas for lecturer affiliation management (post-registration).
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LecturerAffiliationCreate(BaseModel):
    """Add an additional affiliation to an existing lecturer account."""
    institution_id: str
    institutional_email: EmailStr | None = None
    department: str | None = Field(None, max_length=150)
    title: str = Field(..., description="Lecturer | Senior Lecturer | Professor | Assistant Lecturer")

    # Referee for this affiliation
    referee_name: str = Field(..., min_length=2, max_length=160)
    referee_phone: str = Field(..., min_length=7, max_length=20)
    referee_relationship: str = Field(..., min_length=2, max_length=120)


class LecturerAffiliationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    institution_id: str
    institutional_email: str | None
    department: str | None
    title: str
    referee_name: str
    referee_phone: str
    referee_relationship: str
    verification_status: str
    domain_verified: bool
    approved_at: datetime | None
    verification_notes: str | None
    start_date: datetime
    end_date: datetime | None
    created_at: datetime


class LecturerAffiliationListResponse(BaseModel):
    affiliations: list[LecturerAffiliationResponse]