"""
Pydantic schemas for Activity Clubs — Module 003 Phase 10.
"""
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


# ═════════════════════════════════════════════════════════════════════════
# CLUB
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(None, max_length=2000)
    objective: str = Field(..., min_length=20, max_length=2000)
    motive: str = Field(..., min_length=20, max_length=4000)
    institution_id: str
    membership_visibility: str = Field(
        "public", description="public | private"
    )


class ActivityClubUpdate(BaseModel):
    description: str | None = None
    objective: str | None = None
    motive: str | None = None
    membership_visibility: str | None = None
    declared_term_months: int | None = Field(None, ge=6, le=24)
    notes: str | None = None


class ActivityClubResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None
    objective: str
    motive: str
    institution_id: str
    founder_id: str
    membership_visibility: str
    current_level: str
    status: str
    formed_at: datetime | None
    positions_published_at: datetime | None
    first_cycle_due_at: datetime | None
    promoted_to_county_at: datetime | None
    dissolved_at: datetime | None
    revived_at: datetime | None
    halt_warning_at: datetime | None
    halt_recovery_deadline: datetime | None
    approval_stage: str
    institution_rep_approved_at: datetime | None
    institution_rep_approved_by: str | None
    institution_rep_notes: str | None
    regional_rep_approved_at: datetime | None
    regional_rep_approved_by: str | None
    regional_rep_notes: str | None
    rejection_reason: str | None
    declared_term_months: int | None
    member_count: int
    position_count: int
    milestone_plan_json: list | None
    notes: str | None
    created_at: datetime


class ActivityClubListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None
    institution_id: str
    membership_visibility: str
    current_level: str
    status: str
    member_count: int
    position_count: int
    created_at: datetime


class ActivityClubDetailResponse(BaseModel):
    """Club + positions + viewer membership in one call."""
    club: ActivityClubResponse
    viewer_membership: "ActivityClubMembershipResponse | None" = None
    positions: list["ActivityClubPositionResponse"] = []
    milestones: list["ActivityClubMilestoneResponse"] = []


# ═════════════════════════════════════════════════════════════════════════
# MEMBERSHIP
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubJoinRequest(BaseModel):
    message: str | None = Field(None, max_length=500)


class ActivityClubMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    user_id: str
    status: str
    role: str
    request_message: str | None
    approved_by: str | None
    approved_at: datetime | None
    joined_at: datetime
    left_at: datetime | None
    left_reason: str | None
    graduated_at: datetime | None


# ═════════════════════════════════════════════════════════════════════════
# POSITIONS
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubPositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    position_code: str
    title: str
    description: str | None
    position_type: str
    display_order: int
    introduced_in_cycle: int
    introduced_by: str | None
    retired_in_cycle: int | None
    retired_at: datetime | None
    retired_by: str | None
    status: str
    current_holder_id: str | None
    current_term_start: datetime | None
    current_term_end: datetime | None


class ActivityClubCustomPositionProposal(BaseModel):
    position_code: str = Field(..., min_length=2, max_length=64)
    title: str = Field(..., min_length=2, max_length=160)
    description: str | None = Field(None, max_length=2000)


class ActivityClubPositionRetirementProposal(BaseModel):
    position_id: str
    reason: str = Field(..., min_length=10, max_length=2000)


class ActivityClubPositionApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    cycle_id: str | None
    target_position_id: str | None
    proposal_type: str
    proposed_code: str | None
    proposed_title: str | None
    proposed_description: str | None
    retirement_reason: str | None
    proposed_by: str
    proposed_at: datetime
    status: str
    votes_for: int
    votes_against: int
    required_threshold: float
    decided_at: datetime | None


class ActivityClubPositionApprovalBallotRequest(BaseModel):
    vote: str = Field(..., description="yes | no")


# ═════════════════════════════════════════════════════════════════════════
# MILESTONES
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubMilestoneCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(None, max_length=2000)
    period_start: date
    period_end: date
    target_metric: str = Field(..., min_length=3, max_length=200)
    target_value: float | None = None
    target_unit: str | None = Field(None, max_length=64)


class ActivityClubMilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    title: str
    description: str | None
    period_start: date
    period_end: date
    target_metric: str
    target_value: float | None
    target_unit: str | None
    status: str
    report_id: str | None
    declared_by: str
    declared_at: datetime


class ActivityClubMilestoneReportCreate(BaseModel):
    actual_value: float | None = None
    actual_unit: str | None = Field(None, max_length=64)
    outcome_note: str = Field(..., min_length=20, max_length=5000)
    completion_pdf_url: str = Field(..., min_length=5, max_length=500)
    completion_pdf_hash: str | None = Field(None, max_length=128)
    supporting_urls: list[str] | None = None


class ActivityClubMilestoneReportInstitutionReview(BaseModel):
    approve: bool
    notes: str | None = Field(None, max_length=2000)
    institution_rep_report_url: str | None = Field(None, max_length=500)


class ActivityClubMilestoneReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    milestone_id: str
    actual_value: float | None
    actual_unit: str | None
    outcome_note: str
    completion_pdf_url: str
    completion_pdf_hash: str | None
    supporting_urls_json: list | None
    status: str
    submitted_by: str
    submitted_at: datetime
    institution_rep_id: str | None
    institution_rep_decided_at: datetime | None
    institution_rep_notes: str | None
    institution_rep_report_url: str | None
    regional_rep_id: str | None
    regional_rep_received_at: datetime | None
    regional_rep_notes: str | None
    cc_county_rep_notified_at: datetime | None
    cc_super_admin_notified_at: datetime | None


# ═════════════════════════════════════════════════════════════════════════
# ELECTION CYCLES
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubElectionCycleInitiate(BaseModel):
    term_months: int = Field(..., ge=6, le=24)


class ActivityClubElectionCycleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    cycle_number: int
    status: str
    initiated_at: datetime
    positions_published_at: datetime | None
    voting_at: datetime | None
    results_declared_at: datetime | None
    completed_at: datetime | None
    election_fee_paid: bool
    election_fee_amount: int
    election_fee_reference: str | None
    election_fee_paid_at: datetime | None
    election_fee_method: str | None
    term_months: int | None
    failed_reason: str | None
    halt_warning_at: datetime | None
    halt_recovery_deadline: datetime | None


class ActivityClubElectionFeeRecord(BaseModel):
    payment_reference: str = Field(..., min_length=3, max_length=128)
    method: str = Field(..., description="mpesa | card")


# ═════════════════════════════════════════════════════════════════════════
# ELECTION CANDIDATES + VOTES
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubCandidateRegister(BaseModel):
    position_id: str
    manifesto: str | None = Field(None, max_length=4000)
    photo_url: str | None = Field(None, max_length=500)


class ActivityClubCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    cycle_id: str
    club_id: str
    position_id: str
    user_id: str
    manifesto: str | None
    photo_url: str | None
    status: str
    nominated_at: datetime
    votes_count: int


class ActivityClubVoteCast(BaseModel):
    position_id: str
    candidate_id: str


class ActivityClubVoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    cycle_id: str
    club_id: str
    position_id: str
    candidate_id: str
    voter_id: str
    cast_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# DISSOLUTION + REVIVAL
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubDissolutionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    trigger: str
    reason: str
    triggered_by: str | None
    triggered_at: datetime
    snapshot_json: dict | None


class ActivityClubRevivalPetitionCreate(BaseModel):
    letter_text: str = Field(..., min_length=50, max_length=10000)
    supporting_urls: list[str] | None = None


class ActivityClubRevivalPetitionReview(BaseModel):
    approve: bool
    notes: str | None = Field(None, max_length=2000)


class ActivityClubRevivalPetitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    dissolution_event_id: str | None
    filed_by: str
    filed_at: datetime
    letter_text: str
    supporting_urls_json: list | None
    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    cc_institution_admin_notified_at: datetime | None
    cc_county_admin_notified_at: datetime | None
    approved_at: datetime | None
    members_reinstated_count: int


# ═════════════════════════════════════════════════════════════════════════
# APPROVAL EVENTS (audit)
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubApprovalEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    club_id: str
    event_type: str
    actor_id: str | None
    from_state: str | None
    to_state: str | None
    details_json: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# PAYMENT (county promotion fee)
# ═════════════════════════════════════════════════════════════════════════

class ActivityClubCountyPromotionRequest(BaseModel):
    payment_reference: str = Field(..., min_length=3, max_length=128)
    method: str = Field(..., description="mpesa | card")


# Forward references for nested detail response
ActivityClubDetailResponse.model_rebuild()