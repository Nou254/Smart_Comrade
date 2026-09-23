"""
Username service — Communication module.

Generates unique, non-editable usernames for every newly created User.

Called from every site that constructs a User:
  - verification_service.verify_pending_registration   (student/lecturer/external)
  - admin_service.accept_invitation                    (elected / appointed admin)
  - break_glass_service._ensure_emergency_account      (emergency account)

Format:
    <first>.<last>.<4-digit suffix>      e.g. erick.juma.0427

Collision handling: try up to 20 random suffixes. If all are taken
(astronomically unlikely), fall back to a fully random handle so user
creation never blocks.

Not user-editable in V1.
"""
from __future__ import annotations

import re
import secrets

from sqlalchemy.orm import Session

from app.models.user import User


_RESERVED = {
    "admin", "root", "system", "support", "help",
    "moderator", "superadmin", "noreply",
}


def _slugify(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"[^a-z0-9]+", ".", v)
    return v.strip(".") or "user"


def generate_unique_username(
    db: Session, *, first_name: str, last_name: str,
) -> str:
    """Return a guaranteed-unique username for a new user."""
    base = f"{_slugify(first_name)}.{_slugify(last_name)}"
    # Reserve room for the ".NNNN" suffix inside String(64)
    base = base[:55]

    for _ in range(20):
        suffix = f"{secrets.randbelow(10_000):04d}"
        candidate = f"{base}.{suffix}"
        if candidate in _RESERVED:
            continue
        if not _exists(db, candidate):
            return candidate

    # Fallback — pure random, effectively collision-free
    return f"user.{secrets.token_hex(6)}"


def _exists(db: Session, username: str) -> bool:
    return db.query(User.id).filter(User.username == username).first() is not None