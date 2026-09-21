"""
Refund service — Module 012.

Refund policy:
  - Duplicates: automatic
  - Admin override: allowed with mandatory reason
  - Everything else: not refundable

Card refunds may be held if the card on file is expired. The user is
notified and asked to contact support.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.financial import (
    Transaction, RefundRequest, FinancialAuditLog,
    TXN_SUCCESSFUL, TXN_SETTLED, TXN_REFUNDED,
    PROVIDER_CARD, PROVIDER_MPESA,
    REFUND_DUPLICATE, REFUND_ADMIN_OVERRIDE,
    REFUND_SUBMITTED, REFUND_APPROVED, REFUND_REJECTED,
    REFUND_PROCESSING, REFUND_COMPLETED, REFUND_FAILED, REFUND_HELD,
)
from app.services.payment_provider_service import (
    get_provider, PaymentProviderError,
)
from app.services.transaction_service import get_by_id as get_txn


logger = logging.getLogger(__name__)


class RefundError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# AUTOMATIC DUPLICATE REFUND
# ─────────────────────────────────────────────────────────────────────────

def auto_refund_duplicate(
    db: Session, original_txn: Transaction, duplicate_txn: Transaction,
) -> RefundRequest:
    """
    Called by the payment-success dispatcher when a duplicate is detected.
    Creates an auto-approved refund for the duplicate transaction.
    """
    if duplicate_txn.status not in (TXN_SUCCESSFUL, TXN_SETTLED):
        raise RefundError(
            "Duplicate transaction is not in a refundable state.", 409,
        )

    refund = RefundRequest(
        transaction_id=duplicate_txn.id,
        requested_by=None,        # system-initiated
        requested_at=_now(),
        reason_type=REFUND_DUPLICATE,
        reason=(
            f"Automatic refund — duplicate of transaction "
            f"{original_txn.reference}."
        ),
        amount_requested=duplicate_txn.amount,
        currency=duplicate_txn.currency,
        status=REFUND_APPROVED,   # auto-approved
        reviewed_at=_now(),
        reviewed_by=None,
        review_notes="Auto-approved by duplicate detection.",
    )
    db.add(refund)
    _log(db, duplicate_txn.id, "refund.auto_approved", details={
        "original_reference": original_txn.reference,
    })
    db.commit()
    db.refresh(refund)

    # Fire the provider refund
    try:
        process_refund(db, refund.id)
    except Exception:
        logger.exception("[refund] process failed for auto-refund %s", refund.id)

    return refund


# ─────────────────────────────────────────────────────────────────────────
# USER-SUBMITTED REFUND REQUEST
# ─────────────────────────────────────────────────────────────────────────

def submit_refund_request(
    db: Session, *, transaction_id: str, user_id: str,
    reason: str, evidence: dict | None = None,
) -> RefundRequest:
    txn = get_txn(db, transaction_id)
    if txn.status not in (TXN_SUCCESSFUL, TXN_SETTLED):
        raise RefundError(
            "Only successful transactions can be refunded.", 409,
        )
    if txn.is_refunded:
        raise RefundError("This transaction has already been refunded.", 409)

    existing = db.query(RefundRequest).filter(
        RefundRequest.transaction_id == transaction_id,
        RefundRequest.status.in_((
            REFUND_SUBMITTED, REFUND_APPROVED, REFUND_PROCESSING,
        )),
    ).first()
    if existing:
        return existing

    refund = RefundRequest(
        transaction_id=txn.id,
        requested_by=user_id,
        requested_at=_now(),
        reason_type=REFUND_ADMIN_OVERRIDE,
        reason=reason,
        evidence_json=evidence,
        amount_requested=txn.amount,
        currency=txn.currency,
        status=REFUND_SUBMITTED,
    )
    db.add(refund)
    _log(db, txn.id, "refund.submitted", actor_id=user_id,
         details={"reason": reason})
    db.commit()
    db.refresh(refund)
    return refund


def review_refund_request(
    db: Session, *, refund_id: str, reviewer_id: str,
    approve: bool, notes: str | None = None,
) -> RefundRequest:
    refund = _get_refund(db, refund_id)
    if refund.status != REFUND_SUBMITTED:
        raise RefundError(
            f"Refund is not awaiting review (status={refund.status}).", 409,
        )
    refund.reviewed_by = reviewer_id
    refund.reviewed_at = _now()
    refund.review_notes = notes

    if approve:
        refund.status = REFUND_APPROVED
        _log(db, refund.transaction_id, "refund.approved", actor_id=reviewer_id,
             details={"notes": notes})
        db.commit()
        try:
            process_refund(db, refund.id)
        except Exception:
            logger.exception("[refund] process failed for %s", refund.id)
    else:
        refund.status = REFUND_REJECTED
        _log(db, refund.transaction_id, "refund.rejected", actor_id=reviewer_id,
             details={"notes": notes})
        db.commit()

    db.refresh(refund)
    return refund


# ─────────────────────────────────────────────────────────────────────────
# ADMIN OVERRIDE (goodwill refund)
# ─────────────────────────────────────────────────────────────────────────

def admin_override_refund(
    db: Session, *, transaction_id: str, admin_id: str,
    amount: int, reason: str,
) -> RefundRequest:
    txn = get_txn(db, transaction_id)
    if txn.status not in (TXN_SUCCESSFUL, TXN_SETTLED):
        raise RefundError("Only successful transactions can be refunded.", 409)
    if amount <= 0 or amount > txn.amount:
        raise RefundError("Refund amount must be positive and ≤ original.", 400)
    if not reason or len(reason.strip()) < 5:
        raise RefundError("A reason of at least 5 characters is required.", 400)

    refund = RefundRequest(
        transaction_id=txn.id,
        requested_by=admin_id,
        requested_at=_now(),
        reason_type=REFUND_ADMIN_OVERRIDE,
        reason=reason.strip(),
        amount_requested=amount,
        currency=txn.currency,
        status=REFUND_APPROVED,
        reviewed_by=admin_id,
        reviewed_at=_now(),
        review_notes="Admin override.",
    )
    db.add(refund)
    _log(db, txn.id, "refund.admin_override", actor_id=admin_id,
         details={"amount": amount, "reason": reason})
    db.commit()
    db.refresh(refund)

    try:
        process_refund(db, refund.id)
    except Exception:
        logger.exception("[refund] process failed for override %s", refund.id)
    return refund


# ─────────────────────────────────────────────────────────────────────────
# PROVIDER EXECUTION
# ─────────────────────────────────────────────────────────────────────────

def process_refund(db: Session, refund_id: str) -> RefundRequest:
    refund = _get_refund(db, refund_id)
    if refund.status != REFUND_APPROVED:
        raise RefundError(
            f"Cannot process refund in status '{refund.status}'.", 409,
        )

    txn = get_txn(db, refund.transaction_id)
    provider = get_provider(txn.provider)

    refund.status = REFUND_PROCESSING
    refund.processing_started_at = _now()
    db.flush()

    try:
        result = provider.refund(
            provider_reference=txn.provider_reference or txn.reference,
            amount=refund.amount_requested,
            reason=refund.reason,
        )
    except PaymentProviderError as e:
        refund.status = REFUND_FAILED
        refund.failed_at = _now()
        refund.failed_reason = e.message
        _log(db, txn.id, "refund.failed", details={"error": e.message})
        db.commit()
        return refund

    refund.provider_refund_reference = result.provider_refund_reference
    refund.provider_refund_payload = {"status": result.status, "message": result.message}

    if result.status == "completed":
        refund.status = REFUND_COMPLETED
        refund.completed_at = _now()
        txn.is_refunded = True
    elif result.status == "failed":
        refund.status = REFUND_FAILED
        refund.failed_at = _now()
        refund.failed_reason = result.message or "Provider rejected refund."
    else:
        # Processing — wait for webhook
        pass

    _log(db, txn.id, "refund.processing", details={
        "provider_refund_ref": refund.provider_refund_reference,
        "provider_status": result.status,
    })
    db.commit()
    db.refresh(refund)
    return refund


def handle_refund_webhook(
    db: Session, provider_reference: str, status: str, payload: dict | None = None,
) -> RefundRequest | None:
    refund = db.query(RefundRequest).filter(
        RefundRequest.provider_refund_reference == provider_reference,
    ).first()
    if not refund:
        logger.warning("[refund] webhook for unknown ref %s", provider_reference)
        return None

    if status == "completed":
        refund.status = REFUND_COMPLETED
        refund.completed_at = _now()
        txn = get_txn(db, refund.transaction_id)
        txn.is_refunded = True
    elif status == "failed":
        refund.status = REFUND_FAILED
        refund.failed_at = _now()
        refund.failed_reason = (payload or {}).get("reason", "Provider reported failure.")

    if payload:
        refund.provider_refund_payload = payload
    db.commit()
    db.refresh(refund)
    return refund


# ─────────────────────────────────────────────────────────────────────────
# HELD REFUND (card expired etc.)
# ─────────────────────────────────────────────────────────────────────────

def hold_refund(
    db: Session, refund_id: str, reason: str,
) -> RefundRequest:
    refund = _get_refund(db, refund_id)
    refund.status = REFUND_HELD
    refund.held_since = _now()
    refund.held_reason = reason
    _log(db, refund.transaction_id, "refund.held", details={"reason": reason})
    db.commit()
    db.refresh(refund)
    return refund


def release_held_refund(
    db: Session, refund_id: str, admin_id: str,
    *, new_card_reference: str | None = None,
) -> RefundRequest:
    """
    After the user contacts support and provides new card details, the
    admin releases the held refund. The new card reference is stored on
    the transaction so the provider can refund to it.
    """
    refund = _get_refund(db, refund_id)
    if refund.status != REFUND_HELD:
        raise RefundError("Refund is not in held state.", 409)

    txn = get_txn(db, refund.transaction_id)
    if new_card_reference:
        # Overwrite provider reference for refund routing
        txn.provider_payload = dict(txn.provider_payload or {})
        txn.provider_payload["refund_card_reference"] = new_card_reference

    refund.status = REFUND_APPROVED
    refund.reviewed_by = admin_id
    refund.reviewed_at = _now()
    refund.review_notes = f"Released after user provided new payment details."
    refund.held_since = None
    refund.held_reason = None
    db.commit()

    return process_refund(db, refund.id)


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def list_refunds(
    db: Session, *,
    status: str | None = None,
    requested_by: str | None = None,
    transaction_id: str | None = None,
    limit: int = 100,
) -> list[RefundRequest]:
    q = db.query(RefundRequest)
    if status:
        q = q.filter(RefundRequest.status == status)
    if requested_by:
        q = q.filter(RefundRequest.requested_by == requested_by)
    if transaction_id:
        q = q.filter(RefundRequest.transaction_id == transaction_id)
    return q.order_by(RefundRequest.requested_at.desc()).limit(limit).all()


def get_refund(db: Session, refund_id: str) -> RefundRequest:
    return _get_refund(db, refund_id)


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _get_refund(db: Session, refund_id: str) -> RefundRequest:
    refund = db.query(RefundRequest).filter(
        RefundRequest.id == refund_id,
    ).first()
    if not refund:
        raise RefundError("Refund request not found.", 404)
    return refund


def _log(
    db: Session, transaction_id: str, event_type: str,
    *, actor_id: str | None = None, details: dict | None = None,
) -> None:
    db.add(FinancialAuditLog(
        event_type=event_type,
        actor_id=actor_id,
        transaction_id=transaction_id,
        details_json=details,
    ))