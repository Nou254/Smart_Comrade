"""
Group join request model — Module 003 security layer.

Every path into a group (invite token, slug link, direct search) creates
a row in this table. The group leader or secretary approves or rejects.
No membership ever becomes active without an approved request — with the
sole exception of the founding leader (who is auto-active at group
creation).

Lifecycle:
    pending → approved  → membership becomes active
    pending → rejected  → membership stays pending (or is cleaned up)
    pending → withdrawn → the visitor cancelled their own request
    pending → expired   → the request sat unactioned past its TTL
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class GroupJoinRequest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_join_requests"
    __table_args__ = (
        # One pending request per user per group.
        UniqueConstraint(
            "group_id", "user_id", "status",
            name="uq_group_join_request_pending",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','withdrawn','expired')",
            name="ck_join_request_status",
        ),
        CheckConstraint(
            "source IN ('invite_token','slug_link','direct_search','admin_added')",
            name="ck_join_request_source",
        ),
        Index("ix_group_join_requests_group_status", "group_id", "status"),
        Index("ix_group_join_requests_user", "user_id"),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False)

    # Free-text message from the visitor explaining why they want to join.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Course + unit confirmations (captured at submit time) ---
    # The visitor confirms "yes I'm on this course/semester" and checks off
    # the units they're taking from the group's curated list.
    course_confirmed: Mapped[bool] = mapped_column(
        nullable=False, default=False,
    )
    # Snapshot of the unit confirmations — stored as JSON text so this
    # record survives even if the group's curated list later changes.
    unit_confirmations_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # --- Review metadata ---
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- TTL ---
    # Requests expire automatically after this deadline so a leader's queue
    # doesn't fill with stale entries.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    # --- Source tracking ---
    # IP + user agent of the visitor at submit time — supports abuse
    # investigations without retaining anything more invasive.
    request_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_user_agent: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )

    group: Mapped["Group"] = relationship(
        "Group", back_populates="join_requests",
        foreign_keys=[group_id],
    )

    def __repr__(self) -> str:
        return (
            f"<GroupJoinRequest group={self.group_id} "
            f"user={self.user_id} status={self.status}>"
        )