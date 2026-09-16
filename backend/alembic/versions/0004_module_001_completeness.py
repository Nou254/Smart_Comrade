"""module 001 completeness: user fields, role classification, session metadata,
external_profiles, notification_preferences

Revision ID: 0004_module_001_completeness
Revises: 0003_upload_pipeline
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_module_001_completeness"
down_revision = "0003_upload_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users: known_devices, lifecycle, ToS/Privacy ──
    op.add_column("users", sa.Column(
        "known_devices", postgresql.JSONB(astext_type=sa.Text()),
        nullable=True, server_default=sa.text("'[]'::jsonb"),
    ))
    op.add_column("users", sa.Column(
        "deactivated_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("users", sa.Column(
        "reactivation_deadline", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("users", sa.Column(
        "rejected_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("users", sa.Column(
        "rejected_by", sa.String(36), nullable=True,
    ))
    op.create_foreign_key(
        "fk_users_rejected_by_users", "users", "users",
        ["rejected_by"], ["id"], ondelete="SET NULL",
    )
    op.add_column("users", sa.Column(
        "tos_accepted_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("users", sa.Column("tos_version", sa.String(32), nullable=True))
    op.add_column("users", sa.Column(
        "privacy_accepted_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("users", sa.Column("privacy_version", sa.String(32), nullable=True))

    # ── roles: role_class, is_leadership ──
    op.add_column("roles", sa.Column(
        "role_class", sa.String(32), nullable=False, server_default="student_base",
    ))
    op.add_column("roles", sa.Column(
        "is_leadership", sa.Boolean(), nullable=False, server_default=sa.text("false"),
    ))
    op.create_index("ix_roles_role_class", "roles", ["role_class"])
    op.create_index("ix_roles_is_leadership", "roles", ["is_leadership"])

    # ── sessions: device metadata ──
    op.add_column("sessions", sa.Column("device_type", sa.String(32), nullable=True))
    op.add_column("sessions", sa.Column("device_os", sa.String(32), nullable=True))
    op.add_column("sessions", sa.Column("device_browser", sa.String(32), nullable=True))
    op.add_column("sessions", sa.Column("location", sa.String(160), nullable=True))

    # ── external_profiles ──
    op.create_table(
        "external_profiles",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("external_subtype", sa.String(32), nullable=False),
        # Investor
        sa.Column("investment_focus", sa.Text(), nullable=True),
        sa.Column("investor_org_name", sa.String(255), nullable=True),
        sa.Column("investor_role", sa.String(120), nullable=True),
        # Organization
        sa.Column("organization_name", sa.String(255), nullable=True),
        sa.Column("organization_type", sa.String(64), nullable=True),
        sa.Column("industry", sa.String(64), nullable=True),
        sa.Column("registration_number", sa.String(64), nullable=True),
        sa.Column("contact_name", sa.String(160), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        # Alumni
        sa.Column("former_institution", sa.String(255), nullable=True),
        sa.Column("graduation_year", sa.Integer(), nullable=True),
        sa.Column("current_profession", sa.String(160), nullable=True),
        sa.Column("alumni_expertise", sa.Text(), nullable=True),
        # Mentor
        sa.Column("mentor_profession", sa.String(160), nullable=True),
        sa.Column("mentor_expertise", sa.Text(), nullable=True),
        sa.Column("mentor_experience_summary", sa.Text(), nullable=True),
        sa.Column("mentor_availability", sa.String(64), nullable=True),
        # Specialist
        sa.Column("expertise_field", sa.String(160), nullable=True),
        sa.Column("affiliation", sa.String(255), nullable=True),
        # Verification
        sa.Column("verification_status", sa.String(32), nullable=False,
                  server_default="pending"),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_external_profiles_user_id"),
    )
    op.create_index("ix_external_profiles_user_id", "external_profiles", ["user_id"])
    op.create_index("ix_external_profiles_subtype", "external_profiles", ["external_subtype"])
    op.create_index("ix_external_profiles_org_name", "external_profiles", ["organization_name"])

    # ── notification_preferences ──
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sms_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("group_activity", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("announcements", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("elections", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("assessments", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("events", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("opportunities", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("marketing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_notification_preferences_user_id"),
    )
    op.create_index("ix_notif_prefs_user_id", "notification_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notif_prefs_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")

    op.drop_index("ix_external_profiles_org_name", table_name="external_profiles")
    op.drop_index("ix_external_profiles_subtype", table_name="external_profiles")
    op.drop_index("ix_external_profiles_user_id", table_name="external_profiles")
    op.drop_table("external_profiles")

    op.drop_column("sessions", "location")
    op.drop_column("sessions", "device_browser")
    op.drop_column("sessions", "device_os")
    op.drop_column("sessions", "device_type")

    op.drop_index("ix_roles_is_leadership", table_name="roles")
    op.drop_index("ix_roles_role_class", table_name="roles")
    op.drop_column("roles", "is_leadership")
    op.drop_column("roles", "role_class")

    op.drop_constraint("fk_users_rejected_by_users", "users", type_="foreignkey")
    op.drop_column("users", "privacy_version")
    op.drop_column("users", "privacy_accepted_at")
    op.drop_column("users", "tos_version")
    op.drop_column("users", "tos_accepted_at")
    op.drop_column("users", "rejected_by")
    op.drop_column("users", "rejected_at")
    op.drop_column("users", "reactivation_deadline")
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "known_devices")