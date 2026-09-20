"""
Invite & slug security helpers — Module 003.

Centralises the primitives that make the group invite system hard to abuse:

  - Non-guessable slug generation
  - Non-guessable invite-token generation (hashed at rest)
  - Enrollment verification helper (checks a visitor against a group)
  - Logging helper for every invite-related hit

Rate limiting is handled by the existing rate-limit store; this module
exposes the fingerprint keys those rules key on.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.academic import Course, School
from app.models.group import Group, GroupMembership

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

INVITE_TOKEN_LENGTH = 32          # URL-safe base64, ~192 bits of entropy
INVITE_TOKEN_EXPIRY_DAYS = 7
SLUG_SUFFIX_LENGTH = 8            # ~40 bits of entropy
SLUG_MAX_LENGTH = 80


# ============================================================================
# SLUG GENERATION
# ============================================================================

def _slugify(name: str) -> str:
    """
    Turn 'ICT Year 2 Group A' into 'ict-year-2-group-a'.
    Strips everything except a-z, 0-9, and hyphens.
    """
    cleaned = []
    prev_hyphen = False
    for ch in name.lower():
        if ch.isalnum():
            cleaned.append(ch)
            prev_hyphen = False
        elif ch in (" ", "-", "_", "/"):
            if not prev_hyphen and cleaned:
                cleaned.append("-")
                prev_hyphen = True
    result = "".join(cleaned).strip("-")
    return result or "group"


def _random_suffix() -> str:
    """8 characters from the base32 alphabet (excluding ambiguous chars)."""
    alphabet = "23456789abcdefghjkmnpqrstuvwxyz"  # no 0/O/1/I/l
    return "".join(secrets.choice(alphabet) for _ in range(SLUG_SUFFIX_LENGTH))


def generate_unique_slug(db: Session, group_name: str) -> str:
    """
    Generate a unique, non-guessable slug for a group.

    Format: <slugified-name>-<random-suffix>
    Example: ict-year-2-group-a-x7k4p9m2

    Retries up to 5 times on the extremely unlikely collision.
    """
    base = _slugify(group_name)
    # Cap base so total stays under SLUG_MAX_LENGTH
    max_base_len = SLUG_MAX_LENGTH - SLUG_SUFFIX_LENGTH - 1
    if len(base) > max_base_len:
        base = base[:max_base_len].rstrip("-")

    for _ in range(5):
        candidate = f"{base}-{_random_suffix()}"
        existing = db.query(Group).filter(Group.slug == candidate).first()
        if not existing:
            return candidate

    # Extremely unlikely — fall back to a longer suffix
    while True:
        candidate = f"{base}-{_random_suffix()}{_random_suffix()}"
        if not db.query(Group).filter(Group.slug == candidate).first():
            return candidate


# ============================================================================
# INVITE TOKEN
# ============================================================================

def generate_invite_token() -> str:
    """URL-safe token, ~192 bits of entropy."""
    return secrets.token_urlsafe(INVITE_TOKEN_LENGTH)


def hash_invite_token(token: str) -> str:
    """SHA-256 hex digest of the token — stored at rest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invite_token_expiry(now: datetime | None = None) -> datetime:
    """Default: 7 days from now."""
    base = now or datetime.now(timezone.utc)
    return base + timedelta(days=INVITE_TOKEN_EXPIRY_DAYS)


# ============================================================================
# ENROLLMENT VERIFICATION
# ============================================================================

def visitor_matches_group(
    db: Session, visitor_id: str, group: Group,
) -> tuple[bool, str | None]:
    """
    Check whether the visitor's academic context matches the group's.

    Returns (matches, reason_if_not).

    Rules:
      - Visitor's institution_id must match
      - Visitor's course_id must match
      - Visitor's semester_id must match
      - If the group has a combination_id, visitor must be on that combination
    """
    from app.models.academic import StudentEnrollment
    from app.models.user import User

    user = db.query(User).filter(User.id == visitor_id).first()
    if not user:
        return False, "Account not found."
    if user.institution_id and user.institution_id != group.institution_id:
        return False, "You are not enrolled at this institution."

    # Find the visitor's active enrollment in the group's semester
    enrollment = (
        db.query(StudentEnrollment)
        .filter(
            StudentEnrollment.user_id == visitor_id,
            StudentEnrollment.course_id == group.course_id,
            StudentEnrollment.semester_id == group.semester_id,
            StudentEnrollment.status == "active",
        )
        .first()
    )
    if not enrollment:
        return False, (
            "You are not enrolled in this course for this semester."
        )

    if group.combination_id and enrollment.combination_id != group.combination_id:
        return False, "Your subject combination does not match this group."

    return True, None


# ============================================================================
# RATE-LIMIT FINGERPRINTS
# ============================================================================

def fingerprint_ip(ip: str | None) -> str:
    """Used to key per-IP rate limits on preview hits."""
    return f"invite:ip:{ip or 'unknown'}"


def fingerprint_user(user_id: str) -> str:
    """Used to key per-user request-submission rate limits."""
    return f"invite:user:{user_id}"


def fingerprint_group(group_id: str) -> str:
    """Used to key per-group traffic flood detection."""
    return f"invite:group:{group_id}"


# ============================================================================
# AUDIT LOGGER
# ============================================================================

def log_invite_event(
    db: Session,
    *,
    event_type: str,
    group_id: str | None = None,
    actor_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    extra: dict | None = None,
) -> None:
    """
    Append an audit record for any invite-related hit.

    Falls back to Python logging if the audit table is not ready —
    the service layer will call this from every invite endpoint.
    """
    try:
        from app.services.audit_service import log_auth_event
        log_auth_event(
            db,
            event_type=event_type,
            user_id=actor_id,
            ip_address=ip_address,
            user_agent=user_agent,
            event_data={"group_id": group_id, **(extra or {})},
        )
    except Exception:
        # Never let logging failure break the request path.
        logger.warning(
            "invite_audit_fallback event=%s group=%s actor=%s ip=%s",
            event_type, group_id, actor_id, ip_address,
        )