"""
Pydantic schemas for User and Auth endpoints.
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ---------- Request schemas ----------

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


class LecturerRegister(BaseModel):
    """Lecturer registration — institutional email + admin approval required."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr                                # personal or login email
    institutional_email: EmailStr                  # must match institution domain
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., min_length=8, max_length=72)
    institution_id: str
    department: str | None = Field(None, max_length=150)
    title: str = Field(..., description="Lecturer | Senior Lecturer | Professor | Assistant Lecturer")


class ExternalRegister(BaseModel):
    """External user registration — approval required."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., min_length=8, max_length=72)
    external_subtype: str = Field(
        ...,
        description="investor | mentor | organization | alumni | specialist",
    )
    organization_name: str | None = None
    profession: str | None = None
    expertise: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


# ---------- Response schemas ----------

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
    institution_id: str | None
    department: str | None
    title: str | None
    domain_verified: bool
    account_status: str
    created_at: datetime