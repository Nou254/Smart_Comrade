"""add break_glass_config table + is_emergency_account + is_break_glass

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"  
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users.is_emergency_account ---
    op.add_column(
        "users",
        sa.Column(
            "is_emergency_account",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_users_is_emergency_account", "users", ["is_emergency_account"],
    )

    # --- sessions.is_break_glass ---
    op.add_column(
        "sessions",
        sa.Column(
            "is_break_glass",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # --- break_glass_config singleton ---
    op.create_table(
        "break_glass_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("unlock_token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "use_count", sa.Integer(), nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("break_glass_config")
    op.drop_column("sessions", "is_break_glass")
    op.drop_index("ix_users_is_emergency_account", table_name="users")
    op.drop_column("users", "is_emergency_account")