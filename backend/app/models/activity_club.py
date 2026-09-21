"""
Activity club models — Module 003 Phase 10.

An activity club is an institution-scoped student organisation that is
not bound to a course. Chess Club, Debate Club, Coding Club, etc.

Key design points:
  - Tied to exactly one institution
  - Two-level approval chain: Institution Rep → Regional Rep
  - 3-month forming period before positions are published
  - Founder procedural immunity until first election completes
  - Milestone periods are founder-defined (any length)
  - Election fee (KSh 200) recurs at every cycle
  - County promotion fee (KSh 250) at promotion
  - No impeachment; dissolution is soft-delete with snapshot
  - Revival via letter to Regional Admin

Statuses:
  Club              : forming | active | halted | dissolved | county
  Membership        : pending | active | suspended | left | removed | alumni_readonly
  Milestone         : declared | active | report_pending | reported | evaluated | missed
  MilestoneReport   : submitted | institution_approved | institution_rejected
                      | regional_forwarded | closed
  Cycle             : draft | positions_published | candidates_open | voting
                      | closed | verified | completed | failed | halted
  Candidate         : nominated | qualified | withdrawn | disqualified | winner | lost
  PositionApproval  : proposed | approved | rejected | expired
  RevivalPetition   : filed | under_review | approved | rejected
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


# ── constants ────────────────────────────────────────────────────────────

# Membership setting per club
VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"

# Fee amounts (KES)
ELECTION_FEE = 200
PROMOTION_FEE = 250

# Membership caps
INSTITUTION_CLUB_MEMBER_CAP = 5_000
COUNTY_CLUB_MEMBER_CAP = 50_000
MAX_CLUBS_PER_STUDENT = 20

# Forming period
FORMING_PERIOD_DAYS = 90     # 3 months
DEBATE_WINDOW_DAYS = 30      # month 3 → month 4
FIRST_CYCLE_OFFSET_DAYS = 120  # end of month 4 from creation

# Election cycle windows
CYCLE_VOTING_DAY = 7         # day 7 after initiation
CYCLE_RESULT_DAY = 9         # day 9 after initiation

# Position approval window
POSITION_APPROVAL_DELAY_DAYS = 3   # 3 days after positions published + fee paid

# Standard positions (12)
STANDARD_POSITIONS: list[tuple[str, str]] = [
    ("chairperson", "Chairperson / President"),
    ("vice_chairperson", "Vice Chairperson"),
    ("secretary", "Secretary"),
    ("assistant_secretary", "Assistant Secretary"),
    ("treasurer", "Treasurer"),
    ("assistant_treasurer", "Assistant Treasurer"),
    ("organising_secretary", "Organising Secretary"),
    ("publicity_secretary", "Publicity Secretary"),
    ("project_coordinator", "Project Coordinator"),
    ("membership_officer", "Membership Officer"),
    ("events_coordinator", "Events Coordinator"),
    ("welfare_officer", "Welfare Officer"),
]

MAX_CUSTOM_POSITIONS = 10

# Revival / dissolution
HALT_RECOVERY_WINDOW_DAYS = 14


# ─────────────────────────────────────────────────────────────────────────
# 1. CLUB
# ─────────────────────────────────────────────────────────────────────────

class ActivityClub(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_clubs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('forming','active','halted','dissolved','county')",
            name="ck_club_status",
        ),
        CheckConstraint(
            "membership_visibility IN ('public','private')",
            name="ck_club_membership_visibility",
        ),
        CheckConstraint(
            "current_level IN ('institution','county')",
            name="ck_club_level",
        ),
        UniqueConstraint(
            "institution_id", "name",
            name="uq_club_institution_name",
        ),
        Index("ix_clubs_institution", "institution_id"),
        Index("ix_clubs_status", "status"),
        Index("ix_clubs_level", "current_level"),
        Index("ix_clubs_founder", "founder_id"),
    )

    # --- Identity ---
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    motive: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Institution binding ---
    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # --- Founder ---
    founder_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # --- Membership setting ---
    membership_visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=VISIBILITY_PUBLIC,
    )

    # --- Current level ---
    current_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="institution", index=True,
    )

    # --- Lifecycle ---
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="forming", index=True,
    )
    formed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    positions_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    first_cycle_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    promoted_to_county_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    dissolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    revived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    halt_warning_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    halt_recovery_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Approval chain (initial creation) ---
    approval_stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_institution_rep",
    )
    institution_rep_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    institution_rep_approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    institution_rep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    regional_rep_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    regional_rep_approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    regional_rep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Declared term length for the current/next cycle (6m–2y) ---
    declared_term_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # --- Cached counts ---
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Milestone plan as declared (denormalized for quick listing) ---
    milestone_plan_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # --- Free-form notes ---
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ActivityClub {self.slug} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────
# 2. MEMBERSHIP
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubMembership(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_memberships"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','active','suspended','left','removed',"
            "'alumni_readonly')",
            name="ck_club_membership_status",
        ),
        CheckConstraint(
            "role IN ('member','leader','officer')",
            name="ck_club_membership_role",
        ),
        UniqueConstraint(
            "club_id", "user_id",
            name="uq_club_membership",
        ),
        Index("ix_club_memberships_club", "club_id"),
        Index("ix_club_memberships_user", "user_id"),
        Index("ix_club_memberships_status", "status"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True,
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member",
    )

    # --- Join flow ---
    request_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    left_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Alumni transition ---
    graduated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ActivityClubMembership club={self.club_id} "
            f"user={self.user_id} status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 3. POSITIONS
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubPosition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_positions"
    __table_args__ = (
        CheckConstraint(
            "position_type IN ('standard','custom')",
            name="ck_club_position_type",
        ),
        CheckConstraint(
            "status IN ('active','retired')",
            name="ck_club_position_status",
        ),
        CheckConstraint(
            "introduced_in_cycle >= 0",
            name="ck_club_position_introduced_cycle",
        ),
        UniqueConstraint(
            "club_id", "position_code",
            name="uq_club_position_code",
        ),
        Index("ix_club_positions_club", "club_id"),
        Index("ix_club_positions_status", "status"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    position_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    position_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard",
    )

    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Cycle metadata ---
    introduced_in_cycle: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )   # 0 = pre-first-election (founder-defined standard set)
    introduced_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    retired_in_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    retired_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True,
    )

    # --- Current holder (filled after a successful election) ---
    current_holder_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    current_term_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    current_term_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return f"<ActivityClubPosition {self.club_id}:{self.position_code}>"


# ─────────────────────────────────────────────────────────────────────────
# 4. MILESTONES
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubMilestone(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_milestones"
    __table_args__ = (
        CheckConstraint(
            "status IN ('declared','active','report_pending','reported',"
            "'evaluated','missed')",
            name="ck_club_milestone_status",
        ),
        Index("ix_club_milestones_club", "club_id"),
        Index("ix_club_milestones_status", "status"),
        Index("ix_club_milestones_period_end", "period_end"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Period (founder-defined, any length) ---
    period_start: Mapped[datetime] = mapped_column(
        Date(), nullable=False,
    )
    period_end: Mapped[datetime] = mapped_column(
        Date(), nullable=False, index=True,
    )

    # --- Target / KPI ---
    target_metric: Mapped[str] = mapped_column(String(200), nullable=False)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="declared", index=True,
    )

    # --- Links to report ---
    report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(
            "activity_club_milestone_reports.id", ondelete="SET NULL",
        ),
        nullable=True,
    )

    declared_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ActivityClubMilestone {self.id} '{self.title}'>"


# ─────────────────────────────────────────────────────────────────────────
# 5. MILESTONE REPORTS
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubMilestoneReport(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_milestone_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted','institution_approved','institution_rejected',"
            "'regional_forwarded','closed')",
            name="ck_club_milestone_report_status",
        ),
        Index("ix_club_milestone_reports_club", "club_id"),
        Index("ix_club_milestone_reports_milestone", "milestone_id"),
        Index("ix_club_milestone_reports_status", "status"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    milestone_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_club_milestones.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # --- Actual results ---
    actual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome_note: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Evidence ---
    completion_pdf_url: Mapped[str] = mapped_column(String(500), nullable=False)
    completion_pdf_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supporting_urls_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="submitted", index=True,
    )

    # --- Submission ---
    submitted_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # --- Institution Rep decision ---
    institution_rep_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    institution_rep_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    institution_rep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    institution_rep_report_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )

    # --- Regional Rep forwarding ---
    regional_rep_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    regional_rep_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    regional_rep_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- cc recipients ---
    cc_county_rep_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cc_super_admin_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return f"<ActivityClubMilestoneReport {self.id} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────
# 6. ELECTION CYCLES
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubElectionCycle(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_election_cycles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','positions_published','candidates_open',"
            "'voting','closed','verified','completed','failed','halted')",
            name="ck_club_cycle_status",
        ),
        UniqueConstraint("club_id", "cycle_number",
                         name="uq_club_cycle_number"),
        Index("ix_club_cycles_club", "club_id"),
        Index("ix_club_cycles_status", "status"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="draft", index=True,
    )

    # --- Timeline ---
    initiated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    positions_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    voting_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    results_declared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Fee ---
    election_fee_paid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    election_fee_amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=ELECTION_FEE,
    )
    election_fee_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    election_fee_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    election_fee_method: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
    )  # 'mpesa' | 'card'

    # --- Declared term length for this cycle ---
    term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Failure handling ---
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    halt_warning_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    halt_recovery_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ActivityClubElectionCycle club={self.club_id} "
            f"cycle={self.cycle_number} status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 7. ELECTION CANDIDATES
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubElectionCandidate(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_election_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('nominated','qualified','withdrawn','disqualified',"
            "'winner','lost')",
            name="ck_club_candidate_status",
        ),
        UniqueConstraint(
            "cycle_id", "position_id", "user_id",
            name="uq_club_candidate",
        ),
        Index("ix_club_candidates_cycle", "cycle_id"),
        Index("ix_club_candidates_position", "position_id"),
        Index("ix_club_candidates_user", "user_id"),
    )

    cycle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_club_election_cycles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_club_positions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    manifesto: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="nominated", index=True,
    )

    nominated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    votes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<ActivityClubElectionCandidate cycle={self.cycle_id} "
            f"position={self.position_id} user={self.user_id}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 8. ELECTION VOTES
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubElectionVote(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_election_votes"
    __table_args__ = (
        UniqueConstraint(
            "cycle_id", "position_id", "voter_id",
            name="uq_club_vote_per_position",
        ),
        Index("ix_club_votes_cycle", "cycle_id"),
        Index("ix_club_votes_position", "position_id"),
        Index("ix_club_votes_voter", "voter_id"),
    )

    cycle_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_club_election_cycles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_club_positions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_club_election_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    voter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    cast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    vote_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    def __repr__(self) -> str:
        return f"<ActivityClubElectionVote cycle={self.cycle_id}>"


# ─────────────────────────────────────────────────────────────────────────
# 9. POSITION APPROVAL VOTES (custom additions + retirements)
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubPositionApprovalVote(Base, UUIDMixin, TimestampMixin):
    """
    A proposal to add a custom position or retire an existing position.
    Proposed by the elected leader 3+ days after positions are published
    and election fee is paid. Members vote to approve.
    """
    __tablename__ = "activity_club_position_approval_votes"
    __table_args__ = (
        CheckConstraint(
            "proposal_type IN ('add_custom','retire_position')",
            name="ck_club_position_approval_type",
        ),
        CheckConstraint(
            "status IN ('proposed','approved','rejected','expired')",
            name="ck_club_position_approval_status",
        ),
        Index("ix_club_pos_approval_club", "club_id"),
        Index("ix_club_pos_approval_cycle", "cycle_id"),
        Index("ix_club_pos_approval_status", "status"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cycle_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("activity_club_election_cycles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    target_position_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("activity_club_positions.id", ondelete="SET NULL"),
        nullable=True,
    )

    proposal_type: Mapped[str] = mapped_column(String(24), nullable=False)

    # --- For add_custom ---
    proposed_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposed_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    proposed_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- For retire_position ---
    retirement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Metadata ---
    proposed_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="proposed", index=True,
    )

    # --- Voting tallies ---
    votes_for: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    votes_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=2/3,
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ActivityClubPositionApprovalVote {self.id} "
            f"type={self.proposal_type} status={self.status}>"
        )


class ActivityClubPositionApprovalBallot(Base, UUIDMixin, TimestampMixin):
    """One ballot per member per approval proposal."""
    __tablename__ = "activity_club_position_approval_ballots"
    __table_args__ = (
        CheckConstraint(
            "vote IN ('yes','no')",
            name="ck_club_position_approval_ballot_vote",
        ),
        UniqueConstraint(
            "proposal_id", "voter_id",
            name="uq_club_position_approval_ballot",
        ),
        Index("ix_club_pos_approval_ballot_proposal", "proposal_id"),
    )

    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(
            "activity_club_position_approval_votes.id", ondelete="CASCADE",
        ),
        nullable=False, index=True,
    )
    voter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    vote: Mapped[str] = mapped_column(String(8), nullable=False)
    cast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ActivityClubPositionApprovalBallot {self.id}>"


# ─────────────────────────────────────────────────────────────────────────
# 10. DISSOLUTION EVENTS
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubDissolutionEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_dissolution_events"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('failed_election','halted_recovery_expired',"
            "'admin_dissolved','other')",
            name="ck_club_dissolution_trigger",
        ),
        Index("ix_club_dissolution_club", "club_id"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    triggered_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # Snapshot for revival — full JSON of members, positions, milestones
    snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<ActivityClubDissolutionEvent club={self.club_id}>"


# ─────────────────────────────────────────────────────────────────────────
# 11. REVIVAL PETITIONS
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubRevivalPetition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "activity_club_revival_petitions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('filed','under_review','approved','rejected')",
            name="ck_club_revival_status",
        ),
        Index("ix_club_revival_club", "club_id"),
        Index("ix_club_revival_status", "status"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    dissolution_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(
            "activity_club_dissolution_events.id", ondelete="SET NULL",
        ),
        nullable=True,
    )

    filed_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    filed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # The letter
    letter_text: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_urls_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="filed", index=True,
    )

    # --- Review chain: Regional Admin decides ---
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- cc notifications ---
    cc_institution_admin_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cc_county_admin_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- On approval ---
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    members_reinstated_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    def __repr__(self) -> str:
        return f"<ActivityClubRevivalPetition club={self.club_id} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────
# 12. APPROVAL EVENTS (audit trail)
# ─────────────────────────────────────────────────────────────────────────

class ActivityClubApprovalEvent(Base, UUIDMixin, TimestampMixin):
    """
    Immutable audit trail of all approval-chain decisions.
    Complements the state transitions of the club itself.
    """
    __tablename__ = "activity_club_approval_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'club.created','club.institution_rep_approved',"
            "'club.institution_rep_rejected','club.regional_rep_approved',"
            "'club.regional_rep_rejected',"
            "'club.positions_published','club.first_cycle_initiated',"
            "'club.election_fee_paid','club.cycle_completed',"
            "'club.cycle_failed','club.halted','club.dissolved',"
            "'club.revival_petition_filed','club.revival_approved',"
            "'club.revival_rejected','club.revived','club.promoted',"
            "'club.milestone_report_submitted',"
            "'club.milestone_report_institution_approved',"
            "'club.milestone_report_institution_rejected',"
            "'club.milestone_report_regional_forwarded',"
            "'club.milestone_report_closed',"
            "'club.position_approval_proposed',"
            "'club.position_approval_decided',"
            "'club.founder_removed'"
            ")",
            name="ck_club_approval_event_type",
        ),
        Index("ix_club_approval_events_club", "club_id"),
        Index("ix_club_approval_events_type", "event_type"),
    )

    club_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("activity_clubs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)

    details_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<ActivityClubApprovalEvent club={self.club_id} {self.event_type}>"