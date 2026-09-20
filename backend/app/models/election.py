"""
Election models — Module 003 Phase 6.

Covers all four levels (group, school, institution, county) with:
  - Election event with state machine
  - Positions being contested
  - Tickets (paired candidacies) and individual candidates
  - Voter roll (frozen snapshot)
  - Approval votes (15% threshold) and final ballots
  - Results
  - Live streams with suspense window
  - Disputes, appeals, reschedules
  - No-payer fallback events
  - Immutable audit log

Design notes:
  - All votes are cast for tickets, not individual candidates. A single-
    candidate "ticket" handles Treasurer-type positions where the ballot
    has one seat per ticket.
  - Voter roll is snapshotted at election start so eligibility cannot be
    changed mid-election.
  - The state machine is enforced by the service layer via
    `app/services/election_state.py`.
  - Live stream metadata lives on `elections` — one stream per election.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


# ============================================================================
# ELECTION
# ============================================================================

class Election(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "elections"
    __table_args__ = (
        CheckConstraint(
            "level IN ('group','school','institution','county')",
            name="ck_election_level",
        ),
        CheckConstraint(
            "state IN ("
            "'draft','scheduled','nominating','nominational_voting',"
            "'payment_window','awaiting_payment','regional_admin_interim',"
            "'ballot_finalized','campaigning','voting','counting',"
            "'suspense_blackout','result_declared',"
            "'run_off_scheduled','run_off_voting',"
            "'appeal_window','appealed','disputed','completed'"
            ")",
            name="ck_election_state",
        ),
        Index("ix_elections_level", "level"),
        Index("ix_elections_state", "state"),
        Index("ix_elections_constituency", "level", "constituency_id"),
        Index("ix_elections_election_day", "election_day"),
        Index("ix_elections_parent", "parent_election_id"),
    )

    # --- Identity ---
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # constituency_id points at the relevant entity depending on level:
    #   group       → groups.id
    #   school      → schools.id
    #   institution → institutions.id
    #   county      → counties.id
    constituency_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )

    # --- State machine ---
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", index=True,
    )

    # --- Timeline (all UTC) ---
    election_day: Mapped[date] = mapped_column(Date, nullable=False)
    nomination_open_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    nomination_close_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    approval_vote_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payment_window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    payment_window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ballot_finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    voting_open_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    voting_close_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    result_declared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    appeal_window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    dashboard_access_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Voting window duration (minutes) ---
    voting_duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1440,
    )

    # --- Electorate snapshot size (cached) ---
    electorate_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    votes_cast: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # --- Run-off ---
    is_runoff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    parent_election_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Live stream (counting only) ---
    live_stream_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    stream_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    stream_ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    suspense_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Reschedule history (latest only; full history in election_reschedules) ---
    rescheduled_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    rescheduled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- No-payer fallback ---
    under_regional_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # --- Metadata ---
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Relationships ---
    positions: Mapped[list["ElectionPosition"]] = relationship(
        "ElectionPosition", back_populates="election",
        cascade="all, delete-orphan",
    )
    tickets: Mapped[list["ElectionTicket"]] = relationship(
        "ElectionTicket", back_populates="election",
        cascade="all, delete-orphan",
    )
    candidates: Mapped[list["ElectionCandidate"]] = relationship(
        "ElectionCandidate", back_populates="election",
        cascade="all, delete-orphan",
    )
    voter_roll: Mapped[list["ElectionVoterRoll"]] = relationship(
        "ElectionVoterRoll", back_populates="election",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list["ElectionAuditEvent"]] = relationship(
        "ElectionAuditEvent", back_populates="election",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Election {self.level} {self.constituency_id} "
            f"[{self.state}] day={self.election_day}>"
        )


# ============================================================================
# POSITION
# ============================================================================

class ElectionPosition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "election_positions"
    __table_args__ = (
        UniqueConstraint(
            "election_id", "position_code",
            name="uq_election_position_code",
        ),
        CheckConstraint(
            "position_code IN ("
            "'group_leader','group_secretary','group_treasurer',"
            "'school_representative','assistant_school_rep',"
            "'institution_representative','assistant_institution_rep',"
            "'county_representative','assistant_county_rep'"
            ")",
            name="ck_election_position_code",
        ),
        CheckConstraint(
            "status IN ('pending','open','closed','filled','vacant')",
            name="ck_election_position_status",
        ),
        Index("ix_election_positions_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    position_code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Paired positions — e.g. Leader pairs with Secretary, School Rep pairs
    # with Assistant. Null means the position stands alone (Treasurer).
    is_paired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    paired_with_code: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
    )

    max_candidates: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2,
    )
    seats_available: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )

    # Qualification requirements
    required_approval_percentage: Mapped[float] = mapped_column(
        Float, nullable=False, default=15.0,
    )
    nomination_fee: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="KES",
    )

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
    )

    # Winner (populated at result declaration)
    winner_ticket_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("election_tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    winner_candidate_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("election_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    filled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    election: Mapped[Election] = relationship(
        "Election", back_populates="positions",
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionPosition {self.position_code} "
            f"election={self.election_id}>"
        )


# ============================================================================
# TICKET
# ============================================================================

class ElectionTicket(Base, UUIDMixin, TimestampMixin):
    """
    A candidate grouping. Usually 1-2 members. For paired positions
    (Leader+Secretary), a ticket has two candidates. For solo positions
    (Treasurer), a ticket has one candidate.
    """
    __tablename__ = "election_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending_approval','qualified','withdrawn',"
            "'disqualified','winner','runner_up','lost'"
            ")",
            name="ck_election_ticket_status",
        ),
        Index("ix_election_tickets_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # For paired tickets: the primary position (e.g. leader). For solo
    # tickets: the position itself (e.g. treasurer).
    primary_position_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("election_positions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    slogan: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # First-to-file order
    ballot_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending_approval", index=True,
    )

    qualified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    fee_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Cached counters (recomputed by the service layer)
    total_approval_votes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_votes_cast: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    election: Mapped[Election] = relationship(
        "Election", back_populates="tickets",
    )
    candidates: Mapped[list["ElectionCandidate"]] = relationship(
        "ElectionCandidate", back_populates="ticket",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionTicket {self.name or self.id} "
            f"election={self.election_id} status={self.status}>"
        )


# ============================================================================
# CANDIDATE
# ============================================================================

class ElectionCandidate(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "election_candidates"
    __table_args__ = (
        UniqueConstraint(
            "election_id", "user_id", "position_id",
            name="uq_election_candidate_user_position",
        ),
        CheckConstraint(
            "status IN ("
            "'pending','qualified','withdrawn','disqualified'"
            ")",
            name="ck_election_candidate_status",
        ),
        Index("ix_election_candidates_ticket", "ticket_id"),
        Index("ix_election_candidates_user", "user_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("election_tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("election_positions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    manifesto: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    nominated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # Approval tracking
    approval_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    approval_percentage: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
    )
    qualified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Fee
    fee_paid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    fee_payment_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    fee_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
    )

    election: Mapped[Election] = relationship(
        "Election", back_populates="candidates",
    )
    ticket: Mapped[ElectionTicket] = relationship(
        "ElectionTicket", back_populates="candidates",
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionCandidate user={self.user_id} "
            f"position={self.position_id} status={self.status}>"
        )


# ============================================================================
# VOTER ROLL
# ============================================================================

class ElectionVoterRoll(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "election_voter_roll"
    __table_args__ = (
        UniqueConstraint(
            "election_id", "user_id",
            name="uq_election_voter_roll",
        ),
        Index("ix_election_voter_roll_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    has_voted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    voted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    election: Mapped[Election] = relationship(
        "Election", back_populates="voter_roll",
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionVoterRoll election={self.election_id} "
            f"user={self.user_id} voted={self.has_voted}>"
        )


# ============================================================================
# APPROVAL VOTE (15% threshold)
# ============================================================================

class ElectionApprovalVote(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "election_approval_votes"
    __table_args__ = (
        UniqueConstraint(
            "election_id", "candidate_id", "voter_id",
            name="uq_election_approval_vote",
        ),
        Index("ix_election_approval_votes_candidate", "candidate_id"),
        Index("ix_election_approval_votes_voter", "voter_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("election_candidates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    voter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    cast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionApprovalVote candidate={self.candidate_id} "
            f"voter={self.voter_id}>"
        )


# ============================================================================
# BALLOT
# ============================================================================

class ElectionBallot(Base, UUIDMixin, TimestampMixin):
    """
    One vote cast for one position. For paired positions, the ballot
    references the ticket (which carries both candidates). For solo
    positions, the ballot also references the ticket (which has one
    candidate).
    """
    __tablename__ = "election_ballots"
    __table_args__ = (
        UniqueConstraint(
            "election_id", "position_id", "voter_id",
            name="uq_election_ballot",
        ),
        Index("ix_election_ballots_ticket", "ticket_id"),
        Index("ix_election_ballots_position", "position_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("election_positions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("election_tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    voter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    cast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    vote_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionBallot position={self.position_id} "
            f"ticket={self.ticket_id} voter={self.voter_id}>"
        )


# ============================================================================
# RESULT
# ============================================================================

class ElectionResult(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "election_results"
    __table_args__ = (
        UniqueConstraint(
            "election_id", "position_id",
            name="uq_election_result_position",
        ),
        Index("ix_election_results_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("election_positions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    winner_ticket_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("election_tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    winner_candidate_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("election_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )

    total_valid_votes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_invalid_votes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    winner_vote_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    runner_up_ticket_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("election_tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    runner_up_vote_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    margin: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    is_tie: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    tie_ticket_ids: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )

    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    verified_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    official: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ElectionResult position={self.position_id} "
            f"winner={self.winner_candidate_id} tie={self.is_tie}>"
        )


# ============================================================================
# DISPUTE
# ============================================================================

class ElectionDispute(Base, UUIDMixin, TimestampMixin):
    """
    A dispute filed during or immediately after an election. Forwarded
    to the Regional Administrator, who schedules a hearing and issues a
    verdict based on evidence.
    """
    __tablename__ = "election_disputes"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'filed','under_review','hearing_scheduled','hearing_held',"
            "'verdict_issued','resolved','dismissed'"
            ")",
            name="ck_election_dispute_status",
        ),
        Index("ix_election_disputes_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filed_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    filed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    grounds: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    assigned_to: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    hearing_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    hearing_link: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    hearing_held_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verdict_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="filed", index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionDispute election={self.election_id} "
            f"status={self.status}>"
        )


# ============================================================================
# APPEAL (Institution + County only)
# ============================================================================

class ElectionAppeal(Base, UUIDMixin, TimestampMixin):
    """
    Appeal filed within 7 days of election day. Only Institution and
    County levels. Committee composition mirrors the impeachment
    committee for that level. Hearing is public.
    """
    __tablename__ = "election_appeals"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'filed','committee_assembled','hearing_scheduled',"
            "'hearing_held','verdict_issued','resolved','dismissed'"
            ")",
            name="ck_election_appeal_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('confirmed','overturned','run_off_required')",
            name="ck_election_appeal_outcome",
        ),
        Index("ix_election_appeals_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filed_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    filed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    grounds: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Committee — same composition as the impeachment committee
    committee_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    committee_formed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Public hearing
    hearing_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    hearing_link: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    hearing_held_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict_by_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verdict_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="filed", index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionAppeal election={self.election_id} "
            f"status={self.status} outcome={self.outcome}>"
        )


# ============================================================================
# RESCHEDULE
# ============================================================================

class ElectionReschedule(Base, UUIDMixin, TimestampMixin):
    """
    One row per reschedule event. Elections cannot be cancelled, only
    rescheduled. Requests come from the responsible committee; approval
    comes from the Regional Administrator.
    """
    __tablename__ = "election_reschedules"
    __table_args__ = (
        Index("ix_election_reschedules_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    requested_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    old_election_day: Mapped[date] = mapped_column(Date, nullable=False)
    new_election_day: Mapped[date] = mapped_column(Date, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ElectionReschedule election={self.election_id} "
            f"{self.old_election_day}->{self.new_election_day}>"
        )


# ============================================================================
# NO-PAYER EVENT
# ============================================================================

class ElectionNoPayerEvent(Base, UUIDMixin, TimestampMixin):
    """
    Records the no-payer fallback lifecycle when candidates at
    Institution or County level fail to pay nomination fees.
    """
    __tablename__ = "election_no_payer_events"
    __table_args__ = (
        CheckConstraint(
            "phase IN ("
            "'interim_started','extended_window_started',"
            "'extended_window_expired','super_admin_assigned'"
            ")",
            name="ck_election_no_payer_phase",
        ),
        Index("ix_election_no_payer_election", "election_id"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ElectionNoPayerEvent election={self.election_id} "
            f"phase={self.phase}>"
        )


# ============================================================================
# AUDIT EVENT
# ============================================================================

class ElectionAuditEvent(Base, UUIDMixin, TimestampMixin):
    """Immutable log of every electoral action."""
    __tablename__ = "election_audit_events"
    __table_args__ = (
        Index("ix_election_audit_election", "election_id"),
        Index("ix_election_audit_actor", "actor_id"),
        Index("ix_election_audit_type", "event_type"),
    )

    election_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    election: Mapped[Election] = relationship(
        "Election", back_populates="audit_events",
    )

    def __repr__(self) -> str:
        return (
            f"<ElectionAuditEvent {self.event_type} "
            f"election={self.election_id}>"
        )