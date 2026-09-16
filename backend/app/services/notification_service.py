"""
Notification dispatch.

Single entry point for sending notifications to a user, respecting
their preferences (except for security-critical events).

Combines:
  - Email (via provider registry)
  - SMS (via provider registry)
  - In-app (persisted to notifications table — implemented separately)
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
) -> None:
    """
    Send notification to a user, respecting their preferences.

    - force_send=True bypasses preferences (used for security alerts).
    - Mandatory event prefixes also bypass preferences.
    - Non-mandatory events are gated by preference flags.
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

    # ── Email ──────────────────────────────────────────────
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

    # ── SMS ────────────────────────────────────────────────
    if (prefs.sms_enabled or mandatory) and sms_body:
        if user.phone:
            try:
                get_sms_provider().send(to=user.phone, message=sms_body)
            except Exception:
                logger.exception("SMS delivery failed for %s", user.phone)

    # ── In-app ─────────────────────────────────────────────
    # Persistence to a notifications table is handled elsewhere.
    # Left as a hook here so future code doesn't forget.
    _persist_in_app(db, user_id=user_id, subject=subject, body=text_body or html_body)


# ── Helpers ────────────────────────────────────────────────

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
    db: Session, *, user_id: str, subject: str, body: str | None
) -> None:
    """
    Hook for persisting in-app notifications. Currently a no-op —
    will be wired when the notifications table is introduced.
    """
    try:
        # Placeholder until notifications table exists
        pass
    except Exception:
        logger.exception("Failed to persist in-app notification for %s", user_id)