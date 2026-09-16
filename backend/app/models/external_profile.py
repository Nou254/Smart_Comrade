"""
Extended profile for external user types.

One row per external user (investor, organization, alumni, mentor, specialist).
The base `users` table holds identity + auth. This table holds the
role-specific fields for each external subtype.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ExternalProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "external_profiles"
    __table_args__ = (
        Index("ix_external_profiles_user_id", "user_id"),
        Index("ix_external_profiles_subtype", "external_subtype"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )

    # One of: investor | organization | alumni | mentor | specialist
    external_subtype: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )

    # ── Investor fields ──────────────────────────────────────
    investment_focus: Mapped[str | None] = mapped_column(Text, nullable=True)
    investor_org_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    investor_role: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # ── Organization fields ──────────────────────────────────
    organization_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
    )
    organization_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True,   # Company | NGO | Government | Institution
    )
    industry: Mapped[str | None] = mapped_column(
        String(64), nullable=True,   # Technology | Education | Healthcare | ...
    )
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ── Alumni fields ────────────────────────────────────────
    former_institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    graduation_year: Mapped[int | None] = mapped_column(nullable=True)
    current_profession: Mapped[str | None] = mapped_column(String(160), nullable=True)
    alumni_expertise: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Mentor fields ────────────────────────────────────────
    mentor_profession: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mentor_expertise: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentor_experience_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    mentor_availability: Mapped[str | None] = mapped_column(
        String(64), nullable=True,   # Weekdays | Weekends | Evenings | Flexible
    )

    # ── Specialist fields ────────────────────────────────────
    expertise_field: Mapped[str | None] = mapped_column(String(160), nullable=True)
    affiliation: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Verification ─────────────────────────────────────────
    # approved | pending | rejected
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
    )
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", backref="external_profile")

    def __repr__(self) -> str:
        return f"<ExternalProfile user={self.user_id} type={self.external_subtype}>"