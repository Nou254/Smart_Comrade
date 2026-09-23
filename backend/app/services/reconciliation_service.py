"""
Reconciliation service — Module 012.

Matches what we recorded against what the provider says actually
happened. Produces a batch report.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.financial import (
    Transaction, ReconciliationBatch, FinancialAuditLog,
    TXN_SUCCESSFUL, TXN_SETTLED, TXN_FAILED, TXN_PENDING_PROVIDER,
)


logger = logging.getLogger(__name__)


class ReconciliationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# BATCH
# ─────────────────────────────────────────────────────────────────────────

def start_batch(
    db: Session, *, provider: str, period_start: datetime,
    period_end: datetime, run_by: str, notes: str | None = None,
) -> ReconciliationBatch:
    batch = ReconciliationBatch(
        batch_reference=f"REC-{secrets.token_hex(6).upper()}",
        provider=provider,
        period_start=period_start,
        period_end=period_end,
        started_at=_now(),
        status="running",
        run_by=run_by,
        notes=notes,
    )
    db.add(batch)
    db.flush()

    try:
        _compare(db, batch)
    except ReconciliationError as e:
        batch.status = "failed"
        batch.completed_at = _now()
        batch.notes = (
            f"{batch.notes} | {e.message}" if batch.notes else e.message
        )
        _log(db, batch.id, "reconciliation.failed", run_by,
             details={"error": e.message})
        db.commit()
        raise

    batch.completed_at = _now()
    batch.status = "completed"
    _log(db, batch.id, "reconciliation.completed", run_by,
         details={
             "matched": batch.matched_count,
             "missing": batch.missing_in_provider_count,
             "mismatched": batch.mismatched_amount_count,
             "unclaimed": batch.unclaimed_count,
         })
    db.commit()
    db.refresh(batch)
    return batch


# ─────────────────────────────────────────────────────────────────────────
# COMPARISON
# ─────────────────────────────────────────────────────────────────────────

def _compare(db: Session, batch: ReconciliationBatch) -> None:
    """
    Match our local ledger against the provider's view of the period.

    Preferred path is a provider ledger listing. Providers that only offer
    per-reference lookups (M-Pesa) fall back to verifying each transaction
    individually with `verify_payment()`.

    Raises ReconciliationError if the provider could not be reached for any
    transaction, so the batch is recorded as failed rather than silently
    reporting a clean match.
    """
    from app.services.payment_provider_service import (
        get_provider, PaymentProviderError,
    )

    our_txns = db.query(Transaction).filter(
        Transaction.provider == batch.provider,
        Transaction.initiated_at >= batch.period_start,
        Transaction.initiated_at <= batch.period_end,
    ).all()

    batch.total_transactions = len(our_txns)

    provider = get_provider(batch.provider)

    provider_rows = None
    try:
        provider_rows = provider.transaction_list(
            period_start=batch.period_start,
            period_end=batch.period_end,
        )
    except PaymentProviderError as e:
        logger.info(
            "[reconciliation] %s has no ledger listing (%s); verifying "
            "per reference instead",
            batch.provider, e.message,
        )

    matched = 0
    missing = 0
    mismatched = 0
    unclaimed = 0

    if provider_rows is not None:
        by_reference = {
            r.reference: r for r in provider_rows if r.reference
        }
        by_provider_reference = {
            r.provider_reference: r for r in provider_rows if r.provider_reference
        }
        used: set[int] = set()

        for t in our_txns:
            row = by_reference.get(t.reference) or by_provider_reference.get(
                t.provider_reference or "",
            )
            if row is None:
                missing += 1
                continue
            used.add(id(row))
            if row.status == "successful" and row.amount == t.amount:
                matched += 1
            else:
                mismatched += 1

        unclaimed = len([r for r in provider_rows if id(r) not in used])

    else:
        provider_errors = 0
        for t in our_txns:
            try:
                confirmed = provider.verify_payment(
                    reference=t.reference,
                    amount=t.amount,
                    provider_reference=t.provider_reference,
                )
            except PaymentProviderError as e:
                provider_errors += 1
                logger.warning(
                    "[reconciliation] verification failed for %s: %s",
                    t.reference, e.message,
                )
                missing += 1
                continue

            we_recorded = t.status in (TXN_SUCCESSFUL, TXN_SETTLED)
            if we_recorded and confirmed:
                matched += 1
            elif we_recorded and not confirmed:
                mismatched += 1
            elif confirmed and not we_recorded:
                # Provider says paid but we never recorded it.
                mismatched += 1
            else:
                missing += 1

        if our_txns and provider_errors == len(our_txns):
            raise ReconciliationError(
                "Provider verification was unavailable for every transaction.",
                502,
            )

    batch.matched_count = matched
    batch.missing_in_provider_count = missing
    batch.mismatched_amount_count = mismatched
    batch.unclaimed_count = unclaimed
    batch.resolved_count = matched
    batch.flagged_count = missing + mismatched + unclaimed


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def list_batches(
    db: Session, *, provider: str | None = None,
    status: str | None = None, limit: int = 100,
) -> list[ReconciliationBatch]:
    q = db.query(ReconciliationBatch)
    if provider:
        q = q.filter(ReconciliationBatch.provider == provider)
    if status:
        q = q.filter(ReconciliationBatch.status == status)
    return q.order_by(ReconciliationBatch.started_at.desc()).limit(limit).all()


def get_batch(db: Session, batch_id: str) -> ReconciliationBatch:
    b = db.query(ReconciliationBatch).filter(
        ReconciliationBatch.id == batch_id,
    ).first()
    if not b:
        raise ReconciliationError("Reconciliation batch not found.", 404)
    return b


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _log(
    db: Session, batch_id: str, event_type: str, actor_id: str | None,
    *, details: dict | None = None,
) -> None:
    db.add(FinancialAuditLog(
        event_type=event_type,
        actor_id=actor_id,
        details_json={"batch_id": batch_id, **(details or {})},
    ))