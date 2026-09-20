"""
Pydantic schemas for User and Auth endpoints.
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ============================================================================
# REGISTRATION REQUEST SCHEMAS
#
# Phone requirements (PWA users must declare phone; students and alumni may
# omit it; elevated students inherit their existing phone and skip this).
# ============================================================================

class StudentRegister(BaseModel):
    """Student registration — low barrier, auto-active after email verification."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., min_length=8, max_length=72)
    institution_id: str
    # Optional academic context captured at registration
    course_id: str | None = None
    academic_year_id: str | None = None
    semester_id: str | None = None
    # --- Terms / Privacy acceptance ---
    tos_accepted: bool = Field(..., description="Must be true to register")
    privacy_accepted: bool = Field(..., description="Must be true to register")
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


class LecturerRegister(BaseModel):
    """Lecturer registration — phone + referee + admin approval required.

    The first affiliation is captured here. Additional affiliations are added
    post-login via POST /lecturers/affiliations.
    """
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    institutional_email: EmailStr
    phone: str = Field(..., min_length=7, max_length=20)  # required for PWA users
    password: str = Field(..., min_length=8, max_length=72)
    institution_id: str
    department: str | None = Field(None, max_length=150)
    title: str = Field(..., description="Lecturer | Senior Lecturer | Professor | Assistant Lecturer")

    # --- Referee (verified via phone call by admin) ---
    referee_name: str = Field(..., min_length=2, max_length=160)
    referee_phone: str = Field(..., min_length=7, max_length=20)
    referee_relationship: str = Field(..., min_length=2, max_length=120)

    tos_accepted: bool = Field(...)
    privacy_accepted: bool = Field(...)
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


class ExternalRegister(BaseModel):
    """Generic external registration — kept for backward compatibility."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=20)  # required for PWA users
    password: str = Field(..., min_length=8, max_length=72)
    external_subtype: str = Field(
        ...,
        description="investor | mentor | organization | alumni | specialist",
    )
    organization_name: str | None = None
    profession: str | None = None
    expertise: str | None = None
    tos_accepted: bool = Field(...)
    privacy_accepted: bool = Field(...)
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


# --- External subtype-specific schemas ---

class InvestorRegister(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=20)  # required for PWA users
    password: str = Field(..., min_length=8, max_length=72)
    organization_name: str = Field(..., min_length=1, max_length=255)
    role_in_organization: str | None = Field(None, max_length=120)
    investment_focus: str | None = Field(None, max_length=2000)
    tos_accepted: bool = Field(...)
    privacy_accepted: bool = Field(...)
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


class OrganizationRegister(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=20)  # required for PWA users
    password: str = Field(..., min_length=8, max_length=72)
    organization_name: str = Field(..., min_length=1, max_length=255)
    organization_type: str = Field(..., description="Company | NGO | Government | Institution")
    industry: str = Field(..., description="Technology | Education | Healthcare | ...")
    registration_number: str | None = Field(None, max_length=64)
    contact_name: str | None = Field(None, max_length=160)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(None, max_length=32)
    tos_accepted: bool = Field(...)
    privacy_accepted: bool = Field(...)
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


class AlumniRegister(BaseModel):
    """Alumni registration — phone optional (elevated-student exception)."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)  # optional for alumni
    password: str = Field(..., min_length=8, max_length=72)
    former_institution: str = Field(..., min_length=1, max_length=255)
    graduation_year: int = Field(..., ge=1950, le=2100)
    current_profession: str | None = Field(None, max_length=160)
    expertise: str | None = Field(None, max_length=2000)
    tos_accepted: bool = Field(...)
    privacy_accepted: bool = Field(...)
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


class MentorRegister(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=20)  # required for PWA users
    password: str = Field(..., min_length=8, max_length=72)
    profession: str = Field(..., min_length=1, max_length=160)
    areas_of_expertise: list[str] = Field(..., min_length=1)
    experience_summary: str = Field(..., min_length=10, max_length=1000)
    availability: str = Field(..., description="Weekdays | Weekends | Evenings | Flexible")
    tos_accepted: bool = Field(...)
    privacy_accepted: bool = Field(...)
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


class SpecialistRegister(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=20)  # required for PWA users
    password: str = Field(..., min_length=8, max_length=72)
    field_of_expertise: str = Field(..., min_length=1, max_length=160)
    affiliated_organization: str | None = Field(None, max_length=255)
    tos_accepted: bool = Field(...)
    privacy_accepted: bool = Field(...)
    tos_version: str | None = Field("1.0", max_length=32)
    privacy_version: str | None = Field("1.0", max_length=32)


# ============================================================================
# LOGIN / TOKEN
# ============================================================================

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    captcha_token: str | None = None


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None
    user_type: str
    external_subtype: str | None
    account_status: str
    email_verified: bool
    phone_verified: bool
    domain_verified: bool
    institution_id: str | None
    two_factor_enabled: bool
    two_factor_method: str | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ApprovalRequest(BaseModel):
    approve: bool
    reason: str | None = None


class PendingApprovalResponse(BaseModel):
    """Summary shown to admin for pending approvals."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    first_name: str
    last_name: str
    email: str
    institutional_email: str | None
    user_type: str
    external_subtype: str | None = None
    institution_id: str | None
    department: str | None
    title: str | None
    domain_verified: bool
    account_status: str
    created_at: datetime


class ExternalProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    external_subtype: str
    # Investor
    investment_focus: str | None = None
    investor_org_name: str | None = None
    investor_role: str | None = None
    # Organization
    organization_name: str | None = None
    organization_type: str | None = None
    industry: str | None = None
    registration_number: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    # Alumni
    former_institution: str | None = None
    graduation_year: int | None = None
    current_profession: str | None = None
    alumni_expertise: str | None = None
    # Mentor
    mentor_profession: str | None = None
    mentor_expertise: str | None = None
    mentor_experience_summary: str | None = None
    mentor_availability: str | None = None
    # Specialist
    expertise_field: str | None = None
    affiliation: str | None = None
    # Verification
    verification_status: str
    created_at: datetime