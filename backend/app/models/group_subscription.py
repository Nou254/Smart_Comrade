"""
Group subscription model — Module 003 Phase 5.

Every group has at most one active subscription at a time. Historical
rows are preserved when a subscription expires, is cancelled, or is
superseded by a renewal.

State machine:
  trial     → 14-day free period from group creation
  active    → paid subscription currently in effect
  expiring  → active but expires within 10 days (blocks elections)
  expired   → period_end passed with no renewal
  suspended → administratively suspended
  cancelled → user-triggered cancellation

Amount calculation (V1 pricing):
  ≤30 members  → KSh 100 flat
  31-50        → KSh 100 + (members × KSh 20)
  51-60        → capped at KSh 600 total (per current rules)
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class GroupSubscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('trial','active','expiring','expired','suspended','cancelled')",
            name="ck_group_subscription_state",
        ),
        Index("ix_group_subscriptions_group_status", "group_id", "status"),
        Index("ix_group_subscriptions_period_end", "period_end"),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="trial", index=True,
    )
    is_trial: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=True,
    )

    # Snapshot at time of payment — used to compute the next renewal amount
    # and for audit / dispute resolution.
    member_count_at_payment: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    amount_paid: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0,
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

    # --- Payment provider reference (nullable for trial) ---
    payment_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Metadata ---
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<GroupSubscription group={self.group_id} "
            f"status={self.status} ends={self.period_end.date()}>"
        )