"""
Per-user notification preferences.

Security notifications are always sent — they cannot be disabled.
Users can opt in/out of non-essential channels per category.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class NotificationPreference(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        Index("ix_notif_prefs_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )

    # ── Channels ──────────────────────────────────────────
    email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    sms_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    push_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    in_app_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # ── Categories (non-security only; security always sends) ──
    group_activity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    announcements: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    elections: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assessments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    events: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    opportunities: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<NotificationPreference user={self.user_id}>"


# Categories that cannot be disabled (security / account integrity)
MANDATORY_EVENT_PREFIXES = (
    "security.",
    "account.",
    "auth.",
    "session.",
    "password.",
)


def is_mandatory(event_key: str | None) -> bool:
    if not event_key:
        return False
    return any(event_key.startswith(p) for p in MANDATORY_EVENT_PREFIXES)