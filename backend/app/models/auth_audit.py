"""
Auth audit log — immutable record of authentication and security events.
"""
from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AuthAuditLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "auth_audit_logs"
    __table_args__ = (
        Index("ix_auth_audit_event_type", "event_type"),
        Index("ix_auth_audit_user_id_created", "user_id", "created_at"),
    )

    # Nullable because failed logins may not resolve to a user
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # login_success | login_failed | login_locked | logout |
    # register_* | email_verified | phone_verified |
    # password_reset_requested | password_reset_succeeded | password_changed |
    # 2fa_enabled | 2fa_disabled | 2fa_success | 2fa_failed |
    # session_revoked | account_approved | account_rejected

    event_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<AuthAudit {self.event_type} user={self.user_id} ok={self.success}>"