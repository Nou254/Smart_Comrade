"""
Solo learner models — Module 003 (Solo Path).

A solo learner is a registered student with full academic context who
does not belong to any academic group. Monthly subscription: KSh 70.

Solo learners can:
  - see course/school/institution communities
  - discover other solo learners
  - schedule 1-on-1 learning sessions
  - join or create a group at any time (subscription transitions)

Leaving a group returns the student to solo status after paying the
KSh 70 solo rate (14-day grace period).
"""
from datetime import datetime

from sqlalchemy import (
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


SOLO_MONTHLY_FEE = 70


class SoloSubscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "solo_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','expiring','expired','cancelled','suspended')",
            name="ck_solo_subscription_status",
        ),
        Index("ix_solo_subscriptions_user", "user_id"),
        Index("ix_solo_subscriptions_status", "status"),
        Index("ix_solo_subscriptions_period_end", "period_end"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True,
    )
    amount_paid: Mapped[int] = mapped_column(
        Integer, nullable=False, default=SOLO_MONTHLY_FEE,
    )
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="KES",
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    payment_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<SoloSubscription user={self.user_id} "
            f"status={self.status} ends={self.period_end.date()}>"
        )


class SoloLearningSession(Base, UUIDMixin, TimestampMixin):
    """
    A 1-on-1 learning session between two solo learners.
    """
    __tablename__ = "solo_learning_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','accepted','declined','cancelled','completed')",
            name="ck_solo_session_status",
        ),
        Index("ix_solo_sessions_initiator", "initiator_id"),
        Index("ix_solo_sessions_partner", "partner_id"),
        Index("ix_solo_sessions_scheduled", "scheduled_at"),
    )

    initiator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    partner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="proposed", index=True,
    )

    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    declined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    declined_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<SoloLearningSession {self.initiator_id}→{self.partner_id} "
            f"status={self.status}>"
        )