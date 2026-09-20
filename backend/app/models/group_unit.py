"""
Group unit models — Module 003 Phase 4.

When a founder creates a group, they upload a timetable, the OCR pipeline
extracts candidate units, and the founder curates that list. The curated
list becomes the group's authoritative unit list — separate from the
canonical `units` table (which is populated by the Module 002 approval
flow).

Two tables:
  - group_units              : the curated list (one row per unit)
  - group_unit_confirmations : per-member confirmation of each unit
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class GroupUnit(Base, UUIDMixin, TimestampMixin):
    """
    One row per unit in the group's curated list.

    A GroupUnit may optionally reference a canonical Unit (if the founder
    matched one during curation). When no match exists, `unit_id` stays
    null and `code` + `name` carry the founder's data.
    """
    __tablename__ = "group_units"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "code",
            name="uq_group_unit_code",
        ),
        CheckConstraint(
            "source IN ('ocr_extraction','manual','canonical_match')",
            name="ck_group_unit_source",
        ),
        Index("ix_group_units_group_id", "group_id"),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # --- The unit's identity as the group sees it ---
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    year_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Link to the canonical unit, if the founder matched one ---
    unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # --- Provenance ---
    # 'ocr_extraction'     — curated from OCR output, matched or not
    # 'manual'             — founder typed it in
    # 'canonical_match'    — auto-matched to a canonical unit during curation
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="ocr_extraction",
    )
    source_extracted_unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("extracted_units.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )

    # --- Relationships ---
    confirmations: Mapped[list["GroupUnitConfirmation"]] = relationship(
        "GroupUnitConfirmation", back_populates="group_unit",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<GroupUnit {self.code} group={self.group_id}>"


class GroupUnitConfirmation(Base, UUIDMixin, TimestampMixin):
    """
    One row per (group_unit, user) pair — the member's confirmation that
    this unit is one they are taking this semester.

    Used at join time: the joiner reviews the founder's curated list and
    checks each one off. Confirmed units define the joiner's participation
    in that group's unit-level activities.
    """
    __tablename__ = "group_unit_confirmations"
    __table_args__ = (
        UniqueConstraint(
            "group_unit_id", "user_id",
            name="uq_group_unit_confirmation",
        ),
        Index("ix_group_unit_confirmations_user", "user_id"),
    )

    group_unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_units.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    # If the joiner says "no, I'm not taking this", they can flag it for
    # the founder's attention.
    flagged_as_incorrect: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    group_unit: Mapped[GroupUnit] = relationship(
        "GroupUnit", back_populates="confirmations",
    )

    def __repr__(self) -> str:
        return (
            f"<GroupUnitConfirmation unit={self.group_unit_id} "
            f"user={self.user_id} confirmed={self.confirmed}>"
        )