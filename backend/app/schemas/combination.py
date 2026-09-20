"""
Pydantic schemas for the Combination model (Module 002 completion).

A Combination is a course-bound pairing of subjects used by combination-
based programmes (Education Science, etc.).
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# CREATE / UPDATE
# ============================================================================

class CombinationCreate(BaseModel):
    course_id: str
    name: str = Field(..., min_length=2, max_length=200)
    code: str = Field(..., min_length=1, max_length=32)
    description: str | None = None


class CombinationUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    code: str | None = Field(None, min_length=1, max_length=32)
    description: str | None = None
    status: str | None = Field(None, description="active | inactive")


# ============================================================================
# RESPONSE
# ============================================================================

class CombinationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    name: str
    code: str
    description: str | None
    status: str
    created_by: str | None
    created_at: datetime