"""
Subscription gate resolver — Module 005.

Determines whether a student is gated from a given assessment based on:
  - The assessment's mandate type
  - The student's subscription state (via Module 012)

Rules:
  - institution_mandated   → never gated
  - community_contribution → never gated
  - platform_native        → gated iff subscription is expired (past grace)
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.assessment import (
    Assessment, AssessmentAuditLog,
    MANDATE_INSTITUTION, MANDATE_PLATFORM, MANDATE_COMMUNITY,
    AUDIT_SUBSCRIPTION_GATE,
)
from app.models.group import GroupMembership
# Module 012 — only Subscription is imported (no status constant exists)
from app.models.financial import Subscription


logger = logging.getLogger(__name__)


class GateError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# PUBLIC
# ─────────────────────────────────────────────────────────────────────────

def check_student_gate(
    db: Session, *, student_id: str, assessment: Assessment,
    log_decision: bool = True,
) -> dict:
    """
    Returns:
        {
          "gated": bool,
          "reason": str | None,
          "subscription_state": str | None,
        }
    """
    mandate = assessment.mandate_type

    if mandate in (MANDATE_INSTITUTION, MANDATE_COMMUNITY):
        result = {"gated": False, "reason": None, "subscription_state": None}
        if log_decision:
            _log_gate(db, assessment.id, student_id, result)
        return result

    if mandate != MANDATE_PLATFORM:
        raise GateError(f"Unknown mandate type '{mandate}'.", 500)

    # platform_native → check subscription
    sub_state = _resolve_student_subscription_state(db, student_id)

    if sub_state["status"] in ("active", "grace", "trial", "expiring"):
        result = {
            "gated": False,
            "reason": None,
            "subscription_state": sub_state["status"],
        }
    else:
        result = {
            "gated": True,
            "reason": sub_state.get("reason") or "Subscription expired.",
            "subscription_state": sub_state["status"],
        }

    if log_decision:
        _log_gate(db, assessment.id, student_id, result)
    return result


def ensure_student_can_start(
    db: Session, *, student_id: str, assessment: Assessment,
) -> None:
    """Raise 403 if the student is gated."""
    decision = check_student_gate(
        db, student_id=student_id, assessment=assessment, log_decision=True,
    )
    if decision["gated"]:
        raise GateError(
            "Your group's subscription has expired. "
            "Renew to access this assessment.",
            status_code=403,
        )


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _resolve_student_subscription_state(
    db: Session, student_id: str,
) -> dict:
    """
    Resolve the student's subscription state. Considers:
      - Solo subscription (if any active)
      - Group subscriptions for every active group the student is in
    Returns the most favourable state (active > grace > expired).
    """
    now = _now()

    # Solo subscription
    solo = db.query(Subscription).filter(
        Subscription.subscriber_type == "solo",
        Subscription.user_id == student_id,
    ).order_by(Subscription.period_end.desc()).first()

    states: list[dict] = []
    if solo:
        states.append(_subscription_to_state(solo, now))

    # Group subscriptions for every active group
    group_ids = [
        r[0] for r in db.query(GroupMembership.group_id).filter(
            GroupMembership.user_id == student_id,
            GroupMembership.status == "active",
        ).all()
    ]
    if group_ids:
        group_subs = db.query(Subscription).filter(
            Subscription.subscriber_type == "group",
            Subscription.group_id.in_(group_ids),
        ).all()
        for gs in group_subs:
            states.append(_subscription_to_state(gs, now))

    if not states:
        return {"status": "expired", "reason": "No active subscription."}

    # Best state wins
    priority = {"active": 4, "expiring": 3, "grace": 2, "trial": 2,
                "expired": 1, "suspended": 0, "cancelled": 0}
    best = max(states, key=lambda s: priority.get(s["status"], 0))
    return best


def _subscription_to_state(sub: Subscription, now: datetime) -> dict:
    """Reduce a Subscription row to a simple state dict."""
    status = getattr(sub, "status", None)

    # Cancelled or suspended — no access
    if status in ("cancelled", "suspended"):
        return {"status": status, "reason": f"Subscription {status}."}

    # Trial
    if status == "trial":
        if sub.period_end and sub.period_end > now:
            return {"status": "trial", "reason": None}
        return {"status": "expired", "reason": "Trial ended."}

    # Grace / expired / active based on period_end
    if sub.period_end is None:
        return {"status": "expired", "reason": "No period end recorded."}

    if sub.period_end > now:
        # If it ends within 10 days, mark as expiring (still grants access)
        if (sub.period_end - now) <= timedelta(days=10):
            return {"status": "expiring", "reason": None}
        return {"status": "active", "reason": None}

    # Past period_end — check the 7-day grace window
    grace_end = sub.period_end + timedelta(days=7)
    if grace_end > now:
        return {"status": "grace", "reason": None}

    return {"status": "expired", "reason": "Subscription period ended."}


def _log_gate(
    db: Session, assessment_id: str, student_id: str, result: dict,
) -> None:
    try:
        db.add(AssessmentAuditLog(
            assessment_id=assessment_id,
            actor_id=student_id,
            action=AUDIT_SUBSCRIPTION_GATE,
            new_value=(
                f"gated={result['gated']} "
                f"state={result.get('subscription_state')}"
            ),
        ))
        db.flush()
    except Exception:
        logger.exception("Failed to log gate decision")
        # Do not let audit logging failure block the gate decision
        db.rollback()