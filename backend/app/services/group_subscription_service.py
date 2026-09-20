"""
Group subscription service — Module 003 Phase 5.

State machine:
    trial → active → expiring → expired
                ↑
            renewal

Pricing (V1):
    ≤30 members  → KSh 100
    31-50        → KSh 100 + (members - 30) × KSh 20
    >50          → extra capped at KSh 500 → max KSh 600

Election eligibility:
    member_count >= 10 AND subscription is 'active' AND period_end is
    more than 10 days away.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.group import Group, GroupMembership
from app.models.group_subscription import GroupSubscription

logger = logging.getLogger(__name__)


TRIAL_DAYS = 14
EXPIRY_WARNING_DAYS = 10
BASE_FEE = 100
BASE_MEMBER_LIMIT = 30
PER_MEMBER_FEE = 20
EXTRA_FEE_CAP = 500


class SubscriptionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# PRICING
# ============================================================================

def calculate_amount(member_count: int) -> int:
    """
    KSh 100 base for ≤30 members.
    KSh 20/member beyond 30, capped at KSh 500 (max total: KSh 600).
    """
    if member_count < 1:
        member_count = 1
    extras = max(0, member_count - BASE_MEMBER_LIMIT)
    extra_charge = min(extras * PER_MEMBER_FEE, EXTRA_FEE_CAP)
    return BASE_FEE + extra_charge


def calculate_breakdown(member_count: int) -> dict:
    extras = max(0, member_count - BASE_MEMBER_LIMIT)
    raw_extra = extras * PER_MEMBER_FEE
    capped_extra = min(raw_extra, EXTRA_FEE_CAP)
    return {
        "base_fee": BASE_FEE,
        "members_over_limit": extras,
        "raw_extra_fee": raw_extra,
        "capped_extra_fee": capped_extra,
        "was_capped": raw_extra > EXTRA_FEE_CAP,
        "total": BASE_FEE + capped_extra,
    }


# ============================================================================
# SUBSCRIPTION LIFECYCLE
# ============================================================================

def create_trial_subscription(
    db: Session, group_id: str, member_count: int,
) -> GroupSubscription:
    """14-day free trial starting now."""
    now = _now()
    period_end = now + timedelta(days=TRIAL_DAYS)

    sub = GroupSubscription(
        group_id=group_id,
        status="trial",
        is_trial=True,
        member_count_at_payment=member_count,
        amount_paid=0,
        currency="KES",
        period_start=now,
        period_end=period_end,
    )
    db.add(sub)
    db.flush()

    _refresh_group_cache(db, group_id)
    return sub


def activate_subscription(
    db: Session,
    group_id: str,
    member_count: int,
    payment_reference: str,
    duration_days: int = 30,
) -> GroupSubscription:
    """Record a successful payment and create the active subscription window."""
    now = _now()
    amount = calculate_amount(member_count)

    sub = GroupSubscription(
        group_id=group_id,
        status="active",
        is_trial=False,
        member_count_at_payment=member_count,
        amount_paid=amount,
        currency="KES",
        period_start=now,
        period_end=now + timedelta(days=duration_days),
        payment_reference=payment_reference,
        paid_at=now,
    )
    db.add(sub)
    db.flush()

    _refresh_group_cache(db, group_id)
    return sub


def get_active_subscription(
    db: Session, group_id: str,
) -> GroupSubscription | None:
    """Return the current non-terminal subscription, if any."""
    return (
        db.query(GroupSubscription)
        .filter(
            GroupSubscription.group_id == group_id,
            GroupSubscription.status.in_(
                ("trial", "active", "expiring")
            ),
        )
        .order_by(GroupSubscription.period_end.desc())
        .first()
    )


def is_subscription_current(
    db: Session, group_id: str,
) -> tuple[bool, str | None]:
    """
    Current = active (not trial) AND period_end is more than 10 days away.
    Returns (is_current, reason_if_not).
    """
    sub = get_active_subscription(db, group_id)
    if not sub:
        return False, "No active subscription."
    if sub.status == "trial":
        return False, "Group is still in trial period."
    if sub.status in ("expired", "cancelled", "suspended"):
        return False, f"Subscription is {sub.status}."

    now = _now()
    if sub.period_end <= now:
        return False, "Subscription period has ended."

    days_left = (sub.period_end - now).days
    if days_left <= EXPIRY_WARNING_DAYS:
        return False, (
            f"Subscription expires in {days_left} day(s). "
            "Renew at least 11 days before the election window."
        )

    return True, None


def expire_stale_subscriptions(db: Session) -> int:
    """
    Sweep: move any subscription past its period_end to 'expired', and
    flip the group's cached status accordingly. Idempotent.
    """
    now = _now()
    stale = (
        db.query(GroupSubscription)
        .filter(
            GroupSubscription.status.in_(("active", "expiring", "trial")),
            GroupSubscription.period_end <= now,
        )
        .all()
    )
    for sub in stale:
        sub.status = "expired"
        _refresh_group_cache(db, sub.group_id)

    if stale:
        db.commit()
    return len(stale)


def mark_expiring(db: Session) -> int:
    """
    Sweep: any active subscription with ≤10 days left is set to 'expiring'.
    Idempotent.
    """
    now = _now()
    threshold = now + timedelta(days=EXPIRY_WARNING_DAYS)
    soon = (
        db.query(GroupSubscription)
        .filter(
            GroupSubscription.status == "active",
            GroupSubscription.period_end > now,
            GroupSubscription.period_end <= threshold,
        )
        .all()
    )
    for sub in soon:
        sub.status = "expiring"
        _refresh_group_cache(db, sub.group_id)

    if soon:
        db.commit()
    return len(soon)


def _refresh_group_cache(db: Session, group_id: str) -> None:
    """Keep the denormalized fields on Group in sync."""
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        return
    sub = get_active_subscription(db, group_id)
    if sub:
        group.subscription_status = sub.status
        group.subscription_expires_at = sub.period_end
        if sub.status == "trial":
            group.trial_ends_at = sub.period_end
    else:
        group.subscription_status = "expired"
        group.subscription_expires_at = None


# ============================================================================
# ELECTION ELIGIBILITY
# ============================================================================

REQUIRED_MEMBERS_FOR_ELECTION = 10


def check_election_eligibility(
    db: Session, group_id: str,
) -> dict:
    """
    Return a dict with:
        eligible: bool
        member_count: int
        required_members: int
        subscription_status: str
        subscription_current: bool
        blockers: list[str]
        notes: str | None
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise SubscriptionError("Group not found.", 404)

    member_count = group.member_count
    blockers: list[str] = []

    if member_count < REQUIRED_MEMBERS_FOR_ELECTION:
        missing = REQUIRED_MEMBERS_FOR_ELECTION - member_count
        blockers.append(
            f"Needs {missing} more member(s) to reach {REQUIRED_MEMBERS_FOR_ELECTION}."
        )

    is_current, reason = is_subscription_current(db, group_id)
    if not is_current and reason:
        blockers.append(reason)

    sub = get_active_subscription(db, group_id)
    sub_status = sub.status if sub else "none"

    return {
        "group_id": group_id,
        "eligible": len(blockers) == 0,
        "member_count": member_count,
        "required_members": REQUIRED_MEMBERS_FOR_ELECTION,
        "subscription_status": sub_status,
        "subscription_current": is_current,
        "blockers": blockers,
        "notes": None,
    }


def refresh_member_count(db: Session, group_id: str) -> int:
    """
    Recompute the group's cached member count from actual memberships.
    Only counts rows with status='active'.
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise SubscriptionError("Group not found.", 404)

    count = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.status == "active",
        )
        .count()
    )
    group.member_count = count
    db.flush()
    return count