"""
Security alerts.

Detects suspicious login events (new device / new IP) and dispatches
email notifications. Falls back silently on provider failures so login
is never blocked.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.user_agent_parser import parse as parse_ua
from app.models.user import User
from app.services.geo_service import lookup as geo_lookup

logger = logging.getLogger(__name__)


def detect_new_device(db: Session, user: User, user_agent: str | None,
                      ip: str | None) -> bool:
    """
    Return True if this (device fingerprint) hasn't been seen for this user.
    Fingerprint = device_type + os + browser (coarse, privacy-friendly).
    """
    parsed = parse_ua(user_agent)
    fingerprint = f"{parsed.device_type}|{parsed.os}|{parsed.browser}"

    known = getattr(user, "known_devices", None)
    if not known:
        return True

    return fingerprint not in known


def remember_device(db: Session, user: User, user_agent: str | None) -> None:
    """Persist this device fingerprint onto the user's known_devices list."""
    parsed = parse_ua(user_agent)
    fingerprint = f"{parsed.device_type}|{parsed.os}|{parsed.browser}"

    known = list(user.known_devices or [])
    if fingerprint in known:
        return

    known.append(fingerprint)
    # Keep the list bounded
    user.known_devices = known[-20:]
    db.commit()


def emit_new_device_alert(db: Session, user: User, user_agent: str | None,
                          ip: str | None) -> None:
    """
    Send the "new device" email. Safe to call always — errors are logged
    and swallowed so they never interrupt login.
    """
    from app.services.notification_service import notify_user
    from app.core.templates import email_templates

    try:
        parsed = parse_ua(user_agent)
        location = geo_lookup(ip) if ip else None
        location_str = f"{parsed.friendly}" + (f" · {location}" if location else "")

        subject, html, text = email_templates.new_device_login(
            name=user.first_name or "there",
            device=location_str,
            ip=ip,
            when=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        notify_user(
            db, user_id=user.id,
            subject=subject, html_body=html, text_body=text,
            event_key="security.new_device",
            force_send=True,   # security alerts bypass preferences
        )
    except Exception:
        logger.exception("Failed to send new-device alert to %s", user.id)