"""
Invitation records for admin provisioning (Super Admin → Regional Admin, etc.).
"""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AdminInvitation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "admin_invitations"

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    jurisdiction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    jurisdiction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )

    invited_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<AdminInvitation {self.email} role={self.role_code}>"