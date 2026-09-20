"""add campus_role + institution_transitions + transition_requests

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-19
"""
from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


NEW_TYPES = (
    "'UNIVERSITY','UNIVERSITY_COLLEGE','COLLEGE',"
    "'POLYTECHNIC','TVET','TECHNICAL_INSTITUTE',"
    "'KMTC','TTC','OTHER'"
)


def upgrade() -> None:
    # ─── 1. Add campus_role to institutions ───────────────────────────────
    op.add_column(
        "institutions",
        sa.Column(
            "campus_role", sa.String(16),
            nullable=False, server_default="main",
        ),
    )
    op.create_index(
        "ix_institutions_campus_role", "institutions", ["campus_role"],
    )
    op.create_check_constraint(
        "ck_institution_campus_role", "institutions",
        "campus_role IN ('main','branch')",
    )

    # Backfill: any institution with a parent is logically a branch.
    op.execute(
        "UPDATE institutions SET campus_role = 'branch' "
        "WHERE parent_institution_id IS NOT NULL"
    )

    # ─── 2. Expand institution type list ──────────────────────────────────
    op.drop_constraint("ck_institution_type", "institutions", type_="check")
    op.create_check_constraint(
        "ck_institution_type", "institutions",
        f"type IN ({NEW_TYPES})",
    )

    # ─── 3. institution_transition_requests ──────────────────────────────
    op.create_table(
        "institution_transition_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("desired_campus_role", sa.String(16), nullable=True),
        sa.Column("desired_type", sa.String(32), nullable=True),
        sa.Column(
            "desired_parent_institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="pending",
        ),
        sa.Column(
            "reviewed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','withdrawn')",
            name="ck_transition_request_status",
        ),
    )
    op.create_index(
        "ix_transition_requests_institution_id",
        "institution_transition_requests", ["institution_id"],
    )
    op.create_index(
        "ix_transition_requests_requested_by",
        "institution_transition_requests", ["requested_by"],
    )
    op.create_index(
        "ix_transition_requests_status",
        "institution_transition_requests", ["status"],
    )

    # ─── 4. institution_transitions ──────────────────────────────────────
    op.create_table(
        "institution_transitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("transition_type", sa.String(32), nullable=False),
        sa.Column("old_campus_role", sa.String(16), nullable=True),
        sa.Column("old_type", sa.String(32), nullable=True),
        sa.Column(
            "old_parent_institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("new_campus_role", sa.String(16), nullable=True),
        sa.Column("new_type", sa.String(32), nullable=True),
        sa.Column(
            "new_parent_institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column(
            "changed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_request_id", sa.String(36),
            sa.ForeignKey("institution_transition_requests.id", ondelete="SET NULL"),
            nullable=True,
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
    op.create_index(
        "ix_transitions_institution_id",
        "institution_transitions", ["institution_id"],
    )
    op.create_index(
        "ix_transitions_type",
        "institution_transitions", ["transition_type"],
    )
    op.create_index(
        "ix_transitions_changed_by",
        "institution_transitions", ["changed_by"],
    )


def downgrade() -> None:
    op.drop_table("institution_transitions")
    op.drop_table("institution_transition_requests")

    op.drop_constraint("ck_institution_type", "institutions", type_="check")
    op.create_check_constraint(
        "ck_institution_type", "institutions",
        "type IN ('UNIVERSITY','COLLEGE','TVET','POLYTECHNIC','KMTC','OTHER')",
    )

    op.drop_constraint("ck_institution_campus_role", "institutions", type_="check")
    op.drop_index("ix_institutions_campus_role", table_name="institutions")
    op.drop_column("institutions", "campus_role")