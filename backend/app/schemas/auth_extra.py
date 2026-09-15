"""
Schemas for OTP verification, password reset, sessions, 2FA, phone verify, step-up.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Email Verification ---

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)
    purpose: str = Field("registration")


class ResendOtpRequest(BaseModel):
    email: EmailStr
    purpose: str = Field("registration")


class OtpSentResponse(BaseModel):
    message: str
    email: str | None = None
    phone: str | None = None
    expires_in_minutes: int


# --- Phone Verification ---

class SendPhoneOtpRequest(BaseModel):
    phone: str | None = None


class VerifyPhoneRequest(BaseModel):
    otp: str = Field(..., min_length=6, max_length=6)


# --- Password Reset ---

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20)
    new_password: str = Field(..., min_length=8, max_length=72)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=72)


# --- Sessions ---

class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ip_address: str | None
    user_agent: str | None
    device_label: str | None
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    is_revoked: bool


class MessageResponse(BaseModel):
    message: str


# --- 2FA ---

class TwoFactorSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    qr_code_data_uri: str
    backup_codes: list[str]
    message: str


class TwoFactorVerifySetupRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class TwoFactorVerifyLoginRequest(BaseModel):
    temp_token: str
    code: str = Field(..., min_length=6, max_length=16)


class TwoFactorDisableRequest(BaseModel):
    password: str
    code: str = Field(..., min_length=6, max_length=16)


class TwoFactorStatusResponse(BaseModel):
    enabled: bool
    method: str | None
    backup_codes_remaining: int


class TwoFactorEnableEmailRequest(BaseModel):
    """Enable email OTP as the 2FA method. Email must already be verified."""
    pass


class TwoFactorEnableSmsRequest(BaseModel):
    """Enable SMS OTP as the 2FA method. Phone must already be verified."""
    pass


class TwoFactorResendChallengeRequest(BaseModel):
    """Resend a fresh email/SMS 2FA code during login."""
    temp_token: str


# --- Step-up authentication ---

class StepUpRequest(BaseModel):
    password: str
    code: str = Field(..., min_length=6, max_length=16)
    scope: str = Field(..., description="e.g. 'system.config', 'admin.users'")


class StepUpResponse(BaseModel):
    step_up_token: str
    scope: str
    expires_in_minutes: int


# --- Login response union ---

class LoginResponse(BaseModel):
    # Success case
    access_token: str | None = None
    token_type: str | None = "bearer"
    user: dict | None = None
    # 2FA challenge case
    requires_2fa: bool = False
    temp_token: str | None = None
    # Admin 2FA setup required case
    requires_admin_2fa_setup: bool = False
    setup_token: str | None = None