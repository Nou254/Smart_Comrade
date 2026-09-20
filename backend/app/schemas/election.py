"""
Pydantic schemas for Elections — Module 003 Phase 6.

Covers all four levels (group, school, institution, county) with:
  - Election lifecycle creation and state transitions
  - Positions, tickets, candidates
  - Voter roll, approval votes, ballots, results
  - Disputes, appeals, reschedules, no-payer fallback
  - Aggregated views for the admin dashboard

Naming:
  XxxCreate   — request body for creating
  XxxUpdate   — partial update body
  XxxRequest  — request body for an action (e.g. cast, approve, reject)
  XxxResponse — read-only response
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# TYPE ALIASES
# ============================================================================

ElectionLevel = Literal["group", "school", "institution", "county"]

ElectionState = Literal[
    "draft", "scheduled", "nominating", "nominational_voting",
    "payment_window", "awaiting_payment", "regional_admin_interim",
    "ballot_finalized", "campaigning", "voting", "counting",
    "suspense_blackout", "result_declared", "run_off_scheduled",
    "run_off_voting", "appeal_window", "appealed", "disputed", "completed",
]

PositionCode = Literal[
    "group_leader", "group_secretary", "group_treasurer",
    "school_representative", "assistant_school_rep",
    "institution_representative", "assistant_institution_rep",
    "county_representative", "assistant_county_rep",
]


# ============================================================================
# ELECTION — CREATE / RESPONSE
# ============================================================================

class ElectionCreate(BaseModel):
    """
    Create a new election in `draft` state. The service layer computes
    the timeline from `election_day` and `level` using the timelines
    defined in the Module 003 Phase 6 spec.
    """
    title: str = Field(..., min_length=3, max_length=200)
    description: str | None = None
    level: ElectionLevel
    constituency_id: str = Field(
        ...,
        description=(
            "Group id | School id | Institution id | County id — "
            "interpretation depends on `level`."
        ),
    )
    election_day: date = Field(
        ...,
        description=(
            "The day voting opens. All other timeline points are derived "
            "from this date and the level's cycle rules."
        ),
    )
    voting_duration_minutes: int = Field(
        1440,
        ge=60,
        le=2880,
        description=(
            "60 (1h) to 2880 (48h). Defaults to 1440 (24h). Group and "
            "institution levels default to 720 (12h) via the service."
        ),
    )
    notes: str | None = Field(None, max_length=2000)


class ElectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    level: str
    constituency_id: str
    state: str

    # Timeline
    election_day: date
    nomination_open_at: datetime | None
    nomination_close_at: datetime | None
    approval_vote_at: datetime | None
    payment_window_start: datetime | None
    payment_window_end: datetime | None
    ballot_finalized_at: datetime | None
    voting_open_at: datetime | None
    voting_close_at: datetime | None
    result_declared_at: datetime | None
    appeal_window_end: datetime | None
    dashboard_access_at: datetime | None
    voting_duration_minutes: int

    # Counters
    electorate_size: int
    votes_cast: int

    # Run-off
    is_runoff: bool
    parent_election_id: str | None

    # Live stream
    live_stream_url: str | None
    stream_started_at: datetime | None
    stream_ended_at: datetime | None
    suspense_until: datetime | None

    # Reschedule
    rescheduled_from: datetime | None
    rescheduled_reason: str | None

    # No-payer fallback
    under_regional_admin: bool

    # Metadata
    created_by: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ============================================================================
# POSITION
# ============================================================================

class ElectionPositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    position_code: str
    title: str
    description: str | None
    is_paired: bool
    paired_with_code: str | None
    max_candidates: int
    seats_available: int
    required_approval_percentage: float
    nomination_fee: int
    currency: str
    status: str
    winner_ticket_id: str | None
    winner_candidate_id: str | None
    filled_at: datetime | None
    created_at: datetime


# ============================================================================
# TICKET
# ============================================================================

class ElectionTicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    primary_position_id: str
    name: str | None
    slogan: str | None
    color: str | None
    ballot_order: int
    status: str
    qualified_at: datetime | None
    fee_paid_at: datetime | None
    total_approval_votes: int
    total_votes_cast: int
    created_at: datetime


# ============================================================================
# CANDIDATE
# ============================================================================

class ElectionCandidateRegister(BaseModel):
    """
    A user submits a candidacy. For paired positions (e.g. Leader +
    Secretary), the ticket structure is defined by the service — the
    caller submits one candidate at a time and links them by the same
    position group.
    """
    position_id: str
    ticket_name: str | None = Field(
        None, max_length=120,
        description="Optional team name; ignored for solo positions.",
    )
    ticket_slogan: str | None = Field(None, max_length=255)
    manifesto: str = Field(..., min_length=20, max_length=10000)
    photo_url: str | None = Field(None, max_length=500)


class ElectionCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    ticket_id: str
    position_id: str
    user_id: str
    manifesto: str | None
    photo_url: str | None
    nominated_at: datetime
    approval_count: int
    approval_percentage: float
    qualified_at: datetime | None
    fee_paid: bool
    fee_payment_reference: str | None
    fee_paid_at: datetime | None
    status: str
    created_at: datetime


# ============================================================================
# VOTER ROLL
# ============================================================================

class ElectionVoterRollResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    user_id: str
    eligible: bool
    reason: str | None
    frozen_at: datetime
    has_voted: bool
    voted_at: datetime | None


# ============================================================================
# APPROVAL VOTE
# ============================================================================

class ElectionApprovalVoteRequest(BaseModel):
    """A voter approves a candidate (counts toward the 15% threshold)."""
    candidate_id: str


# ============================================================================
# BALLOT
# ============================================================================

class ElectionBallotCast(BaseModel):
    """A voter casts a final ballot for one position."""
    position_id: str
    ticket_id: str


class ElectionBallotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    position_id: str
    ticket_id: str
    voter_id: str
    cast_at: datetime
    vote_hash: str | None


# ============================================================================
# RESULT
# ============================================================================

class ElectionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    position_id: str
    winner_ticket_id: str | None
    winner_candidate_id: str | None
    total_valid_votes: int
    total_invalid_votes: int
    winner_vote_count: int
    runner_up_ticket_id: str | None
    runner_up_vote_count: int
    margin: int
    is_tie: bool
    tie_ticket_ids: dict | None
    declared_at: datetime
    verified_by: str | None
    official: bool
    notes: str | None
    created_at: datetime


# ============================================================================
# STATE TRANSITION
# ============================================================================

class ElectionStateTransitionRequest(BaseModel):
    """
    Manually drive a state transition. The service validates against
    the state machine and rejects invalid transitions.
    """
    to_state: ElectionState
    reason: str | None = Field(None, max_length=2000)


# ============================================================================
# RUN-OFF
# ============================================================================

class ElectionRunOffRequest(BaseModel):
    """
    Trigger a run-off. Called by the service automatically when a tie
    is detected — this schema exists for admin overrides.
    """
    position_id: str
    tied_ticket_ids: list[str] = Field(..., min_length=2)
    scheduled_for: date | None = Field(
        None,
        description=(
            "Defaults to 2 days after the original election day. "
            "Run-offs are final — no appeals window."
        ),
    )


# ============================================================================
# DISPUTE
# ============================================================================

class ElectionDisputeFile(BaseModel):
    grounds: str = Field(..., min_length=20, max_length=5000)
    evidence: dict | None = Field(
        None,
        description="Free-form JSON — links, references, etc.",
    )


class ElectionDisputeVerdict(BaseModel):
    verdict: str = Field(..., min_length=5, max_length=5000)
    notes: str | None = Field(None, max_length=2000)


class ElectionDisputeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    filed_by: str
    filed_at: datetime
    grounds: str
    evidence_json: dict | None
    assigned_to: str | None
    assigned_at: datetime | None
    hearing_scheduled_at: datetime | None
    hearing_link: str | None
    hearing_held_at: datetime | None
    verdict: str | None
    verdict_by: str | None
    verdict_at: datetime | None
    status: str
    created_at: datetime


# ============================================================================
# APPEAL
# ============================================================================

class ElectionAppealFile(BaseModel):
    """Institution and County only. Committee assembled automatically."""
    grounds: str = Field(..., min_length=20, max_length=5000)
    evidence: dict | None = None


class ElectionAppealVerdict(BaseModel):
    outcome: Literal["confirmed", "overturned", "run_off_required"]
    verdict: str = Field(..., min_length=5, max_length=5000)
    notes: str | None = Field(None, max_length=2000)


class ElectionAppealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    filed_by: str
    filed_at: datetime
    grounds: str
    evidence_json: dict | None
    committee_json: dict | None
    committee_formed_at: datetime | None
    hearing_scheduled_at: datetime | None
    hearing_link: str | None
    hearing_held_at: datetime | None
    verdict: str | None
    verdict_by_json: dict | None
    verdict_at: datetime | None
    outcome: str | None
    status: str
    created_at: datetime


# ============================================================================
# RESCHEDULE
# ============================================================================

class ElectionRescheduleRequest(BaseModel):
    """
    Elections cannot be cancelled — only rescheduled. Requested by the
    responsible committee, approved by the Regional Administrator.
    """
    new_election_day: date
    reason: str = Field(..., min_length=10, max_length=2000)
    notes: str | None = Field(None, max_length=2000)


class ElectionRescheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    requested_by: str
    requested_at: datetime
    reason: str
    approved_by: str | None
    approved_at: datetime | None
    old_election_day: date
    new_election_day: date
    notes: str | None
    created_at: datetime


# ============================================================================
# NO-PAYER FALLBACK
# ============================================================================

class ElectionNoPayerEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    triggered_at: datetime
    phase: str
    notes: str | None
    created_at: datetime


# ============================================================================
# AUDIT
# ============================================================================

class ElectionAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    election_id: str
    event_type: str
    actor_id: str | None
    from_state: str | None
    to_state: str | None
    details_json: dict | None
    ip_address: str | None
    created_at: datetime


# ============================================================================
# AGGREGATED VIEWS
# ============================================================================

class ElectionDetailResponse(BaseModel):
    """
    Full election snapshot for the admin console or the voting page.
    Bundles the election + positions + tickets + candidates in one call.
    """
    election: ElectionResponse
    positions: list[ElectionPositionResponse]
    tickets: list[ElectionTicketResponse]
    candidates: list[ElectionCandidateResponse]


class ElectionListResponse(BaseModel):
    """Lightweight list item for the admin console."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    level: str
    constituency_id: str
    state: str
    election_day: date
    electorate_size: int
    votes_cast: int
    created_at: datetime


class ElectionCandidateApprovalStatus(BaseModel):
    """
    Progress view for a candidate — how many approval votes they have,
    what percentage of the electorate that is, and whether they've
    crossed the threshold.
    """
    candidate_id: str
    user_id: str
    position_id: str
    ticket_id: str
    approval_count: int
    electorate_size: int
    approval_percentage: float
    required_percentage: float
    qualified: bool
    fee_paid: bool
    on_final_ballot: bool


class ElectionEligibilityResponse(BaseModel):
    """
    Explains whether the constituency currently meets the requirements
    to start this election. Used by the admin console and the automatic
    trigger.
    """
    level: str
    constituency_id: str
    eligible: bool
    current_compliant_groups: int
    required_groups: int
    current_compliant_institutions: int
    required_institutions: int
    blockers: list[str]
    notes: str | None = None


class ElectionDashboardResponse(BaseModel):
    """Compact overview for the election management dashboard."""
    election_id: str
    title: str
    level: str
    state: str
    election_day: date
    days_until_election: int
    positions_count: int
    candidates_qualified: int
    electorate_size: int
    votes_cast: int
    total_votes_expected: int
    has_tie: bool
    under_appeal: bool
    under_regional_admin: bool