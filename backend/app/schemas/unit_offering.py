"""
Pydantic schemas for UnitOffering (Module 002 completion).

A UnitOffering is a specific occurrence of a Unit during one academic
year and semester. Downstream services (assessments, resources,
discussions) attach to the offering, not the abstract Unit.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# CREATE / UPDATE
# ============================================================================

class UnitOfferingCreate(BaseModel):
    """
    Only the three identifiers are required. institution_id, school_id,
    course_id, and year_level are derived from the Unit by the service
    layer to avoid drift.
    """
    unit_id: str
    academic_year_id: str
    semester_id: str


class UnitOfferingUpdate(BaseModel):
    status: str | None = Field(
        None, description="scheduled | active | completed | archived",
    )


# ============================================================================
# RESPONSE
# ============================================================================

class UnitOfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_id: str
    institution_id: str
    school_id: str
    course_id: str
    academic_year_id: str
    semester_id: str
    year_level: int
    status: str
    enrolled_count: int
    created_at: datetime
    updated_at: datetime