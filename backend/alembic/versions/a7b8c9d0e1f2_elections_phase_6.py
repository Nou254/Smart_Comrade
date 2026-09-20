"""module 003 phase 6 — elections, disputes, appeals, reschedules

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-20

Creates:
  - elections
  - election_positions
  - election_tickets
  - election_candidates
  - election_voter_roll
  - election_approval_votes
  - election_ballots
  - election_results
  - election_disputes
  - election_appeals
  - election_reschedules
  - election_no_payer_events
  - election_audit_events

Alters:
  - groups       : + election_pending_runoff, under_regional_admin
  - institutions : + under_regional_admin
  - counties     : + under_regional_admin

Seeds:
  - 5 new permission codes for the election subsystem
  - grants to the appropriate roles
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    # (code, name, category)
    ("election.view", "View Election", "election"),
    ("election.create", "Create Election", "election"),
    ("election.manage", "Manage Election Lifecycle", "election"),
    ("election.reschedule.request", "Request Election Reschedule", "election"),
    ("election.reschedule.approve", "Approve Election Reschedule", "election"),
]


GRANTS: dict[str, list[str]] = {
    "election.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "group_leader", "group_secretary", "group_treasurer",
        "unit_representative", "student",
    ],
    "election.create": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "school_representative",
        "group_leader",
    ],
    "election.manage": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "school_representative",
    ],
    "election.reschedule.request": [
        "school_representative",
        "institution_representative", "assistant_institution_rep",
        "county_representative",
    ],
    "election.reschedule.approve": [
        "regional_admin",
        "super_admin",
    ],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _extend_existing_tables()
    _create_elections_table()
    _create_election_positions_table()
    _create_election_tickets_table()
    _create_election_candidates_table()
    _create_election_voter_roll_table()
    _create_election_approval_votes_table()
    _create_election_ballots_table()
    _create_election_results_table()
    _create_election_disputes_table()
    _create_election_appeals_table()
    _create_election_reschedules_table()
    _create_election_no_payer_events_table()
    _create_election_audit_events_table()
    _seed_permissions_and_grants()


# ─── 1. Extend existing tables ────────────────────────────────────────────

def _extend_existing_tables() -> None:
    # groups
    op.add_column(
        "groups",
        sa.Column(
            "election_pending_runoff", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.add_column(
        "groups",
        sa.Column(
            "under_regional_admin", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.alter_column("groups", "election_pending_runoff", server_default=None)
    op.alter_column("groups", "under_regional_admin", server_default=None)

    # institutions
    op.add_column(
        "institutions",
        sa.Column(
            "under_regional_admin", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_institutions_under_regional_admin",
        "institutions", ["under_regional_admin"],
    )
    op.alter_column("institutions", "under_regional_admin", server_default=None)

    # counties
    op.add_column(
        "counties",
        sa.Column(
            "under_regional_admin", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_counties_under_regional_admin",
        "counties", ["under_regional_admin"],
    )
    op.alter_column("counties", "under_regional_admin", server_default=None)


# ─── 2. elections ─────────────────────────────────────────────────────────

def _create_elections_table() -> None:
    op.create_table(
        "elections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("constituency_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="draft"),

        sa.Column("election_day", sa.Date(), nullable=False),
        sa.Column("nomination_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nomination_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_vote_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ballot_finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voting_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_declared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("appeal_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dashboard_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "voting_duration_minutes", sa.Integer(),
            nullable=False, server_default="1440",
        ),

        sa.Column(
            "electorate_size", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "votes_cast", sa.Integer(),
            nullable=False, server_default="0",
        ),

        sa.Column(
            "is_runoff", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("parent_election_id", sa.String(36), nullable=True),

        sa.Column("live_stream_url", sa.String(500), nullable=True),
        sa.Column("stream_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stream_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspense_until", sa.DateTime(timezone=True), nullable=True),

        sa.Column("rescheduled_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rescheduled_reason", sa.Text(), nullable=True),

        sa.Column(
            "under_regional_admin", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),

        sa.Column(
            "created_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
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

        sa.ForeignKeyConstraint(
            ["parent_election_id"], ["elections.id"], ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "level IN ('group','school','institution','county')",
            name="ck_election_level",
        ),
        sa.CheckConstraint(
            "state IN ("
            "'draft','scheduled','nominating','nominational_voting',"
            "'payment_window','awaiting_payment','regional_admin_interim',"
            "'ballot_finalized','campaigning','voting','counting',"
            "'suspense_blackout','result_declared',"
            "'run_off_scheduled','run_off_voting',"
            "'appeal_window','appealed','disputed','completed'"
            ")",
            name="ck_election_state",
        ),
    )
    op.create_index("ix_elections_level", "elections", ["level"])
    op.create_index("ix_elections_state", "elections", ["state"])
    op.create_index("ix_elections_constituency", "elections", ["level", "constituency_id"])
    op.create_index("ix_elections_election_day", "elections", ["election_day"])
    op.create_index("ix_elections_parent", "elections", ["parent_election_id"])


# ─── 3. election_positions ────────────────────────────────────────────────

def _create_election_positions_table() -> None:
    op.create_table(
        "election_positions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position_code", sa.String(40), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_paired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paired_with_code", sa.String(40), nullable=True),
        sa.Column("max_candidates", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("seats_available", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "required_approval_percentage", sa.Float(),
            nullable=False, server_default="15.0",
        ),
        sa.Column("nomination_fee", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),

        sa.Column("winner_ticket_id", sa.String(36), nullable=True),
        sa.Column("winner_candidate_id", sa.String(36), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),

        sa.UniqueConstraint(
            "election_id", "position_code",
            name="uq_election_position_code",
        ),
        sa.CheckConstraint(
            "position_code IN ("
            "'group_leader','group_secretary','group_treasurer',"
            "'school_representative','assistant_school_rep',"
            "'institution_representative','assistant_institution_rep',"
            "'county_representative','assistant_county_rep'"
            ")",
            name="ck_election_position_code",
        ),
        sa.CheckConstraint(
            "status IN ('pending','open','closed','filled','vacant')",
            name="ck_election_position_status",
        ),
    )
    op.create_index("ix_election_positions_election", "election_positions", ["election_id"])


# ─── 4. election_tickets ──────────────────────────────────────────────────

def _create_election_tickets_table() -> None:
    op.create_table(
        "election_tickets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "primary_position_id", sa.String(36),
            sa.ForeignKey("election_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("slogan", sa.String(255), nullable=True),
        sa.Column("color", sa.String(16), nullable=True),
        sa.Column("ballot_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="pending_approval",
        ),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fee_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "total_approval_votes", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "total_votes_cast", sa.Integer(),
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
            "status IN ("
            "'pending_approval','qualified','withdrawn',"
            "'disqualified','winner','runner_up','lost','tied'"
            ")",
            name="ck_election_ticket_status",
        ),
    )
    op.create_index("ix_election_tickets_election", "election_tickets", ["election_id"])
    op.create_index(
        "ix_election_tickets_position", "election_tickets", ["primary_position_id"],
    )


# ─── 5. election_candidates ───────────────────────────────────────────────

def _create_election_candidates_table() -> None:
    op.create_table(
        "election_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticket_id", sa.String(36),
            sa.ForeignKey("election_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id", sa.String(36),
            sa.ForeignKey("election_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("manifesto", sa.Text(), nullable=True),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.Column("nominated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "approval_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "approval_percentage", sa.Float(),
            nullable=False, server_default="0.0",
        ),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fee_paid", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("fee_payment_reference", sa.String(128), nullable=True),
        sa.Column("fee_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="pending",
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
            "election_id", "user_id", "position_id",
            name="uq_election_candidate_user_position",
        ),
        sa.CheckConstraint(
            "status IN ('pending','qualified','withdrawn','disqualified')",
            name="ck_election_candidate_status",
        ),
    )
    op.create_index("ix_election_candidates_election", "election_candidates", ["election_id"])
    op.create_index("ix_election_candidates_ticket", "election_candidates", ["ticket_id"])
    op.create_index("ix_election_candidates_position", "election_candidates", ["position_id"])
    op.create_index("ix_election_candidates_user", "election_candidates", ["user_id"])
    op.create_index("ix_election_candidates_status", "election_candidates", ["status"])


# ─── 6. election_voter_roll ───────────────────────────────────────────────

def _create_election_voter_roll_table() -> None:
    op.create_table(
        "election_voter_roll",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "eligible", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "has_voted", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("voted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "election_id", "user_id",
            name="uq_election_voter_roll",
        ),
    )
    op.create_index(
        "ix_election_voter_roll_election", "election_voter_roll", ["election_id"],
    )
    op.create_index(
        "ix_election_voter_roll_user", "election_voter_roll", ["user_id"],
    )
    op.create_index(
        "ix_election_voter_roll_has_voted", "election_voter_roll", ["has_voted"],
    )


# ─── 7. election_approval_votes ───────────────────────────────────────────

def _create_election_approval_votes_table() -> None:
    op.create_table(
        "election_approval_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id", sa.String(36),
            sa.ForeignKey("election_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voter_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
            "election_id", "candidate_id", "voter_id",
            name="uq_election_approval_vote",
        ),
    )
    op.create_index(
        "ix_election_approval_votes_election", "election_approval_votes", ["election_id"],
    )
    op.create_index(
        "ix_election_approval_votes_candidate", "election_approval_votes", ["candidate_id"],
    )
    op.create_index(
        "ix_election_approval_votes_voter", "election_approval_votes", ["voter_id"],
    )


# ─── 8. election_ballots ──────────────────────────────────────────────────

def _create_election_ballots_table() -> None:
    op.create_table(
        "election_ballots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id", sa.String(36),
            sa.ForeignKey("election_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticket_id", sa.String(36),
            sa.ForeignKey("election_tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voter_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cast_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vote_hash", sa.String(128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "election_id", "position_id", "voter_id",
            name="uq_election_ballot",
        ),
    )
    op.create_index("ix_election_ballots_election", "election_ballots", ["election_id"])
    op.create_index("ix_election_ballots_position", "election_ballots", ["position_id"])
    op.create_index("ix_election_ballots_ticket", "election_ballots", ["ticket_id"])
    op.create_index("ix_election_ballots_voter", "election_ballots", ["voter_id"])


# ─── 9. election_results ──────────────────────────────────────────────────

def _create_election_results_table() -> None:
    op.create_table(
        "election_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_id", sa.String(36),
            sa.ForeignKey("election_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("winner_ticket_id", sa.String(36), nullable=True),
        sa.Column("winner_candidate_id", sa.String(36), nullable=True),
        sa.Column(
            "total_valid_votes", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "total_invalid_votes", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "winner_vote_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column("runner_up_ticket_id", sa.String(36), nullable=True),
        sa.Column(
            "runner_up_vote_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column("margin", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "is_tie", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column("tie_ticket_ids", postgresql.JSONB, nullable=True),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "verified_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "official", sa.Boolean(),
            nullable=False, server_default=sa.true(),
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
        sa.ForeignKeyConstraint(
            ["winner_ticket_id"], ["election_tickets.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["winner_candidate_id"], ["election_candidates.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["runner_up_ticket_id"], ["election_tickets.id"], ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "election_id", "position_id",
            name="uq_election_result_position",
        ),
    )
    op.create_index("ix_election_results_election", "election_results", ["election_id"])


# ─── 10. election_disputes ────────────────────────────────────────────────

def _create_election_disputes_table() -> None:
    op.create_table(
        "election_disputes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "filed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grounds", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "assigned_to", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hearing_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hearing_link", sa.String(500), nullable=True),
        sa.Column("hearing_held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column(
            "verdict_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("verdict_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(24),
            nullable=False, server_default="filed",
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
            "status IN ("
            "'filed','under_review','hearing_scheduled','hearing_held',"
            "'verdict_issued','resolved','dismissed'"
            ")",
            name="ck_election_dispute_status",
        ),
    )
    op.create_index("ix_election_disputes_election", "election_disputes", ["election_id"])


# ─── 11. election_appeals ─────────────────────────────────────────────────

def _create_election_appeals_table() -> None:
    op.create_table(
        "election_appeals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "filed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grounds", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB, nullable=True),
        sa.Column("committee_json", postgresql.JSONB, nullable=True),
        sa.Column("committee_formed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hearing_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hearing_link", sa.String(500), nullable=True),
        sa.Column("hearing_held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("verdict_by_json", postgresql.JSONB, nullable=True),
        sa.Column("verdict_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column(
            "status", sa.String(24),
            nullable=False, server_default="filed",
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
            "status IN ("
            "'filed','committee_assembled','hearing_scheduled',"
            "'hearing_held','verdict_issued','resolved','dismissed'"
            ")",
            name="ck_election_appeal_status",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('confirmed','overturned','run_off_required')",
            name="ck_election_appeal_outcome",
        ),
    )
    op.create_index("ix_election_appeals_election", "election_appeals", ["election_id"])


# ─── 12. election_reschedules ─────────────────────────────────────────────

def _create_election_reschedules_table() -> None:
    op.create_table(
        "election_reschedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "approved_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("old_election_day", sa.Date(), nullable=False),
        sa.Column("new_election_day", sa.Date(), nullable=False),
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
        "ix_election_reschedules_election", "election_reschedules", ["election_id"],
    )


# ─── 13. election_no_payer_events ─────────────────────────────────────────

def _create_election_no_payer_events_table() -> None:
    op.create_table(
        "election_no_payer_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
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
            "phase IN ("
            "'interim_started','extended_window_started',"
            "'extended_window_expired','super_admin_assigned'"
            ")",
            name="ck_election_no_payer_phase",
        ),
    )
    op.create_index(
        "ix_election_no_payer_events_election",
        "election_no_payer_events", ["election_id"],
    )


# ─── 14. election_audit_events ────────────────────────────────────────────

def _create_election_audit_events_table() -> None:
    op.create_table(
        "election_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="CASCADE"),
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
        "ix_election_audit_events_election", "election_audit_events", ["election_id"],
    )
    op.create_index(
        "ix_election_audit_events_actor", "election_audit_events", ["actor_id"],
    )
    op.create_index(
        "ix_election_audit_events_type", "election_audit_events", ["event_type"],
    )


# ─── 15. permissions + grants ─────────────────────────────────────────────

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
    # Delete the permissions we added
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

    # Drop election tables (reverse order to respect FK)
    op.drop_index("ix_election_audit_events_type", table_name="election_audit_events")
    op.drop_index("ix_election_audit_events_actor", table_name="election_audit_events")
    op.drop_index("ix_election_audit_events_election", table_name="election_audit_events")
    op.drop_table("election_audit_events")

    op.drop_index(
        "ix_election_no_payer_events_election",
        table_name="election_no_payer_events",
    )
    op.drop_table("election_no_payer_events")

    op.drop_index(
        "ix_election_reschedules_election", table_name="election_reschedules",
    )
    op.drop_table("election_reschedules")

    op.drop_index("ix_election_appeals_election", table_name="election_appeals")
    op.drop_table("election_appeals")

    op.drop_index("ix_election_disputes_election", table_name="election_disputes")
    op.drop_table("election_disputes")

    op.drop_index("ix_election_results_election", table_name="election_results")
    op.drop_table("election_results")

    op.drop_index("ix_election_ballots_voter", table_name="election_ballots")
    op.drop_index("ix_election_ballots_ticket", table_name="election_ballots")
    op.drop_index("ix_election_ballots_position", table_name="election_ballots")
    op.drop_index("ix_election_ballots_election", table_name="election_ballots")
    op.drop_table("election_ballots")

    op.drop_index(
        "ix_election_approval_votes_voter", table_name="election_approval_votes",
    )
    op.drop_index(
        "ix_election_approval_votes_candidate", table_name="election_approval_votes",
    )
    op.drop_index(
        "ix_election_approval_votes_election", table_name="election_approval_votes",
    )
    op.drop_table("election_approval_votes")

    op.drop_index(
        "ix_election_voter_roll_has_voted", table_name="election_voter_roll",
    )
    op.drop_index("ix_election_voter_roll_user", table_name="election_voter_roll")
    op.drop_index("ix_election_voter_roll_election", table_name="election_voter_roll")
    op.drop_table("election_voter_roll")

    op.drop_index("ix_election_candidates_status", table_name="election_candidates")
    op.drop_index("ix_election_candidates_user", table_name="election_candidates")
    op.drop_index("ix_election_candidates_position", table_name="election_candidates")
    op.drop_index("ix_election_candidates_ticket", table_name="election_candidates")
    op.drop_index("ix_election_candidates_election", table_name="election_candidates")
    op.drop_table("election_candidates")

    op.drop_index("ix_election_tickets_position", table_name="election_tickets")
    op.drop_index("ix_election_tickets_election", table_name="election_tickets")
    op.drop_table("election_tickets")

    op.drop_index("ix_election_positions_election", table_name="election_positions")
    op.drop_table("election_positions")

    op.drop_index("ix_elections_parent", table_name="elections")
    op.drop_index("ix_elections_election_day", table_name="elections")
    op.drop_index("ix_elections_constituency", table_name="elections")
    op.drop_index("ix_elections_state", table_name="elections")
    op.drop_index("ix_elections_level", table_name="elections")
    op.drop_table("elections")

    # Revert extension columns
    op.drop_index("ix_counties_under_regional_admin", table_name="counties")
    op.drop_column("counties", "under_regional_admin")

    op.drop_index("ix_institutions_under_regional_admin", table_name="institutions")
    op.drop_column("institutions", "under_regional_admin")

    op.drop_column("groups", "under_regional_admin")
    op.drop_column("groups", "election_pending_runoff")