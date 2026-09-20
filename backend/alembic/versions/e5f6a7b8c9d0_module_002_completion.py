"""module 002 completion — combinations, unit offerings, unit proposals,
registration-number verification

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-20

Creates:
  - combinations
  - unit_offerings
  - unit_proposals (+ items + events)
  - institution_verification_periods
  - institution_registration_numbers

Alters:
  - users                : + registration_number, registration_number_verified
  - student_enrollments  : + combination_id (FK -> combinations.id)
  - unit_memberships     : + confirmation_status / confirmed_at /
                            declined_at / decline_reason

Seeds:
  - 15 new permission codes
  - role -> permission grants
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSION DEFINITIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    # (code, name, category)
    ("combination.create", "Create Combination", "combination"),
    ("combination.view", "View Combination", "combination"),
    ("combination.edit", "Edit Combination", "combination"),

    ("unit_offering.create", "Create Unit Offering", "unit_offering"),
    ("unit_offering.view", "View Unit Offering", "unit_offering"),
    ("unit_offering.edit", "Edit Unit Offering", "unit_offering"),

    ("unit_proposal.create", "Create Unit Proposal", "unit_proposal"),
    ("unit_proposal.view", "View Unit Proposal", "unit_proposal"),
    ("unit_proposal.approve", "Approve Unit Proposal", "unit_proposal"),
    ("unit_proposal.modify_item", "Modify Unit Proposal Item", "unit_proposal"),

    ("verification.period.view", "View Verification Period", "verification"),
    ("verification.period.complete", "Complete Verification Period", "verification"),
    ("verification.roster.upload", "Upload Verification Roster", "verification"),
    ("verification.roster.manual_add", "Manually Add Roster Entry", "verification"),
    ("verification.pair.verify", "Verify Registration Pair", "verification"),
]


GRANTS: dict[str, list[str]] = {
    "combination.create": [
        "super_admin", "regional_admin", "institution_representative",
    ],
    "combination.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "student",
    ],
    "combination.edit": [
        "super_admin", "regional_admin", "institution_representative",
    ],

    "unit_offering.create": [
        "super_admin", "regional_admin",
        "institution_representative", "school_representative",
    ],
    "unit_offering.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "group_leader", "group_secretary", "group_treasurer",
        "unit_representative", "student",
    ],
    "unit_offering.edit": [
        "super_admin", "regional_admin", "institution_representative",
    ],

    "unit_proposal.create": [
        "group_leader",
        "school_representative",
        "institution_representative", "assistant_institution_rep",
        "regional_admin",
    ],
    "unit_proposal.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
    ],
    "unit_proposal.approve": [
        "school_representative", "assistant_school_rep",
        "institution_representative", "assistant_institution_rep",
        "regional_admin", "super_admin",
    ],
    "unit_proposal.modify_item": [
        "school_representative", "assistant_school_rep",
        "institution_representative", "assistant_institution_rep",
        "regional_admin", "super_admin",
    ],

    "verification.period.view": [
        "super_admin", "regional_admin",
        "county_representative", "assistant_county_rep",
        "institution_representative", "assistant_institution_rep",
    ],
    "verification.period.complete": [
        "institution_representative", "assistant_institution_rep",
        "super_admin",
    ],
    "verification.roster.upload": [
        "institution_representative", "assistant_institution_rep",
    ],
    "verification.roster.manual_add": [
        "county_representative", "assistant_county_rep",
        "institution_representative", "assistant_institution_rep",
    ],
    "verification.pair.verify": [
        "institution_representative", "assistant_institution_rep",
        "county_representative", "assistant_county_rep",
    ],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _add_user_columns()
    _add_unit_membership_columns()
    _create_combinations_table()
    _add_combination_fk_to_enrollments()
    _create_unit_offerings_table()
    _create_unit_proposals_tables()
    _create_verification_tables()
    _seed_permissions_and_grants()


# ─── 1. users: registration number ────────────────────────────────────────

def _add_user_columns() -> None:
    op.add_column(
        "users",
        sa.Column("registration_number", sa.String(64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "registration_number_verified", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_users_registration_number", "users", ["registration_number"],
    )
    op.create_index(
        "ix_users_registration_number_verified",
        "users", ["registration_number_verified"],
    )


# ─── 2. unit_memberships: confirmation fields ─────────────────────────────

def _add_unit_membership_columns() -> None:
    op.add_column(
        "unit_memberships",
        sa.Column(
            "confirmation_status", sa.String(16),
            nullable=False, server_default="pending",
        ),
    )
    op.add_column(
        "unit_memberships",
        sa.Column(
            "confirmed_at", sa.DateTime(timezone=True), nullable=True,
        ),
    )
    op.add_column(
        "unit_memberships",
        sa.Column(
            "declined_at", sa.DateTime(timezone=True), nullable=True,
        ),
    )
    op.add_column(
        "unit_memberships",
        sa.Column("decline_reason", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_unit_membership_confirmation", "unit_memberships",
        "confirmation_status IN ('pending','confirmed','declined')",
    )
    op.create_index(
        "ix_unit_memberships_confirmation_status",
        "unit_memberships", ["confirmation_status"],
    )

    # Backfill: existing rows predate the confirmation flow. They represent
    # already-agreed memberships, so mark them as confirmed.
    op.execute(
        "UPDATE unit_memberships SET confirmation_status = 'confirmed'"
    )
    # Now drop the server default so new rows go through the model's default
    # ('pending') rather than the DB-level 'pending' we set for the ALTER.
    op.alter_column(
        "unit_memberships", "confirmation_status",
        server_default=None,
    )


# ─── 3. combinations ──────────────────────────────────────────────────────

def _create_combinations_table() -> None:
    op.create_table(
        "combinations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "course_id", sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="active",
        ),
        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
        sa.UniqueConstraint(
            "course_id", "code", name="uq_combination_course_code",
        ),
        sa.UniqueConstraint(
            "course_id", "name", name="uq_combination_course_name",
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_combination_status",
        ),
    )
    op.create_index(
        "ix_combinations_course_id", "combinations", ["course_id"],
    )
    op.create_index(
        "ix_combinations_status", "combinations", ["status"],
    )
    op.create_index(
        "ix_combinations_created_by", "combinations", ["created_by"],
    )


# ─── 4. student_enrollments: combination_id FK ───────────────────────────

def _add_combination_fk_to_enrollments() -> None:
    op.add_column(
        "student_enrollments",
        sa.Column("combination_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_student_enrollment_combination",
        "student_enrollments", "combinations",
        ["combination_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_student_enrollments_combination_id",
        "student_enrollments", ["combination_id"],
    )


# ─── 5. unit_offerings ────────────────────────────────────────────────────

def _create_unit_offerings_table() -> None:
    op.create_table(
        "unit_offerings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_id", sa.String(36),
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_id", sa.String(36),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id", sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "academic_year_id", sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "semester_id", sa.String(36),
            sa.ForeignKey("semesters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year_level", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="scheduled",
        ),
        sa.Column(
            "enrolled_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "unit_id", "semester_id",
            name="uq_unit_offering_per_semester",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','active','completed','archived')",
            name="ck_unit_offering_status",
        ),
    )
    op.create_index(
        "ix_unit_offerings_unit_id", "unit_offerings", ["unit_id"],
    )
    op.create_index(
        "ix_unit_offerings_institution_id", "unit_offerings", ["institution_id"],
    )
    op.create_index(
        "ix_unit_offerings_course_id", "unit_offerings", ["course_id"],
    )
    op.create_index(
        "ix_unit_offerings_academic_year_id",
        "unit_offerings", ["academic_year_id"],
    )
    op.create_index(
        "ix_unit_offerings_semester_id", "unit_offerings", ["semester_id"],
    )
    op.create_index(
        "ix_unit_offerings_status", "unit_offerings", ["status"],
    )
    op.create_index(
        "ix_unit_offerings_course_semester",
        "unit_offerings", ["course_id", "semester_id"],
    )


# ─── 6. unit_proposals (+ items + events) ─────────────────────────────────

def _create_unit_proposals_tables() -> None:
    # ── unit_proposals ──
    op.create_table(
        "unit_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_id", sa.String(36),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id", sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "academic_year_id", sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "semester_id", sa.String(36),
            sa.ForeignKey("semesters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year_level", sa.Integer(), nullable=False),

        sa.Column("proposal_type", sa.String(24), nullable=False),
        sa.Column(
            "source_upload_id", sa.String(36),
            sa.ForeignKey("timetable_uploads.id", ondelete="SET NULL"),
            nullable=True,
        ),

        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(32),
            nullable=False, server_default="pending_school_rep",
        ),

        sa.Column("current_approver_role", sa.String(32), nullable=True),
        sa.Column(
            "current_approver_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "current_stage_started_at", sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "escalation_deadline", sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.Column(
            "approved_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "rejected_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "rejected_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),

        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),

        sa.CheckConstraint(
            "proposal_type IN ('ocr_extraction','manual_creation')",
            name="ck_unit_proposal_type",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending_school_rep','pending_institution_rep',"
            "'pending_regional_admin','pending_super_admin',"
            "'approved','rejected','withdrawn'"
            ")",
            name="ck_unit_proposal_status",
        ),
    )
    op.create_index(
        "ix_unit_proposals_institution_id",
        "unit_proposals", ["institution_id"],
    )
    op.create_index(
        "ix_unit_proposals_school_id", "unit_proposals", ["school_id"],
    )
    op.create_index(
        "ix_unit_proposals_course_id", "unit_proposals", ["course_id"],
    )
    op.create_index(
        "ix_unit_proposals_semester_id", "unit_proposals", ["semester_id"],
    )
    op.create_index(
        "ix_unit_proposals_created_by", "unit_proposals", ["created_by"],
    )
    op.create_index(
        "ix_unit_proposals_status", "unit_proposals", ["status"],
    )
    op.create_index(
        "ix_unit_proposals_course_semester",
        "unit_proposals", ["course_id", "semester_id"],
    )
    op.create_index(
        "ix_unit_proposals_escalation",
        "unit_proposals", ["escalation_deadline"],
    )
    op.create_index(
        "ix_unit_proposals_current_approver",
        "unit_proposals", ["current_approver_id"],
    )

    # ── unit_proposal_items ──
    op.create_table(
        "unit_proposal_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "proposal_id", sa.String(36),
            sa.ForeignKey("unit_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "existing_unit_id", sa.String(36),
            sa.ForeignKey("units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("proposed_code", sa.String(32), nullable=False),
        sa.Column("proposed_name", sa.String(200), nullable=False),
        sa.Column("proposed_description", sa.Text(), nullable=True),
        sa.Column("year_level", sa.Integer(), nullable=True),
        sa.Column("semester_number", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column(
            "action", sa.String(16),
            nullable=False, server_default="create",
        ),
        sa.Column(
            "item_status", sa.String(16),
            nullable=False, server_default="pending",
        ),
        sa.Column("modified_code", sa.String(32), nullable=True),
        sa.Column("modified_name", sa.String(200), nullable=True),
        sa.Column("modified_description", sa.Text(), nullable=True),
        sa.Column(
            "resulting_unit_id", sa.String(36),
            sa.ForeignKey("units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('create','update','match','skip')",
            name="ck_unit_proposal_item_action",
        ),
        sa.CheckConstraint(
            "item_status IN ('pending','approved','rejected','modified')",
            name="ck_unit_proposal_item_status",
        ),
    )
    op.create_index(
        "ix_unit_proposal_items_proposal",
        "unit_proposal_items", ["proposal_id"],
    )

    # ── unit_proposal_events ──
    op.create_table(
        "unit_proposal_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "proposal_id", sa.String(36),
            sa.ForeignKey("unit_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column(
            "actor_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_stage", sa.String(32), nullable=True),
        sa.Column("to_stage", sa.String(32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        "ix_unit_proposal_events_proposal",
        "unit_proposal_events", ["proposal_id"],
    )


# ─── 7. registration verification tables ──────────────────────────────────

def _create_verification_tables() -> None:
    # ── institution_verification_periods ──
    op.create_table(
        "institution_verification_periods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "initiated_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "start_date", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "end_date", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "extended_until", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "extension_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="scheduled",
        ),
        sa.Column(
            "verified_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "unverified_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','active','extended','completed','expired')",
            name="ck_verification_period_status",
        ),
    )
    op.create_index(
        "ix_verification_periods_institution",
        "institution_verification_periods", ["institution_id"],
    )
    op.create_index(
        "ix_verification_periods_status",
        "institution_verification_periods", ["status"],
    )

    # ── institution_registration_numbers ──
    op.create_table(
        "institution_registration_numbers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "period_id", sa.String(36),
            sa.ForeignKey(
                "institution_verification_periods.id", ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("reg_number", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column(
            "added_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "verified_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "verified_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
        sa.UniqueConstraint(
            "institution_id", "reg_number",
            name="uq_institution_reg_number",
        ),
        sa.CheckConstraint(
            "source IN ('roster_upload','manual_entry','student_submission')",
            name="ck_institution_reg_number_source",
        ),
    )
    op.create_index(
        "ix_institution_reg_numbers_institution",
        "institution_registration_numbers", ["institution_id"],
    )
    op.create_index(
        "ix_institution_reg_numbers_period",
        "institution_registration_numbers", ["period_id"],
    )
    op.create_index(
        "ix_institution_reg_numbers_email",
        "institution_registration_numbers", ["email"],
    )
    op.create_index(
        "ix_institution_reg_numbers_user",
        "institution_registration_numbers", ["user_id"],
    )


# ─── 8. permissions + grants ──────────────────────────────────────────────

def _seed_permissions_and_grants() -> None:
    """
    Insert the new permission codes and grant them to the appropriate
    roles. Uses SQLAlchemy Core so we do not have to know the exact ORM
    models. Idempotent: existing permissions are re-used.
    """
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

    # --- Insert permissions (skip any that already exist) ---
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

    # --- Build code -> id map ---
    code_to_id: dict[str, str] = {
        row[0]: row[1]
        for row in bind.execute(
            sa.text("SELECT code, id FROM permissions")
        ).fetchall()
    }

    # --- Build role code -> id map ---
    role_code_to_id: dict[str, str] = {
        row[0]: row[1]
        for row in bind.execute(
            sa.text("SELECT code, id FROM roles")
        ).fetchall()
    }

    # --- Existing (role_id, permission_id) pairs to avoid duplicates ---
    existing_pairs: set[tuple[str, str]] = {
        (row[0], row[1])
        for row in bind.execute(
            sa.text("SELECT role_id, permission_id FROM role_permissions")
        ).fetchall()
    }

    # --- Insert grants ---
    to_grant: list[dict] = []
    for permission_code, role_codes in GRANTS.items():
        permission_id = code_to_id.get(permission_code)
        if not permission_id:
            continue
        for role_code in role_codes:
            role_id = role_code_to_id.get(role_code)
            if not role_id:
                # Role does not exist in this installation — skip silently.
                continue
            if (role_id, permission_id) in existing_pairs:
                continue
            to_grant.append({
                "id": str(uuid4()),
                "role_id": role_id,
                "permission_id": permission_id,
            })

    if to_grant:
        bind.execute(role_permissions_table.insert(), to_grant)


# ============================================================================
# DOWNGRADE
# ============================================================================

def downgrade() -> None:
    # Reverse grant seed: delete only the permissions this migration added.
    bind = op.get_bind()
    codes = [code for (code, _name, _cat) in NEW_PERMISSIONS]
    if codes:
        placeholders = ",".join(f"'{c}'" for c in codes)
        bind.execute(sa.text(
            f"DELETE FROM role_permissions WHERE permission_id IN "
            f"(SELECT id FROM permissions WHERE code IN ({placeholders}))"
        ))
        bind.execute(sa.text(
            f"DELETE FROM permissions WHERE code IN ({placeholders})"
        ))

    # Verification tables
    op.drop_index(
        "ix_institution_reg_numbers_user",
        table_name="institution_registration_numbers",
    )
    op.drop_index(
        "ix_institution_reg_numbers_email",
        table_name="institution_registration_numbers",
    )
    op.drop_index(
        "ix_institution_reg_numbers_period",
        table_name="institution_registration_numbers",
    )
    op.drop_index(
        "ix_institution_reg_numbers_institution",
        table_name="institution_registration_numbers",
    )
    op.drop_table("institution_registration_numbers")

    op.drop_index(
        "ix_verification_periods_status",
        table_name="institution_verification_periods",
    )
    op.drop_index(
        "ix_verification_periods_institution",
        table_name="institution_verification_periods",
    )
    op.drop_table("institution_verification_periods")

    # Unit proposal tables
    op.drop_index(
        "ix_unit_proposal_events_proposal",
        table_name="unit_proposal_events",
    )
    op.drop_table("unit_proposal_events")

    op.drop_index(
        "ix_unit_proposal_items_proposal",
        table_name="unit_proposal_items",
    )
    op.drop_table("unit_proposal_items")

    for idx in (
        "ix_unit_proposals_current_approver",
        "ix_unit_proposals_escalation",
        "ix_unit_proposals_course_semester",
        "ix_unit_proposals_status",
        "ix_unit_proposals_created_by",
        "ix_unit_proposals_semester_id",
        "ix_unit_proposals_course_id",
        "ix_unit_proposals_school_id",
        "ix_unit_proposals_institution_id",
    ):
        op.drop_index(idx, table_name="unit_proposals")
    op.drop_table("unit_proposals")

    # Unit offerings
    for idx in (
        "ix_unit_offerings_course_semester",
        "ix_unit_offerings_status",
        "ix_unit_offerings_semester_id",
        "ix_unit_offerings_academic_year_id",
        "ix_unit_offerings_course_id",
        "ix_unit_offerings_institution_id",
        "ix_unit_offerings_unit_id",
    ):
        op.drop_index(idx, table_name="unit_offerings")
    op.drop_table("unit_offerings")

    # student_enrollments.combination_id
    op.drop_index(
        "ix_student_enrollments_combination_id",
        table_name="student_enrollments",
    )
    op.drop_constraint(
        "fk_student_enrollment_combination",
        "student_enrollments", type_="foreignkey",
    )
    op.drop_column("student_enrollments", "combination_id")

    # combinations
    op.drop_index("ix_combinations_created_by", table_name="combinations")
    op.drop_index("ix_combinations_status", table_name="combinations")
    op.drop_index("ix_combinations_course_id", table_name="combinations")
    op.drop_table("combinations")

    # unit_memberships confirmation columns
    op.drop_index(
        "ix_unit_memberships_confirmation_status",
        table_name="unit_memberships",
    )
    op.drop_constraint(
        "ck_unit_membership_confirmation",
        "unit_memberships", type_="check",
    )
    op.drop_column("unit_memberships", "decline_reason")
    op.drop_column("unit_memberships", "declined_at")
    op.drop_column("unit_memberships", "confirmed_at")
    op.drop_column("unit_memberships", "confirmation_status")

    # users registration number columns
    op.drop_index(
        "ix_users_registration_number_verified", table_name="users",
    )
    op.drop_index("ix_users_registration_number", table_name="users")
    op.drop_column("users", "registration_number_verified")
    op.drop_column("users", "registration_number")