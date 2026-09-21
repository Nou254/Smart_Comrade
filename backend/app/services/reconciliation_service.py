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

    _compare(db, batch)
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
    Stub comparison. Real implementation would call provider.transaction_list()
    and compare to our local records.
    """
    our_txns = db.query(Transaction).filter(
        Transaction.provider == batch.provider,
        Transaction.initiated_at >= batch.period_start,
        Transaction.initiated_at <= batch.period_end,
    ).all()

    batch.total_transactions = len(our_txns)

    matched = 0
    missing = 0
    mismatched = 0
    for t in our_txns:
        if t.status in (TXN_SUCCESSFUL, TXN_SETTLED):
            matched += 1
        elif t.status in (TXN_FAILED, TXN_PENDING_PROVIDER):
            missing += 1

    batch.matched_count = matched
    batch.missing_in_provider_count = missing
    batch.mismatched_amount_count = mismatched
    batch.unclaimed_count = 0
    batch.resolved_count = matched
    batch.flagged_count = missing + mismatched


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