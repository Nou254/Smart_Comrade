"""
Transaction service — Module 012.

Owns the transaction state machine. Every payment in the platform
ultimately lands here.

Idempotency: every transaction has a `reference`. Webhooks that arrive
twice with the same reference are safely ignored.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.financial import (
    Transaction, FinancialAuditLog, Subscription, EventAdvertisement,
    TXN_INITIATED, TXN_AWAITING_PAYMENT, TXN_PENDING_PROVIDER,
    TXN_SUCCESSFUL, TXN_FAILED, TXN_TIMEOUT, TXN_EXPIRED, TXN_SETTLED,
    TXN_REFUNDED, TXN_CANCELLED, ONE_TIME_FEE_GRACE_DAYS,
)
from app.services.payment_provider_service import (
    get_provider, generate_platform_reference, PaymentProviderError,
)


logger = logging.getLogger(__name__)


# ── exceptions ───────────────────────────────────────────────────────────

class TransactionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# INITIATE
# ─────────────────────────────────────────────────────────────────────────

def initiate_transaction(
    db: Session,
    *,
    transaction_type: str,
    amount: int,
    provider_name: str,
    payer_user_id: str | None = None,
    payer_group_id: str | None = None,
    related_object_type: str | None = None,
    related_object_id: str | None = None,
    description: str | None = None,
    grace_days: int | None = ONE_TIME_FEE_GRACE_DAYS,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> Transaction:
    """
    Create a transaction record and ask the provider to initiate a charge.
    """
    if amount <= 0:
        raise TransactionError("Amount must be positive.", 400)

    provider = get_provider(provider_name)

    ref = generate_platform_reference()
    now = _now()

    txn = Transaction(
        reference=ref,
        payer_user_id=payer_user_id,
        payer_group_id=payer_group_id,
        transaction_type=transaction_type,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        amount=amount,
        currency="KES",
        provider=provider_name,
        status=TXN_INITIATED,
        grace_ends_at=(now + timedelta(days=grace_days)) if grace_days else None,
        initiated_at=now,
        description=description,
        ip_address=ip,
        user_agent=(ua or "")[:255] or None,
    )
    db.add(txn)
    db.flush()

    _log(
        db, txn.id, "transaction.initiated", payer_user_id,
        to_state=TXN_INITIATED,
        details={"type": transaction_type, "amount": amount, "provider": provider_name},
    )

    # Ask provider to initiate the charge
    try:
        initiation = provider.initiate_charge(
            amount=amount,
            currency="KES",
            reference=ref,
            payer_phone=payer_phone,
            payer_email=payer_email,
            description=description or transaction_type,
            callback_url="",  # webhook handled separately
        )
    except PaymentProviderError as e:
        txn.status = TXN_FAILED
        txn.failed_at = _now()
        txn.failed_reason = e.message
        _log(db, txn.id, "transaction.initiation_failed", payer_user_id,
             to_state=TXN_FAILED, details={"error": e.message})
        db.commit()
        raise

    txn.provider_reference = initiation.provider_reference
    txn.status = TXN_PENDING_PROVIDER
    _log(db, txn.id, "transaction.provider_pending", payer_user_id,
         from_state=TXN_INITIATED, to_state=TXN_PENDING_PROVIDER,
         details={"provider_ref": initiation.provider_reference})

    db.commit()
    db.refresh(txn)

    # Attach client instructions for the caller to surface
    txn.client_action_required = initiation.client_action_required      # type: ignore[attr-defined]
    txn.client_instructions = initiation.client_instructions            # type: ignore[attr-defined]
    txn.checkout_url = initiation.checkout_url                          # type: ignore[attr-defined]
    return txn


# ─────────────────────────────────────────────────────────────────────────
# STATE TRANSITIONS
# ─────────────────────────────────────────────────────────────────────────

def mark_successful(
    db: Session, reference: str, provider_payload: dict | None = None,
    provider_reference: str | None = None,
) -> Transaction:
    txn = _get_by_reference(db, reference)

    # Idempotency — if already terminal success-ish, no-op
    if txn.status in (TXN_SUCCESSFUL, TXN_SETTLED):
        return txn

    from_state = txn.status
    txn.status = TXN_SUCCESSFUL
    txn.paid_at = _now()
    if provider_reference:
        txn.provider_reference = provider_reference
    if provider_payload is not None:
        txn.provider_payload = provider_payload

    _log(db, txn.id, "transaction.successful", None,
         from_state=from_state, to_state=TXN_SUCCESSFUL,
         details={"provider_ref": txn.provider_reference})

    db.commit()
    db.refresh(txn)
    return txn


def mark_failed(
    db: Session, reference: str, reason: str,
    provider_payload: dict | None = None,
) -> Transaction:
    txn = _get_by_reference(db, reference)
    if txn.status in (TXN_SUCCESSFUL, TXN_SETTLED, TXN_FAILED):
        return txn

    from_state = txn.status
    txn.status = TXN_FAILED
    txn.failed_at = _now()
    txn.failed_reason = reason
    if provider_payload is not None:
        txn.provider_payload = provider_payload

    _log(db, txn.id, "transaction.failed", None,
         from_state=from_state, to_state=TXN_FAILED,
         details={"reason": reason})

    db.commit()
    db.refresh(txn)
    return txn


def mark_timeout(db: Session, reference: str) -> Transaction:
    txn = _get_by_reference(db, reference)
    if txn.status in (TXN_SUCCESSFUL, TXN_SETTLED, TXN_FAILED, TXN_TIMEOUT):
        return txn

    from_state = txn.status
    txn.status = TXN_TIMEOUT
    txn.failed_at = _now()
    txn.failed_reason = "No provider webhook received within expected window."
    _log(db, txn.id, "transaction.timeout", None,
         from_state=from_state, to_state=TXN_TIMEOUT)

    db.commit()
    db.refresh(txn)
    return txn


def mark_expired(db: Session, reference: str) -> Transaction:
    """Fired when grace window expires with no payment."""
    txn = _get_by_reference(db, reference)
    if txn.status in (TXN_SUCCESSFUL, TXN_SETTLED, TXN_EXPIRED, TXN_FAILED):
        return txn

    from_state = txn.status
    txn.status = TXN_EXPIRED
    txn.expired_at = _now()
    _log(db, txn.id, "transaction.expired", None,
         from_state=from_state, to_state=TXN_EXPIRED)

    db.commit()
    db.refresh(txn)
    return txn


def mark_settled(db: Session, reference: str) -> Transaction:
    """After provider confirms funds have settled into N.O.U. account."""
    txn = _get_by_reference(db, reference)
    if txn.status == TXN_SETTLED:
        return txn
    if txn.status != TXN_SUCCESSFUL:
        raise TransactionError(
            f"Cannot settle transaction in status '{txn.status}'.", 409,
        )
    txn.status = TXN_SETTLED
    txn.settled_at = _now()
    _log(db, txn.id, "transaction.settled", None,
         from_state=TXN_SUCCESSFUL, to_state=TXN_SETTLED)
    db.commit()
    db.refresh(txn)
    return txn


def cancel_transaction(
    db: Session, reference: str, reason: str,
) -> Transaction:
    txn = _get_by_reference(db, reference)
    if txn.status in (TXN_SUCCESSFUL, TXN_SETTLED, TXN_CANCELLED):
        return txn

    from_state = txn.status
    txn.status = TXN_CANCELLED
    txn.failed_reason = reason
    _log(db, txn.id, "transaction.cancelled", None,
         from_state=from_state, to_state=TXN_CANCELLED,
         details={"reason": reason})
    db.commit()
    db.refresh(txn)
    return txn


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_by_reference(db: Session, reference: str) -> Transaction:
    return _get_by_reference(db, reference)


def get_by_id(db: Session, txn_id: str) -> Transaction:
    txn = db.query(Transaction).filter(Transaction.id == txn_id).first()
    if not txn:
        raise TransactionError("Transaction not found.", 404)
    return txn


def list_transactions(
    db: Session,
    *,
    payer_user_id: str | None = None,
    payer_group_id: str | None = None,
    status: str | None = None,
    transaction_type: str | None = None,
    related_object_type: str | None = None,
    related_object_id: str | None = None,
    limit: int = 100,
) -> list[Transaction]:
    q = db.query(Transaction)
    if payer_user_id:
        q = q.filter(Transaction.payer_user_id == payer_user_id)
    if payer_group_id:
        q = q.filter(Transaction.payer_group_id == payer_group_id)
    if status:
        q = q.filter(Transaction.status == status)
    if transaction_type:
        q = q.filter(Transaction.transaction_type == transaction_type)
    if related_object_type:
        q = q.filter(Transaction.related_object_type == related_object_type)
    if related_object_id:
        q = q.filter(Transaction.related_object_id == related_object_id)
    return q.order_by(Transaction.initiated_at.desc()).limit(limit).all()


def find_duplicate_transaction(
    db: Session,
    *,
    payer_user_id: str | None,
    payer_group_id: str | None,
    transaction_type: str,
    related_object_id: str | None,
    within_minutes: int = 5,
) -> Transaction | None:
    """
    Look for a prior successful transaction with the same payer + type
    + related object within the last N minutes. Used for duplicate
    detection → auto-refund.
    """
    threshold = _now() - timedelta(minutes=within_minutes)
    q = db.query(Transaction).filter(
        Transaction.transaction_type == transaction_type,
        Transaction.related_object_id == related_object_id,
        Transaction.status.in_((TXN_SUCCESSFUL, TXN_SETTLED)),
        Transaction.paid_at >= threshold,
    )
    if payer_user_id:
        q = q.filter(Transaction.payer_user_id == payer_user_id)
    if payer_group_id:
        q = q.filter(Transaction.payer_group_id == payer_group_id)
    return q.order_by(Transaction.paid_at.desc()).first()


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _get_by_reference(db: Session, reference: str) -> Transaction:
    txn = db.query(Transaction).filter(Transaction.reference == reference).first()
    if not txn:
        raise TransactionError("Transaction not found.", 404)
    return txn


def _log(
    db: Session, transaction_id: str, event_type: str, actor_id: str | None,
    *, from_state: str | None = None, to_state: str | None = None,
    details: dict | None = None, ip: str | None = None, ua: str | None = None,
) -> None:
    db.add(FinancialAuditLog(
        event_type=event_type,
        actor_id=actor_id,
        transaction_id=transaction_id,
        from_state=from_state,
        to_state=to_state,
        details_json=details,
        ip_address=ip,
        user_agent=ua,
    ))