"""
Inter-group transfer model — Module 003 Phase 8.

Admin-initiated, same-course only. Fee tiers: KSh 20 ordinary, KSh 90 elected.
Elected members' seats become vacant when they transfer.
Blocked during election period.
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class GroupTransfer(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_transfers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','completed','cancelled')",
            name="ck_group_transfer_status",
        ),
        CheckConstraint(
            "transfer_type IN ('ordinary','elected')",
            name="ck_group_transfer_type",
        ),
        Index("ix_group_transfers_student", "student_id"),
        Index("ix_group_transfers_source", "source_group_id"),
        Index("ix_group_transfers_target", "target_group_id"),
        Index("ix_group_transfers_status", "status"),
    )

    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    target_group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    initiated_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False, index=True,
    )
    initiated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    request_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    transfer_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ordinary",
    )
    fee_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="KES",
    )
    fee_paid: Mapped[bool] = mapped_column(
        nullable=False, default=False,
    )
    payment_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    fee_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    seat_vacated: Mapped[bool] = mapped_column(
        nullable=False, default=False,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<GroupTransfer student={self.student_id} "
            f"{self.source_group_id}→{self.target_group_id} [{self.status}]>"
        )