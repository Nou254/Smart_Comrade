"""
Dedicated audit log for administrative actions.
Records what admin did what to whom, with old/new values.
"""
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AdminActionLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "admin_action_logs"
    __table_args__ = (
        Index("ix_admin_action_actor", "actor_id"),
        Index("ix_admin_action_target", "target_type", "target_id"),
        Index("ix_admin_action_created", "created_at"),
    )

    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # e.g. user.suspend, user.approve, role.assign, config.update, invitation.create

    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    jurisdiction_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    jurisdiction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<AdminAction {self.action} by={self.actor_id} target={self.target_type}:{self.target_id}>"