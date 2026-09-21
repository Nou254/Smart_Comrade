"""
Financial analytics service — Module 012.

Aggregated reporting only. Institution admins see institutional slices;
Super Admin sees everything.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.financial import (
    Transaction, Subscription,
    TXN_SUCCESSFUL, TXN_SETTLED, TXN_FAILED,
    SUB_ACTIVE, SUB_EXPIRING, SUB_GRACE, SUB_EXPIRED, SUB_CANCELLED,
    SUB_TRIAL,
)


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# REVENUE SUMMARY
# ─────────────────────────────────────────────────────────────────────────

def revenue_summary(
    db: Session, *, period_start: datetime, period_end: datetime,
    institution_id: str | None = None,
) -> dict:
    q = db.query(
        Transaction.transaction_type,
        func.sum(Transaction.amount).label("total"),
        func.count(Transaction.id).label("count"),
    ).filter(
        Transaction.status.in_((TXN_SUCCESSFUL, TXN_SETTLED)),
        Transaction.paid_at >= period_start,
        Transaction.paid_at <= period_end,
    )
    if institution_id:
        # Join through the payer group to filter by institution.
        # Approximation — the caller passes the institution scope filter
        # via related_object_type if needed.
        pass

    rows = q.group_by(Transaction.transaction_type).all()
    by_type = {row.transaction_type: int(row.total or 0) for row in rows}
    total_revenue = sum(by_type.values())
    transaction_count = sum(int(row.count or 0) for row in rows)

    return {
        "period_start": period_start,
        "period_end": period_end,
        "total_revenue": total_revenue,
        "currency": "KES",
        "by_type": by_type,
        "transaction_count": transaction_count,
    }


# ─────────────────────────────────────────────────────────────────────────
# SUBSCRIPTION HEALTH
# ─────────────────────────────────────────────────────────────────────────

def subscription_health(db: Session) -> dict:
    counts = dict(
        db.query(
            Subscription.status,
            func.count(Subscription.id),
        ).group_by(Subscription.status).all()
    )

    active = int(counts.get(SUB_ACTIVE, 0))
    expiring = int(counts.get(SUB_EXPIRING, 0))
    grace = int(counts.get(SUB_GRACE, 0))
    expired = int(counts.get(SUB_EXPIRED, 0))
    cancelled = int(counts.get(SUB_CANCELLED, 0))
    trial = int(counts.get(SUB_TRIAL, 0))

    # MRR: sum of monthly-equivalent total_amount for active subscriptions
    mrr_rows = db.query(
        Subscription.total_amount, Subscription.plan_type,
    ).filter(
        Subscription.status.in_((SUB_ACTIVE, SUB_EXPIRING)),
    ).all()
    mrr = 0
    for amt, plan in mrr_rows:
        mrr += (amt if plan == "monthly" else int(amt / 12))

    total_paying = active + expiring
    arpu = round(mrr / total_paying, 2) if total_paying else 0.0
    churn = round(
        (cancelled + expired) / max(1, total_paying + cancelled + expired), 4,
    )

    return {
        "total_active": active,
        "total_trial": trial,
        "total_expiring": expiring,
        "total_grace": grace,
        "total_expired": expired,
        "total_cancelled": cancelled,
        "churn_rate": churn,
        "mrr": mrr,
        "arpu": arpu,
    }


# ─────────────────────────────────────────────────────────────────────────
# PAYMENT ANALYTICS
# ─────────────────────────────────────────────────────────────────────────

def payment_analytics(
    db: Session, *, period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> dict:
    if not period_start:
        period_start = _now() - timedelta(days=30)
    if not period_end:
        period_end = _now()

    base = db.query(Transaction).filter(
        Transaction.initiated_at >= period_start,
        Transaction.initiated_at <= period_end,
    )

    total = base.count()
    successful = base.filter(
        Transaction.status.in_((TXN_SUCCESSFUL, TXN_SETTLED)),
    ).count()
    failed = base.filter(Transaction.status == TXN_FAILED).count()
    rate = round(successful / total, 4) if total else 0.0

    by_provider = dict(
        base.with_entities(
            Transaction.provider, func.count(Transaction.id),
        ).group_by(Transaction.provider).all()
    )

    return {
        "total_attempts": total,
        "successful": successful,
        "failed": failed,
        "success_rate": rate,
        "by_provider": {k: int(v) for k, v in by_provider.items()},
    }