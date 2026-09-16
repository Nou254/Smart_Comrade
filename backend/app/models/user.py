"""
User model — Module 001: Identity & Authentication.
"""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """
    Core user account table.
    Holds identity + authentication + verification context.
    """
    __tablename__ = "users"

    # --- Identity ---
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    phone: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True
    )

    # --- Authentication ---
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- User Type (self-selected at registration) ---
    # student | lecturer | external
    user_type: Mapped[str] = mapped_column(
        String(20), default="student", nullable=False, index=True
    )
    # For external users: investor | mentor | organization | alumni | specialist
    external_subtype: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # --- Account Status ---
    # pending | pending_approval | active | suspended | deactivated | rejected
    account_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )

    # --- Verification ---
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Institutional Context (for students and lecturers) ---
    institution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    institutional_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    title: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Approval Metadata ---
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- Rejection Metadata (NEW) ---
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # --- Security ---
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Preferred 2FA method: 'totp' | 'email' | 'sms' (NULL if 2FA disabled)
    two_factor_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(
        default=0, nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Known Devices (NEW — for security alerts) ---
    # JSONB list of fingerprint strings like "mobile|Android|Chrome"
    known_devices: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=list,
    )

    # --- Account Lifecycle (NEW) ---
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reactivation_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Terms / Privacy Acceptance (NEW) ---
    tos_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tos_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    privacy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- Tracking ---
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.user_type}:{self.account_status})>"