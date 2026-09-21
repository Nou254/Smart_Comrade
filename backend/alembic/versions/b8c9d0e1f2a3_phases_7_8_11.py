"""module 003 phases 7+8+11 — cascade triggers, transfers, communities

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-21

Creates:
  - communities
  - community_memberships
  - community_messages
  - community_message_reports
  - community_moderation_actions
  - group_transfers
  - election_trigger_events

Alters:
  - schools      : + compliant_group_count, election_triggered_at
  - institutions : + represented_school_count, election_triggered_at, buffer_ends_at
  - counties     : + represented_institution_count, election_triggered_at

Seeds:
  - 4 new permissions: community.moderate, community.admin,
    group_transfer.manage, cascade.trigger
  - grants to appropriate roles
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    ("community.moderate", "Moderate a Community", "community"),
    ("community.admin", "Administer Communities", "community"),
    ("group_transfer.manage", "Manage Group Transfers", "group_transfer"),
    ("cascade.trigger", "Manually Trigger Cascade Elections", "cascade"),
]


GRANTS: dict[str, list[str]] = {
    "community.moderate": [
        "super_admin", "regional_admin",
        "county_representative", "institution_representative",
        "assistant_institution_rep", "school_representative",
        "assistant_school_rep", "group_leader",
    ],
    "community.admin": [
        "super_admin",
    ],
    "group_transfer.manage": [
        "super_admin", "regional_admin",
        "county_representative", "institution_representative",
    ],
    "cascade.trigger": [
        "super_admin", "regional_admin",
    ],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _extend_academic_tables()
    _create_communities_table()
    _create_community_memberships_table()
    _create_community_messages_table()
    _create_community_message_reports_table()
    _create_community_moderation_actions_table()
    _create_group_transfers_table()
    _create_election_trigger_events_table()
    _seed_permissions_and_grants()


# ─── 1. Extend academic tables ───────────────────────────────────────────

def _extend_academic_tables() -> None:
    # schools
    op.add_column(
        "schools",
        sa.Column("compliant_group_count", sa.Integer(),
                  nullable=False, server_default="0"),
    )
    op.add_column(
        "schools",
        sa.Column("election_triggered_at",
                  sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_schools_compliant_group_count", "schools", ["compliant_group_count"],
    )
    op.alter_column("schools", "compliant_group_count", server_default=None)

    # institutions
    op.add_column(
        "institutions",
        sa.Column("represented_school_count", sa.Integer(),
                  nullable=False, server_default="0"),
    )
    op.add_column(
        "institutions",
        sa.Column("election_triggered_at",
                  sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("buffer_ends_at",
                  sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_institutions_represented_school_count",
        "institutions", ["represented_school_count"],
    )
    op.alter_column("institutions", "represented_school_count", server_default=None)

    # counties
    op.add_column(
        "counties",
        sa.Column("represented_institution_count", sa.Integer(),
                  nullable=False, server_default="0"),
    )
    op.add_column(
        "counties",
        sa.Column("election_triggered_at",
                  sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_counties_represented_institution_count",
        "counties", ["represented_institution_count"],
    )
    op.alter_column("counties", "represented_institution_count", server_default=None)


# ─── 2. communities ──────────────────────────────────────────────────────

def _create_communities_table() -> None:
    op.create_table(
        "communities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("community_type", sa.String(20), nullable=False),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_id", sa.String(36),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "course_id", sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("year_level", sa.Integer(), nullable=True),
        sa.Column(
            "combination_id", sa.String(36),
            sa.ForeignKey("combinations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "academic_year_id", sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("max_message_length", sa.Integer(),
                  nullable=False, server_default="2000"),
        sa.Column("is_active", sa.Boolean(),
                  nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("member_count", sa.Integer(),
                  nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "community_type IN ('course_year','school','institution')",
            name="ck_community_type",
        ),
        sa.UniqueConstraint(
            "community_type", "institution_id", "school_id",
            "course_id", "year_level", "combination_id", "academic_year_id",
            name="uq_community_scope",
        ),
    )
    op.create_index("ix_communities_type", "communities", ["community_type"])
    op.create_index("ix_communities_institution", "communities", ["institution_id"])
    op.create_index("ix_communities_school", "communities", ["school_id"])
    op.create_index("ix_communities_is_active", "communities", ["is_active"])
    op.create_index("ix_communities_member_count", "communities", ["member_count"])


# ─── 3. community_memberships ────────────────────────────────────────────

def _create_community_memberships_table() -> None:
    op.create_table(
        "community_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "community_id", sa.String(36),
            sa.ForeignKey("communities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean(),
                  nullable=False, server_default=sa.true()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "banned_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ban_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "community_id", "user_id",
            name="uq_community_membership",
        ),
        sa.CheckConstraint(
            "role IN ('member','moderator')",
            name="ck_community_member_role",
        ),
    )
    op.create_index(
        "ix_community_memberships_user", "community_memberships", ["user_id"],
    )
    op.create_index(
        "ix_community_memberships_community", "community_memberships", ["community_id"],
    )
    op.create_index(
        "ix_community_memberships_is_active", "community_memberships", ["is_active"],
    )


# ─── 4. community_messages ───────────────────────────────────────────────

def _create_community_messages_table() -> None:
    op.create_table(
        "community_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "community_id", sa.String(36),
            sa.ForeignKey("communities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "reply_to_id", sa.String(36),
            sa.ForeignKey("community_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_deleted", sa.Boolean(),
                  nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("delete_reason", sa.String(255), nullable=True),
        sa.Column("is_hidden", sa.Boolean(),
                  nullable=False, server_default=sa.false()),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_community_messages_community_created",
        "community_messages", ["community_id", "created_at"],
    )
    op.create_index("ix_community_messages_sender", "community_messages", ["sender_id"])
    op.create_index("ix_community_messages_deleted", "community_messages", ["is_deleted"])
    op.create_index("ix_community_messages_hidden", "community_messages", ["is_hidden"])


# ─── 5. community_message_reports ────────────────────────────────────────

def _create_community_message_reports_table() -> None:
    op.create_table(
        "community_message_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "message_id", sa.String(36),
            sa.ForeignKey("community_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16),
                  nullable=False, server_default="pending"),
        sa.Column(
            "reviewed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "message_id", "reporter_id",
            name="uq_community_message_report",
        ),
        sa.CheckConstraint(
            "reason IN ('spam','harassment','hate_speech','misinformation',"
            "'off_topic','academic_integrity','other')",
            name="ck_community_report_reason",
        ),
        sa.CheckConstraint(
            "status IN ('pending','reviewing','resolved','dismissed')",
            name="ck_community_report_status",
        ),
    )
    op.create_index(
        "ix_community_reports_message", "community_message_reports", ["message_id"],
    )
    op.create_index(
        "ix_community_reports_reporter", "community_message_reports", ["reporter_id"],
    )
    op.create_index(
        "ix_community_reports_status", "community_message_reports", ["status"],
    )


# ─── 6. community_moderation_actions ─────────────────────────────────────

def _create_community_moderation_actions_table() -> None:
    op.create_table(
        "community_moderation_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "community_id", sa.String(36),
            sa.ForeignKey("communities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "moderator_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "target_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_message_id", sa.String(36),
            sa.ForeignKey("community_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("until_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "action_type IN ('delete_message','hide_message','mute_member',"
            "'unmute_member','ban_member','unban_member','pin_message')",
            name="ck_community_action_type",
        ),
    )
    op.create_index(
        "ix_community_mod_actions_community",
        "community_moderation_actions", ["community_id"],
    )
    op.create_index(
        "ix_community_mod_actions_target",
        "community_moderation_actions", ["target_user_id"],
    )


# ─── 7. group_transfers ──────────────────────────────────────────────────

def _create_group_transfers_table() -> None:
    op.create_table(
        "group_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "student_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "initiated_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_notes", sa.Text(), nullable=True),
        sa.Column("transfer_type", sa.String(16),
                  nullable=False, server_default="ordinary"),
        sa.Column("fee_amount", sa.Integer(),
                  nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8),
                  nullable=False, server_default="KES"),
        sa.Column("fee_paid", sa.Boolean(),
                  nullable=False, server_default=sa.false()),
        sa.Column("payment_reference", sa.String(128), nullable=True),
        sa.Column("fee_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seat_vacated", sa.Boolean(),
                  nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(16),
                  nullable=False, server_default="pending"),
        sa.Column(
            "reviewed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','completed','cancelled')",
            name="ck_group_transfer_status",
        ),
        sa.CheckConstraint(
            "transfer_type IN ('ordinary','elected')",
            name="ck_group_transfer_type",
        ),
    )
    op.create_index("ix_group_transfers_student", "group_transfers", ["student_id"])
    op.create_index("ix_group_transfers_source", "group_transfers", ["source_group_id"])
    op.create_index("ix_group_transfers_target", "group_transfers", ["target_group_id"])
    op.create_index("ix_group_transfers_status", "group_transfers", ["status"])
    op.create_index("ix_group_transfers_initiator", "group_transfers", ["initiated_by"])


# ─── 8. election_trigger_events ──────────────────────────────────────────

def _create_election_trigger_events_table() -> None:
    op.create_table(
        "election_trigger_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("constituency_id", sa.String(36), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24),
                  nullable=False, server_default="triggered"),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "blocked_by_election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "level IN ('group','school','institution','county')",
            name="ck_trigger_event_level",
        ),
        sa.CheckConstraint(
            "status IN ('triggered','queued','blocked_by_parent','completed')",
            name="ck_trigger_event_status",
        ),
    )
    op.create_index("ix_election_trigger_level", "election_trigger_events", ["level"])
    op.create_index(
        "ix_election_trigger_constituency",
        "election_trigger_events", ["level", "constituency_id"],
    )
    op.create_index(
        "ix_election_trigger_status", "election_trigger_events", ["status"],
    )
    op.create_index(
        "ix_election_trigger_election_id",
        "election_trigger_events", ["election_id"],
    )


# ─── 9. permissions + grants ─────────────────────────────────────────────

def _seed_permissions_and_grants() -> None:
    bind = op.get_bind()

    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
    )
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("id", sa.String),
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )

    existing_codes: set[str] = {
        row[0]
        for row in bind.execute(sa.text("SELECT code FROM permissions")).fetchall()
    }
    to_insert = [
        {"id": str(uuid4()), "code": code, "name": name, "category": cat}
        for (code, name, cat) in NEW_PERMISSIONS
        if code not in existing_codes
    ]
    if to_insert:
        bind.execute(permissions_table.insert(), to_insert)

    code_to_id: dict[str, str] = {
        row[0]: row[1]
        for row in bind.execute(sa.text("SELECT code, id FROM permissions")).fetchall()
    }
    role_code_to_id: dict[str, str] = {
        row[0]: row[1]
        for row in bind.execute(sa.text("SELECT code, id FROM roles")).fetchall()
    }
    existing_pairs: set[tuple[str, str]] = {
        (row[0], row[1])
        for row in bind.execute(
            sa.text("SELECT role_id, permission_id FROM role_permissions")
        ).fetchall()
    }

    to_grant: list[dict] = []
    for perm_code, role_codes in GRANTS.items():
        perm_id = code_to_id.get(perm_code)
        if not perm_id:
            continue
        for role_code in role_codes:
            role_id = role_code_to_id.get(role_code)
            if not role_id:
                continue
            if (role_id, perm_id) in existing_pairs:
                continue
            to_grant.append({
                "id": str(uuid4()),
                "role_id": role_id,
                "permission_id": perm_id,
            })
    if to_grant:
        bind.execute(role_permissions_table.insert(), to_grant)


# ============================================================================
# DOWNGRADE
# ============================================================================

def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for (code, _n, _c) in NEW_PERMISSIONS]
    if codes:
        placeholders = ",".join(f"'{c}'" for c in codes)
        bind.execute(sa.text(
            f"DELETE FROM role_permissions WHERE permission_id IN "
            f"(SELECT id FROM permissions WHERE code IN ({placeholders}))"
        ))
        bind.execute(sa.text(
            f"DELETE FROM permissions WHERE code IN ({placeholders})"
        ))

    op.drop_index(
        "ix_election_trigger_election_id", table_name="election_trigger_events",
    )
    op.drop_index("ix_election_trigger_status", table_name="election_trigger_events")
    op.drop_index(
        "ix_election_trigger_constituency", table_name="election_trigger_events",
    )
    op.drop_index("ix_election_trigger_level", table_name="election_trigger_events")
    op.drop_table("election_trigger_events")

    op.drop_index("ix_group_transfers_initiator", table_name="group_transfers")
    op.drop_index("ix_group_transfers_status", table_name="group_transfers")
    op.drop_index("ix_group_transfers_target", table_name="group_transfers")
    op.drop_index("ix_group_transfers_source", table_name="group_transfers")
    op.drop_index("ix_group_transfers_student", table_name="group_transfers")
    op.drop_table("group_transfers")

    op.drop_index(
        "ix_community_mod_actions_target",
        table_name="community_moderation_actions",
    )
    op.drop_index(
        "ix_community_mod_actions_community",
        table_name="community_moderation_actions",
    )
    op.drop_table("community_moderation_actions")

    op.drop_index("ix_community_reports_status", table_name="community_message_reports")
    op.drop_index("ix_community_reports_reporter", table_name="community_message_reports")
    op.drop_index("ix_community_reports_message", table_name="community_message_reports")
    op.drop_table("community_message_reports")

    op.drop_index("ix_community_messages_hidden", table_name="community_messages")
    op.drop_index("ix_community_messages_deleted", table_name="community_messages")
    op.drop_index("ix_community_messages_sender", table_name="community_messages")
    op.drop_index(
        "ix_community_messages_community_created", table_name="community_messages",
    )
    op.drop_table("community_messages")

    op.drop_index(
        "ix_community_memberships_is_active", table_name="community_memberships",
    )
    op.drop_index(
        "ix_community_memberships_community", table_name="community_memberships",
    )
    op.drop_index(
        "ix_community_memberships_user", table_name="community_memberships",
    )
    op.drop_table("community_memberships")

    op.drop_index("ix_communities_member_count", table_name="communities")
    op.drop_index("ix_communities_is_active", table_name="communities")
    op.drop_index("ix_communities_school", table_name="communities")
    op.drop_index("ix_communities_institution", table_name="communities")
    op.drop_index("ix_communities_type", table_name="communities")
    op.drop_table("communities")

    # Revert academic-table columns
    op.drop_index(
        "ix_counties_represented_institution_count", table_name="counties",
    )
    op.drop_column("counties", "election_triggered_at")
    op.drop_column("counties", "represented_institution_count")

    op.drop_index(
        "ix_institutions_represented_school_count", table_name="institutions",
    )
    op.drop_column("institutions", "buffer_ends_at")
    op.drop_column("institutions", "election_triggered_at")
    op.drop_column("institutions", "represented_school_count")

    op.drop_index(
        "ix_schools_compliant_group_count", table_name="schools",
    )
    op.drop_column("schools", "election_triggered_at")
    op.drop_column("schools", "compliant_group_count")