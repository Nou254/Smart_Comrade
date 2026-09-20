"""module 003 phase 3+4+5 — group formation, invite links, subscriptions

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-20

Creates:
  - group_subscriptions
  - group_units
  - group_unit_confirmations
  - group_join_requests

Alters:
  - groups             : + slug, group_type, combination_id, year_level,
                          is_provisional, invite_token, invite_expires_at,
                          election_triggered_at
  - group_memberships  : + joined_via_invite, course_confirmed_at,
                          units_confirmed_at
  - groups.status      : extend check to include 'pending_election'
  - groups.subscription_status : extend check to include 'expiring'
  - group_memberships.status   : extend check to include 'provisional_pending'

Backfill:
  - Existing groups get a generated slug.
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _extend_groups_table()
    _extend_group_memberships_table()
    _create_group_subscriptions_table()
    _create_group_units_table()
    _create_group_unit_confirmations_table()
    _create_group_join_requests_table()


# ─── groups ───────────────────────────────────────────────────────────────

def _extend_groups_table() -> None:
    # Drop the old status / subscription_status check constraints so we can
    # widen them.
    op.drop_constraint("ck_group_status", "groups", type_="check")
    op.drop_constraint("ck_group_subscription_status", "groups", type_="check")

    # Add the new columns. Slug is added nullable first, backfilled, then
    # set NOT NULL.
    op.add_column(
        "groups",
        sa.Column("slug", sa.String(80), nullable=True),
    )
    op.add_column(
        "groups",
        sa.Column(
            "group_type", sa.String(20),
            nullable=False, server_default="academic",
        ),
    )
    op.add_column(
        "groups",
        sa.Column("combination_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "groups",
        sa.Column("year_level", sa.Integer(), nullable=True),
    )
    op.add_column(
        "groups",
        sa.Column(
            "is_provisional", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
    )
    op.add_column(
        "groups",
        sa.Column("invite_token", sa.String(128), nullable=True),
    )
    op.add_column(
        "groups",
        sa.Column("invite_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "groups",
        sa.Column("election_triggered_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Foreign key for combination_id
    op.create_foreign_key(
        "fk_groups_combination_id",
        "groups", "combinations",
        ["combination_id"], ["id"],
        ondelete="SET NULL",
    )

    # Indexes
    op.create_index("ix_groups_slug", "groups", ["slug"], unique=True)
    op.create_index("ix_groups_group_type", "groups", ["group_type"])
    op.create_index("ix_groups_combination_id", "groups", ["combination_id"])
    op.create_index("ix_groups_invite_token", "groups", ["invite_token"])
    op.create_index("ix_groups_member_count", "groups", ["member_count"])
    op.create_unique_constraint("uq_group_slug", "groups", ["slug"])
    op.create_unique_constraint("uq_group_invite_token", "groups", ["invite_token"])

    # Widen status enums
    op.create_check_constraint(
        "ck_group_status", "groups",
        "status IN ('forming','pending_election','active','suspended','archived')",
    )
    op.create_check_constraint(
        "ck_group_subscription_status", "groups",
        "subscription_status IN ('trial','active','expiring','expired','suspended','cancelled')",
    )
    op.create_check_constraint(
        "ck_group_type", "groups",
        "group_type IN ('academic','activity_club')",
    )

    # Backfill slugs for any existing rows
    _backfill_group_slugs()

    # Now enforce NOT NULL on slug
    op.alter_column("groups", "slug", nullable=False)


def _backfill_group_slugs() -> None:
    """
    Give every existing group a unique, non-guessable slug.
    Runs on the raw connection since we don't want to import models in
    the migration.
    """
    import secrets
    import re

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name FROM groups")).fetchall()

    alphabet = "23456789abcdefghjkmnpqrstuvwxyz"

    def _slugify(name: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return cleaned or "group"

    def _suffix() -> str:
        return "".join(secrets.choice(alphabet) for _ in range(8))

    for row in rows:
        group_id, name = row[0], row[1]
        base = _slugify(name)[:70]
        # Retry on collision (extremely unlikely)
        for _ in range(5):
            candidate = f"{base}-{_suffix()}"
            exists = bind.execute(
                sa.text("SELECT 1 FROM groups WHERE slug = :s"),
                {"s": candidate},
            ).first()
            if not exists:
                break
        bind.execute(
            sa.text("UPDATE groups SET slug = :s WHERE id = :id"),
            {"s": candidate, "id": group_id},
        )


# ─── group_memberships ────────────────────────────────────────────────────

def _extend_group_memberships_table() -> None:
    op.drop_constraint("ck_membership_status", "group_memberships", type_="check")

    op.add_column(
        "group_memberships",
        sa.Column(
            "joined_via_invite", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.add_column(
        "group_memberships",
        sa.Column("course_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "group_memberships",
        sa.Column("units_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "ck_membership_status", "group_memberships",
        "status IN ('provisional_pending','pending','active','suspended','left','removed')",
    )

    # Drop the server default so future inserts go through the model layer.
    op.alter_column(
        "group_memberships", "joined_via_invite",
        server_default=None,
    )


# ─── group_subscriptions ──────────────────────────────────────────────────

def _create_group_subscriptions_table() -> None:
    op.create_table(
        "group_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="trial",
        ),
        sa.Column(
            "is_trial", sa.Integer(),
            nullable=False, server_default="1",
        ),
        sa.Column(
            "member_count_at_payment", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "amount_paid", sa.BigInteger(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "currency", sa.String(8),
            nullable=False, server_default="KES",
        ),
        sa.Column(
            "period_start", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "period_end", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column("payment_reference", sa.String(128), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('trial','active','expiring','expired','suspended','cancelled')",
            name="ck_group_subscription_state",
        ),
    )
    op.create_index(
        "ix_group_subscriptions_group_id",
        "group_subscriptions", ["group_id"],
    )
    op.create_index(
        "ix_group_subscriptions_status",
        "group_subscriptions", ["status"],
    )
    op.create_index(
        "ix_group_subscriptions_group_status",
        "group_subscriptions", ["group_id", "status"],
    )
    op.create_index(
        "ix_group_subscriptions_period_end",
        "group_subscriptions", ["period_end"],
    )
    op.create_index(
        "ix_group_subscriptions_payment_reference",
        "group_subscriptions", ["payment_reference"],
    )


# ─── group_units ──────────────────────────────────────────────────────────

def _create_group_units_table() -> None:
    op.create_table(
        "group_units",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("year_level", sa.Integer(), nullable=True),
        sa.Column("semester_number", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.String(36), nullable=True),
        sa.Column("source", sa.String(24), nullable=False, server_default="ocr_extraction"),
        sa.Column("source_extracted_unit_id", sa.String(36), nullable=True),
        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("group_id", "code", name="uq_group_unit_code"),
        sa.CheckConstraint(
            "source IN ('ocr_extraction','manual','canonical_match')",
            name="ck_group_unit_source",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["units.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_extracted_unit_id"], ["extracted_units.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_group_units_group_id", "group_units", ["group_id"])
    op.create_index("ix_group_units_unit_id", "group_units", ["unit_id"])


# ─── group_unit_confirmations ─────────────────────────────────────────────

def _create_group_unit_confirmations_table() -> None:
    op.create_table(
        "group_unit_confirmations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_unit_id", sa.String(36),
            sa.ForeignKey("group_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "confirmed", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "flagged_as_incorrect", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "group_unit_id", "user_id",
            name="uq_group_unit_confirmation",
        ),
    )
    op.create_index(
        "ix_group_unit_confirmations_group_unit",
        "group_unit_confirmations", ["group_unit_id"],
    )
    op.create_index(
        "ix_group_unit_confirmations_user",
        "group_unit_confirmations", ["user_id"],
    )


# ─── group_join_requests ──────────────────────────────────────────────────

def _create_group_join_requests_table() -> None:
    op.create_table(
        "group_join_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "course_confirmed", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("unit_confirmations_json", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(64), nullable=True),
        sa.Column("request_user_agent", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "group_id", "user_id", "status",
            name="uq_group_join_request_pending",
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','withdrawn','expired')",
            name="ck_join_request_status",
        ),
        sa.CheckConstraint(
            "source IN ('invite_token','slug_link','direct_search','admin_added')",
            name="ck_join_request_source",
        ),
    )
    op.create_index(
        "ix_group_join_requests_group_id",
        "group_join_requests", ["group_id"],
    )
    op.create_index(
        "ix_group_join_requests_user_id",
        "group_join_requests", ["user_id"],
    )
    op.create_index(
        "ix_group_join_requests_status",
        "group_join_requests", ["status"],
    )
    op.create_index(
        "ix_group_join_requests_group_status",
        "group_join_requests", ["group_id", "status"],
    )
    op.create_index(
        "ix_group_join_requests_expires_at",
        "group_join_requests", ["expires_at"],
    )


# ============================================================================
# DOWNGRADE
# ============================================================================

def downgrade() -> None:
    # Drop new tables
    op.drop_index("ix_group_join_requests_expires_at", table_name="group_join_requests")
    op.drop_index("ix_group_join_requests_group_status", table_name="group_join_requests")
    op.drop_index("ix_group_join_requests_status", table_name="group_join_requests")
    op.drop_index("ix_group_join_requests_user_id", table_name="group_join_requests")
    op.drop_index("ix_group_join_requests_group_id", table_name="group_join_requests")
    op.drop_table("group_join_requests")

    op.drop_index("ix_group_unit_confirmations_user", table_name="group_unit_confirmations")
    op.drop_index("ix_group_unit_confirmations_group_unit", table_name="group_unit_confirmations")
    op.drop_table("group_unit_confirmations")

    op.drop_index("ix_group_units_unit_id", table_name="group_units")
    op.drop_index("ix_group_units_group_id", table_name="group_units")
    op.drop_table("group_units")

    op.drop_index("ix_group_subscriptions_payment_reference", table_name="group_subscriptions")
    op.drop_index("ix_group_subscriptions_period_end", table_name="group_subscriptions")
    op.drop_index("ix_group_subscriptions_group_status", table_name="group_subscriptions")
    op.drop_index("ix_group_subscriptions_status", table_name="group_subscriptions")
    op.drop_index("ix_group_subscriptions_group_id", table_name="group_subscriptions")
    op.drop_table("group_subscriptions")

    # Revert membership columns
    op.drop_constraint("ck_membership_status", "group_memberships", type_="check")
    op.create_check_constraint(
        "ck_membership_status", "group_memberships",
        "status IN ('pending','active','suspended','left','removed')",
    )
    op.drop_column("group_memberships", "units_confirmed_at")
    op.drop_column("group_memberships", "course_confirmed_at")
    op.drop_column("group_memberships", "joined_via_invite")

    # Revert group columns
    op.drop_constraint("ck_group_type", "groups", type_="check")
    op.drop_constraint("ck_group_status", "groups", type_="check")
    op.drop_constraint("ck_group_subscription_status", "groups", type_="check")

    op.create_check_constraint(
        "ck_group_status", "groups",
        "status IN ('forming','active','suspended','archived')",
    )
    op.create_check_constraint(
        "ck_group_subscription_status", "groups",
        "subscription_status IN ('trial','active','expired','cancelled')",
    )

    op.drop_constraint("uq_group_invite_token", "groups", type_="unique")
    op.drop_constraint("uq_group_slug", "groups", type_="unique")
    op.drop_constraint("fk_groups_combination_id", "groups", type_="foreignkey")

    op.drop_index("ix_groups_member_count", table_name="groups")
    op.drop_index("ix_groups_invite_token", table_name="groups")
    op.drop_index("ix_groups_combination_id", table_name="groups")
    op.drop_index("ix_groups_group_type", table_name="groups")
    op.drop_index("ix_groups_slug", table_name="groups")

    op.drop_column("groups", "election_triggered_at")
    op.drop_column("groups", "invite_expires_at")
    op.drop_column("groups", "invite_token")
    op.drop_column("groups", "is_provisional")
    op.drop_column("groups", "year_level")
    op.drop_column("groups", "combination_id")
    op.drop_column("groups", "group_type")
    op.drop_column("groups", "slug")