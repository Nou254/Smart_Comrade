"""
Discussion forums — Communication module.

Rules (from the corrected spec):
  - Anyone can create a forum.
  - Institution-scoped forums require Institution Admin approval.
  - A forum must be created ≥3 days before its start date.
  - The creator is the moderator.
  - Join clicks are recorded; the creator sees the participant list.
  - Joining makes the user a participant of that forum.

Tables:
  1. forums
  2. forum_approval_requests
  3. forum_joins
  4. forum_topics
  5. forum_replies
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


VALID_SCOPE_TYPES = (
    "public", "group", "unit", "school", "institution", "county",
)
VALID_VISIBILITIES = ("public", "restricted")
VALID_FORUM_STATUSES = (
    "draft", "pending_approval", "active", "cancelled", "archived",
)
VALID_APPROVAL_STATUSES = ("pending", "approved", "rejected", "withdrawn")


# ============================================================================
# Forum
# ============================================================================

class Forum(Base, UUIDMixin, TimestampMixin):
    """
    A discussion forum.

    `starts_at` is the forum's start/due date. Creation is only allowed
    ≥3 days before this date (enforced by the service layer).

    `moderator_id` is the forum creator by default. Kept as a separate
    field so moderation can later be transferred if needed.
    """
    __tablename__ = "forums"
    __table_args__ = (
        CheckConstraint(
            f"scope_type IN "
            f"({','.join(repr(s) for s in VALID_SCOPE_TYPES)})",
            name="ck_forum_scope_type",
        ),
        CheckConstraint(
            f"visibility IN "
            f"({','.join(repr(v) for v in VALID_VISIBILITIES)})",
            name="ck_forum_visibility",
        ),
        CheckConstraint(
            f"status IN "
            f"({','.join(repr(s) for s in VALID_FORUM_STATUSES)})",
            name="ck_forum_status",
        ),
        UniqueConstraint("slug", name="uq_forum_slug"),
        Index("ix_forums_scope", "scope_type", "scope_ref_id"),
        Index("ix_forums_active", "is_active"),
        Index("ix_forums_starts", "starts_at"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    scope_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
    )
    scope_ref_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="public",
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="general", index=True,
    )

    # Forum scheduling
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Online (Google Meet) or physical
    google_meet_link: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Creator / moderator
    creator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False,
    )
    moderator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=False,
        index=True,
    )

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", index=True,
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    # Cached counters
    participant_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    topic_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    approval_request: Mapped["ForumApprovalRequest | None"] = relationship(
        "ForumApprovalRequest",
        back_populates="forum",
        uselist=False,
        cascade="all, delete-orphan",
    )
    joins: Mapped[list["ForumJoin"]] = relationship(
        "ForumJoin",
        back_populates="forum",
        cascade="all, delete-orphan",
    )
    topics: Mapped[list["ForumTopic"]] = relationship(
        "ForumTopic",
        back_populates="forum",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Forum {self.slug} scope={self.scope_type} status={self.status}>"


# ============================================================================
# ForumApprovalRequest
# ============================================================================

class ForumApprovalRequest(Base, UUIDMixin, TimestampMixin):
    """
    Institution Admin approval record for institution-scoped forums.
    One per forum.
    """
    __tablename__ = "forum_approval_requests"
    __table_args__ = (
        UniqueConstraint("forum_id", name="uq_forum_approval_request_forum"),
        CheckConstraint(
            f"status IN "
            f"({','.join(repr(s) for s in VALID_APPROVAL_STATUSES)})",
            name="ck_forum_approval_status",
        ),
        Index("ix_forum_approval_status", "status"),
        Index("ix_forum_approval_reviewer", "reviewer_id"),
    )

    forum_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("forums.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    requester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False, index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # Filled when an Institution Admin decides
    reviewer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
    )

    forum: Mapped[Forum] = relationship("Forum", back_populates="approval_request")

    def __repr__(self) -> str:
        return (
            f"<ForumApprovalRequest forum={self.forum_id} status={self.status}>"
        )


# ============================================================================
# ForumJoin
# ============================================================================

class ForumJoin(Base, UUIDMixin, TimestampMixin):
    """
    Recorded every time a user clicks join on a forum.
    The list of these rows is what the creator sees as the participant list.
    """
    __tablename__ = "forum_joins"
    __table_args__ = (
        UniqueConstraint("forum_id", "user_id", name="uq_forum_join"),
        Index("ix_forum_joins_forum", "forum_id"),
        Index("ix_forum_joins_user", "user_id"),
    )

    forum_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("forums.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # Track when/if they later leave
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    forum: Mapped[Forum] = relationship("Forum", back_populates="joins")

    def __repr__(self) -> str:
        return f"<ForumJoin forum={self.forum_id} user={self.user_id}>"


# ============================================================================
# ForumTopic
# ============================================================================

class ForumTopic(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "forum_topics"
    __table_args__ = (
        Index("ix_forum_topics_forum_created", "forum_id", "created_at"),
        Index("ix_forum_topics_author", "author_id"),
        Index("ix_forum_topics_pinned", "is_pinned"),
        Index("ix_forum_topics_deleted", "is_deleted"),
    )

    forum_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("forums.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    delete_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reply_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    last_reply_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    forum: Mapped[Forum] = relationship("Forum", back_populates="topics")
    replies: Mapped[list["ForumReply"]] = relationship(
        "ForumReply", back_populates="topic", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ForumTopic {self.id} forum={self.forum_id}>"


# ============================================================================
# ForumReply
# ============================================================================

class ForumReply(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "forum_replies"
    __table_args__ = (
        Index("ix_forum_replies_topic_created", "topic_id", "created_at"),
        Index("ix_forum_replies_author", "author_id"),
        Index("ix_forum_replies_parent", "parent_id"),
        Index("ix_forum_replies_deleted", "is_deleted"),
    )

    topic_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("forum_topics.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("forum_replies.id", ondelete="SET NULL"),
        nullable=True,
    )

    body: Mapped[str] = mapped_column(Text, nullable=False)

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    delete_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    topic: Mapped[ForumTopic] = relationship(
        "ForumTopic", back_populates="replies",
    )

    def __repr__(self) -> str:
        return f"<ForumReply {self.id} topic={self.topic_id}>"