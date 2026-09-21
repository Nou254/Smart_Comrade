"""Pydantic schemas for Impeachment — Module 003 Phase 9."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ── case ────────────────────────────────────────────────────────────────

class ImpeachmentCaseCreate(BaseModel):
    target_user_id: str
    target_role_code: str
    target_level: str = Field(..., description="school | institution | county")
    constituency_id: str
    grounds: str = Field(..., min_length=20, max_length=5000)
    evidence: dict | None = None


class ImpeachmentCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_user_id: str
    target_role_code: str
    target_level: str
    constituency_id: str
    filed_by: str
    filed_at: datetime
    grounds: str
    evidence_json: dict | None
    status: str

    reconciliation_attempted_at: datetime | None
    reconciliation_mediator_id: str | None
    reconciliation_outcome: str | None
    reconciliation_notes: str | None

    petition_required_count: int
    petition_signature_count: int
    petition_reached_at: datetime | None

    committee_json: dict | None
    committee_size: int
    committee_formed_at: datetime | None
    committee_locked: bool
    initializer_id: str | None

    hearing_started_at: datetime | None
    hearing_completed_at: datetime | None
    hearing_is_live_streamed: bool
    hearing_is_closed: bool

    verdict_voting_opened_at: datetime | None
    verdict_voting_opened_by: str | None
    verdict_voting_closed_at: datetime | None
    verdict_voting_closed_by: str | None

    verdict: str | None
    verdict_votes_for: int
    verdict_votes_against: int
    verdict_threshold: float
    verdict_at: datetime | None

    disclosure_period_ends_at: datetime | None
    removal_effective_at: datetime | None

    replacement_election_id: str | None
    replacement_winner_user_id: str | None
    notes: str | None
    created_at: datetime


class ImpeachmentListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_user_id: str
    target_role_code: str
    target_level: str
    constituency_id: str
    status: str
    filed_at: datetime
    verdict: str | None


# ── reconciliation ──────────────────────────────────────────────────────

class ReconciliationAttempt(BaseModel):
    outcome: str = Field(..., description="resolved | unresolved")
    notes: str = Field(..., min_length=5, max_length=2000)


# ── petition ────────────────────────────────────────────────────────────

class PetitionSignRequest(BaseModel):
    """Empty — the signer is the current user."""


class PetitionStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    required: int
    collected: int
    reached: bool
    reached_at: datetime | None


class PetitionSignatureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    signer_id: str
    signed_at: datetime
    signature_hash: str


# ── committee ───────────────────────────────────────────────────────────

class FormCommitteeRequest(BaseModel):
    member_user_ids: list[str] = Field(..., min_length=1)
    moderator_user_id: str


class CommitteeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    members: list[str]
    moderator_user_id: str
    committee_size: int
    locked: bool
    formed_at: datetime


# ── hearing sessions ────────────────────────────────────────────────────

class SessionScheduleRequest(BaseModel):
    """Schedule all 4 sessions. Provide ISO datetimes."""
    accusation_at: datetime
    evidence_at: datetime
    defense_at: datetime
    verdict_at: datetime
    is_live_streamed: bool = True
    is_closed: bool = False


class SessionStartRequest(BaseModel):
    is_live_streamed: bool | None = None
    is_closed: bool | None = None


class SessionMinutesRequest(BaseModel):
    transcript_text: str | None = Field(None, max_length=20000)
    minutes_text: str = Field(..., min_length=5, max_length=20000)
    audio_url: str | None = Field(None, max_length=500)
    audio_hash: str | None = Field(None, max_length=128)


class ImpeachmentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    session_number: int
    session_type: str
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    is_live_streamed: bool
    is_closed: bool
    audio_url: str | None
    audio_hash: str | None
    transcript_text: str | None
    transcript_generated_at: datetime | None
    minutes_text: str | None
    minutes_finalized_at: datetime | None
    minutes_finalized_by: str | None
    status: str
    notes: str | None


# ── verdict voting ──────────────────────────────────────────────────────

class VerdictVoteRequest(BaseModel):
    vote: str = Field(..., description="remove | keep")


class ImpeachmentVoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    voter_id: str
    vote: str
    cast_at: datetime
    vote_hash: str


class VerdictSummary(BaseModel):
    case_id: str
    votes_for: int
    votes_against: int
    committee_size: int
    threshold_required: int
    outcome: str
    verdict: str | None
    verdict_at: datetime | None
    voting_opened_at: datetime | None
    voting_opened_by: str | None
    voting_closed_at: datetime | None
    voting_closed_by: str | None
    voting_is_open: bool


class VerdictVotingStatusResponse(BaseModel):
    """Returned by open/close verdict-voting endpoints."""
    case_id: str
    status: str
    voting_is_open: bool
    voting_opened_at: datetime | None
    voting_opened_by: str | None
    voting_closed_at: datetime | None
    voting_closed_by: str | None
    message: str


# ── disclosure + replacement ────────────────────────────────────────────

class ReplacementElectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    replacement_election_id: str | None
    disclosure_period_ends_at: datetime | None
    replacement_winner_user_id: str | None