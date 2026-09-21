"""module 003 phase 10 — activity clubs

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-21

Creates 13 tables:
  - activity_clubs
  - activity_club_memberships
  - activity_club_positions
  - activity_club_milestones
  - activity_club_milestone_reports  (needs deferred FK back to milestones)
  - activity_club_election_cycles
  - activity_club_election_candidates
  - activity_club_election_votes
  - activity_club_position_approval_votes
  - activity_club_position_approval_ballots
  - activity_club_dissolution_events
  - activity_club_revival_petitions
  - activity_club_approval_events

Seeds:
  - 14 new permission codes for the club subsystem
  - grants to the appropriate roles
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    # (code, name, category)
    ("club.create", "Create an Activity Club", "club"),
    ("club.view", "View Activity Clubs", "club"),
    ("club.edit", "Edit Activity Club", "club"),
    ("club.approve", "Approve Activity Club Requests", "club"),
    ("club.member", "Join / Leave Activity Clubs", "club"),
    ("club.member.manage", "Manage Club Memberships", "club"),
    ("club.positions.manage", "Manage Club Positions", "club"),
    ("club.elections.manage", "Manage Club Elections", "club"),
    ("club.elections.vote", "Vote in Club Elections", "club"),
    ("club.milestones.manage", "Manage Club Milestones", "club"),
    ("club.milestones.review", "Review Club Milestone Reports", "club"),
    ("club.dissolve", "Dissolve an Activity Club", "club"),
    ("club.revive", "Revive a Dissolved Club", "club"),
    ("club.promote", "Promote a Club to County Level", "club"),
]


GRANTS: dict[str, list[str]] = {
    "club.create": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "school_representative",
        "group_leader", "student",
    ],
    "club.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "group_leader", "group_secretary", "group_treasurer",
        "unit_representative", "student",
    ],
    "club.edit": [
        "super_admin", "institution_representative",
        "school_representative", "group_leader",
    ],
    "club.approve": [
        "institution_representative", "assistant_institution_rep",
        "regional_admin", "super_admin",
    ],
    "club.member": [
        "student",
    ],
    "club.member.manage": [
        "group_leader", "school_representative",
        "institution_representative",
    ],
    "club.positions.manage": [
        "group_leader", "school_representative",
        "institution_representative",
    ],
    "club.elections.manage": [
        "group_leader", "school_representative",
        "institution_representative",
    ],
    "club.elections.vote": [
        "student", "group_leader", "school_representative",
    ],
    "club.milestones.manage": [
        "group_leader", "school_representative",
        "institution_representative",
    ],
    "club.milestones.review": [
        "institution_representative", "assistant_institution_rep",
        "regional_admin", "super_admin",
    ],
    "club.dissolve": [
        "super_admin", "regional_admin",
    ],
    "club.revive": [
        "regional_admin", "super_admin",
    ],
    "club.promote": [
        "institution_representative", "regional_admin", "super_admin",
    ],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _create_activity_clubs()
    _create_activity_club_memberships()
    _create_activity_club_positions()
    _create_activity_club_milestones()          # report_id FK added later
    _create_activity_club_milestone_reports()   # FK back to milestones
    _add_milestones_report_fk()                 # defer the FK addition
    _create_activity_club_election_cycles()
    _create_activity_club_election_candidates()
    _create_activity_club_election_votes()
    _create_activity_club_position_approval_votes()
    _create_activity_club_position_approval_ballots()
    _create_activity_club_dissolution_events()
    _create_activity_club_revival_petitions()
    _create_activity_club_approval_events()
    _seed_permissions_and_grants()


# ─── 1. activity_clubs ───────────────────────────────────────────────────

def _create_activity_clubs() -> None:
    op.create_table(
        "activity_clubs",
        sa.Column("id", sa.String(36), primary_key=True),

        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("motive", sa.Text(), nullable=False),

        sa.Column(
            "institution_id", sa.String(36),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "founder_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),

        sa.Column(
            "membership_visibility", sa.String(16),
            nullable=False, server_default="public",
        ),
        sa.Column(
            "current_level", sa.String(16),
            nullable=False, server_default="institution",
        ),

        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="forming",
        ),
        sa.Column("formed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("positions_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_cycle_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_to_county_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dissolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("halt_warning_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("halt_recovery_deadline", sa.DateTime(timezone=True), nullable=True),

        sa.Column(
            "approval_stage", sa.String(32),
            nullable=False, server_default="pending_institution_rep",
        ),
        sa.Column("institution_rep_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "institution_rep_approved_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("institution_rep_notes", sa.Text(), nullable=True),
        sa.Column("regional_rep_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "regional_rep_approved_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("regional_rep_notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),

        sa.Column("declared_term_months", sa.Integer(), nullable=True),
        sa.Column(
            "member_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "position_count", sa.Integer(),
            nullable=False, server_default="0",
        ),

        sa.Column("milestone_plan_json", postgresql.JSONB, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),

        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),

        sa.UniqueConstraint("slug", name="uq_club_slug"),
        sa.UniqueConstraint(
            "institution_id", "name",
            name="uq_club_institution_name",
        ),
        sa.CheckConstraint(
            "status IN ('forming','active','halted','dissolved','county')",
            name="ck_club_status",
        ),
        sa.CheckConstraint(
            "membership_visibility IN ('public','private')",
            name="ck_club_membership_visibility",
        ),
        sa.CheckConstraint(
            "current_level IN ('institution','county')",
            name="ck_club_level",
        ),
    )
    op.create_index("ix_clubs_institution", "activity_clubs", ["institution_id"])
    op.create_index("ix_clubs_status", "activity_clubs", ["status"])
    op.create_index("ix_clubs_level", "activity_clubs", ["current_level"])
    op.create_index("ix_clubs_founder", "activity_clubs", ["founder_id"])


# ─── 2. activity_club_memberships ────────────────────────────────────────

def _create_activity_club_memberships() -> None:
    op.create_table(
        "activity_club_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="active",
        ),
        sa.Column(
            "role", sa.String(16),
            nullable=False, server_default="member",
        ),
        sa.Column("request_message", sa.Text(), nullable=True),
        sa.Column(
            "approved_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_reason", sa.Text(), nullable=True),
        sa.Column("graduated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "club_id", "user_id",
            name="uq_club_membership",
        ),
        sa.CheckConstraint(
            "status IN ('pending','active','suspended','left','removed',"
            "'alumni_readonly')",
            name="ck_club_membership_status",
        ),
        sa.CheckConstraint(
            "role IN ('member','leader','officer')",
            name="ck_club_membership_role",
        ),
    )
    op.create_index("ix_club_memberships_club", "activity_club_memberships", ["club_id"])
    op.create_index("ix_club_memberships_user", "activity_club_memberships", ["user_id"])
    op.create_index("ix_club_memberships_status", "activity_club_memberships", ["status"])


# ─── 3. activity_club_positions ──────────────────────────────────────────

def _create_activity_club_positions() -> None:
    op.create_table(
        "activity_club_positions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position_code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "position_type", sa.String(16),
            nullable=False, server_default="standard",
        ),
        sa.Column(
            "display_order", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "introduced_in_cycle", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "introduced_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("retired_in_cycle", sa.Integer(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "retired_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="active",
        ),
        sa.Column(
            "current_holder_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("current_term_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_term_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "club_id", "position_code",
            name="uq_club_position_code",
        ),
        sa.CheckConstraint(
            "position_type IN ('standard','custom')",
            name="ck_club_position_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','retired')",
            name="ck_club_position_status",
        ),
        sa.CheckConstraint(
            "introduced_in_cycle >= 0",
            name="ck_club_position_introduced_cycle",
        ),
    )
    op.create_index("ix_club_positions_club", "activity_club_positions", ["club_id"])
    op.create_index("ix_club_positions_status", "activity_club_positions", ["status"])


# ─── 4. activity_club_milestones (FK to reports added later) ─────────────

def _create_activity_club_milestones() -> None:
    op.create_table(
        "activity_club_milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("target_metric", sa.String(200), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("target_unit", sa.String(64), nullable=True),
        sa.Column(
            "status", sa.String(24),
            nullable=False, server_default="declared",
        ),
        # report_id column but no FK yet — added after reports table exists
        sa.Column("report_id", sa.String(36), nullable=True),
        sa.Column(
            "declared_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('declared','active','report_pending','reported',"
            "'evaluated','missed')",
            name="ck_club_milestone_status",
        ),
    )
    op.create_index("ix_club_milestones_club", "activity_club_milestones", ["club_id"])
    op.create_index("ix_club_milestones_status", "activity_club_milestones", ["status"])
    op.create_index("ix_club_milestones_period_end", "activity_club_milestones", ["period_end"])


# ─── 5. activity_club_milestone_reports ──────────────────────────────────

def _create_activity_club_milestone_reports() -> None:
    op.create_table(
        "activity_club_milestone_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "milestone_id", sa.String(36),
            sa.ForeignKey("activity_club_milestones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actual_value", sa.Float(), nullable=True),
        sa.Column("actual_unit", sa.String(64), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=False),
        sa.Column("completion_pdf_url", sa.String(500), nullable=False),
        sa.Column("completion_pdf_hash", sa.String(128), nullable=True),
        sa.Column("supporting_urls_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "status", sa.String(32),
            nullable=False, server_default="submitted",
        ),
        sa.Column(
            "submitted_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "institution_rep_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("institution_rep_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("institution_rep_notes", sa.Text(), nullable=True),
        sa.Column("institution_rep_report_url", sa.String(500), nullable=True),
        sa.Column(
            "regional_rep_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("regional_rep_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("regional_rep_notes", sa.Text(), nullable=True),
        sa.Column("cc_county_rep_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cc_super_admin_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('submitted','institution_approved','institution_rejected',"
            "'regional_forwarded','closed')",
            name="ck_club_milestone_report_status",
        ),
    )
    op.create_index(
        "ix_club_milestone_reports_club", "activity_club_milestone_reports", ["club_id"],
    )
    op.create_index(
        "ix_club_milestone_reports_milestone",
        "activity_club_milestone_reports", ["milestone_id"],
    )
    op.create_index(
        "ix_club_milestone_reports_status",
        "activity_club_milestone_reports", ["status"],
    )


# ─── 6. Add the deferred FK from milestones.report_id ────────────────────

def _add_milestones_report_fk() -> None:
    op.create_foreign_key(
        "fk_club_milestones_report_id",
        "activity_club_milestones",
        "activity_club_milestone_reports",
        ["report_id"],
        ["id"],
        ondelete="SET NULL",
    )


# ─── 7. activity_club_election_cycles ────────────────────────────────────

def _create_activity_club_election_cycles() -> None:
    op.create_table(
        "activity_club_election_cycles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(24),
            nullable=False, server_default="draft",
        ),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("positions_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results_declared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "election_fee_paid", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "election_fee_amount", sa.Integer(),
            nullable=False, server_default="200",
        ),
        sa.Column("election_fee_reference", sa.String(128), nullable=True),
        sa.Column("election_fee_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("election_fee_method", sa.String(16), nullable=True),
        sa.Column("term_months", sa.Integer(), nullable=True),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("halt_warning_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("halt_recovery_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("club_id", "cycle_number", name="uq_club_cycle_number"),
        sa.CheckConstraint(
            "status IN ('draft','positions_published','candidates_open',"
            "'voting','closed','verified','completed','failed','halted')",
            name="ck_club_cycle_status",
        ),
    )
    op.create_index("ix_club_cycles_club", "activity_club_election_cycles", ["club_id"])
    op.create_index("ix_club_cycles_status", "activity_club_election_cycles", ["status"])


# ─── 8. activity_club_election_candidates ────────────────────────────────

def _create_activity_club_election_candidates() -> None:
    op.create_table(
        "activity_club_election_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "cycle_id", sa.String(36),
            sa.ForeignKey("activity_club_election_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id", sa.String(36),
            sa.ForeignKey("activity_club_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("manifesto", sa.Text(), nullable=True),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="nominated",
        ),
        sa.Column("nominated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "votes_count", sa.Integer(),
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
            "cycle_id", "position_id", "user_id",
            name="uq_club_candidate",
        ),
        sa.CheckConstraint(
            "status IN ('nominated','qualified','withdrawn','disqualified',"
            "'winner','lost')",
            name="ck_club_candidate_status",
        ),
    )
    op.create_index("ix_club_candidates_cycle", "activity_club_election_candidates", ["cycle_id"])
    op.create_index("ix_club_candidates_position", "activity_club_election_candidates", ["position_id"])
    op.create_index("ix_club_candidates_user", "activity_club_election_candidates", ["user_id"])


# ─── 9. activity_club_election_votes ─────────────────────────────────────

def _create_activity_club_election_votes() -> None:
    op.create_table(
        "activity_club_election_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "cycle_id", sa.String(36),
            sa.ForeignKey("activity_club_election_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id", sa.String(36),
            sa.ForeignKey("activity_club_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id", sa.String(36),
            sa.ForeignKey("activity_club_election_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voter_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cast_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vote_hash", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "cycle_id", "position_id", "voter_id",
            name="uq_club_vote_per_position",
        ),
    )
    op.create_index("ix_club_votes_cycle", "activity_club_election_votes", ["cycle_id"])
    op.create_index("ix_club_votes_position", "activity_club_election_votes", ["position_id"])
    op.create_index("ix_club_votes_voter", "activity_club_election_votes", ["voter_id"])


# ─── 10. activity_club_position_approval_votes ───────────────────────────

def _create_activity_club_position_approval_votes() -> None:
    op.create_table(
        "activity_club_position_approval_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cycle_id", sa.String(36),
            sa.ForeignKey("activity_club_election_cycles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_position_id", sa.String(36),
            sa.ForeignKey("activity_club_positions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("proposal_type", sa.String(24), nullable=False),
        sa.Column("proposed_code", sa.String(64), nullable=True),
        sa.Column("proposed_title", sa.String(160), nullable=True),
        sa.Column("proposed_description", sa.Text(), nullable=True),
        sa.Column("retirement_reason", sa.Text(), nullable=True),
        sa.Column(
            "proposed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="proposed",
        ),
        sa.Column(
            "votes_for", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "votes_against", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "required_threshold", sa.Float(),
            nullable=False, server_default="0.6666666666666666",
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "proposal_type IN ('add_custom','retire_position')",
            name="ck_club_position_approval_type",
        ),
        sa.CheckConstraint(
            "status IN ('proposed','approved','rejected','expired')",
            name="ck_club_position_approval_status",
        ),
    )
    op.create_index(
        "ix_club_pos_approval_club",
        "activity_club_position_approval_votes", ["club_id"],
    )
    op.create_index(
        "ix_club_pos_approval_cycle",
        "activity_club_position_approval_votes", ["cycle_id"],
    )
    op.create_index(
        "ix_club_pos_approval_status",
        "activity_club_position_approval_votes", ["status"],
    )


# ─── 11. activity_club_position_approval_ballots ─────────────────────────

def _create_activity_club_position_approval_ballots() -> None:
    op.create_table(
        "activity_club_position_approval_ballots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "proposal_id", sa.String(36),
            sa.ForeignKey(
                "activity_club_position_approval_votes.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "voter_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vote", sa.String(8), nullable=False),
        sa.Column("cast_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "proposal_id", "voter_id",
            name="uq_club_position_approval_ballot",
        ),
        sa.CheckConstraint(
            "vote IN ('yes','no')",
            name="ck_club_position_approval_ballot_vote",
        ),
    )
    op.create_index(
        "ix_club_pos_approval_ballot_proposal",
        "activity_club_position_approval_ballots", ["proposal_id"],
    )


# ─── 12. activity_club_dissolution_events ────────────────────────────────

def _create_activity_club_dissolution_events() -> None:
    op.create_table(
        "activity_club_dissolution_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "triggered_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "trigger IN ('failed_election','halted_recovery_expired',"
            "'admin_dissolved','other')",
            name="ck_club_dissolution_trigger",
        ),
    )
    op.create_index("ix_club_dissolution_club", "activity_club_dissolution_events", ["club_id"])


# ─── 13. activity_club_revival_petitions ─────────────────────────────────

def _create_activity_club_revival_petitions() -> None:
    op.create_table(
        "activity_club_revival_petitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dissolution_event_id", sa.String(36),
            sa.ForeignKey(
                "activity_club_dissolution_events.id", ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "filed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("letter_text", sa.Text(), nullable=False),
        sa.Column("supporting_urls_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="filed",
        ),
        sa.Column(
            "reviewed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("cc_institution_admin_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cc_county_admin_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "members_reinstated_count", sa.Integer(),
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
        sa.CheckConstraint(
            "status IN ('filed','under_review','approved','rejected')",
            name="ck_club_revival_status",
        ),
    )
    op.create_index("ix_club_revival_club", "activity_club_revival_petitions", ["club_id"])
    op.create_index("ix_club_revival_status", "activity_club_revival_petitions", ["status"])


# ─── 14. activity_club_approval_events ───────────────────────────────────

def _create_activity_club_approval_events() -> None:
    op.create_table(
        "activity_club_approval_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "club_id", sa.String(36),
            sa.ForeignKey("activity_clubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "actor_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_state", sa.String(32), nullable=True),
        sa.Column("to_state", sa.String(32), nullable=True),
        sa.Column("details_json", postgresql.JSONB, nullable=True),
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
            "event_type IN ("
            "'club.created','club.institution_rep_approved',"
            "'club.institution_rep_rejected','club.regional_rep_approved',"
            "'club.regional_rep_rejected',"
            "'club.positions_published','club.first_cycle_initiated',"
            "'club.election_fee_paid','club.cycle_completed',"
            "'club.cycle_failed','club.halted','club.dissolved',"
            "'club.revival_petition_filed','club.revival_approved',"
            "'club.revival_rejected','club.revived','club.promoted',"
            "'club.milestone_report_submitted',"
            "'club.milestone_report_institution_approved',"
            "'club.milestone_report_institution_rejected',"
            "'club.milestone_report_regional_forwarded',"
            "'club.milestone_report_closed',"
            "'club.position_approval_proposed',"
            "'club.position_approval_decided',"
            "'club.founder_removed'"
            ")",
            name="ck_club_approval_event_type",
        ),
    )
    op.create_index(
        "ix_club_approval_events_club", "activity_club_approval_events", ["club_id"],
    )
    op.create_index(
        "ix_club_approval_events_type", "activity_club_approval_events", ["event_type"],
    )


# ─── 15. permissions + grants ────────────────────────────────────────────

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
        for row in bind.execute(sa.text("SELECT code, id FROM permissions")).fetchall()
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
    # Delete permissions we added
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

    # Drop FK first
    op.drop_constraint(
        "fk_club_milestones_report_id",
        "activity_club_milestones",
        type_="foreignkey",
    )

    # Drop tables in reverse dependency order
    op.drop_index(
        "ix_club_approval_events_type", table_name="activity_club_approval_events",
    )
    op.drop_index(
        "ix_club_approval_events_club", table_name="activity_club_approval_events",
    )
    op.drop_table("activity_club_approval_events")

    op.drop_index("ix_club_revival_status", table_name="activity_club_revival_petitions")
    op.drop_index("ix_club_revival_club", table_name="activity_club_revival_petitions")
    op.drop_table("activity_club_revival_petitions")

    op.drop_index(
        "ix_club_dissolution_club", table_name="activity_club_dissolution_events",
    )
    op.drop_table("activity_club_dissolution_events")

    op.drop_index(
        "ix_club_pos_approval_ballot_proposal",
        table_name="activity_club_position_approval_ballots",
    )
    op.drop_table("activity_club_position_approval_ballots")

    op.drop_index(
        "ix_club_pos_approval_status",
        table_name="activity_club_position_approval_votes",
    )
    op.drop_index(
        "ix_club_pos_approval_cycle",
        table_name="activity_club_position_approval_votes",
    )
    op.drop_index(
        "ix_club_pos_approval_club",
        table_name="activity_club_position_approval_votes",
    )
    op.drop_table("activity_club_position_approval_votes")

    op.drop_index("ix_club_votes_voter", table_name="activity_club_election_votes")
    op.drop_index("ix_club_votes_position", table_name="activity_club_election_votes")
    op.drop_index("ix_club_votes_cycle", table_name="activity_club_election_votes")
    op.drop_table("activity_club_election_votes")

    op.drop_index("ix_club_candidates_user", table_name="activity_club_election_candidates")
    op.drop_index("ix_club_candidates_position", table_name="activity_club_election_candidates")
    op.drop_index("ix_club_candidates_cycle", table_name="activity_club_election_candidates")
    op.drop_table("activity_club_election_candidates")

    op.drop_index("ix_club_cycles_status", table_name="activity_club_election_cycles")
    op.drop_index("ix_club_cycles_club", table_name="activity_club_election_cycles")
    op.drop_table("activity_club_election_cycles")

    op.drop_index(
        "ix_club_milestone_reports_status",
        table_name="activity_club_milestone_reports",
    )
    op.drop_index(
        "ix_club_milestone_reports_milestone",
        table_name="activity_club_milestone_reports",
    )
    op.drop_index(
        "ix_club_milestone_reports_club",
        table_name="activity_club_milestone_reports",
    )
    op.drop_table("activity_club_milestone_reports")

    op.drop_index(
        "ix_club_milestones_period_end", table_name="activity_club_milestones",
    )
    op.drop_index("ix_club_milestones_status", table_name="activity_club_milestones")
    op.drop_index("ix_club_milestones_club", table_name="activity_club_milestones")
    op.drop_table("activity_club_milestones")

    op.drop_index("ix_club_positions_status", table_name="activity_club_positions")
    op.drop_index("ix_club_positions_club", table_name="activity_club_positions")
    op.drop_table("activity_club_positions")

    op.drop_index(
        "ix_club_memberships_status", table_name="activity_club_memberships",
    )
    op.drop_index(
        "ix_club_memberships_user", table_name="activity_club_memberships",
    )
    op.drop_index(
        "ix_club_memberships_club", table_name="activity_club_memberships",
    )
    op.drop_table("activity_club_memberships")

    op.drop_index("ix_clubs_founder", table_name="activity_clubs")
    op.drop_index("ix_clubs_level", table_name="activity_clubs")
    op.drop_index("ix_clubs_status", table_name="activity_clubs")
    op.drop_index("ix_clubs_institution", table_name="activity_clubs")
    op.drop_table("activity_clubs")