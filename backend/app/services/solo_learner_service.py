"""
Solo learner service — Module 003 (Solo Path).

Monthly subscription: KSh 70. Solo learners can discover peers and
schedule 1-on-1 sessions. When they join a group, the solo subscription
stops and the group's pool takes over.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.academic import Course, StudentEnrollment
from app.models.group import GroupMembership
from app.models.solo_learner import (
    SoloSubscription, SoloLearningSession, SOLO_MONTHLY_FEE,
)
from app.models.user import User


logger = logging.getLogger(__name__)


SUBSCRIPTION_DAYS = 30
EXPIRING_WARNING_DAYS = 5


class SoloError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# SUBSCRIPTION
# ============================================================================

def subscribe(
    db: Session, user_id: str, payment_reference: str,
) -> SoloSubscription:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise SoloError("User not found.", 404)
    if user.user_type != "student":
        raise SoloError("Only students can subscribe as solo learners.", 403)

    # Reject if user is an active member of any group
    active_group = db.query(GroupMembership).filter(
        GroupMembership.user_id == user_id,
        GroupMembership.status == "active",
    ).first()
    if active_group:
        raise SoloError(
            "You are an active group member. Leave the group before "
            "subscribing as solo.",
            409,
        )

    # Cancel any existing active subscription
    existing = db.query(SoloSubscription).filter(
        SoloSubscription.user_id == user_id,
        SoloSubscription.status.in_(("active", "expiring")),
    ).first()
    if existing:
        existing.status = "cancelled"
        existing.cancelled_at = _now()
        existing.cancelled_reason = "Superseded by new subscription"

    now = _now()
    sub = SoloSubscription(
        user_id=user_id,
        status="active",
        amount_paid=SOLO_MONTHLY_FEE,
        currency="KES",
        period_start=now,
        period_end=now + timedelta(days=SUBSCRIPTION_DAYS),
        payment_reference=payment_reference,
        paid_at=now,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def get_active_subscription(db: Session, user_id: str) -> SoloSubscription | None:
    return (
        db.query(SoloSubscription)
        .filter(
            SoloSubscription.user_id == user_id,
            SoloSubscription.status.in_(("active", "expiring")),
        )
        .order_by(SoloSubscription.period_end.desc())
        .first()
    )


def is_solo_learner(db: Session, user_id: str) -> bool:
    sub = get_active_subscription(db, user_id)
    if not sub:
        return False
    return sub.period_end > _now()


def cancel_subscription(
    db: Session, user_id: str, reason: str | None = None,
) -> SoloSubscription:
    sub = get_active_subscription(db, user_id)
    if not sub:
        raise SoloError("No active solo subscription found.", 404)
    sub.status = "cancelled"
    sub.cancelled_at = _now()
    sub.cancelled_reason = reason or "Cancelled by user"
    db.commit()
    db.refresh(sub)
    return sub


def expire_stale_subscriptions(db: Session) -> int:
    now = _now()
    stale = db.query(SoloSubscription).filter(
        SoloSubscription.status.in_(("active", "expiring")),
        SoloSubscription.period_end <= now,
    ).all()
    for s in stale:
        s.status = "expired"
    if stale:
        db.commit()
    return len(stale)


def mark_expiring(db: Session) -> int:
    now = _now()
    threshold = now + timedelta(days=EXPIRING_WARNING_DAYS)
    soon = db.query(SoloSubscription).filter(
        SoloSubscription.status == "active",
        SoloSubscription.period_end > now,
        SoloSubscription.period_end <= threshold,
    ).all()
    for s in soon:
        s.status = "expiring"
    if soon:
        db.commit()
    return len(soon)


# ============================================================================
# DISCOVERY
# ============================================================================

def discover_solo_learners(
    db: Session, viewer_id: str,
    course_id: str | None = None,
    year_level: int | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """
    Return solo learners in the same institution as the viewer.
    Excludes the viewer themselves.
    """
    viewer = db.query(User).filter(User.id == viewer_id).first()
    if not viewer:
        raise SoloError("Viewer not found.", 404)

    now = _now()
    q = (
        db.query(SoloSubscription)
        .join(User, SoloSubscription.user_id == User.id)
        .filter(
            SoloSubscription.status.in_(("active", "expiring")),
            SoloSubscription.period_end > now,
            SoloSubscription.user_id != viewer_id,
        )
    )
    if viewer.institution_id:
        q = q.filter(User.institution_id == viewer.institution_id)

    # Cursor-based pagination on subscription id
    if cursor:
        q = q.filter(SoloSubscription.id < cursor)

    rows = q.order_by(SoloSubscription.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    next_cursor = rows[-1].id if has_more and rows else None

    cards = []
    for sub in rows:
        user = db.query(User).filter(User.id == sub.user_id).first()
        if not user:
            continue
        # Fetch enrollment for course/year context
        enrollment = (
            db.query(StudentEnrollment)
            .filter(
                StudentEnrollment.user_id == user.id,
                StudentEnrollment.status == "active",
            )
            .order_by(StudentEnrollment.created_at.desc())
            .first()
        )
        cards.append({
            "user_id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "institution_id": user.institution_id,
            "course_id": enrollment.course_id if enrollment else None,
            "year_level": None,
            "interests": None,
        })

    return {
        "learners": cards,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ============================================================================
# SESSIONS
# ============================================================================

def propose_session(
    db: Session, initiator_id: str, data,
) -> SoloLearningSession:
    if initiator_id == data.partner_id:
        raise SoloError("You cannot schedule a session with yourself.", 400)

    if not is_solo_learner(db, initiator_id):
        raise SoloError("You need an active solo subscription.", 403)

    partner = db.query(User).filter(User.id == data.partner_id).first()
    if not partner:
        raise SoloError("Partner not found.", 404)
    if not is_solo_learner(db, data.partner_id):
        raise SoloError("Partner is not an active solo learner.", 409)

    s = SoloLearningSession(
        initiator_id=initiator_id,
        partner_id=data.partner_id,
        title=data.title.strip(),
        description=data.description,
        scheduled_at=data.scheduled_at,
        duration_minutes=data.duration_minutes,
        status="proposed",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def respond_to_session(
    db: Session, session_id: str, user_id: str, data,
) -> SoloLearningSession:
    s = db.query(SoloLearningSession).filter(
        SoloLearningSession.id == session_id,
    ).first()
    if not s:
        raise SoloError("Session not found.", 404)
    if s.partner_id != user_id:
        raise SoloError("Only the invited partner may respond.", 403)
    if s.status != "proposed":
        raise SoloError(f"Session already {s.status}.", 409)

    now = _now()
    if data.accept:
        s.status = "accepted"
        s.accepted_at = now
    else:
        s.status = "declined"
        s.declined_at = now
        s.declined_reason = data.decline_reason

    db.commit()
    db.refresh(s)
    return s


def cancel_session(
    db: Session, session_id: str, user_id: str,
) -> SoloLearningSession:
    s = db.query(SoloLearningSession).filter(
        SoloLearningSession.id == session_id,
    ).first()
    if not s:
        raise SoloError("Session not found.", 404)
    if user_id not in (s.initiator_id, s.partner_id):
        raise SoloError("Only session participants may cancel.", 403)
    if s.status in ("completed", "cancelled"):
        raise SoloError(f"Session is already {s.status}.", 409)

    s.status = "cancelled"
    db.commit()
    db.refresh(s)
    return s


def complete_session(
    db: Session, session_id: str, user_id: str,
) -> SoloLearningSession:
    s = db.query(SoloLearningSession).filter(
        SoloLearningSession.id == session_id,
    ).first()
    if not s:
        raise SoloError("Session not found.", 404)
    if user_id not in (s.initiator_id, s.partner_id):
        raise SoloError("Only session participants may mark complete.", 403)
    if s.status != "accepted":
        raise SoloError("Only accepted sessions can be completed.", 409)
    s.status = "completed"
    s.completed_at = _now()
    db.commit()
    db.refresh(s)
    return s


def list_my_sessions(db: Session, user_id: str) -> list[SoloLearningSession]:
    return (
        db.query(SoloLearningSession)
        .filter(
            (SoloLearningSession.initiator_id == user_id)
            | (SoloLearningSession.partner_id == user_id)
        )
        .order_by(SoloLearningSession.scheduled_at.desc())
        .all()
    )


# ============================================================================
# GROUP TRANSITION
# ============================================================================

def on_join_group(db: Session, user_id: str) -> None:
    """Called when a solo learner becomes an active group member."""
    sub = get_active_subscription(db, user_id)
    if not sub:
        return
    sub.status = "cancelled"
    sub.cancelled_at = _now()
    sub.cancelled_reason = "User joined a group"
    db.commit()


def on_leave_group(
    db: Session, user_id: str, payment_reference: str | None = None,
) -> dict:
    """
    Called when a group member wants to return to solo status.
    Requires KSh 70 payment. 14-day grace period.
    """
    # Check if user is an active group member
    active_groups = db.query(GroupMembership).filter(
        GroupMembership.user_id == user_id,
        GroupMembership.status == "active",
    ).all()

    now = _now()
    grace_end = now + timedelta(days=14)

    if not payment_reference:
        return {
            "grace_period_started_at": now.isoformat(),
            "grace_period_ends_at": grace_end.isoformat(),
            "message": (
                "A 14-day grace period has started. Pay KSh 70 to exit "
                "your group and return to solo status."
            ),
        }

    # With payment: immediately leave all groups and start solo sub
    for m in active_groups:
        m.status = "left"
        m.left_at = now

    db.flush()
    sub = SoloSubscription(
        user_id=user_id,
        status="active",
        amount_paid=SOLO_MONTHLY_FEE,
        currency="KES",
        period_start=now,
        period_end=now + timedelta(days=SUBSCRIPTION_DAYS),
        payment_reference=payment_reference,
        paid_at=now,
    )
    db.add(sub)
    db.commit()
    return {
        "message": "You are now a solo learner.",
        "subscription_id": sub.id,
    }