"""Communication module — add username + profile_visibility; create 14 new tables.

Revision ID: comms001
Revises: b4c5d6e7f8a9
Create Date: 2026-09-23

Adds:
  - users.username            (String(64), unique, nullable until assigned)
  - users.profile_visibility  (String(16), default 'private')

Creates 14 tables:
  1.  direct_conversations
  2.  conversation_requests
  3.  direct_conversation_participants
  4.  direct_messages
  5.  user_blocks
  6.  official_announcements
  7.  official_announcement_audiences
  8.  notifications
  9.  shared_files
  10. forums
  11. forum_approval_requests
  12. forum_joins
  13. forum_topics
  14. forum_replies
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "comms001"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ========================================================================
    # 1. users — add username + profile_visibility
    # ========================================================================
    op.add_column(
        "users",
        sa.Column("username", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_users_username", "users", ["username"], unique=True,
    )
    op.add_column(
        "users",
        sa.Column(
            "profile_visibility",
            sa.String(length=16),
            nullable=False,
            server_default="private",
        ),
    )
    op.create_index(
        "ix_users_profile_visibility", "users", ["profile_visibility"],
    )

    # ========================================================================
    # 2. direct_conversations
    # NOTE: origin_request_id FK is added AFTER conversation_requests exists,
    #       because the two tables have a mutual reference.
    # ========================================================================
    op.create_table(
        "direct_conversations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_key", sa.String(length=80),
                  nullable=False, index=True),
        # origin_request_id stored as a plain String for now.
        # The FK constraint is added below via create_foreign_key.
        sa.Column("origin_request_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="active", index=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.String(length=255), nullable=True),
        sa.Column(
            "last_message_sender_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_blocked", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active','archived','blocked')",
            name="ck_direct_conv_status",
        ),
        sa.UniqueConstraint("conversation_key", name="uq_direct_conv_key"),
    )
    op.create_index(
        "ix_direct_conv_last_message", "direct_conversations",
        ["last_message_at"],
    )

    # ========================================================================
    # 3. conversation_requests — safe to reference direct_conversations now
    # ========================================================================
    op.create_table(
        "conversation_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "requester_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "recipient_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("context_type", sa.String(length=32), nullable=False, index=True),
        sa.Column("context_ref_type", sa.String(length=32), nullable=True),
        sa.Column("context_ref_id", sa.String(length=36), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="pending", index=True),
        sa.Column(
            "conversation_id", sa.String(length=36),
            sa.ForeignKey("direct_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "context_type IN ('student_to_student','student_to_external',"
            "'external_to_student')",
            name="ck_conversation_request_context",
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected','expired','withdrawn')",
            name="ck_conversation_request_status",
        ),
    )
    op.create_index(
        "ix_conv_requests_recipient_status",
        "conversation_requests", ["recipient_id", "status"],
    )
    op.create_index(
        "ix_conv_requests_requester_status",
        "conversation_requests", ["requester_id", "status"],
    )

    # Now complete the mutual FK
    op.create_foreign_key(
        "fk_direct_conversations_origin_request_id",
        "direct_conversations",
        "conversation_requests",
        ["origin_request_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ========================================================================
    # 4. direct_conversation_participants
    # ========================================================================
    op.create_table(
        "direct_conversation_participants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(length=36),
            sa.ForeignKey("direct_conversations.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "user_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_muted", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("is_archived", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint(
            "conversation_id", "user_id",
            name="uq_direct_conv_participant",
        ),
    )
    op.create_index(
        "ix_direct_conv_participant_user",
        "direct_conversation_participants", ["user_id"],
    )

    # ========================================================================
    # 5. direct_messages
    # ========================================================================
    op.create_table(
        "direct_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(length=36),
            sa.ForeignKey("direct_conversations.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "sender_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "reply_to_id", sa.String(length=36),
            sa.ForeignKey("direct_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_edited", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("delete_reason", sa.String(length=255), nullable=True),
        sa.Column("is_reported", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index(
        "ix_direct_messages_conv_created",
        "direct_messages", ["conversation_id", "created_at"],
    )
    op.create_index("ix_direct_messages_sender", "direct_messages", ["sender_id"])
    op.create_index("ix_direct_messages_deleted", "direct_messages", ["is_deleted"])

    # ========================================================================
    # 6. user_blocks
    # ========================================================================
    op.create_table(
        "user_blocks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "blocker_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "blocked_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_block"),
    )

    # ========================================================================
    # 7. official_announcements
    # ========================================================================
    op.create_table(
        "official_announcements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "publisher_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False, index=True,
        ),
        sa.Column("publisher_role", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, index=True),
        sa.Column("scope_ref_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("classification", sa.String(length=24), nullable=False, index=True),
        sa.Column("priority", sa.String(length=16), nullable=False,
                  server_default="normal", index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column(
            "correction_of_id", sa.String(length=36),
            sa.ForeignKey("official_announcements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="published", index=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True,
                  index=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audience_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "level IN ('group','unit','school','institution','county','platform')",
            name="ck_official_announcement_level",
        ),
        sa.CheckConstraint(
            "classification IN ('academic','administrative','election',"
            "'assessment','event','emergency','opportunity','project','general')",
            name="ck_official_announcement_classification",
        ),
        sa.CheckConstraint(
            "priority IN ('normal','important','critical')",
            name="ck_official_announcement_priority",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','published','archived')",
            name="ck_official_announcement_status",
        ),
        sa.CheckConstraint(
            "(level = 'platform' AND scope_ref_id IS NULL) OR "
            "(level != 'platform' AND scope_ref_id IS NOT NULL)",
            name="ck_official_announcement_scope",
        ),
    )
    op.create_index(
        "ix_official_announcement_level_scope",
        "official_announcements", ["level", "scope_ref_id"],
    )

    # ========================================================================
    # 8. official_announcement_audiences
    # ========================================================================
    op.create_table(
        "official_announcement_audiences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "announcement_id", sa.String(length=36),
            sa.ForeignKey("official_announcements.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "user_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_still_eligible", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint(
            "announcement_id", "user_id",
            name="uq_official_announcement_audience",
        ),
    )

    # ========================================================================
    # 9. notifications
    # ========================================================================
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("category", sa.String(length=24), nullable=False, index=True),
        sa.Column("priority", sa.String(length=16), nullable=False,
                  server_default="normal", index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=True, index=True),
        sa.Column("source_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("link_url", sa.String(length=500), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="pending", index=True),
        sa.Column("is_system_generated", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("requires_acknowledgment", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True,
                  index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('academic','assessment','election','impeachment',"
            "'event','administrative','opportunity','project','announcement',"
            "'emergency','system','security')",
            name="ck_notification_category",
        ),
        sa.CheckConstraint(
            "priority IN ('normal','important','critical')",
            name="ck_notification_priority",
        ),
        sa.CheckConstraint(
            "status IN ('pending','delivered','read','dismissed','expired')",
            name="ck_notification_status",
        ),
    )
    op.create_index(
        "ix_notifications_user_status", "notifications",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_notifications_user_created", "notifications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_notifications_source", "notifications",
        ["source_type", "source_id"],
    )

    # ========================================================================
    # 10. shared_files
    # ========================================================================
    op.create_table(
        "shared_files",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "owner_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False, index=True,
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False, index=True),
        sa.Column("scope_ref_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_url", sa.String(length=500), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "parent_file_id", sa.String(length=36),
            sa.ForeignKey("shared_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("malware_scan_status", sa.String(length=16), nullable=False,
                  server_default="pending", index=True),
        sa.Column("malware_scan_notes", sa.Text(), nullable=True),
        sa.Column("malware_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "scope_type IN ('direct','unit','community')",
            name="ck_shared_file_scope_type",
        ),
        sa.CheckConstraint(
            "malware_scan_status IN ('pending','scanning','clean',"
            "'infected','failed','skipped')",
            name="ck_shared_file_scan_status",
        ),
    )
    op.create_index(
        "ix_shared_files_scope", "shared_files",
        ["scope_type", "scope_ref_id"],
    )
    op.create_index("ix_shared_files_owner", "shared_files", ["owner_id"])
    op.create_index("ix_shared_files_parent", "shared_files", ["parent_file_id"])
    op.create_index("ix_shared_files_scan", "shared_files",
                    ["malware_scan_status"])

    # ========================================================================
    # 11. forums
    # ========================================================================
    op.create_table(
        "forums",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, index=True),
        sa.Column("slug", sa.String(length=80), nullable=False, index=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.String(length=16), nullable=False, index=True),
        sa.Column("scope_ref_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("visibility", sa.String(length=16), nullable=False,
                  server_default="public"),
        sa.Column("category", sa.String(length=32), nullable=False,
                  server_default="general", index=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False,
                  index=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("google_meet_link", sa.String(length=500), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column(
            "creator_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "moderator_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False, index=True,
        ),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="active", index=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true(), index=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("participant_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("topic_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "scope_type IN ('public','group','unit','school','institution','county')",
            name="ck_forum_scope_type",
        ),
        sa.CheckConstraint(
            "visibility IN ('public','restricted')",
            name="ck_forum_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('draft','pending_approval','active','cancelled','archived')",
            name="ck_forum_status",
        ),
        sa.UniqueConstraint("slug", name="uq_forum_slug"),
    )
    op.create_index("ix_forums_scope", "forums", ["scope_type", "scope_ref_id"])

    # ========================================================================
    # 12. forum_approval_requests
    # ========================================================================
    op.create_table(
        "forum_approval_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "forum_id", sa.String(length=36),
            sa.ForeignKey("forums.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "requester_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False, index=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reviewer_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="pending", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','withdrawn')",
            name="ck_forum_approval_status",
        ),
        sa.UniqueConstraint("forum_id", name="uq_forum_approval_request_forum"),
    )

    # ========================================================================
    # 13. forum_joins
    # ========================================================================
    op.create_table(
        "forum_joins",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "forum_id", sa.String(length=36),
            sa.ForeignKey("forums.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "user_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("forum_id", "user_id", name="uq_forum_join"),
    )

    # ========================================================================
    # 14. forum_topics
    # ========================================================================
    op.create_table(
        "forum_topics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "forum_id", sa.String(length=36),
            sa.ForeignKey("forums.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "author_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("is_locked", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("delete_reason", sa.String(length=255), nullable=True),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True,
                  index=True),
        sa.Column(
            "last_reply_by_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index(
        "ix_forum_topics_forum_created", "forum_topics",
        ["forum_id", "created_at"],
    )

    # ========================================================================
    # 15. forum_replies
    # ========================================================================
    op.create_table(
        "forum_replies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "topic_id", sa.String(length=36),
            sa.ForeignKey("forum_topics.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "author_id", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "parent_id", sa.String(length=36),
            sa.ForeignKey("forum_replies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False,
                  server_default=sa.false(), index=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by", sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("delete_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index(
        "ix_forum_replies_topic_created", "forum_replies",
        ["topic_id", "created_at"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_index("ix_forum_replies_topic_created", table_name="forum_replies")
    op.drop_table("forum_replies")

    op.drop_index("ix_forum_topics_forum_created", table_name="forum_topics")
    op.drop_table("forum_topics")

    op.drop_table("forum_joins")
    op.drop_table("forum_approval_requests")
    op.drop_index("ix_forums_scope", table_name="forums")
    op.drop_table("forums")

    op.drop_index("ix_shared_files_scan", table_name="shared_files")
    op.drop_index("ix_shared_files_parent", table_name="shared_files")
    op.drop_index("ix_shared_files_owner", table_name="shared_files")
    op.drop_index("ix_shared_files_scope", table_name="shared_files")
    op.drop_table("shared_files")

    op.drop_index("ix_notifications_source", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index("ix_notifications_user_status", table_name="notifications")
    op.drop_table("notifications")

    op.drop_table("official_announcement_audiences")
    op.drop_index(
        "ix_official_announcement_level_scope",
        table_name="official_announcements",
    )
    op.drop_table("official_announcements")

    op.drop_table("user_blocks")

    op.drop_index("ix_direct_messages_deleted", table_name="direct_messages")
    op.drop_index("ix_direct_messages_sender", table_name="direct_messages")
    op.drop_index("ix_direct_messages_conv_created", table_name="direct_messages")
    op.drop_table("direct_messages")

    op.drop_index(
        "ix_direct_conv_participant_user",
        table_name="direct_conversation_participants",
    )
    op.drop_table("direct_conversation_participants")

    # Drop the mutual FK before dropping either table
    op.drop_constraint(
        "fk_direct_conversations_origin_request_id",
        "direct_conversations",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_conv_requests_requester_status",
        table_name="conversation_requests",
    )
    op.drop_index(
        "ix_conv_requests_recipient_status",
        table_name="conversation_requests",
    )
    op.drop_table("conversation_requests")

    op.drop_index("ix_direct_conv_last_message", table_name="direct_conversations")
    op.drop_table("direct_conversations")

    op.drop_index("ix_users_profile_visibility", table_name="users")
    op.drop_column("users", "profile_visibility")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "username")