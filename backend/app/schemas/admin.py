"""
Schemas for admin provisioning, suspension, config, and audit.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    invitation_token: str | None = None  # dev only


class AcceptInvitationRequest(BaseModel):
    token: str = Field(..., min_length=20)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., min_length=8, max_length=72)


class SuspendRequest(BaseModel):
    reason: str | None = None


class ReactivateRequest(BaseModel):
    reason: str | None = None


class ConfigUpdateRequest(BaseModel):
    value: dict
    reason: str | None = None


class ConfigEntry(BaseModel):
    key: str
    value: dict


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