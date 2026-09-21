"""
Pydantic schemas for the Financial module — Module 012.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ═════════════════════════════════════════════════════════════════════════
# SUBSCRIPTIONS
# ═════════════════════════════════════════════════════════════════════════

class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subscriber_type: str
    group_id: str | None
    user_id: str | None
    plan_type: str

    base_amount: int
    extra_member_amount: int
    total_amount: int
    currency: str
    member_count_at_payment: int

    status: str
    trial_ends_at: datetime | None
    period_start: datetime | None
    period_end: datetime | None
    expiring_warning_ends_at: datetime | None
    grace_period_ends_at: datetime | None
    solo_access_window_ends_at: datetime | None

    auto_renew: bool
    preferred_provider: str
    last_renewal_transaction_id: str | None
    renewal_reminder_sent_at: datetime | None

    charge_hour_local: int
    next_charge_at_utc: datetime | None
    last_pre_charge_notice_at: datetime | None
    card_failure_count: int

    cancelled_at: datetime | None
    cancelled_reason: str | None
    created_at: datetime


class SubscriptionSubscribeRequest(BaseModel):
    """Group or solo subscribe to a plan."""
    plan_type: str = Field(..., description="monthly | yearly")
    preferred_provider: str = Field(
        ..., description="mpesa | card | bank | manual",
    )
    charge_hour_local: int = Field(10, ge=0, le=23)


class SubscriptionCancelRequest(BaseModel):
    reason: str | None = Field(None, max_length=500)


# ═════════════════════════════════════════════════════════════════════════
# TRANSACTIONS
# ═════════════════════════════════════════════════════════════════════════

class TransactionInitiateRequest(BaseModel):
    transaction_type: str = Field(..., min_length=2, max_length=40)
    related_object_type: str | None = Field(None, max_length=32)
    related_object_id: str | None = Field(None, max_length=36)
    provider: str = Field(..., description="mpesa | card | bank | manual")
    payer_phone: str | None = Field(None, max_length=20)
    payer_email: str | None = Field(None, max_length=255)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    payer_user_id: str | None
    payer_group_id: str | None
    transaction_type: str
    related_object_type: str | None
    related_object_id: str | None
    amount: int
    currency: str
    provider: str
    provider_reference: str | None
    status: str
    grace_ends_at: datetime | None
    initiated_at: datetime
    paid_at: datetime | None
    settled_at: datetime | None
    expired_at: datetime | None
    failed_at: datetime | None
    failed_reason: str | None
    is_refunded: bool
    refund_held: bool
    refund_held_reason: str | None
    description: str | None
    created_at: datetime


class TransactionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    transaction_type: str
    amount: int
    currency: str
    provider: str
    status: str
    initiated_at: datetime
    paid_at: datetime | None


# ═════════════════════════════════════════════════════════════════════════
# INVOICES / RECEIPTS
# ═════════════════════════════════════════════════════════════════════════

class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    invoice_number: str
    transaction_id: str
    payer_user_id: str | None
    payer_group_id: str | None
    line_items_json: list
    subtotal: int
    tax: int
    total: int
    currency: str
    status: str
    issued_at: datetime
    due_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    voided_reason: str | None
    pdf_url: str | None
    created_at: datetime


class ReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    receipt_number: str
    transaction_id: str
    invoice_id: str | None
    payer_user_id: str | None
    payer_group_id: str | None
    amount: int
    currency: str
    payment_method: str
    provider_reference: str
    status: str
    issued_at: datetime
    voided_at: datetime | None
    voided_reason: str | None
    pdf_url: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# REFUNDS
# ═════════════════════════════════════════════════════════════════════════

class RefundSubmitRequest(BaseModel):
    transaction_id: str
    reason: str = Field(..., min_length=5, max_length=2000)
    evidence: dict | None = None


class RefundReviewRequest(BaseModel):
    approve: bool
    review_notes: str | None = Field(None, max_length=2000)


class RefundAdminOverrideRequest(BaseModel):
    transaction_id: str
    amount: int = Field(..., ge=1)
    reason: str = Field(..., min_length=5, max_length=2000)


class RefundRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    transaction_id: str
    requested_by: str | None
    requested_at: datetime
    reason_type: str
    reason: str
    evidence_json: dict | None
    amount_requested: int
    currency: str
    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    provider_refund_reference: str | None
    processing_started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    failed_reason: str | None
    held_since: datetime | None
    held_reason: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# EVENT ADVERTISEMENTS
# ═════════════════════════════════════════════════════════════════════════

class EventAdvertisementInitiateRequest(BaseModel):
    event_id: str
    scope: str = Field(..., description="public | county | national")
    provider: str = Field(..., description="mpesa | card | bank | manual")


class EventAdvertisementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    scope: str
    monthly_fee: int
    currency: str
    initial_transaction_id: str | None
    last_renewal_transaction_id: str | None
    starts_at: datetime | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    status: str
    auto_renew: bool
    grace_ends_at: datetime | None
    paused_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# FEE INITIATION (from other modules)
# ═════════════════════════════════════════════════════════════════════════

class NominationFeeInitiateRequest(BaseModel):
    candidate_id: str
    level: str = Field(..., description="school | institution | county")
    provider: str = Field(..., description="mpesa | card | bank | manual")


class ClubFeeInitiateRequest(BaseModel):
    fee_type: str = Field(..., description="election_cycle | promotion")
    related_object_id: str  # cycle_id or club_id
    provider: str = Field(..., description="mpesa | card | bank | manual")


class TransferFeeInitiateRequest(BaseModel):
    transfer_id: str
    transfer_type: str = Field(..., description="ordinary | elected")
    provider: str = Field(..., description="mpesa | card | bank | manual")


class GroupExitFeeInitiateRequest(BaseModel):
    user_id: str
    provider: str = Field(..., description="mpesa | card | bank | manual")


class VacancyFeeInitiateRequest(BaseModel):
    group_id: str
    provider: str = Field(..., description="mpesa | card | bank | manual")


# ═════════════════════════════════════════════════════════════════════════
# RECONCILIATION
# ═════════════════════════════════════════════════════════════════════════

class ReconciliationBatchCreateRequest(BaseModel):
    provider: str = Field(..., description="mpesa | card | bank | manual")
    period_start: datetime
    period_end: datetime
    notes: str | None = Field(None, max_length=2000)


class ReconciliationBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_reference: str
    provider: str
    period_start: datetime
    period_end: datetime
    started_at: datetime
    completed_at: datetime | None
    status: str
    total_transactions: int
    matched_count: int
    missing_in_provider_count: int
    mismatched_amount_count: int
    unclaimed_count: int
    resolved_count: int
    flagged_count: int
    run_by: str | None
    report_pdf_url: str | None
    details_json: dict | None
    notes: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# AUDIT
# ═════════════════════════════════════════════════════════════════════════

class FinancialAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    actor_id: str | None
    transaction_id: str | None
    subscription_id: str | None
    refund_request_id: str | None
    from_state: str | None
    to_state: str | None
    details_json: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════

class FinancialNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    transaction_id: str | None
    subscription_id: str | None
    category: str
    channel: str
    scheduled_at_utc: datetime
    scheduled_local_hour: int
    local_timezone: str
    delivered_at_utc: datetime | None
    delivery_status: str
    delivery_error: str | None
    delivery_attempts: int
    last_attempt_at: datetime | None
    is_urgent: bool
    deferred_from_utc: datetime | None
    payload_json: dict | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═════════════════════════════════════════════════════════════════════════

class RevenueSummaryResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    total_revenue: int
    currency: str
    by_type: dict[str, int]
    transaction_count: int


class SubscriptionHealthResponse(BaseModel):
    total_active: int
    total_trial: int
    total_expiring: int
    total_grace: int
    total_expired: int
    total_cancelled: int
    churn_rate: float
    mrr: int
    arpu: float


class PaymentAnalyticsResponse(BaseModel):
    total_attempts: int
    successful: int
    failed: int
    success_rate: float
    by_provider: dict[str, int]