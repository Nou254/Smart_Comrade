"""module 003 phase 9 — impeachment

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-21

Creates:
  - impeachment_cases
  - impeachment_petitions
  - impeachment_sessions
  - impeachment_votes

Includes the verdict-voting-control columns added in the follow-up fix:
  - impeachment_cases.verdict_voting_opened_at
  - impeachment_cases.verdict_voting_opened_by
  - impeachment_cases.verdict_voting_closed_at
  - impeachment_cases.verdict_voting_closed_by

Seeds:
  - 3 new permission codes for the impeachment subsystem
  - grants to the appropriate roles
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    # (code, name, category)
    ("impeachment.file", "File an Impeachment Case", "impeachment"),
    ("impeachment.manage", "Manage Impeachment Hearings", "impeachment"),
    ("impeachment.vote", "Vote on Impeachment Verdict", "impeachment"),
]


GRANTS: dict[str, list[str]] = {
    "impeachment.file": [
        "super_admin", "regional_admin",
        "county_representative", "institution_representative",
        "school_representative", "group_leader",
    ],
    "impeachment.manage": [
        "super_admin", "regional_admin",
        "county_representative", "institution_representative",
    ],
    "impeachment.vote": [
        # Voting is enforced at the service layer by committee membership,
        # but the permission code still exists so the UI can gate the button.
        "super_admin", "regional_admin",
        "county_representative", "institution_representative",
        "school_representative", "group_leader",
    ],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _create_impeachment_cases_table()
    _create_impeachment_petitions_table()
    _create_impeachment_sessions_table()
    _create_impeachment_votes_table()
    _seed_permissions_and_grants()


# ─── 1. impeachment_cases ────────────────────────────────────────────────

def _create_impeachment_cases_table() -> None:
    op.create_table(
        "impeachment_cases",
        sa.Column("id", sa.String(36), primary_key=True),

        # --- Target ---
        sa.Column(
            "target_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_role_code", sa.String(64), nullable=False),
        sa.Column("target_level", sa.String(16), nullable=False),
        sa.Column("constituency_id", sa.String(36), nullable=False),

        # --- Filing ---
        sa.Column(
            "filed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column(
            "filed_at", sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("grounds", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB, nullable=True),

        sa.Column(
            "status", sa.String(32),
            nullable=False, server_default="filed",
        ),

        # --- Reconciliation ---
        sa.Column(
            "reconciliation_attempted_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "reconciliation_mediator_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reconciliation_outcome", sa.String(32), nullable=True),
        sa.Column("reconciliation_notes", sa.Text(), nullable=True),

        # --- Petition ---
        sa.Column(
            "petition_required_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "petition_signature_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "petition_reached_at",
            sa.DateTime(timezone=True), nullable=True,
        ),

        # --- Committee ---
        sa.Column("committee_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "committee_size", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "committee_formed_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "committee_locked", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "initializer_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # --- Hearing ---
        sa.Column(
            "hearing_started_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "hearing_completed_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "hearing_is_live_streamed", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "hearing_is_closed", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),

        # --- Verdict voting control (added in fix) ---
        sa.Column(
            "verdict_voting_opened_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "verdict_voting_opened_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "verdict_voting_closed_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "verdict_voting_closed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # --- Verdict ---
        sa.Column("verdict", sa.String(24), nullable=True),
        sa.Column(
            "verdict_votes_for", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "verdict_votes_against", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "verdict_threshold", sa.Float(),
            nullable=False, server_default="0.6666666666666666",
        ),
        sa.Column(
            "verdict_at", sa.DateTime(timezone=True), nullable=True,
        ),

        # --- Post-removal ---
        sa.Column(
            "disclosure_period_ends_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "removal_effective_at",
            sa.DateTime(timezone=True), nullable=True,
        ),

        # --- Replacement election ---
        sa.Column(
            "replacement_election_id", sa.String(36),
            sa.ForeignKey("elections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "replacement_winner_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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

        # --- Checks ---
        sa.CheckConstraint(
            "target_level IN ('school','institution','county')",
            name="ck_impeachment_target_level",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'filed','reconciliation','petition','petition_failed',"
            "'dismissed_via_reconciliation','committee_forming','hearing',"
            "'verdict_removed','verdict_reinstated','disclosure_period',"
            "'replacement_election','resolved_removed','resolved_reinstated',"
            "'withdrawn'"
            ")",
            name="ck_impeachment_status",
        ),
    )

    op.create_index("ix_impeachment_status", "impeachment_cases", ["status"])
    op.create_index("ix_impeachment_target", "impeachment_cases", ["target_user_id"])
    op.create_index(
        "ix_impeachment_constituency", "impeachment_cases",
        ["target_level", "constituency_id"],
    )


# ─── 2. impeachment_petitions ────────────────────────────────────────────

def _create_impeachment_petitions_table() -> None:
    op.create_table(
        "impeachment_petitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id", sa.String(36),
            sa.ForeignKey("impeachment_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signer_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signed_at", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "signature_hash", sa.String(128), nullable=False,
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

        sa.UniqueConstraint(
            "case_id", "signer_id",
            name="uq_impeachment_petition_signer",
        ),
    )
    op.create_index(
        "ix_impeachment_petition_case", "impeachment_petitions", ["case_id"],
    )
    op.create_index(
        "ix_impeachment_petition_signer", "impeachment_petitions", ["signer_id"],
    )


# ─── 3. impeachment_sessions ─────────────────────────────────────────────

def _create_impeachment_sessions_table() -> None:
    op.create_table(
        "impeachment_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id", sa.String(36),
            sa.ForeignKey("impeachment_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_number", sa.Integer(), nullable=False),
        sa.Column("session_type", sa.String(16), nullable=False),

        sa.Column(
            "scheduled_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True,
        ),

        sa.Column(
            "is_live_streamed", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "is_closed", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),

        # --- AI-assisted transcription ---
        sa.Column("audio_url", sa.String(500), nullable=True),
        sa.Column("audio_hash", sa.String(128), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column(
            "transcript_generated_at",
            sa.DateTime(timezone=True), nullable=True,
        ),

        # --- Minutes ---
        sa.Column("minutes_text", sa.Text(), nullable=True),
        sa.Column(
            "minutes_finalized_at",
            sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "minutes_finalized_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),

        sa.Column(
            "status", sa.String(16),
            nullable=False, server_default="scheduled",
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

        sa.UniqueConstraint(
            "case_id", "session_number",
            name="uq_impeachment_session_number",
        ),
        sa.CheckConstraint(
            "session_type IN ('accusation','evidence','defense','verdict')",
            name="ck_impeachment_session_type",
        ),
        sa.CheckConstraint(
            "session_number BETWEEN 1 AND 4",
            name="ck_impeachment_session_number_range",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','in_progress','completed','adjourned')",
            name="ck_impeachment_session_status",
        ),
    )
    op.create_index(
        "ix_impeachment_session_case", "impeachment_sessions", ["case_id"],
    )


# ─── 4. impeachment_votes ────────────────────────────────────────────────

def _create_impeachment_votes_table() -> None:
    op.create_table(
        "impeachment_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id", sa.String(36),
            sa.ForeignKey("impeachment_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "voter_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vote", sa.String(8), nullable=False),
        sa.Column(
            "cast_at", sa.DateTime(timezone=True), nullable=False,
        ),
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
            "case_id", "voter_id",
            name="uq_impeachment_vote",
        ),
        sa.CheckConstraint(
            "vote IN ('remove','keep')",
            name="ck_impeachment_vote_value",
        ),
    )
    op.create_index(
        "ix_impeachment_vote_case", "impeachment_votes", ["case_id"],
    )
    op.create_index(
        "ix_impeachment_vote_voter", "impeachment_votes", ["voter_id"],
    )


# ─── 5. permissions + grants ─────────────────────────────────────────────

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
    # Remove the permissions we added
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
    op.drop_index("ix_impeachment_vote_voter", table_name="impeachment_votes")
    op.drop_index("ix_impeachment_vote_case", table_name="impeachment_votes")
    op.drop_table("impeachment_votes")

    op.drop_index(
        "ix_impeachment_session_case", table_name="impeachment_sessions",
    )
    op.drop_table("impeachment_sessions")

    op.drop_index(
        "ix_impeachment_petition_signer", table_name="impeachment_petitions",
    )
    op.drop_index(
        "ix_impeachment_petition_case", table_name="impeachment_petitions",
    )
    op.drop_table("impeachment_petitions")

    op.drop_index(
        "ix_impeachment_constituency", table_name="impeachment_cases",
    )
    op.drop_index("ix_impeachment_target", table_name="impeachment_cases")
    op.drop_index("ix_impeachment_status", table_name="impeachment_cases")
    op.drop_table("impeachment_cases")