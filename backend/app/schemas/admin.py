"""
Schemas for admin provisioning, suspension, config, audit, and user deletion.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ============================================================================
# Invitations
# ============================================================================

class InvitationCreate(BaseModel):
    email: EmailStr
    role_code: str
    jurisdiction_type: str
    jurisdiction_id: str | None = None
    notes: str | None = None


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role_code: str
    jurisdiction_type: str
    jurisdiction_id: str | None
    expires_at: datetime
    is_used: bool
    invitation_token: str | None = None


class AcceptInvitationRequest(BaseModel):
    token: str = Field(..., min_length=20)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., min_length=8, max_length=72)


# ============================================================================
# Suspend / reactivate
# ============================================================================

class SuspendRequest(BaseModel):
    reason: str | None = None


class ReactivateRequest(BaseModel):
    reason: str | None = None


# ============================================================================
# User deletion (NEW — Super Admin only)
# ============================================================================

class UserDeletionRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=500)
    confirm_email: EmailStr = Field(
        ..., description="Must match the target user's email exactly"
    )


class UserDeletionResponse(BaseModel):
    message: str
    deleted_user_id: str
    deleted_at: datetime


# ============================================================================
# System config
# ============================================================================

class ConfigUpdateRequest(BaseModel):
    value: dict
    reason: str | None = None


class ConfigEntry(BaseModel):
    key: str
    value: dict


# ============================================================================
# Admin action log
# ============================================================================

class AdminActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    actor_id: str | None
    actor_role: str | None
    action: str
    target_type: str | None
    target_id: str | None
    old_value: str | None
    new_value: str | None
    reason: str | None
    ip_address: str | None
    created_at: datetime


# ============================================================================
# Notification preferences (NEW)
# ============================================================================

class NotificationPreferencesUpdate(BaseModel):
    email_enabled: bool | None = None
    sms_enabled: bool | None = None
    push_enabled: bool | None = None
    in_app_enabled: bool | None = None
    group_activity: bool | None = None
    announcements: bool | None = None
    elections: bool | None = None
    assessments: bool | None = None
    events: bool | None = None
    opportunities: bool | None = None
    marketing: bool | None = None


class NotificationPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email_enabled: bool
    sms_enabled: bool
    push_enabled: bool
    in_app_enabled: bool
    group_activity: bool
    announcements: bool
    elections: bool
    assessments: bool
    events: bool
    opportunities: bool
    marketing: bool