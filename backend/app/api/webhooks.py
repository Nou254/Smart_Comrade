"""
Payment provider webhooks — Module 012.

Each provider has its own endpoint. All verification goes through the
registered PaymentProvider instance.

These endpoints are PUBLIC (no auth) but signature-verified.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.financial import (
    Transaction, TXN_SUCCESSFUL, TXN_SETTLED,
    PROVIDER_MPESA, PROVIDER_CARD, PROVIDER_BANK, PROVIDER_MANUAL,
)
from app.services.payment_provider_service import (
    get_provider, PaymentProviderError,
)
from app.services.transaction_service import (
    mark_successful, mark_failed, find_duplicate_transaction,
)
from app.services.fee_service import handle_payment_success
from app.services.refund_service import (
    handle_refund_webhook, auto_refund_duplicate,
)
from app.services.invoice_receipt_service import generate_receipt

router = APIRouter(prefix="/webhooks", tags=["Payment Webhooks"])


logger = logging.getLogger(__name__)


def _process_webhook(
    db: Session, provider_name: str, raw_body: bytes, headers: dict,
) -> dict:
    provider = get_provider(provider_name)

    if not provider.verify_webhook(raw_body, headers):
        logger.warning("[webhook.%s] signature verification failed", provider_name)
        raise HTTPException(401, "Invalid webhook signature.")

    try:
        event = provider.parse_webhook(raw_body)
    except PaymentProviderError as e:
        raise HTTPException(e.status_code, e.message)

    if not event.reference:
        raise HTTPException(400, "Missing reference in webhook.")

    # --- Refund webhook? ---
    # Refund webhooks carry a provider_refund_reference in raw_payload
    raw = event.raw_payload or {}
    if raw.get("event_kind") == "refund":
        refund = handle_refund_webhook(
            db,
            provider_reference=raw.get("provider_refund_reference", ""),
            status=event.status,
            payload=raw,
        )
        if not refund:
            logger.warning("[webhook.%s] refund webhook for unknown ref", provider_name)
        return {"ok": True, "kind": "refund"}

    # --- Payment webhook ---
    txn = db.query(Transaction).filter(
        Transaction.reference == event.reference,
    ).first()
    if not txn:
        logger.warning(
            "[webhook.%s] unknown reference %s", provider_name, event.reference,
        )
        # Ack anyway to prevent provider retries storm
        return {"ok": True, "kind": "unknown_reference"}

    # Idempotency — already terminal?
    if txn.status in (TXN_SUCCESSFUL, TXN_SETTLED):
        return {"ok": True, "kind": "duplicate_ignored", "status": txn.status}

    # Amount check
    if event.amount and event.amount != txn.amount:
        logger.warning(
            "[webhook.%s] amount mismatch: expected %s, got %s, ref=%s",
            provider_name, txn.amount, event.amount, event.reference,
        )
        mark_failed(
            db, event.reference,
            reason=f"Amount mismatch (expected {txn.amount}, got {event.amount}).",
            provider_payload=event.raw_payload,
        )
        return {"ok": True, "kind": "amount_mismatch"}

    if event.status == "successful":
        # Check for duplicates BEFORE marking success
        duplicate_of = find_duplicate_transaction(
            db,
            payer_user_id=txn.payer_user_id,
            payer_group_id=txn.payer_group_id,
            transaction_type=txn.transaction_type,
            related_object_id=txn.related_object_id,
            within_minutes=5,
        )

        mark_successful(
            db, event.reference,
            provider_payload=event.raw_payload,
            provider_reference=event.provider_reference,
        )

        # Generate invoice + receipt
        try:
            generate_receipt(db, txn.id)
        except Exception:
            logger.exception("[webhook] receipt generation failed for %s", txn.id)

        # Fire downstream handler
        try:
            handle_payment_success(db, txn.id, event.reference)
        except Exception:
            logger.exception("[webhook] downstream handler failed for %s", txn.id)

        # Duplicate → auto-refund
        if duplicate_of:
            try:
                auto_refund_duplicate(db, duplicate_of, txn)
            except Exception:
                logger.exception(
                    "[webhook] auto-refund failed for %s (dup of %s)",
                    txn.id, duplicate_of.id,
                )

        return {"ok": True, "kind": "payment_success", "transaction_id": txn.id}

    if event.status == "failed":
        mark_failed(
            db, event.reference,
            reason=raw.get("reason", "Provider reported failure."),
            provider_payload=event.raw_payload,
        )
        return {"ok": True, "kind": "payment_failure", "transaction_id": txn.id}

    # Pending / unknown status
    return {"ok": True, "kind": "pending", "status": event.status}


# ═════════════════════════════════════════════════════════════════════════
# PROVIDER ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════

@router.post("/mpesa")
async def mpesa_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    headers = dict(request.headers)
    return _process_webhook(db, PROVIDER_MPESA, raw, headers)


@router.post("/card")
async def card_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    headers = dict(request.headers)
    return _process_webhook(db, PROVIDER_CARD, raw, headers)


@router.post("/bank")
async def bank_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    headers = dict(request.headers)
    return _process_webhook(db, PROVIDER_BANK, raw, headers)


@router.post("/manual")
async def manual_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    headers = dict(request.headers)
    return _process_webhook(db, PROVIDER_MANUAL, raw, headers)