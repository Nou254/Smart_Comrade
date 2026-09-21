"""
Financial models — Module 012.

Single source of truth for all money in Smart Comrade.

Core principles:
  - No wallet balances. The platform never holds money.
  - Provider-agnostic. M-Pesa, card, bank all abstracted.
  - Every transaction is auditable. Never silently modified.
  - Idempotent. Duplicate webhooks are no-ops.
  - Refunds only for duplicates (or admin override, audited).
  - Payment happens AFTER approval (state-first, pay-to-continue).

Grace periods:
  - Group trial                     : 14 days
  - Solo trial                      : 14 days
  - Group expiring warning          : 10 days
  - Solo expiring warning           : 5 days
  - Group lapse grace               : 3 days
  - Solo access window              : 5 days
  - Group → solo exit grace         : 14 days
  - One-time fee grace (all others) : 3 days

Notification pipeline:
  - All timestamps stored in UTC
  - All scheduling respects user's local timezone
  - Default delivery hour: 10:00 local
  - Sleep window: 21:00–07:00 local (defer non-urgent to 07:00)
  - Card users receive SMS + in-app
  - M-Pesa group members receive in-app
  - M-Pesa group leaders receive in-app + email
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


# ── constants ────────────────────────────────────────────────────────────

# Subscriber types
SUBSCRIBER_GROUP = "group"
SUBSCRIBER_SOLO = "solo"

# Subscription plans
PLAN_MONTHLY = "monthly"
PLAN_YEARLY = "yearly"

# Subscription states
SUB_TRIAL = "trial"
SUB_ACTIVE = "active"
SUB_EXPIRING = "expiring"
SUB_GRACE = "grace"
SUB_EXPIRED = "expired"
SUB_SUSPENDED = "suspended"
SUB_CANCELLED = "cancelled"

# Transaction types (17 total fee types)
TXN_GROUP_SUBSCRIPTION = "group_subscription"
TXN_GROUP_SUBSCRIPTION_ANNUAL = "group_subscription_annual"
TXN_SOLO_SUBSCRIPTION = "solo_subscription"
TXN_SOLO_SUBSCRIPTION_ANNUAL = "solo_subscription_annual"
TXN_EXTRA_MEMBER_FEE = "extra_member_fee"
TXN_EVENT_AD_PUBLIC = "event_advertisement_public"
TXN_EVENT_AD_COUNTY = "event_advertisement_county"
TXN_EVENT_AD_NATIONAL = "event_advertisement_national"
TXN_NOMINATION_SCHOOL = "nomination_fee_school"
TXN_NOMINATION_INSTITUTION = "nomination_fee_institution"
TXN_NOMINATION_COUNTY = "nomination_fee_county"
TXN_CLUB_ELECTION_FEE = "club_election_fee"
TXN_CLUB_PROMOTION_FEE = "club_promotion_fee"
TXN_TRANSFER_ORDINARY = "transfer_fee_ordinary"
TXN_TRANSFER_ELECTED = "transfer_fee_elected"
TXN_GROUP_TO_SOLO_EXIT = "group_to_solo_exit_fee"
TXN_GROUP_LEADER_VACANCY = "group_leader_vacancy_fee"

ALL_TRANSACTION_TYPES = (
    TXN_GROUP_SUBSCRIPTION,
    TXN_GROUP_SUBSCRIPTION_ANNUAL,
    TXN_SOLO_SUBSCRIPTION,
    TXN_SOLO_SUBSCRIPTION_ANNUAL,
    TXN_EXTRA_MEMBER_FEE,
    TXN_EVENT_AD_PUBLIC,
    TXN_EVENT_AD_COUNTY,
    TXN_EVENT_AD_NATIONAL,
    TXN_NOMINATION_SCHOOL,
    TXN_NOMINATION_INSTITUTION,
    TXN_NOMINATION_COUNTY,
    TXN_CLUB_ELECTION_FEE,
    TXN_CLUB_PROMOTION_FEE,
    TXN_TRANSFER_ORDINARY,
    TXN_TRANSFER_ELECTED,
    TXN_GROUP_TO_SOLO_EXIT,
    TXN_GROUP_LEADER_VACANCY,
)

# Fee amounts (KES)
FEE_AMOUNTS: dict[str, int] = {
    TXN_GROUP_SUBSCRIPTION: 100,
    TXN_GROUP_SUBSCRIPTION_ANNUAL: 900,
    TXN_SOLO_SUBSCRIPTION: 50,
    TXN_SOLO_SUBSCRIPTION_ANNUAL: 500,
    TXN_EXTRA_MEMBER_FEE: 20,
    TXN_EVENT_AD_PUBLIC: 200,
    TXN_EVENT_AD_COUNTY: 500,
    TXN_EVENT_AD_NATIONAL: 700,
    TXN_NOMINATION_SCHOOL: 100,
    TXN_NOMINATION_INSTITUTION: 200,
    TXN_NOMINATION_COUNTY: 350,
    TXN_CLUB_ELECTION_FEE: 200,
    TXN_CLUB_PROMOTION_FEE: 250,
    TXN_TRANSFER_ORDINARY: 20,
    TXN_TRANSFER_ELECTED: 90,
    TXN_GROUP_TO_SOLO_EXIT: 70,
    TXN_GROUP_LEADER_VACANCY: 70,
}

# Grace periods (days)
GROUP_TRIAL_DAYS = 14
SOLO_TRIAL_DAYS = 14
GROUP_EXPIRING_WARNING_DAYS = 10
SOLO_EXPIRING_WARNING_DAYS = 5
GROUP_LAPSE_GRACE_DAYS = 3
SOLO_ACCESS_WINDOW_DAYS = 5
GROUP_TO_SOLO_EXIT_GRACE_DAYS = 14
ONE_TIME_FEE_GRACE_DAYS = 3

# Extra-member fee cap
EXTRA_MEMBER_FEE_CAP = 500

# Transaction states
TXN_INITIATED = "initiated"
TXN_AWAITING_PAYMENT = "awaiting_payment"
TXN_PENDING_PROVIDER = "pending_provider"
TXN_SUCCESSFUL = "successful"
TXN_FAILED = "failed"
TXN_TIMEOUT = "timeout"
TXN_EXPIRED = "expired"
TXN_SETTLED = "settled"
TXN_REFUNDED = "refunded"
TXN_CANCELLED = "cancelled"

ALL_TXN_STATES = (
    TXN_INITIATED,
    TXN_AWAITING_PAYMENT,
    TXN_PENDING_PROVIDER,
    TXN_SUCCESSFUL,
    TXN_FAILED,
    TXN_TIMEOUT,
    TXN_EXPIRED,
    TXN_SETTLED,
    TXN_REFUNDED,
    TXN_CANCELLED,
)

# Payment providers
PROVIDER_MPESA = "mpesa"
PROVIDER_CARD = "card"
PROVIDER_BANK = "bank"
PROVIDER_MANUAL = "manual"

ALL_PROVIDERS = (PROVIDER_MPESA, PROVIDER_CARD, PROVIDER_BANK, PROVIDER_MANUAL)

# Refund reasons
REFUND_DUPLICATE = "duplicate"
REFUND_ADMIN_OVERRIDE = "admin_override"

# Refund states
REFUND_SUBMITTED = "submitted"
REFUND_APPROVED = "approved"
REFUND_REJECTED = "rejected"
REFUND_PROCESSING = "processing"
REFUND_COMPLETED = "completed"
REFUND_FAILED = "failed"
REFUND_HELD = "held_card_expired"     # card expired, needs manual intervention

ALL_REFUND_STATES = (
    REFUND_SUBMITTED,
    REFUND_APPROVED,
    REFUND_REJECTED,
    REFUND_PROCESSING,
    REFUND_COMPLETED,
    REFUND_FAILED,
    REFUND_HELD,
)

# Event ad scopes
EVENT_SCOPE_PUBLIC = "public"
EVENT_SCOPE_COUNTY = "county"
EVENT_SCOPE_NATIONAL = "national"

ALL_EVENT_SCOPES = (EVENT_SCOPE_PUBLIC, EVENT_SCOPE_COUNTY, EVENT_SCOPE_NATIONAL)

# Event ad states
EVENT_AD_PENDING = "pending_payment"
EVENT_AD_ACTIVE = "active"
EVENT_AD_EXPIRED = "expired"
EVENT_AD_PAUSED = "paused"
EVENT_AD_CANCELLED = "cancelled"

ALL_EVENT_AD_STATES = (
    EVENT_AD_PENDING,
    EVENT_AD_ACTIVE,
    EVENT_AD_EXPIRED,
    EVENT_AD_PAUSED,
    EVENT_AD_CANCELLED,
)

# Notification categories
NOTIF_TRIAL_ENDING = "trial_ending"
NOTIF_TRIAL_ENDED = "trial_ended"
NOTIF_PRE_CHARGE_D7 = "pre_charge_notice_d7"
NOTIF_PRE_CHARGE_D3 = "pre_charge_notice_d3"
NOTIF_PRE_CHARGE_D1 = "pre_charge_notice_d1"
NOTIF_CHARGE_SUCCESS = "charge_success"
NOTIF_CHARGE_FAILED = "charge_failed"
NOTIF_EXPIRING_SOON = "expiring_soon"
NOTIF_RENEWAL_REMINDER = "renewal_reminder"
NOTIF_EXPIRY_DAY = "expiry_day"
NOTIF_GRACE_STARTED = "grace_started"
NOTIF_GRACE_MID = "grace_mid"
NOTIF_GRACE_ENDING = "grace_ending"
NOTIF_READ_ONLY = "read_only_entered"
NOTIF_PAYMENT_SUCCESS = "payment_success"
NOTIF_PAYMENT_FAILURE = "payment_failure"
NOTIF_REFUND_INITIATED = "refund_initiated"
NOTIF_REFUND_SENT = "refund_sent"
NOTIF_REFUND_COMPLETED = "refund_completed"
NOTIF_REFUND_HELD = "refund_held"
NOTIF_DUPLICATE_DETECTED = "duplicate_detected"

# Notification channels
CHANNEL_IN_APP = "in_app"
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"

ALL_NOTIFICATION_CHANNELS = (CHANNEL_IN_APP, CHANNEL_EMAIL, CHANNEL_SMS)

# Notification delivery states
NOTIF_PENDING = "pending"
NOTIF_DELIVERED = "delivered"
NOTIF_FAILED = "failed"
NOTIF_HELD_SLEEP = "held_sleep_window"
NOTIF_CANCELLED = "cancelled"

# Notification delivery rules
DEFAULT_NOTIFICATION_HOUR_LOCAL = 10     # 10:00 AM local
SLEEP_WINDOW_START_HOUR = 21             # 21:00
SLEEP_WINDOW_END_HOUR = 7                # 07:00

# Currency
CURRENCY_KES = "KES"


# ─────────────────────────────────────────────────────────────────────────
# 1. SUBSCRIPTIONS
# ─────────────────────────────────────────────────────────────────────────

class Subscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "subscriber_type IN ('group','solo')",
            name="ck_sub_subscriber_type",
        ),
        CheckConstraint(
            "plan_type IN ('monthly','yearly')",
            name="ck_sub_plan_type",
        ),
        CheckConstraint(
            "status IN ('trial','active','expiring','grace','expired',"
            "'suspended','cancelled')",
            name="ck_sub_status",
        ),
        CheckConstraint(
            "(subscriber_type = 'group' AND group_id IS NOT NULL) OR "
            "(subscriber_type = 'solo' AND user_id IS NOT NULL)",
            name="ck_sub_subscriber_binding",
        ),
        CheckConstraint(
            "preferred_provider IN ('mpesa','card','bank','manual')",
            name="ck_sub_preferred_provider",
        ),
        Index("ix_subs_group", "group_id"),
        Index("ix_subs_user", "user_id"),
        Index("ix_subs_status", "status"),
        Index("ix_subs_period_end", "period_end"),
        Index("ix_subs_next_charge", "next_charge_at_utc"),
    )

    subscriber_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
    )
    group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    plan_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PLAN_MONTHLY,
    )

    # --- Amounts ---
    base_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_member_amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default=CURRENCY_KES,
    )
    member_count_at_payment: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # --- Lifecycle ---
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SUB_TRIAL, index=True,
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    # 10 days before period_end for groups, 5 for solo
    expiring_warning_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 3 days after period_end for groups
    grace_period_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 5 days after period_end for solo
    solo_access_window_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Renewal ---
    auto_renew: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    preferred_provider: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PROVIDER_MPESA,
    )
    last_renewal_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    renewal_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Card auto-charge ---
    charge_hour_local: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_NOTIFICATION_HOUR_LOCAL,
    )
    next_charge_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_pre_charge_notice_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    card_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # --- Cancellation ---
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Subscription {self.subscriber_type} "
            f"group={self.group_id} user={self.user_id} status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 2. TRANSACTIONS
# ─────────────────────────────────────────────────────────────────────────

class Transaction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('mpesa','card','bank','manual')",
            name="ck_txn_provider",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALL_TXN_STATES)})",
            name="ck_txn_status",
        ),
        Index("ix_txn_payer_user", "payer_user_id"),
        Index("ix_txn_payer_group", "payer_group_id"),
        Index("ix_txn_status", "status"),
        Index("ix_txn_type", "transaction_type"),
        Index("ix_txn_related", "related_object_type", "related_object_id"),
        Index("ix_txn_provider_ref", "provider_reference"),
        Index("ix_txn_grace_ends", "grace_ends_at"),
    )

    # --- Idempotency key ---
    reference: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
    )

    # --- Payer ---
    payer_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    payer_group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # --- Classification ---
    transaction_type: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True,
    )
    related_object_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )
    related_object_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True,
    )

    # --- Amount ---
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default=CURRENCY_KES,
    )

    # --- Provider ---
    provider: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PROVIDER_MPESA,
    )
    provider_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
    )
    provider_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- State ---
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=TXN_INITIATED, index=True,
    )

    # --- Grace window for one-time fees ---
    grace_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Lifecycle timestamps ---
    initiated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Refund state ---
    is_refunded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    refund_held: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    refund_held_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Context ---
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Transaction {self.reference} type={self.transaction_type} "
            f"status={self.status} amount={self.amount}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 3. INVOICES
# ─────────────────────────────────────────────────────────────────────────

class Invoice(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','issued','paid','void','refunded')",
            name="ck_invoice_status",
        ),
        Index("ix_invoice_status", "status"),
        Index("ix_invoice_payer_user", "payer_user_id"),
        Index("ix_invoice_payer_group", "payer_group_id"),
    )

    invoice_number: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True,
    )
    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    payer_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    payer_group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    line_items_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    tax: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default=CURRENCY_KES,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="issued", index=True,
    )

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    voided_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<Invoice {self.invoice_number} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────
# 4. RECEIPTS
# ─────────────────────────────────────────────────────────────────────────

class Receipt(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('issued','void','refunded')",
            name="ck_receipt_status",
        ),
        Index("ix_receipt_status", "status"),
        Index("ix_receipt_payer_user", "payer_user_id"),
        Index("ix_receipt_payer_group", "payer_group_id"),
    )

    receipt_number: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True,
    )
    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    invoice_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    payer_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    payer_group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default=CURRENCY_KES,
    )
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_reference: Mapped[str] = mapped_column(
        String(128), nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="issued", index=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    voided_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<Receipt {self.receipt_number} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────
# 5. REFUND REQUESTS
# ─────────────────────────────────────────────────────────────────────────

class RefundRequest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "refund_requests"
    __table_args__ = (
        CheckConstraint(
            "reason_type IN ('duplicate','admin_override')",
            name="ck_refund_reason_type",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALL_REFUND_STATES)})",
            name="ck_refund_status",
        ),
        Index("ix_refund_txn", "transaction_id"),
        Index("ix_refund_status", "status"),
        Index("ix_refund_requested_by", "requested_by"),
    )

    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    requested_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    reason_type: Mapped[str] = mapped_column(
        String(24), nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    amount_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default=CURRENCY_KES,
    )

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=REFUND_SUBMITTED, index=True,
    )

    # --- Review ---
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Provider execution ---
    provider_refund_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    provider_refund_payload: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Held state (card expired etc.) ---
    held_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    held_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<RefundRequest txn={self.transaction_id} "
            f"amount={self.amount_requested} status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 6. EVENT ADVERTISEMENTS
# ─────────────────────────────────────────────────────────────────────────

class EventAdvertisement(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "event_advertisements"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('public','county','national')",
            name="ck_event_ad_scope",
        ),
        CheckConstraint(
            "status IN ('pending_payment','active','expired',"
            "'paused','cancelled')",
            name="ck_event_ad_status",
        ),
        Index("ix_event_ad_event", "event_id"),
        Index("ix_event_ad_status", "status"),
        Index("ix_event_ad_period_end", "current_period_end"),
    )

    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
    )
    monthly_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default=CURRENCY_KES,
    )

    initial_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_renewal_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )

    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EVENT_AD_PENDING, index=True,
    )
    auto_renew: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # --- Grace period ---
    grace_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<EventAdvertisement event={self.event_id} "
            f"scope={self.scope} status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 7. RECONCILIATION BATCHES
# ─────────────────────────────────────────────────────────────────────────

class ReconciliationBatch(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "reconciliation_batches"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('mpesa','card','bank','manual')",
            name="ck_recon_provider",
        ),
        Index("ix_recon_provider", "provider"),
        Index("ix_recon_status", "status"),
    )

    batch_reference: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
    )

    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", index=True,
    )

    total_transactions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    matched_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    missing_in_provider_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    mismatched_amount_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    unclaimed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    resolved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    flagged_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    run_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    report_pdf_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    details_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ReconciliationBatch {self.batch_reference} "
            f"provider={self.provider} status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────────────────
# 8. FINANCIAL AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────

class FinancialAuditLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "financial_audit_log"
    __table_args__ = (
        Index("ix_fin_audit_txn", "transaction_id"),
        Index("ix_fin_audit_subscription", "subscription_id"),
        Index("ix_fin_audit_refund", "refund_request_id"),
        Index("ix_fin_audit_event_type", "event_type"),
        Index("ix_fin_audit_actor", "actor_id"),
    )

    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    refund_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("refund_requests.id", ondelete="SET NULL"),
        nullable=True,
    )

    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)

    details_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<FinancialAuditLog {self.event_type}>"


# ─────────────────────────────────────────────────────────────────────────
# 9. FINANCIAL NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────

class FinancialNotification(Base, UUIDMixin, TimestampMixin):
    """
    Scheduled notification for any financial event.
    Stored in UTC; delivery respects the user's local timezone.
    """
    __tablename__ = "financial_notifications"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('in_app','email','sms')",
            name="ck_fin_notif_channel",
        ),
        CheckConstraint(
            "delivery_status IN ('pending','delivered','failed',"
            "'held_sleep_window','cancelled')",
            name="ck_fin_notif_delivery_status",
        ),
        Index("ix_fin_notif_user", "user_id"),
        Index("ix_fin_notif_status", "delivery_status"),
        Index("ix_fin_notif_scheduled", "scheduled_at_utc"),
        Index("ix_fin_notif_txn", "transaction_id"),
        Index("ix_fin_notif_sub", "subscription_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    subscription_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )

    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)

    # --- Scheduling (all UTC) ---
    scheduled_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    scheduled_local_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_NOTIFICATION_HOUR_LOCAL,
    )
    local_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Africa/Nairobi",
    )

    # --- Delivery ---
    delivered_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    delivery_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=NOTIF_PENDING, index=True,
    )
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Deferral ---
    is_urgent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    deferred_from_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<FinancialNotification {self.category} "
            f"user={self.user_id} channel={self.channel} "
            f"status={self.delivery_status}>"
        )