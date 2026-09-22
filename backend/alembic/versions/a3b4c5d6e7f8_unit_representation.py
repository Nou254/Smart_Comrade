"""module 004 — unit representation: unit_representatives, unit_networks,
unit_network_members, unit_coordination_messages, unit_discussions,
unit_announcements, unit_issues, unit_issue_escalations, unit_questions,
unit_question_responses, unit_shared_resources

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-22

Design decisions wired in:
  - Network archived when semester ends (read-only)
  - Rep replacement removes the outgoing rep silently (no notification)
  - Shared resources AI-scanned for unit relevance before publishing
  - Educational questions answered by AI within 5 minutes
  - Reps can raise questions on behalf of anonymous students
  - Non-reps see public issue summaries and outcomes

Table creation order (respects FKs):
  1. unit_representatives
  2. unit_networks
  3. unit_network_members
  4. unit_coordination_messages
  5. unit_discussions
  6. unit_announcements
  7. unit_issues
  8. unit_issue_escalations
  9. unit_questions
 10. unit_question_responses
 11. unit_shared_resources
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    ("unit_rep.view",          "View Unit Representatives",     "unit_representation"),
    ("unit_rep.appoint",       "Appoint Unit Representatives",  "unit_representation"),
    ("unit_network.view",      "View Unit Networks",            "unit_representation"),
    ("unit_network.post",      "Post in Unit Networks",         "unit_representation"),
    ("unit_issue.raise",       "Raise Unit Issues",             "unit_representation"),
    ("unit_issue.escalate",    "Escalate Unit Issues",          "unit_representation"),
    ("unit_question.pose",     "Pose Unit Questions",           "unit_representation"),
    ("unit_resource.share",    "Share Unit Resources",          "unit_representation"),
    ("unit_discussion.moderate", "Moderate Unit Discussions",   "unit_representation"),
    ("unit_analytics.view",    "View Unit Analytics",           "unit_representation"),
]

GRANTS: dict[str, list[str]] = {
    # Broad read — students see who represents them
    "unit_rep.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "group_leader", "group_secretary", "group_treasurer",
        "student",
    ],
    # Only Group Leaders appoint Unit Reps
    "unit_rep.appoint": ["group_leader"],
    # Network view — admins can see networks, members-only at service layer
    "unit_network.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
    ],
    # Network post — service layer verifies network membership
    "unit_network.post": [
        "super_admin", "school_representative", "group_leader",
    ],
    # Issue raise — service layer verifies active rep
    "unit_issue.raise": [
        "super_admin", "school_representative", "group_leader",
    ],
    # Issue escalate — service layer verifies rep or supervisor
    "unit_issue.escalate": [
        "super_admin", "school_representative", "group_leader",
    ],
    # Question pose — service layer verifies active rep
    "unit_question.pose": [
        "super_admin", "school_representative", "group_leader",
    ],
    # Resource share — service layer verifies active rep
    "unit_resource.share": [
        "super_admin", "school_representative", "group_leader",
    ],
    # Discussion moderation
    "unit_discussion.moderate": [
        "super_admin", "school_representative",
        "institution_representative", "assistant_institution_rep",
    ],
    # Analytics view
    "unit_analytics.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
    ],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _create_unit_representatives()
    _create_unit_networks()
    _create_unit_network_members()
    _create_unit_coordination_messages()
    _create_unit_discussions()
    _create_unit_announcements()
    _create_unit_issues()
    _create_unit_issue_escalations()
    _create_unit_questions()
    _create_unit_question_responses()
    _create_unit_shared_resources()
    _seed_permissions_and_grants()


# ─── 1. unit_representatives ─────────────────────────────────────────────

def _create_unit_representatives() -> None:
    op.create_table(
        "unit_representatives",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalized for fast queries
        sa.Column(
            "semester_id", sa.String(36),
            sa.ForeignKey("semesters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "appointed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("appointed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False,
            server_default="pending",
        ),
        sa.Column("term_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("term_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", sa.Text(), nullable=True),
        sa.Column(
            "replaced_by_id", sa.String(36),
            sa.ForeignKey("unit_representatives.id", ondelete="SET NULL"),
            nullable=True,
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
            "status IN ('pending','active','suspended','ended','replaced','resigned')",
            name="ck_unit_rep_status",
        ),
    )
    op.create_index("ix_unit_reps_group", "unit_representatives", ["group_id"])
    op.create_index("ix_unit_reps_user", "unit_representatives", ["user_id"])
    op.create_index(
        "ix_unit_reps_offering", "unit_representatives", ["unit_offering_id"],
    )
    op.create_index(
        "ix_unit_reps_semester", "unit_representatives", ["semester_id"],
    )
    op.create_index("ix_unit_reps_status", "unit_representatives", ["status"])
    # Only one ACTIVE rep per (group, offering)
    op.create_index(
        "uq_active_unit_rep_per_group_offering",
        "unit_representatives",
        ["group_id", "unit_offering_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


# ─── 2. unit_networks ────────────────────────────────────────────────────

def _create_unit_networks() -> None:
    op.create_table(
        "unit_networks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "semester_id", sa.String(36),
            sa.ForeignKey("semesters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supervisor_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "unit_offering_id", name="uq_unit_network_offering",
        ),
    )
    op.create_index(
        "ix_unit_networks_semester", "unit_networks", ["semester_id"],
    )
    op.create_index("ix_unit_networks_active", "unit_networks", ["is_active"])
    op.create_index(
        "ix_unit_networks_supervisor", "unit_networks", ["supervisor_user_id"],
    )


# ─── 3. unit_network_members ─────────────────────────────────────────────

def _create_unit_network_members() -> None:
    op.create_table(
        "unit_network_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "network_id", sa.String(36),
            sa.ForeignKey("unit_networks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable for supervisors/observers who aren't appointed reps
        sa.Column(
            "representative_id", sa.String(36),
            sa.ForeignKey("unit_representatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_in_network", sa.String(16), nullable=False,
            server_default="rep",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true(),
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_reason", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "role_in_network IN ('rep','supervisor','observer')",
            name="ck_unit_network_member_role",
        ),
        sa.UniqueConstraint(
            "network_id", "user_id", name="uq_unit_network_member_user",
        ),
    )
    op.create_index(
        "ix_unit_network_members_network", "unit_network_members", ["network_id"],
    )
    op.create_index(
        "ix_unit_network_members_user", "unit_network_members", ["user_id"],
    )
    op.create_index(
        "ix_unit_network_members_active", "unit_network_members", ["is_active"],
    )
    op.create_index(
        "ix_unit_network_members_rep", "unit_network_members",
        ["representative_id"],
    )


# ─── 4. unit_coordination_messages ───────────────────────────────────────

def _create_unit_coordination_messages() -> None:
    op.create_table(
        "unit_coordination_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "network_id", sa.String(36),
            sa.ForeignKey("unit_networks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "reply_to_id", sa.String(36),
            sa.ForeignKey("unit_coordination_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by", sa.String(36),
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
    )
    op.create_index(
        "ix_unit_coord_messages_network_created",
        "unit_coordination_messages",
        ["network_id", "created_at"],
    )
    op.create_index(
        "ix_unit_coord_messages_sender",
        "unit_coordination_messages", ["sender_id"],
    )


# ─── 5. unit_discussions ─────────────────────────────────────────────────

def _create_unit_discussions() -> None:
    op.create_table(
        "unit_discussions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id", sa.String(36),
            sa.ForeignKey("unit_discussions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "is_pinned", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_locked", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by", sa.String(36),
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
    )
    op.create_index(
        "ix_unit_discussions_offering_created",
        "unit_discussions",
        ["unit_offering_id", "created_at"],
    )
    op.create_index(
        "ix_unit_discussions_parent", "unit_discussions", ["parent_id"],
    )
    op.create_index(
        "ix_unit_discussions_author", "unit_discussions", ["author_id"],
    )
    op.create_index(
        "ix_unit_discussions_pinned", "unit_discussions", ["is_pinned"],
    )


# ─── 6. unit_announcements ───────────────────────────────────────────────

def _create_unit_announcements() -> None:
    op.create_table(
        "unit_announcements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "publisher_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("publisher_role", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "is_pinned", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_archived", sa.Boolean(), nullable=False,
            server_default=sa.false(),
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
            "publisher_role IN ('rep','supervisor','lecturer')",
            name="ck_unit_announcement_role",
        ),
    )
    op.create_index(
        "ix_unit_announcements_offering_created",
        "unit_announcements",
        ["unit_offering_id", "created_at"],
    )
    op.create_index(
        "ix_unit_announcements_publisher",
        "unit_announcements", ["publisher_id"],
    )
    op.create_index(
        "ix_unit_announcements_pinned", "unit_announcements", ["is_pinned"],
    )


# ─── 7. unit_issues ──────────────────────────────────────────────────────

def _create_unit_issues() -> None:
    op.create_table(
        "unit_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raised_by_representative_id", sa.String(36),
            sa.ForeignKey("unit_representatives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raised_by_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_anonymous", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("anonymous_student_reference", sa.String(128), nullable=True),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(24), nullable=False,
            server_default="identified",
        ),
        sa.Column(
            "current_escalation_level", sa.String(16), nullable=False,
            server_default="network",
        ),
        sa.Column(
            "current_escalation_target_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_public", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("public_summary", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('identified','under_network_discussion','escalated',"
            "'under_review','resolved','dismissed','withdrawn')",
            name="ck_unit_issue_status",
        ),
        sa.CheckConstraint(
            "category IN ('content','resource','scheduling','assessment',"
            "'practical','communication','other')",
            name="ck_unit_issue_category",
        ),
        sa.CheckConstraint(
            "current_escalation_level IN "
            "('none','network','supervisor','lecturer','school','institution')",
            name="ck_unit_issue_escalation_level",
        ),
    )
    op.create_index(
        "ix_unit_issues_offering_status",
        "unit_issues", ["unit_offering_id", "status"],
    )
    op.create_index("ix_unit_issues_public", "unit_issues", ["is_public"])
    op.create_index(
        "ix_unit_issues_raised_by",
        "unit_issues", ["raised_by_representative_id"],
    )
    op.create_index(
        "ix_unit_issues_raiser_user", "unit_issues", ["raised_by_user_id"],
    )


# ─── 8. unit_issue_escalations ───────────────────────────────────────────

def _create_unit_issue_escalations() -> None:
    op.create_table(
        "unit_issue_escalations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "issue_id", sa.String(36),
            sa.ForeignKey("unit_issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_level", sa.String(16), nullable=False),
        sa.Column("to_level", sa.String(16), nullable=False),
        sa.Column(
            "escalated_by_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "response_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_notes", sa.Text(), nullable=True),
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
        "ix_unit_issue_escalations_issue",
        "unit_issue_escalations", ["issue_id", "escalated_at"],
    )
    op.create_index(
        "ix_unit_issue_escalations_escalator",
        "unit_issue_escalations", ["escalated_by_user_id"],
    )


# ─── 9. unit_questions ───────────────────────────────────────────────────

def _create_unit_questions() -> None:
    op.create_table(
        "unit_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "raised_by_representative_id", sa.String(36),
            sa.ForeignKey("unit_representatives.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "raised_by_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_anonymous", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("anonymous_student_reference", sa.String(128), nullable=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "category", sa.String(24), nullable=False,
            server_default="educational",
        ),
        sa.Column(
            "status", sa.String(24), nullable=False,
            server_default="posed",
        ),
        sa.Column("posed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ai_response_deadline", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column("ai_responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supervisor_notified_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('posed','ai_researching','ai_responded',"
            "'supervisor_review','resolved','dismissed')",
            name="ck_unit_question_status",
        ),
        sa.CheckConstraint(
            "category IN ('educational','content_clarification',"
            "'resource_verification','assessment_format','other_educational')",
            name="ck_unit_question_category",
        ),
    )
    op.create_index(
        "ix_unit_questions_offering", "unit_questions", ["unit_offering_id"],
    )
    op.create_index("ix_unit_questions_status", "unit_questions", ["status"])
    op.create_index(
        "ix_unit_questions_raiser_user",
        "unit_questions", ["raised_by_user_id"],
    )
    op.create_index(
        "ix_unit_questions_rep", "unit_questions",
        ["raised_by_representative_id"],
    )


# ─── 10. unit_question_responses ─────────────────────────────────────────

def _create_unit_question_responses() -> None:
    op.create_table(
        "unit_question_responses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "question_id", sa.String(36),
            sa.ForeignKey("unit_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("responder_type", sa.String(16), nullable=False),
        sa.Column(
            "responder_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("research_sources_json", postgresql.JSONB, nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column(
            "superseded_by_response_id", sa.String(36),
            sa.ForeignKey("unit_question_responses.id", ondelete="SET NULL"),
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
            "responder_type IN ('ai','supervisor')",
            name="ck_unit_question_response_type",
        ),
    )
    op.create_index(
        "ix_unit_question_responses_question",
        "unit_question_responses", ["question_id", "created_at"],
    )


# ─── 11. unit_shared_resources ───────────────────────────────────────────

def _create_unit_shared_resources() -> None:
    op.create_table(
        "unit_shared_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "unit_offering_id", sa.String(36),
            sa.ForeignKey("unit_offerings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shared_by_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("file_url", sa.String(500), nullable=True),
        sa.Column("external_url", sa.String(500), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column(
            "visibility", sa.String(24), nullable=False,
            server_default="network_only",
        ),
        sa.Column(
            "ai_scan_status", sa.String(24), nullable=False,
            server_default="pending",
        ),
        sa.Column("ai_scan_confidence", sa.Float(), nullable=True),
        sa.Column("ai_scan_notes", sa.Text(), nullable=True),
        sa.Column("ai_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_published", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "resource_type IN ('document','link','note','code')",
            name="ck_unit_resource_type",
        ),
        sa.CheckConstraint(
            "visibility IN ('network_only','all_unit_students')",
            name="ck_unit_resource_visibility",
        ),
        sa.CheckConstraint(
            "ai_scan_status IN ('pending','scanning','verified_unit_match',"
            "'flagged_off_topic','failed')",
            name="ck_unit_resource_scan_status",
        ),
    )
    op.create_index(
        "ix_unit_shared_resources_offering",
        "unit_shared_resources", ["unit_offering_id"],
    )
    op.create_index(
        "ix_unit_shared_resources_published",
        "unit_shared_resources", ["is_published"],
    )
    op.create_index(
        "ix_unit_shared_resources_sharer",
        "unit_shared_resources", ["shared_by_user_id"],
    )
    op.create_index(
        "ix_unit_shared_resources_scan",
        "unit_shared_resources", ["ai_scan_status"],
    )


# ─── 12. permissions + grants ────────────────────────────────────────────

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
        for row in bind.execute(sa.text("SELECT code FROM permissions")).fetchall()
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
        for row in bind.execute(sa.text("SELECT code, id FROM roles")).fetchall()
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

    # Drop tables in reverse FK order

    op.drop_index(
        "ix_unit_shared_resources_scan",
        table_name="unit_shared_resources",
    )
    op.drop_index(
        "ix_unit_shared_resources_sharer",
        table_name="unit_shared_resources",
    )
    op.drop_index(
        "ix_unit_shared_resources_published",
        table_name="unit_shared_resources",
    )
    op.drop_index(
        "ix_unit_shared_resources_offering",
        table_name="unit_shared_resources",
    )
    op.drop_table("unit_shared_resources")

    op.drop_index(
        "ix_unit_question_responses_question",
        table_name="unit_question_responses",
    )
    op.drop_table("unit_question_responses")

    op.drop_index("ix_unit_questions_rep", table_name="unit_questions")
    op.drop_index(
        "ix_unit_questions_raiser_user", table_name="unit_questions",
    )
    op.drop_index("ix_unit_questions_status", table_name="unit_questions")
    op.drop_index("ix_unit_questions_offering", table_name="unit_questions")
    op.drop_table("unit_questions")

    op.drop_index(
        "ix_unit_issue_escalations_escalator",
        table_name="unit_issue_escalations",
    )
    op.drop_index(
        "ix_unit_issue_escalations_issue",
        table_name="unit_issue_escalations",
    )
    op.drop_table("unit_issue_escalations")

    op.drop_index("ix_unit_issues_raiser_user", table_name="unit_issues")
    op.drop_index("ix_unit_issues_raised_by", table_name="unit_issues")
    op.drop_index("ix_unit_issues_public", table_name="unit_issues")
    op.drop_index("ix_unit_issues_offering_status", table_name="unit_issues")
    op.drop_table("unit_issues")

    op.drop_index(
        "ix_unit_announcements_pinned", table_name="unit_announcements",
    )
    op.drop_index(
        "ix_unit_announcements_publisher", table_name="unit_announcements",
    )
    op.drop_index(
        "ix_unit_announcements_offering_created",
        table_name="unit_announcements",
    )
    op.drop_table("unit_announcements")

    op.drop_index(
        "ix_unit_discussions_pinned", table_name="unit_discussions",
    )
    op.drop_index(
        "ix_unit_discussions_author", table_name="unit_discussions",
    )
    op.drop_index(
        "ix_unit_discussions_parent", table_name="unit_discussions",
    )
    op.drop_index(
        "ix_unit_discussions_offering_created",
        table_name="unit_discussions",
    )
    op.drop_table("unit_discussions")

    op.drop_index(
        "ix_unit_coord_messages_sender",
        table_name="unit_coordination_messages",
    )
    op.drop_index(
        "ix_unit_coord_messages_network_created",
        table_name="unit_coordination_messages",
    )
    op.drop_table("unit_coordination_messages")

    op.drop_index(
        "ix_unit_network_members_rep", table_name="unit_network_members",
    )
    op.drop_index(
        "ix_unit_network_members_active", table_name="unit_network_members",
    )
    op.drop_index(
        "ix_unit_network_members_user", table_name="unit_network_members",
    )
    op.drop_index(
        "ix_unit_network_members_network", table_name="unit_network_members",
    )
    op.drop_table("unit_network_members")

    op.drop_index(
        "ix_unit_networks_supervisor", table_name="unit_networks",
    )
    op.drop_index("ix_unit_networks_active", table_name="unit_networks")
    op.drop_index("ix_unit_networks_semester", table_name="unit_networks")
    op.drop_table("unit_networks")

    # unit_representatives has a self-FK; drop indexes then table
    op.drop_index(
        "uq_active_unit_rep_per_group_offering",
        table_name="unit_representatives",
    )
    op.drop_index("ix_unit_reps_status", table_name="unit_representatives")
    op.drop_index("ix_unit_reps_semester", table_name="unit_representatives")
    op.drop_index("ix_unit_reps_offering", table_name="unit_representatives")
    op.drop_index("ix_unit_reps_user", table_name="unit_representatives")
    op.drop_index("ix_unit_reps_group", table_name="unit_representatives")
    op.drop_table("unit_representatives")