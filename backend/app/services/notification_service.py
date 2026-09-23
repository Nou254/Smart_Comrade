"""
Notification dispatch.

Single entry point for sending notifications to a user, respecting
their preferences (except for security-critical events).

Combines:
  - Email (via provider registry)
  - SMS (via provider registry)
  - In-app (persisted via notification_store)
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.providers import get_email_provider, get_sms_provider
from app.models.notification_preference import (
    NotificationPreference,
    is_mandatory,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ============================================================================
# Notification category inference
# ============================================================================
#
# The Communication module's persistent store categorizes notifications.
# Existing call sites use `event_key` strings like "assessment.submitted"
# or "security.new_device". We map the prefix to a canonical category so
# the store can index and filter correctly.

_EVENT_KEY_TO_CATEGORY: dict[str, str] = {
    "assessment": "assessment",
    "election": "election",
    "impeachment": "impeachment",
    "event": "event",
    "announcement": "announcement",
    "opportunity": "opportunity",
    "project": "project",
    "security": "security",
    "auth": "security",
    "session": "security",
    "password": "security",
    "account": "administrative",
    "group": "academic",
    "unit": "academic",
    "evaluation": "assessment",
    "finance": "administrative",
    "subscription": "administrative",
    "refund": "administrative",
    "transfer": "administrative",
    "club": "event",
    "community": "announcement",
}

_CRITICAL_CATEGORIES = {"security", "emergency"}


def _infer_category(event_key: str | None) -> str:
    if not event_key:
        return "system"
    prefix = event_key.split(".", 1)[0].lower()
    return _EVENT_KEY_TO_CATEGORY.get(prefix, "system")


def _infer_priority(category: str, *, force_urgent: bool = False) -> str:
    if force_urgent or category in _CRITICAL_CATEGORIES:
        return "critical"
    if category in ("election", "impeachment", "assessment"):
        return "important"
    return "normal"


# ============================================================================
# Public API
# ============================================================================

def notify_user(
    db: Session,
    *,
    user_id: str,
    subject: str,
    html_body: str | None = None,
    text_body: str | None = None,
    sms_body: str | None = None,
    event_key: str | None = None,
    force_send: bool = False,
    source_type: str | None = None,
    source_id: str | None = None,
    link_url: str | None = None,
    payload: dict | None = None,
) -> None:
    """
    Send notification to a user, respecting their preferences.

    - force_send=True bypasses preferences (used for security alerts).
    - Mandatory event prefixes also bypass preferences.
    - Non-mandatory events are gated by preference flags.
    - Every notification is persisted to the Communication store.

    New kwargs (Communication module):
      - source_type / source_id : loose reference to the triggering entity
      - link_url                : deep-link target in the UI
      - payload                 : structured data for the client
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning("notify_user: user %s not found", user_id)
        return

    prefs = _get_or_create_prefs(db, user_id)

    mandatory = force_send or is_mandatory(event_key)
    allowed = mandatory or _allowed_by_prefs(prefs, event_key)

    if not allowed:
        logger.debug(
            "Skipping notification for %s (event=%s) per user preferences",
            user_id, event_key,
        )
        return

    # ── Email ──────────────────────────────────────────────────────────
    if prefs.email_enabled or mandatory:
        if user.email and html_body:
            try:
                get_email_provider().send(
                    to=user.email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                )
            except Exception:
                logger.exception("Email delivery failed for %s", user.email)

    # ── SMS ────────────────────────────────────────────────────────────
    if (prefs.sms_enabled or mandatory) and sms_body:
        if user.phone:
            try:
                get_sms_provider().send(to=user.phone, message=sms_body)
            except Exception:
                logger.exception("SMS delivery failed for %s", user.phone)

    # ── In-app (persistent) ────────────────────────────────────────────
    _persist_in_app(
        db,
        user_id=user_id,
        subject=subject,
        body=text_body or html_body,
        event_key=event_key,
        source_type=source_type,
        source_id=source_id,
        link_url=link_url,
        payload=payload,
        force_urgent=mandatory and (event_key or "").startswith("security."),
    )


# ============================================================================
# Helpers
# ============================================================================

def users_with_roles(db: Session, role_codes: tuple[str, ...]) -> list[str]:
    """
    Return the ids of users holding any of the given role codes with an
    active, non-expired assignment. Used by services that notify role
    holders rather than named users.
    """
    from datetime import datetime, timezone

    from app.models.role import Role, UserRole

    now = datetime.now(timezone.utc)
    rows = (
        db.query(UserRole)
        .join(Role, UserRole.role_id == Role.id)
        .filter(Role.code.in_(role_codes), UserRole.status == "active")
        .all()
    )
    return [
        r.user_id for r in rows
        if r.end_date is None or r.end_date > now
    ]


def _get_or_create_prefs(db: Session, user_id: str) -> NotificationPreference:
    prefs = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id)
        .first()
    )
    if prefs:
        return prefs
    prefs = NotificationPreference(user_id=user_id)
    db.add(prefs)
    db.commit()
    db.refresh(prefs)
    return prefs


def _allowed_by_prefs(prefs: NotificationPreference, event_key: str | None) -> bool:
    if not event_key:
        return True

    if event_key.startswith("group."):
        return prefs.group_activity
    if event_key.startswith("announcement."):
        return prefs.announcements
    if event_key.startswith("election."):
        return prefs.elections
    if event_key.startswith("assessment."):
        return prefs.assessments
    if event_key.startswith("event."):
        return prefs.events
    if event_key.startswith("opportunity."):
        return prefs.opportunities
    if event_key.startswith("marketing."):
        return prefs.marketing

    # Unknown category → allow by default
    return True


def _persist_in_app(
    db: Session,
    *,
    user_id: str,
    subject: str,
    body: str | None,
    event_key: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    link_url: str | None = None,
    payload: dict | None = None,
    force_urgent: bool = False,
) -> None:
    """
    Persist an in-app notification via the Communication store.

    Wrapped in try/except so that a failure to persist never blocks the
    caller. Email/SMS already fired; the store is best-effort.
    """
    try:
        from app.services.notification_store import create_for_users

        category = _infer_category(event_key)
        priority = _infer_priority(category, force_urgent=force_urgent)

        create_for_users(
            db,
            user_ids=[user_id],
            category=category,
            title=subject,
            body=body or subject,
            priority=priority,
            source_type=source_type,
            source_id=source_id,
            link_url=link_url,
            payload_json=payload,
            is_system_generated=True,
        )
    except Exception:
        logger.exception(
            "Failed to persist in-app notification for %s", user_id,
        )