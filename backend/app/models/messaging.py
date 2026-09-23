"""
Direct messaging + blocking — Communication module.

Design (from the corrected rules):
  - Direct messages are relationship-scoped, not open chat.
  - A conversation requires an accepted ConversationRequest first.
  - Both directions require the OTHER party to accept:
        student → student     : recipient accepts
        student → external    : external accepts
        external → student    : student accepts
  - Students may only be the initiator when contacting externals,
    but externals can send requests that wait for student acceptance.
  - Private profiles still receive requests; only profile fields are hidden.
  - Blocking is enforced across requests and conversations.

Tables:
  1. conversation_requests
  2. direct_conversations
  3. direct_conversation_participants
  4. direct_messages
  5. user_blocks
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


# ── Enumerations ───────────────────────────────────────────────────────
VALID_REQUEST_CONTEXT_TYPES = (
    "student_to_student",
    "student_to_external",
    "external_to_student",
)
VALID_REQUEST_STATUSES = (
    "pending", "accepted", "rejected", "expired", "withdrawn",
)
VALID_CONVERSATION_STATUSES = ("active", "archived", "blocked")


# ============================================================================
# ConversationRequest — the DM proposal
# ============================================================================

class ConversationRequest(Base, UUIDMixin, TimestampMixin):
    """
    A request to open a direct conversation.

    The pair (requester_id, recipient_id) may have at most one pending
    request at a time. Once accepted, a DirectConversation is created
    and the request becomes its origin.
    """
    __tablename__ = "conversation_requests"
    __table_args__ = (
        CheckConstraint(
            f"context_type IN "
            f"({','.join(repr(c) for c in VALID_REQUEST_CONTEXT_TYPES)})",
            name="ck_conversation_request_context",
        ),
        CheckConstraint(
            f"status IN "
            f"({','.join(repr(s) for s in VALID_REQUEST_STATUSES)})",
            name="ck_conversation_request_status",
        ),
        Index("ix_conv_requests_recipient_status",
              "recipient_id", "status"),
        Index("ix_conv_requests_requester_status",
              "requester_id", "status"),
        Index("ix_conv_requests_expires", "expires_at"),
    )

    requester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    recipient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    context_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
    )
    # Optional reference to whatever context triggered the request
    # (e.g., a mentorship id, project id, unit offering id)
    context_ref_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )
    context_ref_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )

    # Short introduction the requester provides
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
    )

    # Set when the request is accepted → points at the resulting conversation
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("direct_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Decision metadata
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )

    # Auto-expiry for unaccepted requests
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )

    conversation: Mapped["DirectConversation | None"] = relationship(
        "DirectConversation",
        foreign_keys=[conversation_id],
        post_update=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationRequest {self.id} "
            f"{self.requester_id}->{self.recipient_id} status={self.status}>"
        )


# ============================================================================
# DirectConversation — the accepted conversation
# ============================================================================

class DirectConversation(Base, UUIDMixin, TimestampMixin):
    """
    An open 1:1 conversation.

    `conversation_key` is the deterministic unordered pair
    `min(id):max(id)` so the same two users cannot have two open
    conversations simultaneously.

    `origin_request_id` links back to the accepted request that
    created this conversation.
    """
    __tablename__ = "direct_conversations"
    __table_args__ = (
        UniqueConstraint("conversation_key", name="uq_direct_conv_key"),
        CheckConstraint(
            f"status IN "
            f"({','.join(repr(s) for s in VALID_CONVERSATION_STATUSES)})",
            name="ck_direct_conv_status",
        ),
        Index("ix_direct_conv_last_message", "last_message_at"),
    )

    conversation_key: Mapped[str] = mapped_column(
        String(80), nullable=False, index=True,
    )

    # The request that opened this conversation, if any (historical)
    origin_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversation_requests.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", index=True,
    )

    # Cached for inbox listing
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_message_preview: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    last_message_sender_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    # Mirrored block state for quick inbox filtering
    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    participants: Mapped[list["DirectConversationParticipant"]] = relationship(
        "DirectConversationParticipant",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["DirectMessage"]] = relationship(
        "DirectMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<DirectConversation {self.id} status={self.status}>"


# ============================================================================
# DirectConversationParticipant — per-user state
# ============================================================================

class DirectConversationParticipant(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "direct_conversation_participants"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "user_id",
            name="uq_direct_conv_participant",
        ),
        Index("ix_direct_conv_participant_user", "user_id"),
    )

    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("direct_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    is_muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    conversation: Mapped[DirectConversation] = relationship(
        "DirectConversation", back_populates="participants",
    )

    def __repr__(self) -> str:
        return (
            f"<DirectConversationParticipant conv={self.conversation_id} "
            f"user={self.user_id}>"
        )


# ============================================================================
# DirectMessage
# ============================================================================

class DirectMessage(Base, UUIDMixin, TimestampMixin):
    """
    A single message inside an open conversation.
    Deletion is soft so moderation/legal review can still access the body.
    """
    __tablename__ = "direct_messages"
    __table_args__ = (
        Index(
            "ix_direct_messages_conv_created",
            "conversation_id", "created_at",
        ),
        Index("ix_direct_messages_sender", "sender_id"),
        Index("ix_direct_messages_deleted", "is_deleted"),
    )

    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("direct_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    reply_to_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("direct_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
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

    is_reported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    conversation: Mapped[DirectConversation] = relationship(
        "DirectConversation", back_populates="messages",
    )

    def __repr__(self) -> str:
        return f"<DirectMessage {self.id} conv={self.conversation_id}>"


# ============================================================================
# UserBlock
# ============================================================================

class UserBlock(Base, UUIDMixin, TimestampMixin):
    """
    Directional block from blocker_id against blocked_id.

    Does not suppress:
      - Emergency notifications
      - Election notices (eligibility-bound)
      - Assessment reminders for enrolled assessments
      - Official institutional announcements from authoritative publishers
    """
    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_user_block"),
        Index("ix_user_blocks_blocker", "blocker_id"),
        Index("ix_user_blocks_blocked", "blocked_id"),
    )

    blocker_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    blocked_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<UserBlock {self.blocker_id} -> {self.blocked_id}>"