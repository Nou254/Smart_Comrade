"""
Lecturer affiliation model.

A lecturer may hold multiple concurrent affiliations, one per institution.
Each affiliation carries its own institutional email (optional), department,
title, and referee for verification.

The first affiliation is captured at registration and mirrored into the
legacy single-valued fields on `users` (institution_id, institutional_email,
department, title) for backward compatibility. Additional affiliations are
stored here only.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class LecturerAffiliation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "lecturer_affiliations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "institution_id",
            name="uq_lecturer_aff_user_institution",
        ),
        Index("ix_lecturer_aff_user_id", "user_id"),
        Index("ix_lecturer_aff_institution_id", "institution_id"),
        Index("ix_lecturer_aff_status", "verification_status"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # --- Academic context ---
    institutional_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    title: Mapped[str] = mapped_column(String(50), nullable=False)

    # --- Referee (per-affiliation) ---
    # Referee is per-affiliation because a department head at one institution
    # is not the same person as at another. Admin calls both phones during
    # verification.
    referee_name: Mapped[str] = mapped_column(String(160), nullable=False)
    referee_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    referee_relationship: Mapped[str] = mapped_column(String(120), nullable=False)

    # --- Verification ---
    # pending   : awaiting admin phone-call verification
    # verified  : admin confirmed via referee call
    # rejected  : admin rejected the affiliation
    # ended     : lecturer left this institution (historical record)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    domain_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Lifecycle ---
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Relations ---
    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], backref="lecturer_affiliations",
    )

    def __repr__(self) -> str:
        return (
            f"<LecturerAffiliation user={self.user_id} "
            f"institution={self.institution_id} status={self.verification_status}>"
        )