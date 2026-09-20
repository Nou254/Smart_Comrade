"""
Pydantic schemas for academic structure.

Module 002 additions (previous):
  - InstitutionCreate gains campus_role (required)
  - InstitutionUpdate does NOT expose campus_role / parent / type
  - InstitutionTransitionResponse
  - InstitutionTransitionRequestCreate / Response
  - MainCampusOption

Module 002 completion additions:
  - StudentEnrollment gets combination_id
  - UnitMembership gets confirmation_status / confirmed_at / declined_at /
    decline_reason
  - UnitMembershipConfirmationRequest / Response
  - Cascade option schemas for the strict registration flow
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# GEOGRAPHY
# ============================================================================

class RegionCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = None


class RegionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    description: str | None
    created_at: datetime


class CountyCreate(BaseModel):
    region_id: str
    code: str = Field(..., min_length=1, max_length=16)
    name: str = Field(..., min_length=1, max_length=64)


class CountyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    region_id: str
    code: str
    name: str
    created_at: datetime


# ============================================================================
# INSTITUTION
# ============================================================================

class InstitutionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    short_name: str | None = Field(None, max_length=50)
    code: str = Field(..., min_length=2, max_length=32)
    type: str = Field(
        ...,
        description=(
            "UNIVERSITY|UNIVERSITY_COLLEGE|COLLEGE|POLYTECHNIC|"
            "TVET|TECHNICAL_INSTITUTE|KMTC|TTC|OTHER"
        ),
    )
    campus_role: str = Field(..., description="main | branch")
    county_id: str
    parent_institution_id: str | None = Field(
        None,
        description="Required if campus_role='branch'; must be null otherwise.",
    )
    physical_address: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None


class InstitutionUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    short_name: str | None = None
    physical_address: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    logo_url: str | None = None
    status: str | None = None


class InstitutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    short_name: str | None
    code: str
    type: str
    campus_role: str
    county_id: str
    parent_institution_id: str | None
    physical_address: str | None
    email: str | None
    phone: str | None
    website: str | None
    logo_url: str | None
    status: str
    created_at: datetime


class MainCampusOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    type: str
    county_id: str


# ============================================================================
# INSTITUTION TRANSITIONS
# ============================================================================

class InstitutionTransitionCreate(BaseModel):
    new_campus_role: str | None = Field(None, description="main | branch")
    new_type: str | None = Field(
        None,
        description=(
            "UNIVERSITY|UNIVERSITY_COLLEGE|COLLEGE|POLYTECHNIC|"
            "TVET|TECHNICAL_INSTITUTE|KMTC|TTC|OTHER"
        ),
    )
    new_parent_institution_id: str | None = None
    reason: str | None = Field(None, max_length=2000)
    reference: str | None = Field(None, max_length=255)


class InstitutionTransitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    institution_id: str
    transition_type: str
    old_campus_role: str | None
    old_type: str | None
    old_parent_institution_id: str | None
    new_campus_role: str | None
    new_type: str | None
    new_parent_institution_id: str | None
    reason: str | None
    reference: str | None
    changed_by: str | None
    changed_at: datetime
    source_request_id: str | None


# ============================================================================
# INSTITUTION TRANSITION REQUESTS
# ============================================================================

class InstitutionTransitionRequestCreate(BaseModel):
    desired_campus_role: str | None = Field(None, description="main | branch")
    desired_type: str | None = None
    desired_parent_institution_id: str | None = None
    reason: str = Field(..., min_length=5, max_length=2000)
    reference: str | None = Field(None, max_length=255)


class InstitutionTransitionRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    institution_id: str
    requested_by: str
    requested_at: datetime
    desired_campus_role: str | None
    desired_type: str | None
    desired_parent_institution_id: str | None
    reason: str
    reference: str | None
    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime


class TransitionReviewRequest(BaseModel):
    notes: str | None = Field(None, max_length=2000)


# ============================================================================
# SCHOOL
# ============================================================================

class SchoolCreate(BaseModel):
    institution_id: str
    name: str = Field(..., min_length=2, max_length=200)
    code: str = Field(..., min_length=1, max_length=32)
    description: str | None = None


class SchoolUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    description: str | None = None
    status: str | None = None


class SchoolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    institution_id: str
    name: str
    code: str
    description: str | None
    status: str
    created_at: datetime


# ============================================================================
# COURSE
# ============================================================================

class CourseCreate(BaseModel):
    school_id: str
    name: str = Field(..., min_length=2, max_length=200)
    code: str = Field(..., min_length=1, max_length=32)
    duration_years: int | None = Field(None, ge=1, le=10)
    description: str | None = None


class CourseUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    duration_years: int | None = None
    description: str | None = None
    status: str | None = None


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    school_id: str
    name: str
    code: str
    duration_years: int | None
    description: str | None
    status: str
    created_at: datetime


# ============================================================================
# UNIT
# ============================================================================

class UnitCreate(BaseModel):
    course_id: str
    name: str = Field(..., min_length=2, max_length=200)
    code: str = Field(..., min_length=1, max_length=32)
    description: str | None = None
    year_level: int | None = Field(None, ge=1, le=10)
    semester_number: int | None = Field(None, ge=1, le=3)


class UnitUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    description: str | None = None
    year_level: int | None = None
    semester_number: int | None = None
    status: str | None = None


class UnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    course_id: str
    name: str
    code: str
    description: str | None
    year_level: int | None
    semester_number: int | None
    status: str
    created_at: datetime


# ============================================================================
# ACADEMIC YEAR
# ============================================================================

class AcademicYearCreate(BaseModel):
    institution_id: str
    name: str = Field(..., min_length=4, max_length=32, description="e.g. 2026/2027")
    start_date: date
    end_date: date


class AcademicYearUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None


class AcademicYearResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    institution_id: str
    name: str
    start_date: date
    end_date: date
    status: str
    created_at: datetime


# ============================================================================
# SEMESTER
# ============================================================================

class SemesterCreate(BaseModel):
    academic_year_id: str
    number: int = Field(..., ge=1, le=3)
    name: str = Field(..., min_length=2, max_length=50)
    start_date: date
    end_date: date


class SemesterUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None


class SemesterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    academic_year_id: str
    number: int
    name: str
    start_date: date
    end_date: date
    status: str
    created_at: datetime


# ============================================================================
# STUDENT ENROLLMENT
# ============================================================================

class StudentEnrollmentCreate(BaseModel):
    user_id: str
    institution_id: str
    course_id: str
    combination_id: str | None = Field(
        None,
        description=(
            "Optional. Populate only when the course has combinations "
            "defined and the student selected one during registration."
        ),
    )
    academic_year_id: str
    semester_id: str
    start_date: date
    end_date: date | None = None
    notes: str | None = None


class StudentEnrollmentUpdate(BaseModel):
    status: str | None = None
    combination_id: str | None = None
    end_date: date | None = None
    notes: str | None = None


class StudentEnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    institution_id: str
    course_id: str
    combination_id: str | None
    academic_year_id: str
    semester_id: str
    status: str
    start_date: date
    end_date: date | None
    notes: str | None
    created_at: datetime


# ============================================================================
# UNIT MEMBERSHIP
# ============================================================================

class UnitMembershipCreate(BaseModel):
    user_id: str
    unit_id: str
    semester_id: str


class UnitMembershipUpdate(BaseModel):
    status: str | None = None


class UnitMembershipConfirmationRequest(BaseModel):
    """
    Student's per-unit confirmation after joining a group (or during the
    course-unit enrollment flow). The confirmation_status field on
    UnitMembership tracks this — set 'confirmed' or 'declined'.
    """
    confirmation_status: str = Field(
        ..., description="confirmed | declined",
    )
    decline_reason: str | None = Field(
        None,
        max_length=2000,
        description="Required if confirmation_status='declined'.",
    )


class UnitMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    unit_id: str
    semester_id: str
    status: str
    confirmation_status: str
    confirmed_at: datetime | None
    declined_at: datetime | None
    decline_reason: str | None
    created_at: datetime


class UnitMembershipConfirmationResponse(BaseModel):
    """Result of a confirmation or decline action."""
    membership_id: str
    confirmation_status: str
    confirmed_at: datetime | None
    declined_at: datetime | None
    message: str


# ============================================================================
# CASCADE OPTIONS (strict registration flow)
# ============================================================================
#
# A single aggregated endpoint returns the static/small datasets the
# cascade needs to bootstrap, so the frontend doesn't make 4 round trips
# to render step 1. Deeper levels (counties by region, institutions by
# county + type + campus_role, schools by institution, courses by school,
# combinations by course, semesters by academic year) are fetched with
# the existing filtered endpoints.

class CascadeInstitutionType(BaseModel):
    code: str
    label: str


class CascadeOptionsResponse(BaseModel):
    """
    Bootstrap payload for the registration cascade.

    regions            — all regions, ordered by name
    institution_types  — static enum of institution types
    campus_roles       — ['main', 'branch']
    year_levels        — [1, 2, 3, 4, 5]
    """
    regions: list[RegionResponse]
    institution_types: list[CascadeInstitutionType]
    campus_roles: list[str]
    year_levels: list[int]