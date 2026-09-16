"""
Schemas for OTP verification, password reset, sessions, 2FA, phone verify,
step-up, account deactivation, and login response.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ============================================================================
# Email verification
# ============================================================================

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


# ============================================================================
# Phone verification
# ============================================================================

class SendPhoneOtpRequest(BaseModel):
    phone: str | None = None


class VerifyPhoneRequest(BaseModel):
    otp: str = Field(..., min_length=6, max_length=6)


# ============================================================================
# Password reset
# ============================================================================

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20)
    new_password: str = Field(..., min_length=8, max_length=72)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=72)


# ============================================================================
# Sessions
# ============================================================================

class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ip_address: str | None
    user_agent: str | None
    device_label: str | None
    # --- Session metadata (NEW) ---
    device_type: str | None = None
    device_os: str | None = None
    device_browser: str | None = None
    location: str | None = None
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    is_revoked: bool


class MessageResponse(BaseModel):
    message: str


# ============================================================================
# 2FA
# ============================================================================

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
    pass


class TwoFactorEnableSmsRequest(BaseModel):
    pass


class TwoFactorResendChallengeRequest(BaseModel):
    temp_token: str


# ============================================================================
# Step-up authentication
# ============================================================================

class StepUpRequest(BaseModel):
    password: str
    code: str = Field(..., min_length=6, max_length=16)
    scope: str = Field(..., description="e.g. 'system.config', 'admin.users'")


class StepUpResponse(BaseModel):
    step_up_token: str
    scope: str
    expires_in_minutes: int


# ============================================================================
# Account deactivation (NEW)
# ============================================================================

class DeactivateAccountRequest(BaseModel):
    password: str
    reason: str | None = Field(None, max_length=500)
    confirm: bool = Field(..., description="Must be true to confirm deactivation")


class ReactivateAccountRequest(BaseModel):
    password: str


class DeactivationResponse(BaseModel):
    message: str
    deactivated_at: datetime
    reactivation_deadline: datetime
    grace_period_days: int


# ============================================================================
# Login response (extended)
# ============================================================================

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

    # --- Redirect + environment (NEW) ---
    redirect_to: str | None = None
    hub: str | None = None
    environment_warning: str | None = None
    environment: str | None = None

    # --- CAPTCHA required (NEW) ---
    requires_captcha: bool = False

    #---Pending registration ----
    requires_verification:bool = False