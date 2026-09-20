"""add lecturer_affiliations table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lecturer_affiliations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("institutional_email", sa.String(255), nullable=True),
        sa.Column("department", sa.String(150), nullable=True),
        sa.Column("title", sa.String(50), nullable=False),
        sa.Column("referee_name", sa.String(160), nullable=False),
        sa.Column("referee_phone", sa.String(32), nullable=False),
        sa.Column("referee_relationship", sa.String(120), nullable=False),
        sa.Column(
            "verification_status", sa.String(20),
            nullable=False, server_default="pending",
        ),
        sa.Column(
            "domain_verified", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column(
            "approved_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        sa.Column(
            "start_date", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "institution_id",
            name="uq_lecturer_aff_user_institution",
        ),
    )
    op.create_index(
        "ix_lecturer_aff_user_id", "lecturer_affiliations", ["user_id"],
    )
    op.create_index(
        "ix_lecturer_aff_institution_id",
        "lecturer_affiliations", ["institution_id"],
    )
    op.create_index(
        "ix_lecturer_aff_status",
        "lecturer_affiliations", ["verification_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_lecturer_aff_status", table_name="lecturer_affiliations")
    op.drop_index("ix_lecturer_aff_institution_id", table_name="lecturer_affiliations")
    op.drop_index("ix_lecturer_aff_user_id", table_name="lecturer_affiliations")
    op.drop_table("lecturer_affiliations")