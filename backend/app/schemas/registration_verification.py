"""
Pydantic schemas for registration number verification (Module 002 completion).

A Super Admin initiates a verification period for an institution. The
Institution Rep executes primary verification by matching (reg_number, email)
pairs against the institution's roster. The County Rep collaborates on
manual verification and can add new roster entries.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ============================================================================
# VERIFICATION PERIOD
# ============================================================================

class InstitutionVerificationPeriodCreate(BaseModel):
    institution_id: str
    start_date: datetime
    end_date: datetime
    notes: str | None = Field(None, max_length=2000)


class InstitutionVerificationPeriodExtendRequest(BaseModel):
    """Institution Rep requests an extension; Super Admin approves."""
    new_end_date: datetime
    notes: str | None = Field(None, max_length=2000)


class InstitutionVerificationPeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    institution_id: str
    initiated_by: str
    start_date: datetime
    end_date: datetime
    extended_until: datetime | None
    extension_count: int
    status: str
    verified_count: int
    unverified_count: int
    completed_at: datetime | None
    notes: str | None
    created_at: datetime


# ============================================================================
# ROSTER ENTRIES
# ============================================================================

class RosterEntryCreate(BaseModel):
    """A single (reg_number, email) pair."""
    reg_number: str = Field(..., min_length=1, max_length=64)
    email: EmailStr


class RosterBulkUploadRequest(BaseModel):
    """
    Upload many pairs at once. The service layer matches each pair
    against registered users and stores unmatched pairs for future use.
    """
    period_id: str | None = Field(
        None,
        description="Optional: the period this upload belongs to.",
    )
    entries: list[RosterEntryCreate] = Field(..., min_length=1)


class InstitutionRegistrationNumberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    institution_id: str
    period_id: str | None
    reg_number: str
    email: str
    user_id: str | None
    source: str
    added_by: str | None
    is_active: bool
    verified_at: datetime | None
    verified_by: str | None
    created_at: datetime


# ============================================================================
# PAIR VERIFICATION
# ============================================================================

class PairVerificationRequest(BaseModel):
    """Verify a single pair — used by the Institution Rep during the period."""
    reg_number: str = Field(..., min_length=1, max_length=64)
    email: EmailStr


class PairVerificationResponse(BaseModel):
    """
    Result of a pair verification attempt.

    verified         — True if the pair matched a registered user.
    matched_user_id  — The user the pair was matched to (null on mismatch).
    recorded         — True if the pair was stored as a known entry.
    message          — Human-readable explanation.
    """
    verified: bool
    matched_user_id: str | None
    recorded: bool
    message: str


# ============================================================================
# BULK VERIFICATION REPORT
# ============================================================================

class BulkVerificationSummary(BaseModel):
    """Returned after a bulk roster upload."""
    total_entries: int
    matched: int
    unmatched_stored: int
    duplicates_skipped: int
    errors: list[str] = []