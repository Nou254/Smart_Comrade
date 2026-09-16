"""
Pending-registration cache.

Holds user registration data in cache until email verification succeeds.
Only on successful verification is the data promoted to the `users` table.

Key layout:
    pending:register:{sha256(email_lower)}       -> record dict
    pending:register:phone:{sha256(phone)}       -> {"email": email}

TTL: 24 hours.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.cache_store import CacheStore, build_cache
from app.core.config import settings

logger = logging.getLogger(__name__)


PENDING_REGISTRATION_TTL_SECONDS = 24 * 3600


_cache: CacheStore | None = None


def _get_cache() -> CacheStore:
    global _cache
    if _cache is None:
        _cache = build_cache(
            getattr(settings, "CACHE_BACKEND", "memory"),
            getattr(settings, "REDIS_URL", None),
        )
    return _cache


def _email_key(email: str) -> str:
    h = hashlib.sha256(email.lower().strip().encode()).hexdigest()
    return f"pending:register:{h}"


def _phone_key(phone: str) -> str:
    h = hashlib.sha256(phone.strip().encode()).hexdigest()
    return f"pending:register:phone:{h}"


def store_pending(
    *,
    email: str,
    phone: str | None,
    first_name: str,
    last_name: str,
    password_hash: str,
    user_type: str,
    external_subtype: str | None = None,
    institution_id: str | None = None,
    institutional_email: str | None = None,
    department: str | None = None,
    title: str | None = None,
    domain_verified: bool = False,
    tos_version: str | None = None,
    privacy_version: str | None = None,
    otp_hash: str,
    otp_expires_at: datetime,
    purpose: str = "registration",
    extra: dict | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "email": email.lower().strip(),
        "phone": phone.strip() if phone else None,
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "password_hash": password_hash,
        "user_type": user_type,
        "external_subtype": external_subtype,
        "institution_id": institution_id,
        "institutional_email": (
            institutional_email.lower().strip() if institutional_email else None
        ),
        "department": department,
        "title": title,
        "domain_verified": domain_verified,
        "tos_version": tos_version,
        "privacy_version": privacy_version,
        "tos_accepted_at": now.isoformat(),
        "privacy_accepted_at": now.isoformat(),
        "otp_hash": otp_hash,
        "otp_expires_at": otp_expires_at.isoformat(),
        "otp_attempts": 0,
        "otp_resends": 0,
        "purpose": purpose,
        "created_at": now.isoformat(),
    }
    if extra:
        record["extra"] = extra

    cache = _get_cache()
    cache.set(_email_key(email), record, PENDING_REGISTRATION_TTL_SECONDS)
    if phone:
        cache.set(
            _phone_key(phone),
            {"email": email.lower().strip()},
            PENDING_REGISTRATION_TTL_SECONDS,
        )


def get_pending(email: str) -> dict | None:
    return _get_cache().get(_email_key(email))


def update_pending(email: str, **fields) -> bool:
    cache = _get_cache()
    record = cache.get(_email_key(email))
    if not record:
        return False
    record.update(fields)
    cache.set(_email_key(email), record, PENDING_REGISTRATION_TTL_SECONDS)
    return True


def delete_pending(email: str) -> None:
    cache = _get_cache()
    record = cache.get(_email_key(email))
    if record and record.get("phone"):
        cache.delete(_phone_key(record["phone"]))
    cache.delete(_email_key(email))


def is_phone_pending(phone: str) -> bool:
    entry = _get_cache().get(_phone_key(phone))
    return bool(entry and entry.get("email"))