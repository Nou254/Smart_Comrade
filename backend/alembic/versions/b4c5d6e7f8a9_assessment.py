"""module 005 — assessment: assessments, question_banks, questions, attempts,
responses, submissions, results, feedback, appeals, assessment_audit_log,
assessment_audience_snapshots, assessment_catalog_entries, ai_assistance_log

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-22

Design decisions wired in:
  - Assessment executes in the PWA; the App is awareness only
  - Two modes: directed (assigned, notified) + system_wide (voluntary, catalog)
  - No approval workflow — created → published → audience notified
  - Creator role determines mandate type + subscription gating
  - Published assessments persist after creator leaves office
  - 60-day activity rule does NOT apply to assessment creation or attempts
  - Institution-mandated assessments bypass subscription gating
  - Only Unit Rep (platform_native) assessments are subscription-gated
  - Audience snapshot at publish time
  - Catalog entries created lazily for system-wide
  - AI assists every assessment creation with routed model selection
  - Human judgment is final for all consequential academic outcomes

Table creation order (respects FKs):
  1. assessments
  2. question_banks
  3. questions
  4. attempts
  5. responses
  6. submissions
  7. results
  8. feedback
  9. appeals
 10. assessment_audit_log
 11. assessment_audience_snapshots
 12. assessment_catalog_entries
 13. ai_assistance_log
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    ("assessment.create",          "Create Assessments",             "assessment"),
    ("assessment.view",            "View Assessments",               "assessment"),
    ("assessment.attempt",         "Take Assessments",               "assessment"),
    ("assessment.grade",           "Grade Assessment Responses",     "assessment"),
    ("assessment.finalise",        "Finalise Assessment Results",    "assessment"),
    ("assessment.appeal.submit",   "Submit Result Appeals",          "assessment"),
    ("assessment.appeal.review",   "Review Result Appeals",          "assessment"),
    ("assessment.catalog.view",    "Browse Assessment Catalog",      "assessment"),
    ("assessment.catalog.publish", "Publish System-Wide Assessments","assessment"),
    ("assessment.analytics.view",  "View Assessment Analytics",      "assessment"),
]

GRANTS: dict[str, list[str]] = {
    "assessment.create": [
        "super_admin", "regional_admin", "lecturer",
        "unit_supervisor", "group_leader", "mentor",
    ],
    "assessment.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "group_leader", "group_secretary", "group_treasurer",
        "student",
    ],
    "assessment.attempt": [
        "student",
    ],
    "assessment.grade": [
        "super_admin", "regional_admin", "lecturer", "unit_supervisor",
    ],
    "assessment.finalise": [
        "super_admin", "regional_admin", "lecturer", "unit_supervisor",
    ],
    "assessment.appeal.submit": [
        "student",
    ],
    "assessment.appeal.review": [
        "super_admin", "regional_admin", "institution_representative",
    ],
    "assessment.catalog.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "school_representative",
        "group_leader", "student",
    ],
    "assessment.catalog.publish": [
        "super_admin", "regional_admin", "lecturer",
        "unit_supervisor", "mentor",
    ],
    "assessment.analytics.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "lecturer", "unit_supervisor",
    ],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _create_assessments()
    _create_question_banks()
    _create_questions()
    _create_attempts()
    _create_responses()
    _create_submissions()
    _create_results()
    _create_feedback()
    _create_appeals()
    _create_assessment_audit_log()
    _create_audience_snapshots()
    _create_catalog_entries()
    _create_ai_assistance_log()
    _seed_permissions_and_grants()


# ─── 1. assessments ──────────────────────────────────────────────────────

def _create_assessments() -> None:
    op.create_table(
        "assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assessment_mode", sa.String(16), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("created_by_role", sa.String(32), nullable=False),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("specialty_unit_ids", postgresql.JSONB, nullable=True),
        sa.Column("mandate_type", sa.String(32), nullable=False),
        sa.Column(
            "subscription_gated", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("audience_scope", sa.String(24), nullable=True),
        sa.Column("audience_ref_id", sa.String(36), nullable=True),
        sa.Column(
            "audience_snapshot_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "audience_resolution", sa.String(16),
            nullable=False, server_default="snapshot",
        ),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "wall_clock_hard_end", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "max_attempts", sa.Integer(),
            nullable=False, server_default="1",
        ),
        sa.Column("passing_score", sa.Numeric(6, 2), nullable=True),
        sa.Column(
            "auto_grading_enabled", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "ai_assisted_creation", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("ai_model_used", sa.String(64), nullable=True),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="draft",
        ),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "assessment_mode IN ('directed','system_wide')",
            name="ck_assessment_mode",
        ),
        sa.CheckConstraint(
            "category IN ('knowledge','written','practical','programming',"
            "'logic','skills','project','practice')",
            name="ck_assessment_category",
        ),
        sa.CheckConstraint(
            "type IN ('quiz','assignment','examination','practical','practice')",
            name="ck_assessment_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft','published','in_progress','closed','archived')",
            name="ck_assessment_status",
        ),
        sa.CheckConstraint(
            "mandate_type IN ('institution_mandated','platform_native',"
            "'community_contribution')",
            name="ck_assessment_mandate_type",
        ),
        sa.CheckConstraint(
            "created_by_role IN ('super_admin','regional_admin','lecturer',"
            "'unit_supervisor','unit_representative','mentor')",
            name="ck_assessment_creator_role",
        ),
        sa.CheckConstraint(
            "audience_scope IS NULL OR audience_scope IN "
            "('group','unit_offering','course_year','institution',"
            "'county','region','custom')",
            name="ck_assessment_audience_scope",
        ),
        sa.CheckConstraint(
            "(assessment_mode = 'system_wide' AND audience_scope IS NULL "
            "AND audience_ref_id IS NULL) OR "
            "(assessment_mode = 'directed' AND audience_scope IS NOT NULL)",
            name="ck_assessment_mode_audience_consistency",
        ),
        sa.CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR end_at > start_at",
            name="ck_assessment_timeline_order",
        ),
    )
    op.create_index(
        "ix_assessments_creator", "assessments", ["created_by"],
    )
    op.create_index(
        "ix_assessments_mode_status", "assessments",
        ["assessment_mode", "status"],
    )
    op.create_index(
        "ix_assessments_offering", "assessments", ["unit_offering_id"],
    )
    op.create_index("ix_assessments_group", "assessments", ["group_id"])
    op.create_index(
        "ix_assessments_institution", "assessments", ["institution_id"],
    )
    op.create_index(
        "ix_assessments_status_start", "assessments",
        ["status", "start_at"],
    )
    op.create_index(
        "ix_assessments_open", "assessments",
        ["assessment_mode", "end_at"],
    )
    op.create_index("ix_assessments_status", "assessments", ["status"])


# ─── 2. question_banks ───────────────────────────────────────────────────

def _create_question_banks() -> None:
    op.create_table(
        "question_banks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_id", sa.String(36),
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "is_active", sa.Boolean(),
            nullable=False, server_default=sa.true(),
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
    op.create_index("ix_question_banks_unit", "question_banks", ["unit_id"])
    op.create_index(
        "ix_question_banks_creator", "question_banks", ["created_by"],
    )
    op.create_index(
        "ix_question_banks_active", "question_banks", ["is_active"],
    )


# ─── 3. questions ────────────────────────────────────────────────────────

def _create_questions() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id", sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "question_bank_id", sa.String(36),
            sa.ForeignKey("question_banks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question_type", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("options_json", postgresql.JSONB, nullable=True),
        sa.Column("correct_answer_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "point_value", sa.Numeric(6, 2),
            nullable=False, server_default="1.0",
        ),
        sa.Column(
            "order_index", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "difficulty", sa.String(16),
            nullable=False, server_default="intermediate",
        ),
        sa.Column("topic_tags", postgresql.JSONB, nullable=True),
        sa.Column("ai_draft_id", sa.String(64), nullable=True),
        sa.Column(
            "ai_generated_content", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("ai_validation_status", sa.String(24), nullable=True),
        sa.Column("ai_validation_notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "question_type IN ('mcq','true_false','fill_blank',"
            "'essay','file_upload')",
            name="ck_question_type",
        ),
        sa.CheckConstraint(
            "difficulty IN ('beginner','intermediate','advanced')",
            name="ck_question_difficulty",
        ),
        sa.CheckConstraint(
            "ai_validation_status IS NULL OR ai_validation_status IN "
            "('passed','failed','needs_review')",
            name="ck_question_ai_validation_status",
        ),
        sa.CheckConstraint(
            "assessment_id IS NOT NULL OR question_bank_id IS NOT NULL",
            name="ck_question_has_parent",
        ),
        sa.CheckConstraint(
            "point_value >= 0",
            name="ck_question_point_value_nonneg",
        ),
    )
    op.create_index(
        "ix_questions_assessment", "questions", ["assessment_id"],
    )
    op.create_index(
        "ix_questions_bank", "questions", ["question_bank_id"],
    )
    op.create_index(
        "ix_questions_order", "questions",
        ["assessment_id", "order_index"],
    )


# ─── 4. attempts ─────────────────────────────────────────────────────────

def _create_attempts() -> None:
    op.create_table(
        "attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id", sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attempt_number", sa.Integer(),
            nullable=False, server_default="1",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "timer_expires_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("score", sa.Numeric(8, 2), nullable=True),
        sa.Column("percentage", sa.Numeric(6, 2), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="in_progress",
        ),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('in_progress','submitted','timed_out',"
            "'graded','abandoned')",
            name="ck_attempt_status",
        ),
        sa.UniqueConstraint(
            "assessment_id", "student_id", "attempt_number",
            name="uq_attempt_number_per_student_assessment",
        ),
    )
    op.create_index("ix_attempts_student", "attempts", ["student_id"])
    op.create_index(
        "ix_attempts_assessment", "attempts", ["assessment_id"],
    )
    op.create_index("ix_attempts_status", "attempts", ["status"])
    op.create_index(
        "ix_attempts_timer", "attempts", ["timer_expires_at"],
    )
    # Only one ACTIVE attempt per (student, assessment)
    op.create_index(
        "uq_active_attempt_per_student_assessment",
        "attempts",
        ["assessment_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )


# ─── 5. responses ────────────────────────────────────────────────────────

def _create_responses() -> None:
    op.create_table(
        "responses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "attempt_id", sa.String(36),
            sa.ForeignKey("attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id", sa.String(36),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_file_url", sa.String(500), nullable=True),
        sa.Column("response_json", postgresql.JSONB, nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score_earned", sa.Numeric(6, 2), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "graded_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ai_preliminary_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("ai_score_rationale", sa.Text(), nullable=True),
        sa.Column(
            "ai_graded_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("ai_grade_model", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "attempt_id", "question_id",
            name="uq_response_per_attempt_question",
        ),
    )
    op.create_index("ix_responses_attempt", "responses", ["attempt_id"])
    op.create_index("ix_responses_question", "responses", ["question_id"])
    op.create_index("ix_responses_grader", "responses", ["graded_by"])


# ─── 6. submissions ──────────────────────────────────────────────────────

def _create_submissions() -> None:
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "attempt_id", sa.String(36),
            sa.ForeignKey("attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_url", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
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
        "ix_submissions_attempt", "submissions", ["attempt_id"],
    )
    op.create_index(
        "ix_submissions_uploaded", "submissions", ["uploaded_at"],
    )


# ─── 7. results ──────────────────────────────────────────────────────────

def _create_results() -> None:
    op.create_table(
        "results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id", sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "best_attempt_id", sa.String(36),
            sa.ForeignKey("attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("final_score", sa.Numeric(8, 2), nullable=False),
        sa.Column("percentage", sa.Numeric(6, 2), nullable=False),
        sa.Column("grade", sa.String(8), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("competence_level", sa.String(16), nullable=True),
        sa.Column(
            "is_official", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "finalised_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "finalised_by", sa.String(36),
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
        sa.CheckConstraint(
            "competence_level IS NULL OR competence_level IN "
            "('introductory','developing','competent','advanced')",
            name="ck_result_competence_level",
        ),
        sa.UniqueConstraint(
            "assessment_id", "student_id",
            name="uq_result_per_student_assessment",
        ),
    )
    op.create_index(
        "ix_results_assessment", "results", ["assessment_id"],
    )
    op.create_index("ix_results_student", "results", ["student_id"])
    op.create_index("ix_results_passed", "results", ["passed"])


# ─── 8. feedback ─────────────────────────────────────────────────────────

def _create_feedback() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id", sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "is_anonymous", sa.Boolean(),
            nullable=False, server_default=sa.false(),
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
        "ix_feedback_assessment", "feedback", ["assessment_id"],
    )
    op.create_index("ix_feedback_student", "feedback", ["student_id"])


# ─── 9. appeals ──────────────────────────────────────────────────────────

def _create_appeals() -> None:
    op.create_table(
        "appeals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "result_id", sa.String(36),
            sa.ForeignKey("results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grounds", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "status", sa.String(32),
            nullable=False, server_default="submitted",
        ),
        sa.Column(
            "reviewer_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("original_result_json", postgresql.JSONB, nullable=True),
        sa.Column("corrected_result_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('submitted','under_review','resolved_confirmed',"
            "'resolved_corrected','reassessment_authorised','rejected')",
            name="ck_appeal_status",
        ),
    )
    op.create_index("ix_appeals_result", "appeals", ["result_id"])
    op.create_index("ix_appeals_student", "appeals", ["student_id"])
    op.create_index("ix_appeals_status", "appeals", ["status"])
    op.create_index("ix_appeals_reviewer", "appeals", ["reviewer_id"])


# ─── 10. assessment_audit_log ────────────────────────────────────────────

def _create_assessment_audit_log() -> None:
    op.create_table(
        "assessment_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id", sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('create','publish','open','close','archive',"
            "'evaluate','modify_result','appeal_review','cancel',"
            "'audience_change','subscription_gate_decision')",
            name="ck_assessment_audit_action",
        ),
    )
    op.create_index(
        "ix_assessment_audit_assessment", "assessment_audit_log",
        ["assessment_id"],
    )
    op.create_index(
        "ix_assessment_audit_actor", "assessment_audit_log", ["actor_id"],
    )
    op.create_index(
        "ix_assessment_audit_action", "assessment_audit_log", ["action"],
    )
    op.create_index(
        "ix_assessment_audit_created", "assessment_audit_log", ["created_at"],
    )


# ─── 11. assessment_audience_snapshots ───────────────────────────────────

def _create_audience_snapshots() -> None:
    op.create_table(
        "assessment_audience_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id", sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_still_eligible", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_reason", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "assessment_id", "user_id",
            name="uq_audience_snapshot_per_student",
        ),
    )
    op.create_index(
        "ix_audience_snapshot_assessment", "assessment_audience_snapshots",
        ["assessment_id"],
    )
    op.create_index(
        "ix_audience_snapshot_user", "assessment_audience_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_audience_snapshot_active", "assessment_audience_snapshots",
        ["assessment_id", "removed_at"],
    )


# ─── 12. assessment_catalog_entries ──────────────────────────────────────

def _create_catalog_entries() -> None:
    op.create_table(
        "assessment_catalog_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id", sa.String(36),
            sa.ForeignKey("assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "primary_unit_id", sa.String(36),
            sa.ForeignKey("units.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("specialty_unit_ids", postgresql.JSONB, nullable=True),
        sa.Column("specialty_tags", postgresql.JSONB, nullable=True),
        sa.Column(
            "difficulty", sa.String(16),
            nullable=False, server_default="intermediate",
        ),
        sa.Column(
            "estimated_duration_minutes", sa.Integer(), nullable=True,
        ),
        sa.Column(
            "view_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "take_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column("average_rating", sa.Float(), nullable=True),
        sa.Column(
            "rating_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "is_featured", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "difficulty IN ('beginner','intermediate','advanced')",
            name="ck_catalog_entry_difficulty",
        ),
        sa.UniqueConstraint(
            "assessment_id", name="uq_catalog_entry_per_assessment",
        ),
    )
    op.create_index(
        "ix_catalog_entries_unit", "assessment_catalog_entries",
        ["primary_unit_id"],
    )
    op.create_index(
        "ix_catalog_entries_featured", "assessment_catalog_entries",
        ["is_featured"],
    )
    op.create_index(
        "ix_catalog_entries_rating", "assessment_catalog_entries",
        ["average_rating"],
    )


# ─── 13. ai_assistance_log ───────────────────────────────────────────────

def _create_ai_assistance_log() -> None:
    op.create_table(
        "ai_assistance_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(24), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column(
            "actor_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "prompt_tokens", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "completion_tokens", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("request_summary", sa.Text(), nullable=True),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column(
            "succeeded", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('draft','validate','grade','summarize','hint')",
            name="ck_ai_log_action",
        ),
        sa.CheckConstraint(
            "entity_type IN ('assessment','question','response',"
            "'result','report')",
            name="ck_ai_log_entity_type",
        ),
    )
    op.create_index(
        "ix_ai_log_entity", "ai_assistance_log",
        ["entity_type", "entity_id"],
    )
    op.create_index("ix_ai_log_actor", "ai_assistance_log", ["actor_id"])
    op.create_index("ix_ai_log_model", "ai_assistance_log", ["model_used"])
    op.create_index("ix_ai_log_action", "ai_assistance_log", ["action"])
    op.create_index("ix_ai_log_created", "ai_assistance_log", ["created_at"])


# ─── 14. permissions + grants ────────────────────────────────────────────

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
        for row in bind.execute(
            sa.text("SELECT code FROM permissions")
        ).fetchall()
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
        for row in bind.execute(
            sa.text("SELECT code, id FROM permissions")
        ).fetchall()
    }
    role_code_to_id: dict[str, str] = {
        row[0]: row[1]
        for row in bind.execute(
            sa.text("SELECT code, id FROM roles")
        ).fetchall()
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

    # Drop in reverse FK order

    op.drop_index("ix_ai_log_created", table_name="ai_assistance_log")
    op.drop_index("ix_ai_log_action", table_name="ai_assistance_log")
    op.drop_index("ix_ai_log_model", table_name="ai_assistance_log")
    op.drop_index("ix_ai_log_actor", table_name="ai_assistance_log")
    op.drop_index("ix_ai_log_entity", table_name="ai_assistance_log")
    op.drop_table("ai_assistance_log")

    op.drop_index(
        "ix_catalog_entries_rating",
        table_name="assessment_catalog_entries",
    )
    op.drop_index(
        "ix_catalog_entries_featured",
        table_name="assessment_catalog_entries",
    )
    op.drop_index(
        "ix_catalog_entries_unit",
        table_name="assessment_catalog_entries",
    )
    op.drop_table("assessment_catalog_entries")

    op.drop_index(
        "ix_audience_snapshot_active",
        table_name="assessment_audience_snapshots",
    )
    op.drop_index(
        "ix_audience_snapshot_user",
        table_name="assessment_audience_snapshots",
    )
    op.drop_index(
        "ix_audience_snapshot_assessment",
        table_name="assessment_audience_snapshots",
    )
    op.drop_table("assessment_audience_snapshots")

    op.drop_index(
        "ix_assessment_audit_created", table_name="assessment_audit_log",
    )
    op.drop_index(
        "ix_assessment_audit_action", table_name="assessment_audit_log",
    )
    op.drop_index(
        "ix_assessment_audit_actor", table_name="assessment_audit_log",
    )
    op.drop_index(
        "ix_assessment_audit_assessment", table_name="assessment_audit_log",
    )
    op.drop_table("assessment_audit_log")

    op.drop_index("ix_appeals_reviewer", table_name="appeals")
    op.drop_index("ix_appeals_status", table_name="appeals")
    op.drop_index("ix_appeals_student", table_name="appeals")
    op.drop_index("ix_appeals_result", table_name="appeals")
    op.drop_table("appeals")

    op.drop_index("ix_feedback_student", table_name="feedback")
    op.drop_index("ix_feedback_assessment", table_name="feedback")
    op.drop_table("feedback")

    op.drop_index("ix_results_passed", table_name="results")
    op.drop_index("ix_results_student", table_name="results")
    op.drop_index("ix_results_assessment", table_name="results")
    op.drop_table("results")

    op.drop_index("ix_submissions_uploaded", table_name="submissions")
    op.drop_index("ix_submissions_attempt", table_name="submissions")
    op.drop_table("submissions")

    op.drop_index("ix_responses_grader", table_name="responses")
    op.drop_index("ix_responses_question", table_name="responses")
    op.drop_index("ix_responses_attempt", table_name="responses")
    op.drop_table("responses")

    op.drop_index(
        "uq_active_attempt_per_student_assessment", table_name="attempts",
    )
    op.drop_index("ix_attempts_timer", table_name="attempts")
    op.drop_index("ix_attempts_status", table_name="attempts")
    op.drop_index("ix_attempts_assessment", table_name="attempts")
    op.drop_index("ix_attempts_student", table_name="attempts")
    op.drop_table("attempts")

    op.drop_index("ix_questions_order", table_name="questions")
    op.drop_index("ix_questions_bank", table_name="questions")
    op.drop_index("ix_questions_assessment", table_name="questions")
    op.drop_table("questions")

    op.drop_index("ix_question_banks_active", table_name="question_banks")
    op.drop_index("ix_question_banks_creator", table_name="question_banks")
    op.drop_index("ix_question_banks_unit", table_name="question_banks")
    op.drop_table("question_banks")

    op.drop_index("ix_assessments_status", table_name="assessments")
    op.drop_index("ix_assessments_open", table_name="assessments")
    op.drop_index("ix_assessments_status_start", table_name="assessments")
    op.drop_index("ix_assessments_institution", table_name="assessments")
    op.drop_index("ix_assessments_group", table_name="assessments")
    op.drop_index("ix_assessments_offering", table_name="assessments")
    op.drop_index("ix_assessments_mode_status", table_name="assessments")
    op.drop_index("ix_assessments_creator", table_name="assessments")
    op.drop_table("assessments")