"""
Unit proposal model — Module 002 completion.

A UnitProposal is the routing wrapper for a batch of units that were
created outside of the group timetable-OCR flow. This is the "direct
creation" path described in the canonical spec:

  - A School Rep (or higher) creates units for a specific course,
    year level, and semester.
  - The proposal routes upward for approval.
  - The escalation ladder is:
        School Rep -> Institution Rep -> Regional Admin -> Super Admin
    (County Representative is skipped and receives only reports.)
  - Every two hours without a response, the proposal escalates one level.
  - Assistants at each level are notified in parallel.
  - The approver may modify individual items before approving.

Group founders curating their own group's units do NOT use this flow —
they have direct privilege to set the group's unit list.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class UnitProposal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_proposals"
    __table_args__ = (
        CheckConstraint(
            "proposal_type IN ('ocr_extraction','manual_creation')",
            name="ck_unit_proposal_type",
        ),
        CheckConstraint(
            "status IN ("
            "'pending_school_rep','pending_institution_rep',"
            "'pending_regional_admin','pending_super_admin',"
            "'approved','rejected','withdrawn'"
            ")",
            name="ck_unit_proposal_status",
        ),
        Index("ix_unit_proposals_status", "status"),
        Index("ix_unit_proposals_course_semester", "course_id", "semester_id"),
        Index("ix_unit_proposals_escalation", "escalation_deadline"),
        Index("ix_unit_proposals_current_approver", "current_approver_id"),
    )

    # ---- Academic context ----
    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    school_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    academic_year_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
    )
    semester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("semesters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    year_level: Mapped[int] = mapped_column(Integer, nullable=False)

    # ---- Origin ----
    # 'ocr_extraction' — sourced from a timetable upload (nullable FK).
    # 'manual_creation' — submitted directly by an authorised actor.
    proposal_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_upload_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("timetable_uploads.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- Lifecycle ----
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_school_rep", index=True,
    )

    # Who is expected to respond right now.
    current_approver_role: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )
    current_approver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Timing for the two-hour escalation windows.
    current_stage_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    escalation_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    # ---- Outcome ----
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    rejected_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["UnitProposalItem"]] = relationship(
        "UnitProposalItem", back_populates="proposal",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["UnitProposalEvent"]] = relationship(
        "UnitProposalEvent", back_populates="proposal",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<UnitProposal {self.id} course={self.course_id} "
            f"status={self.status}>"
        )


class UnitProposalItem(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_proposal_items"
    __table_args__ = (
        CheckConstraint(
            "action IN ('create','update','match','skip')",
            name="ck_unit_proposal_item_action",
        ),
        CheckConstraint(
            "item_status IN ('pending','approved','rejected','modified')",
            name="ck_unit_proposal_item_status",
        ),
        Index("ix_unit_proposal_items_proposal", "proposal_id"),
    )

    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Existing unit this item corresponds to (if matched).
    existing_unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Proposed values from the creator.
    proposed_code: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_name: Mapped[str] = mapped_column(String(200), nullable=False)
    proposed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # OCR metadata (nullable for manual creation).
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Classification + state.
    action: Mapped[str] = mapped_column(
        String(16), nullable=False, default="create",
    )
    item_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending",
    )

    # Approver modifications — kept separate from proposed values so the
    # original submission remains visible for audit.
    modified_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    modified_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    modified_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result after approval.
    resulting_unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    proposal: Mapped[UnitProposal] = relationship(
        "UnitProposal", back_populates="items",
    )

    def effective_code(self) -> str:
        return self.modified_code or self.proposed_code

    def effective_name(self) -> str:
        return self.modified_name or self.proposed_name

    def __repr__(self) -> str:
        return (
            f"<UnitProposalItem {self.proposed_code} "
            f"action={self.action} status={self.item_status}>"
        )


class UnitProposalEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "unit_proposal_events"
    __table_args__ = (
        Index("ix_unit_proposal_events_proposal", "proposal_id"),
    )

    proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("unit_proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    # created | approved | rejected | escalated | modified | withdrawn
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)

    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    from_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    proposal: Mapped[UnitProposal] = relationship(
        "UnitProposal", back_populates="events",
    )

    def __repr__(self) -> str:
        return f"<UnitProposalEvent {self.event_type}>"