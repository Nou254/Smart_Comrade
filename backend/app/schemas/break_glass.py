"""Break-glass schemas."""
from datetime import datetime
from pydantic import BaseModel, Field


class BreakGlassSetupResponse(BaseModel):
    share_a: str
    share_b: str
    message: str


class BreakGlassStatusResponse(BaseModel):
    configured: bool
    use_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime | None = None


class BreakGlassUnlockRequest(BaseModel):
    share_a: str = Field(..., min_length=40)
    share_b: str = Field(..., min_length=40)
    reason: str = Field(..., min_length=5, max_length=500)


class BreakGlassUnlockResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    message: str


class BreakGlassRevokeResponse(BaseModel):
    revoked_count: int