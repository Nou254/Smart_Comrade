"""add upload_files updated_at

Revision ID: 714f4f4f81a0
Revises: 0003_upload_pipeline
"""
from alembic import op
import sqlalchemy as sa

revision = "714f4f4f81a0"
down_revision = "0003_upload_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "upload_files",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("upload_files", "updated_at")