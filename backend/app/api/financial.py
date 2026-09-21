"""
Financial endpoints — Module 012.

Route order: literal prefixes (/subscriptions/me/, /refunds/me/,
/fees/..., /analytics/..., /notifications/..., /reconciliation/...)
before dynamic segments.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.models.financial import (
    Subscription, Transaction, Invoice, Receipt, RefundRequest,
    EventAdvertisement, ReconciliationBatch, FinancialAuditLog,
    FinancialNotification,
    ALL_TXN_STATES, ALL_REFUND_STATES, ALL_TRANSACTION_TYPES,
    FEE_AMOUNTS, SUBSCRIBER_GROUP, SUBSCRIBER_SOLO,
)
from app.schemas.financial import (
    SubscriptionResponse, SubscriptionSubscribeRequest, SubscriptionCancelRequest,
    TransactionInitiateRequest, TransactionResponse, TransactionListResponse,
    InvoiceResponse, ReceiptResponse,
    RefundSubmitRequest, RefundReviewRequest, RefundAdminOverrideRequest,
    RefundRequestResponse,
    EventAdvertisementInitiateRequest, EventAdvertisementResponse,
    NominationFeeInitiateRequest, ClubFeeInitiateRequest,
    TransferFeeInitiateRequest, GroupExitFeeInitiateRequest,
    VacancyFeeInitiateRequest,
    ReconciliationBatchCreateRequest, ReconciliationBatchResponse,
    FinancialAuditEventResponse, FinancialNotificationResponse,
    RevenueSummaryResponse, SubscriptionHealthResponse, PaymentAnalyticsResponse,
)
from app.services.subscription_service import (
    SubscriptionError,
    compute_group_fee, compute_solo_fee,
    start_group_trial, start_solo_trial,
    initiate_subscription_payment, activate_subscription,
    mark_expiring, enter_grace, mark_expired,
    cancel_subscription, cancel_solo_on_group_join,
    get_active_subscription, get_subscription, list_due_for_renewal,
)
from app.services.transaction_service import (
    TransactionError,
    initiate_transaction, get_by_id, get_by_reference, list_transactions,
)
from app.services.fee_service import (
    FeeError,
    initiate_nomination_fee, initiate_club_election_fee,
    initiate_club_promotion_fee, initiate_event_advertisement,
    initiate_transfer_fee, initiate_group_to_solo_exit,
    initiate_group_leader_vacancy,
)
from app.services.invoice_receipt_service import (
    InvoiceError,
    list_invoices, list_receipts, get_invoice, get_receipt,
)
from app.services.refund_service import (
    RefundError,
    submit_refund_request, review_refund_request,
    admin_override_refund, hold_refund, release_held_refund,
    list_refunds, get_refund,
)
from app.services.reconciliation_service import (
    ReconciliationError,
    start_batch, list_batches, get_batch,
)
from app.services.notification_scheduler_service import (
    NotificationError,
    schedule_notification, deliver_due_notifications,
    list_notifications,
)
from app.services.financial_analytics_service import (
    revenue_summary, subscription_health, payment_analytics,
)
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/financial", tags=["Financial"])


def _err(e):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _assert_owner_or_admin(
    current_user: User, payer_user_id: str | None,
) -> None:
    """Fee initiation: caller must be the payer or a super admin."""
    if payer_user_id and str(payer_user_id) != str(current_user.id):
        raise HTTPException(
            status_code=403,
            detail="You can only initiate fees for your own account.",
        )


# ═════════════════════════════════════════════════════════════════════════
# SUBSCRIPTIONS
# ═════════════════════════════════════════════════════════════════════════

@router.get("/subscriptions/me", response_model=SubscriptionResponse | None)
def get_my_subscription(
    subscriber_type: str = Query(..., description="group | solo"),
    group_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if subscriber_type == SUBSCRIBER_SOLO:
        return get_active_subscription(
            db, subscriber_type, user_id=current_user.id,
        )
    if subscriber_type == SUBSCRIBER_GROUP and group_id:
        return get_active_subscription(
            db, subscriber_type, group_id=group_id,
        )
    return None


@router.post("/subscriptions/me/subscribe", response_model=SubscriptionResponse)
def post_subscribe(
    payload: SubscriptionSubscribeRequest,
    subscriber_type: str = Query(..., description="group | solo"),
    group_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start a subscription. If no active subscription exists, a new one
    starts in trial state. Returns the subscription with its computed
    fee.
    """
    try:
        if subscriber_type == SUBSCRIBER_SOLO:
            sub = start_solo_trial(db, current_user.id)
        elif subscriber_type == SUBSCRIBER_GROUP and group_id:
            sub = start_group_trial(db, group_id)
        else:
            raise HTTPException(400, "Invalid subscriber_type/group_id.")
    except SubscriptionError as e:
        _err(e)
    return sub


@router.post("/subscriptions/me/cancel", response_model=SubscriptionResponse)
def post_cancel_subscription(
    payload: SubscriptionCancelRequest,
    subscription_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cancel_subscription(db, subscription_id, reason=payload.reason)
    except SubscriptionError as e:
        _err(e)


@router.get("/subscriptions/due-for-renewal", response_model=list[SubscriptionResponse])
def get_due_for_renewal(
    within_days: int = Query(10, ge=1, le=30),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return list_due_for_renewal(db, within_days=within_days)


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
def get_one_subscription(
    subscription_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_subscription(db, subscription_id)
    except SubscriptionError as e:
        _err(e)


@router.post("/subscriptions/{subscription_id}/pay")
def post_subscription_payment(
    subscription_id: str,
    provider: str = Query(..., description="mpesa | card | bank | manual"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        txn = initiate_subscription_payment(
            db, subscription_id, provider_name=provider,
            payer_phone=current_user.phone,
            payer_email=current_user.email,
            ip=_ip(request) if request else None,
            ua=_ua(request) if request else None,
        )
    except (SubscriptionError, TransactionError) as e:
        _err(e)
    return {
        "transaction_id": txn.id,
        "reference": txn.reference,
        "provider_reference": txn.provider_reference,
        "status": txn.status,
        "amount": txn.amount,
        "client_action_required": getattr(txn, "client_action_required", False),
        "client_instructions": getattr(txn, "client_instructions", None),
    }


# ═════════════════════════════════════════════════════════════════════════
# TRANSACTIONS
# ═════════════════════════════════════════════════════════════════════════

@router.post("/transactions", response_model=TransactionResponse, status_code=201)
def post_transaction(
    payload: TransactionInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.transaction_type not in ALL_TRANSACTION_TYPES:
        raise HTTPException(
            400, f"Unknown transaction_type '{payload.transaction_type}'.",
        )
    amount = FEE_AMOUNTS.get(payload.transaction_type)
    if amount is None:
        raise HTTPException(400, "No fee configured for this transaction type.")
    try:
        return initiate_transaction(
            db,
            transaction_type=payload.transaction_type,
            amount=amount,
            provider_name=payload.provider,
            payer_user_id=current_user.id,
            related_object_type=payload.related_object_type,
            related_object_id=payload.related_object_id,
            payer_phone=payload.payer_phone or current_user.phone,
            payer_email=payload.payer_email or current_user.email,
            ip=_ip(request),
            ua=_ua(request),
        )
    except TransactionError as e:
        _err(e)


@router.get("/transactions", response_model=list[TransactionListResponse])
def get_transactions(
    status: str | None = Query(None),
    transaction_type: str | None = Query(None),
    related_object_type: str | None = Query(None),
    related_object_id: str | None = Query(None),
    group_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the caller's own transactions by default; admins may filter."""
    payer_user_id = None
    payer_group_id = None
    if not getattr(current_user, "is_super_admin", False):
        payer_user_id = current_user.id
        if group_id:
            payer_group_id = None  # fall through — service filters by user first
    return list_transactions(
        db,
        payer_user_id=payer_user_id,
        payer_group_id=payer_group_id,
        status=status,
        transaction_type=transaction_type,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        limit=limit,
    )


@router.get("/transactions/by-reference/{reference}", response_model=TransactionResponse)
def get_transaction_by_reference(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_by_reference(db, reference)
    except TransactionError as e:
        _err(e)


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_one_transaction(
    transaction_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_by_id(db, transaction_id)
    except TransactionError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# INVOICES + RECEIPTS
# ═════════════════════════════════════════════════════════════════════════

@router.get("/invoices", response_model=list[InvoiceResponse])
def get_invoices(
    status: str | None = Query(None),
    group_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_invoices(
        db,
        payer_user_id=current_user.id,
        payer_group_id=group_id,
        status=status,
        limit=limit,
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_one_invoice(
    invoice_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_invoice(db, invoice_id)
    except InvoiceError as e:
        _err(e)


@router.get("/receipts", response_model=list[ReceiptResponse])
def get_receipts(
    status: str | None = Query(None),
    group_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_receipts(
        db,
        payer_user_id=current_user.id,
        payer_group_id=group_id,
        status=status,
        limit=limit,
    )


@router.get("/receipts/{receipt_id}", response_model=ReceiptResponse)
def get_one_receipt(
    receipt_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_receipt(db, receipt_id)
    except InvoiceError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# REFUNDS
# ═════════════════════════════════════════════════════════════════════════

@router.post("/refunds", response_model=RefundRequestResponse, status_code=201)
def post_refund_request(
    payload: RefundSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return submit_refund_request(
            db,
            transaction_id=payload.transaction_id,
            user_id=current_user.id,
            reason=payload.reason,
            evidence=payload.evidence,
        )
    except RefundError as e:
        _err(e)


@router.get("/refunds/me", response_model=list[RefundRequestResponse])
def get_my_refunds(
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_refunds(db, requested_by=current_user.id, status=status)


@router.get("/refunds", response_model=list[RefundRequestResponse])
def get_all_refunds(
    status: str | None = Query(None),
    transaction_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return list_refunds(
        db, status=status, transaction_id=transaction_id, limit=limit,
    )


@router.post("/refunds/{refund_id}/review", response_model=RefundRequestResponse)
def post_review_refund(
    refund_id: str,
    payload: RefundReviewRequest,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = review_refund_request(
            db, refund_id=refund_id, reviewer_id=current_user.id,
            approve=payload.approve, notes=payload.review_notes,
        )
    except RefundError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id,
        action=f"refund.{'approve' if payload.approve else 'reject'}",
        target_type="refund_request", target_id=refund_id,
        reason=payload.review_notes,
    )
    return result


@router.post("/refunds/admin-override", response_model=RefundRequestResponse, status_code=201)
def post_admin_override(
    payload: RefundAdminOverrideRequest,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = admin_override_refund(
            db,
            transaction_id=payload.transaction_id,
            admin_id=current_user.id,
            amount=payload.amount,
            reason=payload.reason,
        )
    except RefundError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="refund.admin_override",
        target_type="transaction", target_id=payload.transaction_id,
        new_value=str(payload.amount), reason=payload.reason,
    )
    return result


@router.post("/refunds/{refund_id}/hold", response_model=RefundRequestResponse)
def post_hold_refund(
    refund_id: str,
    reason: str = Query(..., min_length=5, max_length=1000),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return hold_refund(db, refund_id, reason=reason)
    except RefundError as e:
        _err(e)


@router.post("/refunds/{refund_id}/release", response_model=RefundRequestResponse)
def post_release_refund(
    refund_id: str,
    new_card_reference: str | None = Query(None, max_length=128),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return release_held_refund(
            db, refund_id, admin_id=current_user.id,
            new_card_reference=new_card_reference,
        )
    except RefundError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# FEE INITIATION (called by other modules or users)
# ═════════════════════════════════════════════════════════════════════════

@router.post("/fees/nomination")
def post_fee_nomination(
    payload: NominationFeeInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        txn = initiate_nomination_fee(
            db, candidate_id=payload.candidate_id, level=payload.level,
            provider_name=payload.provider, payer_user_id=current_user.id,
            payer_phone=current_user.phone, payer_email=current_user.email,
            ip=_ip(request), ua=_ua(request),
        )
    except FeeError as e:
        _err(e)
    return {
        "transaction_id": txn.id, "reference": txn.reference,
        "status": txn.status, "amount": txn.amount,
        "client_action_required": getattr(txn, "client_action_required", False),
        "client_instructions": getattr(txn, "client_instructions", None),
    }


@router.post("/fees/club-election")
def post_fee_club_election(
    payload: ClubFeeInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.fee_type != "election_cycle":
        raise HTTPException(400, "fee_type must be 'election_cycle'.")
    try:
        txn = initiate_club_election_fee(
            db, cycle_id=payload.related_object_id,
            provider_name=payload.provider, payer_user_id=current_user.id,
            payer_phone=current_user.phone, payer_email=current_user.email,
            ip=_ip(request), ua=_ua(request),
        )
    except FeeError as e:
        _err(e)
    return {"transaction_id": txn.id, "reference": txn.reference,
            "status": txn.status, "amount": txn.amount}


@router.post("/fees/club-promotion")
def post_fee_club_promotion(
    payload: ClubFeeInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.fee_type != "promotion":
        raise HTTPException(400, "fee_type must be 'promotion'.")
    try:
        txn = initiate_club_promotion_fee(
            db, club_id=payload.related_object_id,
            provider_name=payload.provider, payer_user_id=current_user.id,
            payer_phone=current_user.phone, payer_email=current_user.email,
            ip=_ip(request), ua=_ua(request),
        )
    except FeeError as e:
        _err(e)
    return {"transaction_id": txn.id, "reference": txn.reference,
            "status": txn.status, "amount": txn.amount}


@router.post("/fees/event-advertisement")
def post_fee_event_ad(
    payload: EventAdvertisementInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        txn = initiate_event_advertisement(
            db, event_id=payload.event_id, scope=payload.scope,
            provider_name=payload.provider, payer_user_id=current_user.id,
            payer_phone=current_user.phone, payer_email=current_user.email,
            ip=_ip(request), ua=_ua(request),
        )
    except FeeError as e:
        _err(e)
    return {"transaction_id": txn.id, "reference": txn.reference,
            "status": txn.status, "amount": txn.amount}


@router.post("/fees/transfer")
def post_fee_transfer(
    payload: TransferFeeInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        txn = initiate_transfer_fee(
            db, transfer_id=payload.transfer_id,
            transfer_type=payload.transfer_type,
            provider_name=payload.provider, payer_user_id=current_user.id,
            payer_phone=current_user.phone, payer_email=current_user.email,
            ip=_ip(request), ua=_ua(request),
        )
    except FeeError as e:
        _err(e)
    return {"transaction_id": txn.id, "reference": txn.reference,
            "status": txn.status, "amount": txn.amount}


@router.post("/fees/group-exit")
def post_fee_group_exit(
    payload: GroupExitFeeInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_owner_or_admin(current_user, payload.user_id)
    try:
        txn = initiate_group_to_solo_exit(
            db, user_id=payload.user_id,
            provider_name=payload.provider,
            payer_phone=current_user.phone, payer_email=current_user.email,
            ip=_ip(request), ua=_ua(request),
        )
    except FeeError as e:
        _err(e)
    return {"transaction_id": txn.id, "reference": txn.reference,
            "status": txn.status, "amount": txn.amount}


@router.post("/fees/vacancy")
def post_fee_vacancy(
    payload: VacancyFeeInitiateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        txn = initiate_group_leader_vacancy(
            db, group_id=payload.group_id, user_id=current_user.id,
            provider_name=payload.provider,
            payer_phone=current_user.phone, payer_email=current_user.email,
            ip=_ip(request), ua=_ua(request),
        )
    except FeeError as e:
        _err(e)
    return {"transaction_id": txn.id, "reference": txn.reference,
            "status": txn.status, "amount": txn.amount}


# ═════════════════════════════════════════════════════════════════════════
# RECONCILIATION
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/reconciliation/batches",
    response_model=ReconciliationBatchResponse,
    status_code=201,
)
def post_reconciliation_batch(
    payload: ReconciliationBatchCreateRequest,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return start_batch(
            db,
            provider=payload.provider,
            period_start=payload.period_start,
            period_end=payload.period_end,
            run_by=current_user.id,
            notes=payload.notes,
        )
    except ReconciliationError as e:
        _err(e)


@router.get(
    "/reconciliation/batches",
    response_model=list[ReconciliationBatchResponse],
)
def get_reconciliation_batches(
    provider: str | None = Query(None),
    status: str | None = Query(None),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return list_batches(db, provider=provider, status=status)


@router.get(
    "/reconciliation/batches/{batch_id}",
    response_model=ReconciliationBatchResponse,
)
def get_one_reconciliation_batch(
    batch_id: str,
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return get_batch(db, batch_id)
    except ReconciliationError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═════════════════════════════════════════════════════════════════════════

@router.get("/analytics/revenue", response_model=RevenueSummaryResponse)
def get_revenue_analytics(
    period_days: int = Query(30, ge=1, le=365),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days)
    return RevenueSummaryResponse(**revenue_summary(
        db, period_start=start, period_end=end,
    ))


@router.get("/analytics/subscriptions", response_model=SubscriptionHealthResponse)
def get_subscription_analytics(
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return SubscriptionHealthResponse(**subscription_health(db))


@router.get("/analytics/payments", response_model=PaymentAnalyticsResponse)
def get_payment_analytics(
    period_days: int = Query(30, ge=1, le=365),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days)
    return PaymentAnalyticsResponse(**payment_analytics(
        db, period_start=start, period_end=end,
    ))


# ═════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════

@router.get("/notifications", response_model=list[FinancialNotificationResponse])
def get_notifications(
    status: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_notifications(
        db,
        user_id=None if getattr(current_user, "is_super_admin", False) else current_user.id,
        status=status,
        category=category,
        limit=limit,
    )


@router.post("/notifications/deliver-due")
def post_deliver_due(
    batch_size: int = Query(200, ge=1, le=1000),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Cron-style trigger. In production this is called by a scheduler."""
    return deliver_due_notifications(db, batch_size=batch_size)


# ═════════════════════════════════════════════════════════════════════════
# AUDIT
# ═════════════════════════════════════════════════════════════════════════

@router.get("/audit", response_model=list[FinancialAuditEventResponse])
def get_audit_log(
    transaction_id: str | None = Query(None),
    subscription_id: str | None = Query(None),
    refund_request_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    q = db.query(FinancialAuditLog)
    if transaction_id:
        q = q.filter(FinancialAuditLog.transaction_id == transaction_id)
    if subscription_id:
        q = q.filter(FinancialAuditLog.subscription_id == subscription_id)
    if refund_request_id:
        q = q.filter(FinancialAuditLog.refund_request_id == refund_request_id)
    return q.order_by(FinancialAuditLog.created_at.desc()).limit(limit).all()