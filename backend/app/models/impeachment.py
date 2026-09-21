"""
Impeachment models — Module 003 Phase 9.

Applies at School, Institution, and County levels only.
Group officials and activity-club executives are NOT impeachable.

Flow:
  filed → reconciliation → petition → committee_forming → hearing
    → verdict_removed → disclosure_period → replacement_election → resolved_removed
    → verdict_reinstated → resolved_reinstated
    → petition_failed / dismissed_via_reconciliation / withdrawn (terminal)

Hearing sub-flow (while case.status == 'hearing'):
  sessions 1..4 scheduled
    → session 1 (accusation) started → completed
    → session 2 (evidence)   started → completed
    → session 3 (defense)    started → completed
    → session 4 (verdict)    started
        → moderator OPENS verdict voting  (verdict_voting_opened_at stamped)
        → committee members cast votes
        → auto-finalize on threshold reached / mathematically eliminated
        → (optionally) moderator CLOSES verdict voting
        → session 4 completed

Rules:
  - Petition: 25% of the electorate that originally elected the target.
  - Committee: 2/3 of the relevant officials at the level immediately
    below the target (School Rep → Group Leaders, Institution Rep →
    School Reps, County Rep → Institution Reps).
  - Committee is locked for the duration.
  - Verdict: 2/3 of the committee must vote to remove.
  - Moderator (initializer) does NOT vote.
  - Only the moderator opens the voting.
  - Acting officials cannot be impeached.
  - No appeals.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


# ── constants ────────────────────────────────────────────────────────────

TARGET_LEVELS = ("school", "institution", "county")
CASE_STATES = (
    "filed",                   # initial complaint
    "reconciliation",          # admin attempting resolution
    "petition",                # collecting 25% signatures
    "petition_failed",         # threshold not reached
    "dismissed_via_reconciliation",
    "committee_forming",       # 25% reached, assembling committee
    "hearing",                 # 4 sessions in progress
    "verdict_removed",         # 2/3 voted to remove
    "verdict_reinstated",      # less than 2/3
    "disclosure_period",       # 14 days post-removal
    "replacement_election",    # 12h voting
    "resolved_removed",        # final
    "resolved_reinstated",     # final
    "withdrawn",               # case dropped
)

SESSION_TYPES = ("accusation", "evidence", "defense", "verdict")


# ── case ─────────────────────────────────────────────────────────────────

class ImpeachmentCase(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "impeachment_cases"
    __table_args__ = (
        CheckConstraint(
            "target_level IN ('school','institution','county')",
            name="ck_impeachment_target_level",
        ),
        CheckConstraint(
            "status IN ("
            "'filed','reconciliation','petition','petition_failed',"
            "'dismissed_via_reconciliation','committee_forming','hearing',"
            "'verdict_removed','verdict_reinstated','disclosure_period',"
            "'replacement_election','resolved_removed','resolved_reinstated',"
            "'withdrawn'"
            ")",
            name="ck_impeachment_status",
        ),
        Index("ix_impeachment_status", "status"),
        Index("ix_impeachment_target", "target_user_id"),
        Index("ix_impeachment_constituency", "target_level", "constituency_id"),
    )

    # --- Target ---
    target_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    target_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    target_level: Mapped[str] = mapped_column(String(16), nullable=False)
    constituency_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # --- Filing ---
    filed_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False,
    )
    filed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    grounds: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="filed", index=True,
    )

    # --- Reconciliation ---
    reconciliation_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    reconciliation_mediator_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reconciliation_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reconciliation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Petition ---
    petition_required_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    petition_signature_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    petition_reached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Committee ---
    committee_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    committee_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    committee_formed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    committee_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    initializer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    # --- Hearing ---
    hearing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    hearing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    hearing_is_live_streamed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    hearing_is_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # --- Verdict voting control (Session 4) ---
    # The moderator MUST explicitly open voting during Session 4 before
    # any committee member can cast a verdict vote.
    verdict_voting_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    verdict_voting_opened_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    verdict_voting_closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    verdict_voting_closed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    # --- Verdict ---
    verdict: Mapped[str | None] = mapped_column(String(24), nullable=True)
    verdict_votes_for: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verdict_votes_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verdict_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=2/3)
    verdict_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Post-removal ---
    disclosure_period_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    removal_effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Replacement election ---
    replacement_election_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="SET NULL"),
        nullable=True,
    )
    replacement_winner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── petition signatures ──────────────────────────────────────────────────

class ImpeachmentPetition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "impeachment_petitions"
    __table_args__ = (
        UniqueConstraint("case_id", "signer_id", name="uq_impeachment_petition_signer"),
        Index("ix_impeachment_petition_case", "case_id"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("impeachment_cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    signer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    signature_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ── hearing sessions ─────────────────────────────────────────────────────

class ImpeachmentSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "impeachment_sessions"
    __table_args__ = (
        UniqueConstraint("case_id", "session_number",
                         name="uq_impeachment_session_number"),
        CheckConstraint(
            "session_type IN ('accusation','evidence','defense','verdict')",
            name="ck_impeachment_session_type",
        ),
        CheckConstraint(
            "session_number BETWEEN 1 AND 4",
            name="ck_impeachment_session_number_range",
        ),
        CheckConstraint(
            "status IN ('scheduled','in_progress','completed','adjourned')",
            name="ck_impeachment_session_status",
        ),
        Index("ix_impeachment_session_case", "case_id"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("impeachment_cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    session_number: Mapped[int] = mapped_column(Integer, nullable=False)
    session_type: Mapped[str] = mapped_column(String(16), nullable=False)

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    is_live_streamed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- AI-assisted transcription ---
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Minutes (reviewed then finalized) ---
    minutes_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    minutes_finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    minutes_finalized_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="scheduled",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── committee votes ──────────────────────────────────────────────────────

class ImpeachmentVote(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "impeachment_votes"
    __table_args__ = (
        UniqueConstraint("case_id", "voter_id", name="uq_impeachment_vote"),
        CheckConstraint(
            "vote IN ('remove','keep')",
            name="ck_impeachment_vote_value",
        ),
        Index("ix_impeachment_vote_case", "case_id"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("impeachment_cases.id", ondelete="CASCADE"),
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
    vote_hash: Mapped[str] = mapped_column(String(128), nullable=False)