"""
Subscription service — Module 012.

Owns group + solo subscription lifecycle.

Grace periods:
  - Group trial            : 14 days
  - Solo trial             : 14 days
  - Group expiring warning : 10 days
  - Solo expiring warning  : 5 days
  - Group lapse grace      : 3 days
  - Solo access window     : 5 days
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.financial import (
    Subscription, FinancialAuditLog,
    SUBSCRIBER_GROUP, SUBSCRIBER_SOLO,
    PLAN_MONTHLY, PLAN_YEARLY,
    SUB_TRIAL, SUB_ACTIVE, SUB_EXPIRING, SUB_GRACE, SUB_EXPIRED,
    SUB_SUSPENDED, SUB_CANCELLED,
    GROUP_TRIAL_DAYS, SOLO_TRIAL_DAYS,
    GROUP_EXPIRING_WARNING_DAYS, SOLO_EXPIRING_WARNING_DAYS,
    GROUP_LAPSE_GRACE_DAYS, SOLO_ACCESS_WINDOW_DAYS,
    FEE_AMOUNTS, TXN_GROUP_SUBSCRIPTION, TXN_GROUP_SUBSCRIPTION_ANNUAL,
    TXN_SOLO_SUBSCRIPTION, TXN_SOLO_SUBSCRIPTION_ANNUAL,
    EXTRA_MEMBER_FEE_CAP,
)
from app.services.transaction_service import (
    initiate_transaction, TransactionError,
)


logger = logging.getLogger(__name__)


class SubscriptionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# FEE COMPUTATION
# ─────────────────────────────────────────────────────────────────────────

def compute_group_fee(member_count: int, plan_type: str = PLAN_MONTHLY) -> dict:
    """
    Base KSh 100 for ≤30 members.
    Members 31–50 add KSh 20 each (capped at KSh 500 of extras).
    Members >50 → cap reached; total = KSh 600/month max.
    """
    if plan_type == PLAN_YEARLY:
        base = FEE_AMOUNTS[TXN_GROUP_SUBSCRIPTION_ANNUAL]
        return {
            "base_amount": base,
            "extra_member_amount": 0,
            "total_amount": base,
            "plan_type": plan_type,
            "member_count": member_count,
        }

    base = FEE_AMOUNTS[TXN_GROUP_SUBSCRIPTION]
    extra_members = max(0, member_count - 30)
    extra_amount = min(extra_members * FEE_AMOUNTS["extra_member_fee"], EXTRA_MEMBER_FEE_CAP)
    return {
        "base_amount": base,
        "extra_member_amount": extra_amount,
        "total_amount": base + extra_amount,
        "plan_type": plan_type,
        "member_count": member_count,
    }


def compute_solo_fee(plan_type: str = PLAN_MONTHLY) -> dict:
    if plan_type == PLAN_YEARLY:
        amt = FEE_AMOUNTS[TXN_SOLO_SUBSCRIPTION_ANNUAL]
    else:
        amt = FEE_AMOUNTS[TXN_SOLO_SUBSCRIPTION]
    return {
        "base_amount": amt,
        "extra_member_amount": 0,
        "total_amount": amt,
        "plan_type": plan_type,
    }


# ─────────────────────────────────────────────────────────────────────────
# TRIAL
# ─────────────────────────────────────────────────────────────────────────

def start_group_trial(
    db: Session, group_id: str,
) -> Subscription:
    return _start_trial(
        db, SUBSCRIBER_GROUP, group_id=group_id,
        trial_days=GROUP_TRIAL_DAYS, member_count=1,
    )


def start_solo_trial(
    db: Session, user_id: str,
) -> Subscription:
    return _start_trial(
        db, SUBSCRIBER_SOLO, user_id=user_id,
        trial_days=SOLO_TRIAL_DAYS, member_count=1,
    )


def _start_trial(
    db: Session, subscriber_type: str,
    *, group_id: str | None = None, user_id: str | None = None,
    trial_days: int, member_count: int,
) -> Subscription:
    existing = get_active_subscription(
        db, subscriber_type, group_id=group_id, user_id=user_id,
    )
    if existing:
        return existing

    now = _now()
    if subscriber_type == SUBSCRIBER_GROUP:
        fee = compute_group_fee(member_count)
    else:
        fee = compute_solo_fee()

    sub = Subscription(
        subscriber_type=subscriber_type,
        group_id=group_id,
        user_id=user_id,
        plan_type=fee["plan_type"],
        base_amount=fee["base_amount"],
        extra_member_amount=fee["extra_member_amount"],
        total_amount=fee["total_amount"],
        currency="KES",
        member_count_at_payment=member_count,
        status=SUB_TRIAL,
        trial_ends_at=now + timedelta(days=trial_days),
        period_start=now,
        period_end=now + timedelta(days=trial_days),
    )
    db.add(sub)
    _log(db, sub, "subscription.trial_started", details={"days": trial_days})
    db.commit()
    db.refresh(sub)
    return sub


# ─────────────────────────────────────────────────────────────────────────
# PAYMENT / ACTIVATION
# ─────────────────────────────────────────────────────────────────────────

def initiate_subscription_payment(
    db: Session, subscription_id: str, provider_name: str,
    *, payer_phone: str | None = None, payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    sub = _get(db, subscription_id)
    if sub.status not in (SUB_TRIAL, SUB_ACTIVE, SUB_EXPIRING, SUB_GRACE, SUB_EXPIRED):
        raise SubscriptionError(
            f"Cannot initiate payment in status '{sub.status}'.", 409,
        )

    # Recompute fee in case member count changed
    if sub.subscriber_type == SUBSCRIBER_GROUP:
        fee = compute_group_fee(sub.member_count_at_payment, sub.plan_type)
    else:
        fee = compute_solo_fee(sub.plan_type)

    sub.base_amount = fee["base_amount"]
    sub.extra_member_amount = fee["extra_member_amount"]
    sub.total_amount = fee["total_amount"]

    txn_type = _txn_type_for_subscription(sub)
    return initiate_transaction(
        db,
        transaction_type=txn_type,
        amount=sub.total_amount,
        provider_name=provider_name,
        payer_user_id=sub.user_id,
        payer_group_id=sub.group_id,
        related_object_type="subscription",
        related_object_id=sub.id,
        description=f"Subscription {sub.plan_type} for {sub.subscriber_type}",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip,
        ua=ua,
    )


def activate_subscription(
    db: Session, subscription_id: str, transaction_id: str,
) -> Subscription:
    sub = _get(db, subscription_id)
    now = _now()

    months = 12 if sub.plan_type == PLAN_YEARLY else 1
    days = 365 if sub.plan_type == PLAN_YEARLY else 30

    sub.status = SUB_ACTIVE
    sub.period_start = now
    sub.period_end = now + timedelta(days=days)
    sub.last_renewal_transaction_id = transaction_id

    if sub.subscriber_type == SUBSCRIBER_GROUP:
        sub.expiring_warning_ends_at = sub.period_end - timedelta(
            days=GROUP_EXPIRING_WARNING_DAYS,
        )
        sub.grace_period_ends_at = sub.period_end + timedelta(
            days=GROUP_LAPSE_GRACE_DAYS,
        )
        sub.solo_access_window_ends_at = None
    else:
        sub.expiring_warning_ends_at = sub.period_end - timedelta(
            days=SOLO_EXPIRING_WARNING_DAYS,
        )
        sub.solo_access_window_ends_at = sub.period_end + timedelta(
            days=SOLO_ACCESS_WINDOW_DAYS,
        )
        sub.grace_period_ends_at = None

    _log(db, sub, "subscription.activated", details={
        "period_end": sub.period_end.isoformat(),
        "plan_months": months,
    })
    db.commit()
    db.refresh(sub)
    return sub


# ─────────────────────────────────────────────────────────────────────────
# PERIODIC STATE TRANSITIONS (called by cron/scheduler)
# ─────────────────────────────────────────────────────────────────────────

def mark_expiring(db: Session) -> int:
    """Move active subscriptions into 'expiring' state when they enter
    the warning window."""
    now = _now()
    rows = db.query(Subscription).filter(
        Subscription.status == SUB_ACTIVE,
        Subscription.expiring_warning_ends_at.isnot(None),
        Subscription.expiring_warning_ends_at <= now,
        Subscription.period_end > now,
    ).all()
    for sub in rows:
        sub.status = SUB_EXPIRING
        _log(db, sub, "subscription.expiring", from_state=SUB_ACTIVE, to_state=SUB_EXPIRING)
    if rows:
        db.commit()
    return len(rows)


def enter_grace(db: Session) -> int:
    """Move subscriptions past period_end into grace (groups) or access window (solo)."""
    now = _now()
    rows = db.query(Subscription).filter(
        Subscription.status.in_((SUB_ACTIVE, SUB_EXPIRING)),
        Subscription.period_end <= now,
    ).all()
    count = 0
    for sub in rows:
        if sub.subscriber_type == SUBSCRIBER_GROUP:
            sub.status = SUB_GRACE
            if not sub.grace_period_ends_at:
                sub.grace_period_ends_at = sub.period_end + timedelta(
                    days=GROUP_LAPSE_GRACE_DAYS,
                )
        else:
            sub.status = SUB_GRACE   # solo uses same state, different timer
            if not sub.solo_access_window_ends_at:
                sub.solo_access_window_ends_at = sub.period_end + timedelta(
                    days=SOLO_ACCESS_WINDOW_DAYS,
                )
        _log(db, sub, "subscription.grace_entered",
             to_state=SUB_GRACE)
        count += 1
    if rows:
        db.commit()
    return count


def mark_expired(db: Session) -> int:
    """Subscriptions past grace → expired."""
    now = _now()
    rows = db.query(Subscription).filter(
        Subscription.status == SUB_GRACE,
    ).all()
    count = 0
    for sub in rows:
        deadline = (
            sub.grace_period_ends_at if sub.subscriber_type == SUBSCRIBER_GROUP
            else sub.solo_access_window_ends_at
        )
        if deadline and deadline <= now:
            sub.status = SUB_EXPIRED
            _log(db, sub, "subscription.expired", to_state=SUB_EXPIRED)
            count += 1
    if rows:
        db.commit()
    return count


def cancel_subscription(
    db: Session, subscription_id: str, reason: str | None = None,
) -> Subscription:
    sub = _get(db, subscription_id)
    sub.status = SUB_CANCELLED
    sub.cancelled_at = _now()
    sub.cancelled_reason = reason or "Cancelled by user"
    _log(db, sub, "subscription.cancelled", to_state=SUB_CANCELLED,
         details={"reason": reason})
    db.commit()
    db.refresh(sub)
    return sub


def suspend_subscription(
    db: Session, subscription_id: str, reason: str,
) -> Subscription:
    sub = _get(db, subscription_id)
    sub.status = SUB_SUSPENDED
    _log(db, sub, "subscription.suspended", to_state=SUB_SUSPENDED,
         details={"reason": reason})
    db.commit()
    db.refresh(sub)
    return sub


# ─────────────────────────────────────────────────────────────────────────
# GROUP → SOLO TRANSITION (auto-cancel)
# ─────────────────────────────────────────────────────────────────────────

def cancel_solo_on_group_join(
    db: Session, user_id: str, reason: str = "User joined a group",
) -> Subscription | None:
    sub = get_active_subscription(db, SUBSCRIBER_SOLO, user_id=user_id)
    if not sub:
        return None
    return cancel_subscription(db, sub.id, reason=reason)


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_active_subscription(
    db: Session, subscriber_type: str,
    *, group_id: str | None = None, user_id: str | None = None,
) -> Subscription | None:
    q = db.query(Subscription).filter(
        Subscription.subscriber_type == subscriber_type,
        Subscription.status.in_((SUB_TRIAL, SUB_ACTIVE, SUB_EXPIRING, SUB_GRACE)),
    )
    if group_id:
        q = q.filter(Subscription.group_id == group_id)
    if user_id:
        q = q.filter(Subscription.user_id == user_id)
    return q.order_by(Subscription.period_end.desc().nullslast()).first()


def get_subscription(db: Session, subscription_id: str) -> Subscription:
    return _get(db, subscription_id)


def list_due_for_renewal(db: Session, within_days: int = 10) -> list[Subscription]:
    now = _now()
    threshold = now + timedelta(days=within_days)
    return db.query(Subscription).filter(
        Subscription.status.in_((SUB_ACTIVE, SUB_EXPIRING)),
        Subscription.period_end.isnot(None),
        Subscription.period_end <= threshold,
    ).order_by(Subscription.period_end).all()


def list_due_for_grace_transition(db: Session) -> list[Subscription]:
    now = _now()
    return db.query(Subscription).filter(
        Subscription.status.in_((SUB_ACTIVE, SUB_EXPIRING)),
        Subscription.period_end <= now,
    ).all()


def list_due_for_expiry(db: Session) -> list[Subscription]:
    now = _now()
    rows = db.query(Subscription).filter(
        Subscription.status == SUB_GRACE,
    ).all()
    ready = []
    for sub in rows:
        deadline = (
            sub.grace_period_ends_at if sub.subscriber_type == SUBSCRIBER_GROUP
            else sub.solo_access_window_ends_at
        )
        if deadline and deadline <= now:
            ready.append(sub)
    return ready


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _get(db: Session, subscription_id: str) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).first()
    if not sub:
        raise SubscriptionError("Subscription not found.", 404)
    return sub


def _txn_type_for_subscription(sub: Subscription) -> str:
    if sub.subscriber_type == SUBSCRIBER_GROUP:
        return (
            TXN_GROUP_SUBSCRIPTION_ANNUAL if sub.plan_type == PLAN_YEARLY
            else TXN_GROUP_SUBSCRIPTION
        )
    return (
        TXN_SOLO_SUBSCRIPTION_ANNUAL if sub.plan_type == PLAN_YEARLY
        else TXN_SOLO_SUBSCRIPTION
    )


def _log(
    db: Session, sub: Subscription, event_type: str,
    *, from_state: str | None = None, to_state: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(FinancialAuditLog(
        event_type=event_type,
        subscription_id=sub.id,
        from_state=from_state,
        to_state=to_state,
        details_json=details,
    ))