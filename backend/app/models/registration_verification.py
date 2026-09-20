"""
Registration number verification models — Module 002 completion.

Institutions periodically verify that their enrolled students exist in
the real world, by checking each student's registration number against
an official roster.

From the canonical spec:
  - A Super Admin initiates a verification period for an institution.
  - The Institution Rep executes primary verification.
  - The County Rep collaborates on manual verification.
  - A registration number is only valid when paired with the correct
    email address. The pair is the unit of verification.
  - Unverified students have their access restricted entirely until
    they re-verify.

Two tables:
  - institution_verification_periods : one row per period per institution.
  - institution_registration_numbers : the roster, one row per pair.

The student side is captured by User.registration_number (added to
`app/models/user.py`).
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


class InstitutionVerificationPeriod(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "institution_verification_periods"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','active','extended','completed','expired')",
            name="ck_verification_period_status",
        ),
        Index("ix_verification_periods_institution", "institution_id"),
        Index("ix_verification_periods_status", "status"),
    )

    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    initiated_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False, index=True,
    )

    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    # Extension is granted by the Super Admin after a request from the
    # Institution Rep. `extended_until` is only meaningful when set.
    extended_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    extension_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="scheduled", index=True,
    )

    verified_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    unverified_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    registration_numbers: Mapped[list["InstitutionRegistrationNumber"]] = (
        relationship(
            "InstitutionRegistrationNumber",
            back_populates="period",
            cascade="all, delete-orphan",
        )
    )

    def __repr__(self) -> str:
        return (
            f"<InstitutionVerificationPeriod {self.id} "
            f"institution={self.institution_id} status={self.status}>"
        )


class InstitutionRegistrationNumber(Base, UUIDMixin, TimestampMixin):
    """
    A single roster entry: a (reg_number, email) pair belonging to an
    institution. This is the "known number" pool.

    A pair becomes verified when a matching registered user is found.
    A pair with no user match is retained so that a future student
    registering with that pair auto-verifies.
    """
    __tablename__ = "institution_registration_numbers"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "reg_number",
            name="uq_institution_reg_number",
        ),
        CheckConstraint(
            "source IN ('roster_upload','manual_entry','student_submission')",
            name="ck_institution_reg_number_source",
        ),
        Index("ix_institution_reg_numbers_email", "email"),
        Index("ix_institution_reg_numbers_user", "user_id"),
    )

    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Nullable: a roster entry may be added between periods for future use.
    period_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("institution_verification_periods.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    reg_number: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Set once this roster entry is matched to a registered user.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    source: Mapped[str] = mapped_column(String(24), nullable=False)
    added_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # Set when the pair has been matched to a registered student.
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    verified_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    period: Mapped[InstitutionVerificationPeriod | None] = relationship(
        "InstitutionVerificationPeriod", back_populates="registration_numbers",
    )

    def __repr__(self) -> str:
        return (
            f"<InstitutionRegistrationNumber {self.reg_number} "
            f"institution={self.institution_id} verified={self.verified_at is not None}>"
        )