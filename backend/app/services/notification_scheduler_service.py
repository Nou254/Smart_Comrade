"""
Financial notification scheduler — Module 012.

All scheduling is timezone-aware:
  - Stored in UTC
  - Delivery computed in the user's local timezone
  - Default hour: 10:00 local
  - Sleep window: 21:00–07:00 local (non-urgent deferred to 07:00)
  - Urgent notifications bypass the sleep window

Delivery channels:
  - Card users: SMS + in-app
  - M-Pesa group members: in-app
  - M-Pesa group leaders: in-app + email
  - M-Pesa solo: in-app + email
"""
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.financial import (
    FinancialNotification,
    CHANNEL_IN_APP, CHANNEL_EMAIL, CHANNEL_SMS,
    NOTIF_PENDING, NOTIF_DELIVERED, NOTIF_FAILED, NOTIF_HELD_SLEEP,
    NOTIF_CANCELLED,
    DEFAULT_NOTIFICATION_HOUR_LOCAL,
    SLEEP_WINDOW_START_HOUR, SLEEP_WINDOW_END_HOUR,
)


logger = logging.getLogger(__name__)


class NotificationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# SCHEDULING
# ─────────────────────────────────────────────────────────────────────────

def schedule_notification(
    db: Session, *,
    user_id: str, category: str, channel: str,
    scheduled_at_utc: datetime,
    local_timezone: str = "Africa/Nairobi",
    local_hour: int = DEFAULT_NOTIFICATION_HOUR_LOCAL,
    is_urgent: bool = False,
    transaction_id: str | None = None,
    subscription_id: str | None = None,
    payload: dict | None = None,
) -> FinancialNotification:
    """
    Create a scheduled notification. Applies the sleep-window rule to
    defer non-urgent notifications that would otherwise land between
    21:00 and 07:00 in the user's local time.
    """
    if channel not in (CHANNEL_IN_APP, CHANNEL_EMAIL, CHANNEL_SMS):
        raise NotificationError(f"Unknown channel '{channel}'.", 400)

    deferred_from: datetime | None = None

    if not is_urgent:
        safe_time = _next_safe_delivery_time(scheduled_at_utc, local_timezone)
        if safe_time != scheduled_at_utc:
            deferred_from = scheduled_at_utc
            scheduled_at_utc = safe_time

    n = FinancialNotification(
        user_id=user_id,
        transaction_id=transaction_id,
        subscription_id=subscription_id,
        category=category,
        channel=channel,
        scheduled_at_utc=scheduled_at_utc,
        scheduled_local_hour=local_hour,
        local_timezone=local_timezone,
        delivery_status=NOTIF_PENDING,
        is_urgent=is_urgent,
        deferred_from_utc=deferred_from,
        payload_json=payload,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def _next_safe_delivery_time(
    dt_utc: datetime, local_tz_name: str,
) -> datetime:
    """
    Return a UTC datetime that falls outside the sleep window in the
    given local timezone. If the input is inside the window, we defer
    to 07:00 the next local morning.
    """
    try:
        tz = ZoneInfo(local_tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Africa/Nairobi")

    local_dt = dt_utc.astimezone(tz)
    local_hour = local_dt.hour

    if local_hour >= SLEEP_WINDOW_START_HOUR:
        # Defer to 07:00 the next local day
        next_local = (local_dt + timedelta(days=1)).replace(
            hour=SLEEP_WINDOW_END_HOUR, minute=0, second=0, microsecond=0,
        )
        return next_local.astimezone(timezone.utc)
    if local_hour < SLEEP_WINDOW_END_HOUR:
        # Same day, defer to 07:00 local
        same_day_7 = local_dt.replace(
            hour=SLEEP_WINDOW_END_HOUR, minute=0, second=0, microsecond=0,
        )
        return same_day_7.astimezone(timezone.utc)
    return dt_utc


# ─────────────────────────────────────────────────────────────────────────
# DELIVERY (called by cron)
# ─────────────────────────────────────────────────────────────────────────

def deliver_due_notifications(
    db: Session, *, batch_size: int = 200,
) -> dict:
    """
    Pick up all pending notifications whose scheduled_at_utc has arrived
    and dispatch them through the platform's in-app / email / SMS
    providers. Failed notifications are retried up to three times.
    """
    now = _now()
    rows = db.query(FinancialNotification).filter(
        FinancialNotification.delivery_status == NOTIF_PENDING,
        FinancialNotification.scheduled_at_utc <= now,
    ).order_by(FinancialNotification.scheduled_at_utc).limit(batch_size).all()

    delivered = 0
    failed = 0
    for n in rows:
        try:
            _dispatch(db, n)
            n.delivery_status = NOTIF_DELIVERED
            n.delivered_at_utc = now
            n.delivery_attempts = (n.delivery_attempts or 0) + 1
            n.last_attempt_at = now
            delivered += 1
        except Exception as e:
            n.delivery_attempts = (n.delivery_attempts or 0) + 1
            n.last_attempt_at = now
            n.delivery_error = str(e)[:500]
            if n.delivery_attempts >= 3:
                n.delivery_status = NOTIF_FAILED
                failed += 1
            logger.exception("[notif] delivery failed for %s", n.id)

    if rows:
        db.commit()
    return {"delivered": delivered, "failed": failed, "total": len(rows)}


_DEFAULT_TITLES: dict[str, str] = {
    "subscription_expiring": "Your subscription is expiring soon",
    "subscription_expired": "Your subscription has expired",
    "payment_received": "Payment received",
    "payment_failed": "Payment failed",
    "refund_processed": "Refund processed",
}


def _dispatch(db: Session, n: FinancialNotification) -> None:
    """
    Deliver one financial notification through its channel:
      - in_app → persistent notification row (notification_store)
      - email  → configured email provider
      - sms    → configured SMS provider

    Raises on failure so the caller can retry and record the error.
    """
    payload = n.payload_json or {}
    title = payload.get("title") or _DEFAULT_TITLES.get(
        n.category, "Smart Comrade account update",
    )
    body = payload.get("body") or _render_body(n, payload)

    if n.channel == CHANNEL_IN_APP:
        from app.services.notification_store import create_for_users
        create_for_users(
            db,
            user_ids=[n.user_id],
            category="administrative",
            title=title,
            body=body,
            priority="important" if n.is_urgent else "normal",
            source_type="financial_notification",
            source_id=n.id,
            link_url=payload.get("link_url"),
            payload_json=payload,
            is_system_generated=True,
        )
        return

    from app.models.user import User

    user = db.query(User).filter(User.id == n.user_id).first()
    if not user:
        raise NotificationError(
            f"User {n.user_id} not found for delivery.", 404,
        )

    if n.channel == CHANNEL_EMAIL:
        if not user.email:
            raise NotificationError("User has no email address.", 400)
        from app.core.providers import get_email_provider
        get_email_provider().send(
            to=user.email,
            subject=title,
            html_body=f"<p>{body}</p>",
            text_body=body,
        )
        return

    if n.channel == CHANNEL_SMS:
        if not user.phone:
            raise NotificationError("User has no phone number.", 400)
        from app.core.providers import get_sms_provider
        get_sms_provider().send(to=user.phone, message=body)
        return

    raise NotificationError(f"Unknown channel '{n.channel}'.", 400)


def _render_body(n: FinancialNotification, payload: dict) -> str:
    """Compose a readable fallback body when the payload has none."""
    amount = payload.get("amount")
    currency = payload.get("currency") or "KES"
    if amount is not None:
        return f"{n.category.replace('_', ' ').capitalize()}: {amount} {currency}."
    return f"{n.category.replace('_', ' ').capitalize()}."


# ─────────────────────────────────────────────────────────────────────────
# HIGH-LEVEL SCHEDULERS (called by other services)
# ─────────────────────────────────────────────────────────────────────────

def schedule_subscription_reminders(
    db: Session, subscription_id: str,
    categories: list[str],
    days_offsets: list[int],
    *,
    payload_base: dict | None = None,
) -> int:
    """
    Given a subscription, schedule a set of reminders at N days before
    period_end. Uses the subscription owner's timezone and preferred
    channel.
    """
    from app.models.financial import Subscription
    from app.models.user import User

    sub = db.query(Subscription).filter(
        Subscription.id == subscription_id,
    ).first()
    if not sub or not sub.period_end:
        return 0

    # Determine the user who receives the notification
    target_user_id = sub.user_id
    if sub.subscriber_type == "group" and sub.group_id:
        from app.models.group import Group
        g = db.query(Group).filter(Group.id == sub.group_id).first()
        if g:
            target_user_id = g.creator_id

    if not target_user_id:
        return 0

    user = db.query(User).filter(User.id == target_user_id).first()
    tz_name = (user.timezone if user else None) or "Africa/Nairobi"

    count = 0
    for cat, offset in zip(categories, days_offsets):
        when = sub.period_end - timedelta(days=offset)
        schedule_notification(
            db,
            user_id=target_user_id,
            category=cat,
            channel=CHANNEL_IN_APP,
            scheduled_at_utc=when,
            local_timezone=tz_name,
            subscription_id=sub.id,
            payload=payload_base,
        )
        count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def list_notifications(
    db: Session, *,
    user_id: str | None = None,
    status: str | None = None,
    category: str | None = None,
    limit: int = 100,
) -> list[FinancialNotification]:
    q = db.query(FinancialNotification)
    if user_id:
        q = q.filter(FinancialNotification.user_id == user_id)
    if status:
        q = q.filter(FinancialNotification.delivery_status == status)
    if category:
        q = q.filter(FinancialNotification.category == category)
    return q.order_by(
        FinancialNotification.scheduled_at_utc.desc(),
    ).limit(limit).all()