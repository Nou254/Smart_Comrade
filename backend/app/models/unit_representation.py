"""
Unit Representation models — Module 004.

The academic coordination layer that connects students taking the same
unit across different groups.

Design decisions locked:
  - Network archived when the semester ends (read-only)
  - Rep replacement removes the outgoing rep from the network silently
  - Shared resources are AI-scanned to affirm unit relevance
  - Disagreements between reps are resolved by posing an educational
    question to the supervisor + AI assistant; AI responds within 5
    minutes after research
  - A rep can raise a question on behalf of an anonymous student
  - Non-reps can see issues and their outcomes (public summary)
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


# ── constants ────────────────────────────────────────────────────────────

# Representative status
REP_PENDING = "pending"
REP_ACTIVE = "active"
REP_SUSPENDED = "suspended"
REP_ENDED = "ended"
REP_REPLACED = "replaced"
REP_RESIGNED = "resigned"

ALL_REP_STATUSES = (
    REP_PENDING, REP_ACTIVE, REP_SUSPENDED,
    REP_ENDED, REP_REPLACED, REP_RESIGNED,
)

# Network member roles
NETWORK_ROLE_REP = "rep"
NETWORK_ROLE_SUPERVISOR = "supervisor"
NETWORK_ROLE_OBSERVER = "observer"

ALL_NETWORK_ROLES = (
    NETWORK_ROLE_REP, NETWORK_ROLE_SUPERVISOR, NETWORK_ROLE_OBSERVER,
)

# Issue categories
ISSUE_CATEGORIES = (
    "content", "resource", "scheduling", "assessment",
    "practical", "communication", "other",
)

# Issue statuses
ISSUE_IDENTIFIED = "identified"
ISSUE_UNDER_NETWORK_DISCUSSION = "under_network_discussion"
ISSUE_ESCALATED = "escalated"
ISSUE_UNDER_REVIEW = "under_review"
ISSUE_RESOLVED = "resolved"
ISSUE_DISMISSED = "dismissed"
ISSUE_WITHDRAWN = "withdrawn"

ALL_ISSUE_STATUSES = (
    ISSUE_IDENTIFIED, ISSUE_UNDER_NETWORK_DISCUSSION, ISSUE_ESCALATED,
    ISSUE_UNDER_REVIEW, ISSUE_RESOLVED, ISSUE_DISMISSED, ISSUE_WITHDRAWN,
)

# Escalation levels
LEVEL_NONE = "none"
LEVEL_NETWORK = "network"
LEVEL_SUPERVISOR = "supervisor"
LEVEL_LECTURER = "lecturer"
LEVEL_SCHOOL = "school"
LEVEL_INSTITUTION = "institution"

ALL_ESCALATION_LEVELS = (
    LEVEL_NONE, LEVEL_NETWORK, LEVEL_SUPERVISOR,
    LEVEL_LECTURER, LEVEL_SCHOOL, LEVEL_INSTITUTION,
)

# Question statuses (AI-assisted flow)
QUESTION_POSED = "posed"
QUESTION_AI_RESEARCHING = "ai_researching"
QUESTION_AI_RESPONDED = "ai_responded"
QUESTION_SUPERVISOR_REVIEW = "supervisor_review"
QUESTION_RESOLVED = "resolved"
QUESTION_DISMISSED = "dismissed"

ALL_QUESTION_STATUSES = (
    QUESTION_POSED, QUESTION_AI_RESEARCHING, QUESTION_AI_RESPONDED,
    QUESTION_SUPERVISOR_REVIEW, QUESTION_RESOLVED, QUESTION_DISMISSED,
)

# Question categories — must be educational
QUESTION_CATEGORIES = (
    "educational", "content_clarification", "resource_verification",
    "assessment_format", "other_educational",
)

# Question response time limit
QUESTION_AI_RESPONSE_MINUTES = 5

# Resource types
RESOURCE_TYPES = ("document", "link", "note", "code")

# Resource visibility
RESOURCE_VISIBILITY_NETWORK = "network_only"
RESOURCE_VISIBILITY_UNIT = "all_unit_students"

# AI scan statuses for shared resources
SCAN_PENDING = "pending"
SCAN_SCANNING = "scanning"
SCAN_VERIFIED = "verified_unit_match"
SCAN_FLAGGED = "flagged_off_topic"
SCAN_FAILED = "failed"

ALL_SCAN_STATUSES = (
    SCAN_PENDING, SCAN_SCANNING, SCAN_VERIFIED, SCAN_FLAGGED, SCAN_FAILED,
)


# ─────────────────────────────────────────────────────────────────────────
# 1. UNIT REPRESENTATIVE (appointment record)
# ─────────────────────────────────────────────────────────────────────────

class UnitRepresentative(Base, UUIDMixin, TimestampMixin):
    """
    One row per (group, unit offering, semester) appointment.

    Only one active appointment per group per offering, enforced by a
    partial unique index. Historical appointments (ended/replaced/resigned)
    accumulate freely.
    """
    __tablename__ = "unit_representatives"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALL_REP_STATUSES)})",
            name="ck_unit_rep_status",
        ),
        Index("ix_unit_reps_group", "group_id"),
        Index("ix_unit_reps_user", "user_id"),
        Index("ix_unit_reps_offering", "unit_offering_id"),
        Index("ix_unit_reps_semester", "semester_id"),
        # Only one ACTIVE rep per (group, offering)
        Index(
            "uq_active_unit_rep_per_group_offering",
            "group_id", "unit_offering_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    unit_offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Denormalized for fast queries
    semester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("semesters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Who appointed them
    appointed_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    appointed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=REP_PENDING, index=True,
    )
    term_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    term_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional — replacement rep (if this appointment was superseded)
    replaced_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("unit_representatives.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UnitRepresentative group={self.group_id} "
            f"offering={self.unit_offering_id} status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 2. UNIT NETWORK (one per unit offering)
# ─────────────────────────────────────────────────────────────────────────

class UnitNetwork(Base, UUIDMixin, TimestampMixin):
    """
    The coordination environment for a unit offering.

    Created lazily when the first rep is appointed. Persists until the
    semester ends, then is archived (read-only).
    """
    __tablename__ = "unit_networks"
    __table_args__ = (
        UniqueConstraint("unit_offering_id", name="uq_unit_network_offering"),
        Index("ix_unit_networks_semester", "semester_id"),
        Index("ix_unit_networks_active", "is_active"),
    )

    unit_offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    semester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("semesters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Assigned academic supervisor (nullable until Module 002 assigns one)
    supervisor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<UnitNetwork offering={self.unit_offering_id} "
            f"active={self.is_active}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 3. NETWORK MEMBER (junction)
# ─────────────────────────────────────────────────────────────────────────

class UnitNetworkMember(Base, UUIDMixin, TimestampMixin):
    """
    Membership row linking users to a network. Covers reps (via
    representative_id) and the supervisor (via user_id only).
    """
    __tablename__ = "unit_network_members"
    __table_args__ = (
        UniqueConstraint(
            "network_id", "user_id",
            name="uq_unit_network_member_user",
        ),
        CheckConstraint(
            f"role_in_network IN ({','.join(repr(r) for r in ALL_NETWORK_ROLES)})",
            name="ck_unit_network_member_role",
        ),
        Index("ix_unit_network_members_network", "network_id"),
        Index("ix_unit_network_members_user", "user_id"),
        Index("ix_unit_network_members_active", "is_active"),
    )

    network_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_networks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Nullable for supervisors/observers who aren't appointed reps
    representative_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("unit_representatives.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    role_in_network: Mapped[str] = mapped_column(
        String(16), nullable=False, default=NETWORK_ROLE_REP,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # Reason for leaving — 'replaced', 'semester_ended', 'resigned', etc.
    left_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UnitNetworkMember network={self.network_id} "
            f"user={self.user_id} role={self.role_in_network}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 4. NETWORK COORDINATION MESSAGES (rep-to-rep chat)
# ─────────────────────────────────────────────────────────────────────────

class UnitCoordinationMessage(Base, UUIDMixin, TimestampMixin):
    """
    Chat messages within a network — rep-to-rep coordination.

    When a rep is replaced, they are removed from the network. No
    notification is sent. Historical messages remain queryable to the
    network members who remain.
    """
    __tablename__ = "unit_coordination_messages"
    __table_args__ = (
        Index(
            "ix_unit_coord_messages_network_created",
            "network_id", "created_at",
        ),
        Index("ix_unit_coord_messages_sender", "sender_id"),
    )

    network_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_networks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("unit_coordination_messages.id",
                             ondelete="SET NULL"),
        nullable=True,
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<UnitCoordinationMessage network={self.network_id}>"


# ─────────────────────────────────────────────────────────────────────────
# 5. UNIT DISCUSSIONS (student-facing threads)
# ─────────────────────────────────────────────────────────────────────────

class UnitDiscussion(Base, UUIDMixin, TimestampMixin):
    """
    Student-facing discussion threads at the unit level.

    Any student taking the unit can participate. Threads with parent_id
    set are replies. Root threads have a title; replies do not.
    """
    __tablename__ = "unit_discussions"
    __table_args__ = (
        Index(
            "ix_unit_discussions_offering_created",
            "unit_offering_id", "created_at",
        ),
        Index("ix_unit_discussions_parent", "parent_id"),
        Index("ix_unit_discussions_author", "author_id"),
    )

    unit_offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("unit_discussions.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<UnitDiscussion offering={self.unit_offering_id} "
            f"author={self.author_id}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 6. UNIT ANNOUNCEMENTS
# ─────────────────────────────────────────────────────────────────────────

class UnitAnnouncement(Base, UUIDMixin, TimestampMixin):
    """Official unit-wide announcements from reps, supervisors, lecturers."""
    __tablename__ = "unit_announcements"
    __table_args__ = (
        CheckConstraint(
            "publisher_role IN ('rep','supervisor','lecturer')",
            name="ck_unit_announcement_role",
        ),
        Index(
            "ix_unit_announcements_offering_created",
            "unit_offering_id", "created_at",
        ),
    )

    unit_offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    publisher_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    publisher_role: Mapped[str] = mapped_column(String(16), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    def __repr__(self) -> str:
        return f"<UnitAnnouncement offering={self.unit_offering_id}>"


# ─────────────────────────────────────────────────────────────────────────
# 7. UNIT ISSUES
# ─────────────────────────────────────────────────────────────────────────

class UnitIssue(Base, UUIDMixin, TimestampMixin):
    """
    Structured issue reports raised by reps.

    Non-reps can see public issues and their outcomes via the
    public_summary field. The full issue record remains visible only to
    the network and the supervisor.
    """
    __tablename__ = "unit_issues"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALL_ISSUE_STATUSES)})",
            name="ck_unit_issue_status",
        ),
        CheckConstraint(
            f"current_escalation_level IN "
            f"({','.join(repr(l) for l in ALL_ESCALATION_LEVELS)})",
            name="ck_unit_issue_escalation_level",
        ),
        CheckConstraint(
            f"category IN ({','.join(repr(c) for c in ISSUE_CATEGORIES)})",
            name="ck_unit_issue_category",
        ),
        Index("ix_unit_issues_offering_status", "unit_offering_id", "status"),
        Index("ix_unit_issues_public", "is_public"),
    )

    unit_offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    raised_by_representative_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_representatives.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    raised_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Anonymous student on whose behalf the rep is raising the issue
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    anonymous_student_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )

    category: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ISSUE_IDENTIFIED, index=True,
    )
    current_escalation_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LEVEL_NETWORK,
    )
    current_escalation_target_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Public visibility to non-reps
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    public_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UnitIssue offering={self.unit_offering_id} "
            f"status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 8. UNIT ISSUE ESCALATIONS
# ─────────────────────────────────────────────────────────────────────────

class UnitIssueEscalation(Base, UUIDMixin, TimestampMixin):
    """Immutable history of escalation events for an issue."""
    __tablename__ = "unit_issue_escalations"
    __table_args__ = (
        Index("ix_unit_issue_escalations_issue", "issue_id", "escalated_at"),
    )

    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_issues.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    from_level: Mapped[str] = mapped_column(String(16), nullable=False)
    to_level: Mapped[str] = mapped_column(String(16), nullable=False)

    escalated_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    escalated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    response_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    response_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UnitIssueEscalation issue={self.issue_id} "
            f"{self.from_level}->{self.to_level}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 9. UNIT QUESTIONS (AI-assisted educational research)
# ─────────────────────────────────────────────────────────────────────────

class UnitQuestion(Base, UUIDMixin, TimestampMixin):
    """
    Educational questions posed when reps disagree, or when clarification
    is needed. Supervisor + AI assistant research silently; the AI
    responds within 5 minutes of posing.

    Question must be educational in nature. Non-educational questions
    are rejected at the service layer.
    """
    __tablename__ = "unit_questions"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALL_QUESTION_STATUSES)})",
            name="ck_unit_question_status",
        ),
        CheckConstraint(
            f"category IN ({','.join(repr(c) for c in QUESTION_CATEGORIES)})",
            name="ck_unit_question_category",
        ),
        Index("ix_unit_questions_offering", "unit_offering_id"),
        Index("ix_unit_questions_status", "status"),
    )

    unit_offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    raised_by_representative_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("unit_representatives.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    raised_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Raised on behalf of an anonymous student
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    anonymous_student_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )

    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(24), nullable=False, default="educational",
    )

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=QUESTION_POSED, index=True,
    )

    posed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    # posed_at + 5 minutes
    ai_response_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    ai_responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    supervisor_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UnitQuestion offering={self.unit_offering_id} "
            f"status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 10. UNIT QUESTION RESPONSES
# ─────────────────────────────────────────────────────────────────────────

class UnitQuestionResponse(Base, UUIDMixin, TimestampMixin):
    """
    A response to a unit question. From the AI assistant or from the
    supervisor. Supervisor responses may supersede AI responses.
    """
    __tablename__ = "unit_question_responses"
    __table_args__ = (
        CheckConstraint(
            "responder_type IN ('ai','supervisor')",
            name="ck_unit_question_response_type",
        ),
        Index("ix_unit_question_responses_question", "question_id", "created_at"),
    )

    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_questions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    responder_type: Mapped[str] = mapped_column(String(16), nullable=False)
    responder_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    research_sources_json: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
    )
    confidence_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )

    # If a supervisor response overrides an earlier AI response
    superseded_by_response_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("unit_question_responses.id",
                             ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<UnitQuestionResponse question={self.question_id} "
            f"type={self.responder_type}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 11. UNIT SHARED RESOURCES (with AI scan)
# ─────────────────────────────────────────────────────────────────────────

class UnitSharedResource(Base, UUIDMixin, TimestampMixin):
    """
    Resources shared through the network. Every resource is scanned by
    AI to affirm its relevance to the unit before publishing.
    """
    __tablename__ = "unit_shared_resources"
    __table_args__ = (
        CheckConstraint(
            f"resource_type IN ({','.join(repr(t) for t in RESOURCE_TYPES)})",
            name="ck_unit_resource_type",
        ),
        CheckConstraint(
            f"visibility IN ('{RESOURCE_VISIBILITY_NETWORK}', "
            f"'{RESOURCE_VISIBILITY_UNIT}')",
            name="ck_unit_resource_visibility",
        ),
        CheckConstraint(
            f"ai_scan_status IN "
            f"({','.join(repr(s) for s in ALL_SCAN_STATUSES)})",
            name="ck_unit_resource_scan_status",
        ),
        Index("ix_unit_shared_resources_offering", "unit_offering_id"),
        Index("ix_unit_shared_resources_published", "is_published"),
    )

    unit_offering_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shared_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # If the resource originated as a group resource and was cross-posted
    source_group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)

    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    visibility: Mapped[str] = mapped_column(
        String(24), nullable=False, default=RESOURCE_VISIBILITY_NETWORK,
    )

    # AI scan results
    ai_scan_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=SCAN_PENDING, index=True,
    )
    ai_scan_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_scan_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Publication
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<UnitSharedResource offering={self.unit_offering_id} "
            f"status={self.ai_scan_status}>"
        )