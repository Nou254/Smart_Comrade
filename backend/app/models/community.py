"""
Communication community models — Module 003 Phase 11.

Three community types, auto-membership from enrollment:
  - course_year: institution + course + year + combination + academic_year
  - school:      institution + school
  - institution: institution

Strictly text-only. No media, no voice, no attachments. Max 2000 chars.
Rate limits enforced at the service layer.
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


# ============================================================================
# COMMUNITY
# ============================================================================

class Community(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "communities"
    __table_args__ = (
        CheckConstraint(
            "community_type IN ('course_year','school','institution')",
            name="ck_community_type",
        ),
        
        UniqueConstraint(
            "community_type", "institution_id", "school_id", "course_id",
            "year_level", "combination_id", "academic_year_id",
            name="uq_community_scope",
        ),
        Index("ix_communities_type", "community_type"),
        Index("ix_communities_institution", "institution_id"),
        Index("ix_communities_school", "school_id"),
    )

    community_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
    )

    # Scope identifiers — nullable depending on type
    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    school_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    course_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=True,
    )
    year_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    combination_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combinations.id", ondelete="SET NULL"),
        nullable=True,
    )
    academic_year_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cached display
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Settings
    max_message_length: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2000,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Membership count cache
    member_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, index=True,
    )

    memberships: Mapped[list["CommunityMembership"]] = relationship(
        "CommunityMembership", back_populates="community",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["CommunityMessage"]] = relationship(
        "CommunityMessage", back_populates="community",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Community {self.community_type}:{self.name}>"


# ============================================================================
# MEMBERSHIP
# ============================================================================

class CommunityMembership(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "community_memberships"
    __table_args__ = (
        UniqueConstraint(
            "community_id", "user_id",
            name="uq_community_membership",
        ),
        CheckConstraint(
            "role IN ('member','moderator')",
            name="ck_community_member_role",
        ),
        Index("ix_community_memberships_user", "user_id"),
    )

    community_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("communities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Moderation state
    muted_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    banned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    banned_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    ban_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    community: Mapped[Community] = relationship(
        "Community", back_populates="memberships",
    )

    def __repr__(self) -> str:
        return (
            f"<CommunityMembership community={self.community_id} "
            f"user={self.user_id} role={self.role}>"
        )


# ============================================================================
# MESSAGE
# ============================================================================

class CommunityMessage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "community_messages"
    __table_args__ = (
        Index("ix_community_messages_community_created", "community_id", "created_at"),
        Index("ix_community_messages_sender", "sender_id"),
        Index("ix_community_messages_deleted", "is_deleted"),
    )

    community_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("communities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    reply_to_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("community_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    delete_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    hidden_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    community: Mapped[Community] = relationship(
        "Community", back_populates="messages",
    )

    def __repr__(self) -> str:
        return f"<CommunityMessage community={self.community_id} sender={self.sender_id}>"


# ============================================================================
# REPORT
# ============================================================================

class CommunityMessageReport(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "community_message_reports"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "reporter_id",
            name="uq_community_message_report",
        ),
        CheckConstraint(
            "reason IN ("
            "'spam','harassment','hate_speech','misinformation',"
            "'off_topic','academic_integrity','other'"
            ")",
            name="ck_community_report_reason",
        ),
        CheckConstraint(
            "status IN ('pending','reviewing','resolved','dismissed')",
            name="ck_community_report_status",
        ),
        Index("ix_community_reports_message", "message_id"),
    )

    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("community_messages.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reporter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CommunityMessageReport message={self.message_id} reason={self.reason}>"


# ============================================================================
# MODERATION ACTION (audit)
# ============================================================================

class CommunityModerationAction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "community_moderation_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ("
            "'delete_message','hide_message','mute_member',"
            "'unmute_member','ban_member','unban_member','pin_message'"
            ")",
            name="ck_community_action_type",
        ),
        Index("ix_community_mod_actions_community", "community_id"),
        Index("ix_community_mod_actions_target", "target_user_id"),
    )

    community_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("communities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    moderator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    target_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    target_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("community_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    until_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return f"<CommunityModerationAction {self.action_type} community={self.community_id}>"