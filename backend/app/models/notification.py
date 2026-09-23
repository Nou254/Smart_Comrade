"""
Persistent notifications — Communication module.

One row per user per delivery. Fan-out at write time.

Emergency is a priority flag rather than a separate table; the service
layer enforces that only authorized publishers can set
priority='critical' with category='emergency'.

Tables:
  1. notifications
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


VALID_CATEGORIES = (
    "academic", "assessment", "election", "impeachment",
    "event", "administrative", "opportunity", "project",
    "announcement", "emergency", "system", "security",
)
VALID_PRIORITIES = ("normal", "important", "critical")
VALID_STATUSES = ("pending", "delivered", "read", "dismissed", "expired")


class Notification(Base, UUIDMixin, TimestampMixin):
    """
    source_type / source_id are loose references to the entity that
    triggered the notification (assessment, election, conversation,
    announcement, etc.). Strings rather than FKs so the notification
    store does not need a foreign key into every other module.
    """
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({','.join(repr(c) for c in VALID_CATEGORIES)})",
            name="ck_notification_category",
        ),
        CheckConstraint(
            f"priority IN ({','.join(repr(p) for p in VALID_PRIORITIES)})",
            name="ck_notification_priority",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in VALID_STATUSES)})",
            name="ck_notification_status",
        ),
        Index("ix_notifications_user_status", "user_id", "status"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_source", "source_type", "source_id"),
        Index("ix_notifications_priority", "priority"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    category: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    source_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True,
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )

    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
    )
    is_system_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    requires_acknowledgment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Notification {self.id} user={self.user_id} "
            f"category={self.category} status={self.status}>"
        )