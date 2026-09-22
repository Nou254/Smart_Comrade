"""module 003 — solo learner: solo_subscriptions, solo_learning_sessions

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa


revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "solo_subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("amount_paid", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_reference", sa.String(128), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "status IN ('active','expiring','expired','cancelled','suspended')",
            name="ck_solo_subscription_status",
        ),
    )
    op.create_index("ix_solo_subscriptions_user", "solo_subscriptions", ["user_id"])
    op.create_index("ix_solo_subscriptions_status", "solo_subscriptions", ["status"])
    op.create_index("ix_solo_subscriptions_period_end", "solo_subscriptions", ["period_end"])

    op.create_table(
        "solo_learning_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "initiator_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "partner_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "status IN ('proposed','accepted','declined','cancelled','completed')",
            name="ck_solo_session_status",
        ),
    )
    op.create_index("ix_solo_sessions_initiator", "solo_learning_sessions", ["initiator_id"])
    op.create_index("ix_solo_sessions_partner", "solo_learning_sessions", ["partner_id"])
    op.create_index("ix_solo_sessions_scheduled", "solo_learning_sessions", ["scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_solo_sessions_scheduled", table_name="solo_learning_sessions")
    op.drop_index("ix_solo_sessions_partner", table_name="solo_learning_sessions")
    op.drop_index("ix_solo_sessions_initiator", table_name="solo_learning_sessions")
    op.drop_table("solo_learning_sessions")

    op.drop_index("ix_solo_subscriptions_period_end", table_name="solo_subscriptions")
    op.drop_index("ix_solo_subscriptions_status", table_name="solo_subscriptions")
    op.drop_index("ix_solo_subscriptions_user", table_name="solo_subscriptions")
    op.drop_table("solo_subscriptions")