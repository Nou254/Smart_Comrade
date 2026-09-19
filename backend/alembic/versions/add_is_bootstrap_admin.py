"""add users.is_bootstrap_admin

Revision ID: a1b2c3d4e5f6
Revises: 7902c6fd32e6
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "7902c6fd32e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_bootstrap_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_users_is_bootstrap_admin",
        "users",
        ["is_bootstrap_admin"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_is_bootstrap_admin", table_name="users")
    op.drop_column("users", "is_bootstrap_admin")