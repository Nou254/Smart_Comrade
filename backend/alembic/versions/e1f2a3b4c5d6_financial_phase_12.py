"""module 012 — financial: subscriptions, transactions, invoices, receipts,
refund_requests, event_advertisements, reconciliation_batches,
financial_audit_log, financial_notifications

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-21

Also:
  - Adds users.timezone
  - Creates a minimal events stub table (owned by Module 009 later)
  - Seeds 8 permission codes for the financial subsystem

Table creation order (respects FKs):
  1. events (stub)
  2. transactions
  3. subscriptions
  4. invoices
  5. receipts
  6. refund_requests
  7. event_advertisements
  8. reconciliation_batches
  9. financial_audit_log
 10. financial_notifications
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


# ============================================================================
# PERMISSIONS
# ============================================================================

NEW_PERMISSIONS: list[tuple[str, str, str]] = [
    ("financial.view", "View Own Financial Records", "financial"),
    ("financial.manage", "Manage Financial Records", "financial"),
    ("financial.refund.request", "Request a Refund", "financial"),
    ("financial.refund.approve", "Approve Refund Requests", "financial"),
    ("financial.reconcile", "Run Reconciliation Batches", "financial"),
    ("financial.reports.view", "View Financial Reports", "financial"),
    ("financial.config.manage", "Configure Financial Settings", "financial"),
    ("financial.webhook.receive", "Receive Payment Webhooks", "financial"),
]

GRANTS: dict[str, list[str]] = {
    "financial.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative", "assistant_institution_rep",
        "school_representative", "assistant_school_rep",
        "group_leader", "group_secretary", "group_treasurer",
        "student",
    ],
    "financial.manage": ["super_admin"],
    "financial.refund.request": [
        "student", "group_leader", "group_secretary", "group_treasurer",
        "school_representative", "institution_representative",
        "county_representative",
    ],
    "financial.refund.approve": ["super_admin"],
    "financial.reconcile": ["super_admin"],
    "financial.reports.view": [
        "super_admin", "regional_admin", "county_representative",
        "institution_representative",
    ],
    "financial.config.manage": ["super_admin"],
    "financial.webhook.receive": ["super_admin"],
}


# ============================================================================
# UPGRADE
# ============================================================================

def upgrade() -> None:
    _add_user_timezone()
    _create_events_stub()
    _create_transactions()          # no FKs to later tables
    _create_subscriptions()         # FK to transactions
    _create_invoices()
    _create_receipts()
    _create_refund_requests()
    _create_event_advertisements()
    _create_reconciliation_batches()
    _create_financial_audit_log()
    _create_financial_notifications()
    _seed_permissions_and_grants()


# ─── users.timezone ──────────────────────────────────────────────────────

def _add_user_timezone() -> None:
    op.add_column(
        "users",
        sa.Column(
            "timezone", sa.String(64),
            nullable=False, server_default="Africa/Nairobi",
        ),
    )
    # Drop the server default after backfill so the model default takes over.
    op.alter_column("users", "timezone", server_default=None)


# ─── events stub (owned by Module 009 later) ─────────────────────────────

def _create_events_stub() -> None:
    """
    Minimal events table so event_advertisements.event_id has a valid FK
    target. Module 009 will extend this with the full schema when it lands.
    """
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False, server_default="group"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
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
        sa.CheckConstraint(
            "scope IN ('group','school','institution','county','regional','national')",
            name="ck_events_stub_scope",
        ),
    )
    op.create_index("ix_events_stub_scope", "events", ["scope"])
    op.create_index("ix_events_stub_status", "events", ["status"])


# ─── 1. transactions ─────────────────────────────────────────────────────
# Created before subscriptions because subscriptions.last_renewal_transaction_id
# has an FK to transactions.id.

def _create_transactions() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "payer_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "payer_group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("transaction_type", sa.String(40), nullable=False),
        sa.Column("related_object_type", sa.String(32), nullable=True),
        sa.Column("related_object_id", sa.String(36), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("provider", sa.String(16), nullable=False, server_default="mpesa"),
        sa.Column("provider_reference", sa.String(128), nullable=True),
        sa.Column("provider_payload", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="initiated"),
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("is_refunded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("refund_held", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("refund_held_reason", sa.Text(), nullable=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "provider IN ('mpesa','card','bank','manual')",
            name="ck_txn_provider",
        ),
        sa.CheckConstraint(
            "status IN ('initiated','awaiting_payment','pending_provider',"
            "'successful','failed','timeout','expired','settled',"
            "'refunded','cancelled')",
            name="ck_txn_status",
        ),
    )
    op.create_index("ix_txn_payer_user", "transactions", ["payer_user_id"])
    op.create_index("ix_txn_payer_group", "transactions", ["payer_group_id"])
    op.create_index("ix_txn_status", "transactions", ["status"])
    op.create_index("ix_txn_type", "transactions", ["transaction_type"])
    op.create_index("ix_txn_related", "transactions",
                    ["related_object_type", "related_object_id"])
    op.create_index("ix_txn_provider_ref", "transactions", ["provider_reference"])
    op.create_index("ix_txn_grace_ends", "transactions", ["grace_ends_at"])


# ─── 2. subscriptions ────────────────────────────────────────────────────

def _create_subscriptions() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscriber_type", sa.String(16), nullable=False),
        sa.Column(
            "group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("plan_type", sa.String(16), nullable=False, server_default="monthly"),

        sa.Column("base_amount", sa.Integer(), nullable=False),
        sa.Column("extra_member_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("member_count_at_payment", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("status", sa.String(16), nullable=False, server_default="trial"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiring_warning_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("solo_access_window_ends_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("preferred_provider", sa.String(16), nullable=False, server_default="mpesa"),
        sa.Column(
            "last_renewal_transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("renewal_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("charge_hour_local", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("next_charge_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pre_charge_notice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("card_failure_count", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "subscriber_type IN ('group','solo')",
            name="ck_sub_subscriber_type",
        ),
        sa.CheckConstraint(
            "plan_type IN ('monthly','yearly')",
            name="ck_sub_plan_type",
        ),
        sa.CheckConstraint(
            "status IN ('trial','active','expiring','grace','expired','suspended','cancelled')",
            name="ck_sub_status",
        ),
        sa.CheckConstraint(
            "(subscriber_type = 'group' AND group_id IS NOT NULL) OR "
            "(subscriber_type = 'solo' AND user_id IS NOT NULL)",
            name="ck_sub_subscriber_binding",
        ),
        sa.CheckConstraint(
            "preferred_provider IN ('mpesa','card','bank','manual')",
            name="ck_sub_preferred_provider",
        ),
    )
    op.create_index("ix_subs_group", "subscriptions", ["group_id"])
    op.create_index("ix_subs_user", "subscriptions", ["user_id"])
    op.create_index("ix_subs_status", "subscriptions", ["status"])
    op.create_index("ix_subs_period_end", "subscriptions", ["period_end"])
    op.create_index("ix_subs_next_charge", "subscriptions", ["next_charge_at_utc"])


# ─── 3. invoices ─────────────────────────────────────────────────────────

def _create_invoices() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_number", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "payer_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "payer_group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("line_items_json", postgresql.JSONB, nullable=False),
        sa.Column("subtotal", sa.Integer(), nullable=False),
        sa.Column("tax", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(16), nullable=False, server_default="issued"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_reason", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "status IN ('draft','issued','paid','void','refunded')",
            name="ck_invoice_status",
        ),
    )
    op.create_index("ix_invoice_status", "invoices", ["status"])
    op.create_index("ix_invoice_payer_user", "invoices", ["payer_user_id"])
    op.create_index("ix_invoice_payer_group", "invoices", ["payer_group_id"])


# ─── 4. receipts ─────────────────────────────────────────────────────────

def _create_receipts() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("receipt_number", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "invoice_id", sa.String(36),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "payer_user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "payer_group_id", sa.String(36),
            sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("payment_method", sa.String(16), nullable=False),
        sa.Column("provider_reference", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="issued"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_reason", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "status IN ('issued','void','refunded')",
            name="ck_receipt_status",
        ),
    )
    op.create_index("ix_receipt_status", "receipts", ["status"])
    op.create_index("ix_receipt_payer_user", "receipts", ["payer_user_id"])
    op.create_index("ix_receipt_payer_group", "receipts", ["payer_group_id"])


# ─── 5. refund_requests ──────────────────────────────────────────────────

def _create_refund_requests() -> None:
    op.create_table(
        "refund_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "requested_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_type", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB, nullable=True),
        sa.Column("amount_requested", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column("status", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column(
            "reviewed_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("provider_refund_reference", sa.String(128), nullable=True),
        sa.Column("provider_refund_payload", postgresql.JSONB, nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("held_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("held_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "reason_type IN ('duplicate','admin_override')",
            name="ck_refund_reason_type",
        ),
        sa.CheckConstraint(
            "status IN ('submitted','approved','rejected','processing',"
            "'completed','failed','held_card_expired')",
            name="ck_refund_status",
        ),
    )
    op.create_index("ix_refund_txn", "refund_requests", ["transaction_id"])
    op.create_index("ix_refund_status", "refund_requests", ["status"])
    op.create_index("ix_refund_requested_by", "refund_requests", ["requested_by"])


# ─── 6. event_advertisements ─────────────────────────────────────────────

def _create_event_advertisements() -> None:
    op.create_table(
        "event_advertisements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_id", sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("monthly_fee", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="KES"),
        sa.Column(
            "initial_transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "last_renewal_transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_payment"),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "scope IN ('public','county','national')",
            name="ck_event_ad_scope",
        ),
        sa.CheckConstraint(
            "status IN ('pending_payment','active','expired','paused','cancelled')",
            name="ck_event_ad_status",
        ),
    )
    op.create_index("ix_event_ad_event", "event_advertisements", ["event_id"])
    op.create_index("ix_event_ad_status", "event_advertisements", ["status"])
    op.create_index("ix_event_ad_period_end", "event_advertisements", ["current_period_end"])


# ─── 7. reconciliation_batches ───────────────────────────────────────────

def _create_reconciliation_batches() -> None:
    op.create_table(
        "reconciliation_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("batch_reference", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("total_transactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_in_provider_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mismatched_amount_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unclaimed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flagged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "run_by", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("report_pdf_url", sa.String(500), nullable=True),
        sa.Column("details_json", postgresql.JSONB, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "provider IN ('mpesa','card','bank','manual')",
            name="ck_recon_provider",
        ),
    )
    op.create_index("ix_recon_provider", "reconciliation_batches", ["provider"])
    op.create_index("ix_recon_status", "reconciliation_batches", ["status"])


# ─── 8. financial_audit_log ──────────────────────────────────────────────

def _create_financial_audit_log() -> None:
    op.create_table(
        "financial_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "actor_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "subscription_id", sa.String(36),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "refund_request_id", sa.String(36),
            sa.ForeignKey("refund_requests.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("from_state", sa.String(32), nullable=True),
        sa.Column("to_state", sa.String(32), nullable=True),
        sa.Column("details_json", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_fin_audit_txn", "financial_audit_log", ["transaction_id"])
    op.create_index("ix_fin_audit_subscription", "financial_audit_log", ["subscription_id"])
    op.create_index("ix_fin_audit_refund", "financial_audit_log", ["refund_request_id"])
    op.create_index("ix_fin_audit_event_type", "financial_audit_log", ["event_type"])
    op.create_index("ix_fin_audit_actor", "financial_audit_log", ["actor_id"])


# ─── 9. financial_notifications ──────────────────────────────────────────

def _create_financial_notifications() -> None:
    op.create_table(
        "financial_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "transaction_id", sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "subscription_id", sa.String(36),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("scheduled_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_local_hour", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("local_timezone", sa.String(64), nullable=False,
                  server_default="Africa/Nairobi"),
        sa.Column("delivered_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_urgent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deferred_from_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("now()")),

        sa.CheckConstraint(
            "channel IN ('in_app','email','sms')",
            name="ck_fin_notif_channel",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('pending','delivered','failed',"
            "'held_sleep_window','cancelled')",
            name="ck_fin_notif_delivery_status",
        ),
    )
    op.create_index("ix_fin_notif_user", "financial_notifications", ["user_id"])
    op.create_index("ix_fin_notif_status", "financial_notifications", ["delivery_status"])
    op.create_index("ix_fin_notif_scheduled", "financial_notifications", ["scheduled_at_utc"])
    op.create_index("ix_fin_notif_txn", "financial_notifications", ["transaction_id"])
    op.create_index("ix_fin_notif_sub", "financial_notifications", ["subscription_id"])


# ─── 10. permissions + grants ────────────────────────────────────────────

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

    # Drop tables in reverse FK order (dependent tables first)
    op.drop_index("ix_fin_notif_sub", table_name="financial_notifications")
    op.drop_index("ix_fin_notif_txn", table_name="financial_notifications")
    op.drop_index("ix_fin_notif_scheduled", table_name="financial_notifications")
    op.drop_index("ix_fin_notif_status", table_name="financial_notifications")
    op.drop_index("ix_fin_notif_user", table_name="financial_notifications")
    op.drop_table("financial_notifications")

    op.drop_index("ix_fin_audit_actor", table_name="financial_audit_log")
    op.drop_index("ix_fin_audit_event_type", table_name="financial_audit_log")
    op.drop_index("ix_fin_audit_refund", table_name="financial_audit_log")
    op.drop_index("ix_fin_audit_subscription", table_name="financial_audit_log")
    op.drop_index("ix_fin_audit_txn", table_name="financial_audit_log")
    op.drop_table("financial_audit_log")

    op.drop_index("ix_recon_status", table_name="reconciliation_batches")
    op.drop_index("ix_recon_provider", table_name="reconciliation_batches")
    op.drop_table("reconciliation_batches")

    op.drop_index("ix_event_ad_period_end", table_name="event_advertisements")
    op.drop_index("ix_event_ad_status", table_name="event_advertisements")
    op.drop_index("ix_event_ad_event", table_name="event_advertisements")
    op.drop_table("event_advertisements")

    op.drop_index("ix_refund_requested_by", table_name="refund_requests")
    op.drop_index("ix_refund_status", table_name="refund_requests")
    op.drop_index("ix_refund_txn", table_name="refund_requests")
    op.drop_table("refund_requests")

    op.drop_index("ix_receipt_payer_group", table_name="receipts")
    op.drop_index("ix_receipt_payer_user", table_name="receipts")
    op.drop_index("ix_receipt_status", table_name="receipts")
    op.drop_table("receipts")

    op.drop_index("ix_invoice_payer_group", table_name="invoices")
    op.drop_index("ix_invoice_payer_user", table_name="invoices")
    op.drop_index("ix_invoice_status", table_name="invoices")
    op.drop_table("invoices")

    # subscriptions depends on transactions, drop it first
    op.drop_index("ix_subs_next_charge", table_name="subscriptions")
    op.drop_index("ix_subs_period_end", table_name="subscriptions")
    op.drop_index("ix_subs_status", table_name="subscriptions")
    op.drop_index("ix_subs_user", table_name="subscriptions")
    op.drop_index("ix_subs_group", table_name="subscriptions")
    op.drop_table("subscriptions")

    # now transactions can be dropped
    op.drop_index("ix_txn_grace_ends", table_name="transactions")
    op.drop_index("ix_txn_provider_ref", table_name="transactions")
    op.drop_index("ix_txn_related", table_name="transactions")
    op.drop_index("ix_txn_type", table_name="transactions")
    op.drop_index("ix_txn_status", table_name="transactions")
    op.drop_index("ix_txn_payer_group", table_name="transactions")
    op.drop_index("ix_txn_payer_user", table_name="transactions")
    op.drop_table("transactions")

    op.drop_index("ix_events_stub_status", table_name="events")
    op.drop_index("ix_events_stub_scope", table_name="events")
    op.drop_table("events")

    op.drop_column("users", "timezone")