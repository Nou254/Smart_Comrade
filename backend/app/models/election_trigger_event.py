"""
Election trigger event — Module 003 Phase 7.

Logs every automatic cascade trigger: when a group hit its threshold
and caused a school election to be scheduled, when a school rep was
elected and caused an institution election, etc.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ElectionTriggerEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "election_trigger_events"
    __table_args__ = (
        CheckConstraint(
            "level IN ('group','school','institution','county')",
            name="ck_trigger_event_level",
        ),
        CheckConstraint(
            "status IN ('triggered','queued','blocked_by_parent','completed')",
            name="ck_trigger_event_status",
        ),
        Index("ix_election_trigger_level", "level"),
        Index("ix_election_trigger_constituency", "level", "constituency_id"),
    )

    level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    constituency_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="triggered", index=True,
    )

    # If the trigger resulted in an election, this points at it
    election_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # If blocked by a parent election, which one
    blocked_by_election_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("elections.id", ondelete="SET NULL"),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ElectionTriggerEvent {self.level}:{self.constituency_id} "
            f"[{self.status}]>"
        )