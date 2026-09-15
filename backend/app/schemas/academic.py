"""
Pydantic schemas for academic structure.
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
    type: str = Field(..., description="UNIVERSITY|COLLEGE|TVET|POLYTECHNIC|KMTC|OTHER")
    county_id: str
    parent_institution_id: str | None = None
    physical_address: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None


class InstitutionUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    short_name: str | None = None
    type: str | None = None
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
    county_id: str
    parent_institution_id: str | None
    physical_address: str | None
    email: str | None
    phone: str | None
    website: str | None
    logo_url: str | None
    status: str
    created_at: datetime


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
    academic_year_id: str
    semester_id: str
    start_date: date
    end_date: date | None = None
    notes: str | None = None


class StudentEnrollmentUpdate(BaseModel):
    status: str | None = None
    end_date: date | None = None
    notes: str | None = None


class StudentEnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    institution_id: str
    course_id: str
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


class UnitMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    unit_id: str
    semester_id: str
    status: str
    created_at: datetime