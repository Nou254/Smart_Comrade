"""
Business logic for registration number verification — Module 002 completion.

Super Admin initiates a period for an institution. The Institution Rep
executes primary verification by matching (reg_number, email) pairs
against the roster. The County Rep collaborates on manual verification
and can add new entries to the roster for future use.

Pair-based matching rule:
  - A registration number is only valid when paired with the correct email.
  - The pair is the unit of verification.
  - Unverified students have their access restricted until they re-verify.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.academic import AcademicStructureAudit, Institution
from app.models.registration_verification import (
    InstitutionRegistrationNumber,
    InstitutionVerificationPeriod,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(
    db: Session, user_id: str | None, entity_type: str, entity_id: str,
    action: str, old_value: str | None = None, new_value: str | None = None,
    reason: str | None = None,
) -> None:
    db.add(AcademicStructureAudit(
        user_id=user_id, entity_type=entity_type, entity_id=entity_id,
        action=action, old_value=old_value, new_value=new_value, reason=reason,
    ))


def _normalise_email(email: str) -> str:
    return email.strip().lower()


# ============================================================================
# VERIFICATION PERIODS
# ============================================================================

def initiate_verification_period(
    db: Session, data, super_admin_id: str,
) -> InstitutionVerificationPeriod:
    institution = db.query(Institution).filter(
        Institution.id == data.institution_id
    ).first()
    if not institution:
        raise VerificationError("Institution not found.", 404)

    if data.start_date >= data.end_date:
        raise VerificationError("start_date must be before end_date.", 400)

    # One open period at a time.
    open_period = (
        db.query(InstitutionVerificationPeriod)
        .filter(
            InstitutionVerificationPeriod.institution_id == institution.id,
            InstitutionVerificationPeriod.status.in_(
                ("scheduled", "active", "extended")
            ),
        )
        .first()
    )
    if open_period:
        raise VerificationError(
            "An open verification period already exists for this institution.", 409,
        )

    period = InstitutionVerificationPeriod(
        institution_id=institution.id,
        initiated_by=super_admin_id,
        start_date=data.start_date,
        end_date=data.end_date,
        status="scheduled",
        notes=data.notes,
    )
    db.add(period)
    db.flush()

    _audit(
        db, super_admin_id, "InstitutionVerificationPeriod", period.id, "CREATE",
        new_value=f"institution={institution.code}",
    )
    db.commit()
    db.refresh(period)
    return period


def list_verification_periods(
    db: Session,
    institution_id: str | None = None,
    status: str | None = None,
) -> list[InstitutionVerificationPeriod]:
    q = db.query(InstitutionVerificationPeriod)
    if institution_id:
        q = q.filter(InstitutionVerificationPeriod.institution_id == institution_id)
    if status:
        q = q.filter(InstitutionVerificationPeriod.status == status)
    return q.order_by(InstitutionVerificationPeriod.start_date.desc()).all()


def get_verification_period(
    db: Session, period_id: str,
) -> InstitutionVerificationPeriod:
    p = (
        db.query(InstitutionVerificationPeriod)
        .filter(InstitutionVerificationPeriod.id == period_id)
        .first()
    )
    if not p:
        raise VerificationError("Verification period not found.", 404)
    return p


def extend_verification_period(
    db: Session, period_id: str, data, reviewer_id: str,
) -> InstitutionVerificationPeriod:
    period = get_verification_period(db, period_id)
    if period.status not in ("scheduled", "active", "extended"):
        raise VerificationError(
            f"Cannot extend a period in status '{period.status}'.", 409,
        )
    if data.new_end_date <= period.end_date:
        raise VerificationError(
            "new_end_date must be later than the current end_date.", 400,
        )

    period.extended_until = data.new_end_date
    period.extension_count = (period.extension_count or 0) + 1
    period.status = "extended"
    if data.notes:
        period.notes = (period.notes or "") + f"\n[Extension] {data.notes}"

    _audit(
        db, reviewer_id, "InstitutionVerificationPeriod", period.id, "EXTEND",
        old_value=str(period.end_date), new_value=str(data.new_end_date),
    )
    db.commit()
    db.refresh(period)
    return period


def complete_verification_period(
    db: Session, period_id: str, user_id: str,
) -> InstitutionVerificationPeriod:
    period = get_verification_period(db, period_id)
    if period.status == "completed":
        return period
    period.status = "completed"
    period.completed_at = _now()
    _refresh_counts(db, period)
    _audit(
        db, user_id, "InstitutionVerificationPeriod", period.id, "COMPLETE",
        new_value="completed",
    )
    db.commit()
    db.refresh(period)
    return period


def _refresh_counts(
    db: Session, period: InstitutionVerificationPeriod,
) -> None:
    """Recompute verified_count from the roster. Called on completion."""
    verified = (
        db.query(InstitutionRegistrationNumber)
        .filter(
            InstitutionRegistrationNumber.period_id == period.id,
            InstitutionRegistrationNumber.verified_at.isnot(None),
        )
        .count()
    )
    period.verified_count = verified


# ============================================================================
# ROSTER — bulk upload
# ============================================================================

def upload_roster(
    db: Session, data, uploader_id: str,
) -> dict:
    """
    Bulk upload of (reg_number, email) pairs. For each entry:
      - store the pair if not already known for this institution
      - attempt to match to a registered user by email
      - if matched, link the user and flip registration_number_verified=True
    """
    institution_id: str | None = None
    if data.period_id:
        period = get_verification_period(db, data.period_id)
        institution_id = period.institution_id
    else:
        # Roster entries must belong to some institution. Require the caller
        # to supply the period so the institution is unambiguous.
        raise VerificationError(
            "period_id is required so the roster is scoped to an institution.", 400,
        )

    matched = 0
    unmatched_stored = 0
    duplicates_skipped = 0
    errors: list[str] = []

    for entry in data.entries:
        reg = entry.reg_number.strip()
        email = _normalise_email(entry.email)
        if not reg or not email:
            errors.append(f"Skipped blank entry for reg_number={reg!r}")
            continue

        existing = db.query(InstitutionRegistrationNumber).filter(
            InstitutionRegistrationNumber.institution_id == institution_id,
            InstitutionRegistrationNumber.reg_number == reg,
        ).first()

        if existing:
            duplicates_skipped += 1
            # If it wasn't verified yet and the user exists, verify now.
            if existing.verified_at is None:
                user = db.query(User).filter(User.email == email).first()
                if user:
                    existing.user_id = user.id
                    existing.verified_at = _now()
                    existing.verified_by = uploader_id
                    user.registration_number = reg
                    user.registration_number_verified = True
                    matched += 1
            continue

        user = db.query(User).filter(User.email == email).first()

        row = InstitutionRegistrationNumber(
            institution_id=institution_id,
            period_id=data.period_id,
            reg_number=reg,
            email=email,
            user_id=user.id if user else None,
            source="roster_upload",
            added_by=uploader_id,
            is_active=True,
            verified_at=_now() if user else None,
            verified_by=uploader_id if user else None,
        )
        db.add(row)

        if user:
            user.registration_number = reg
            user.registration_number_verified = True
            matched += 1
        else:
            unmatched_stored += 1

    _audit(
        db, uploader_id, "InstitutionVerificationPeriod", data.period_id,
        "ROSTER_UPLOAD",
        new_value=f"entries={len(data.entries)} matched={matched} "
                  f"unmatched_stored={unmatched_stored}",
    )
    db.commit()

    period = get_verification_period(db, data.period_id)
    _refresh_counts(db, period)
    db.commit()

    return {
        "total_entries": len(data.entries),
        "matched": matched,
        "unmatched_stored": unmatched_stored,
        "duplicates_skipped": duplicates_skipped,
        "errors": errors,
    }


# ============================================================================
# PAIR VERIFICATION — single
# ============================================================================

def verify_pair(
    db: Session, data, verifier_id: str,
) -> dict:
    """
    Verify a single (reg_number, email) pair. Used by the Institution Rep
    during an active period.

    Outcome matrix:
      - Pair in roster + user matches   → verified
      - Pair in roster + no user        → stored, user_id remains null
      - Pair not in roster + user found → created & verified
      - Pair not in roster + no user    → created, stored for future use
    """
    reg = data.reg_number.strip()
    email = _normalise_email(data.email)
    if not reg or not email:
        raise VerificationError("reg_number and email are required.", 400)

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise VerificationError("No registered user with that email.", 404)

    if not user.institution_id:
        raise VerificationError(
            "This user has no institution on file. Cannot verify.", 409,
        )

    institution_id = user.institution_id

    # Already verified with the same pair?
    existing_for_user = db.query(InstitutionRegistrationNumber).filter(
        InstitutionRegistrationNumber.user_id == user.id,
        InstitutionRegistrationNumber.verified_at.isnot(None),
    ).first()
    if existing_for_user and existing_for_user.reg_number == reg:
        return {
            "verified": True,
            "matched_user_id": user.id,
            "recorded": False,
            "message": "This pair is already verified.",
        }

    row = db.query(InstitutionRegistrationNumber).filter(
        InstitutionRegistrationNumber.institution_id == institution_id,
        InstitutionRegistrationNumber.reg_number == reg,
    ).first()

    if row:
        # Optionally check the pair matches.
        if _normalise_email(row.email) != email:
            return {
                "verified": False,
                "matched_user_id": None,
                "recorded": False,
                "message": (
                    "Registration number is already tied to a different email. "
                    "The pair does not match."
                ),
            }
        row.user_id = user.id
        row.verified_at = _now()
        row.verified_by = verifier_id
        recorded = False
    else:
        row = InstitutionRegistrationNumber(
            institution_id=institution_id,
            period_id=None,
            reg_number=reg,
            email=email,
            user_id=user.id,
            source="student_submission",
            added_by=verifier_id,
            is_active=True,
            verified_at=_now(),
            verified_by=verifier_id,
        )
        db.add(row)
        recorded = True

    user.registration_number = reg
    user.registration_number_verified = True

    _audit(
        db, verifier_id, "InstitutionRegistrationNumber", row.id, "VERIFY",
        new_value=f"user={user.id} reg_number={reg}",
    )
    db.commit()

    return {
        "verified": True,
        "matched_user_id": user.id,
        "recorded": recorded,
        "message": "Pair verified successfully.",
    }


# ============================================================================
# MANUAL ENTRY — County Rep adds a new registration number
# ============================================================================

def add_manual_roster_entry(
    db: Session, data, adder_id: str,
) -> InstitutionRegistrationNumber:
    """
    Insert a new (reg_number, email) pair into an institution's roster.
    Used by the County Rep when manual verification requires adding a
    number that isn't yet known.
    """
    # Use the period to determine the institution.
    if not data.period_id:
        raise VerificationError("period_id is required.", 400)
    period = get_verification_period(db, data.period_id)

    reg = data.reg_number.strip()
    email = _normalise_email(data.email)

    existing = db.query(InstitutionRegistrationNumber).filter(
        InstitutionRegistrationNumber.institution_id == period.institution_id,
        InstitutionRegistrationNumber.reg_number == reg,
    ).first()
    if existing:
        raise VerificationError(
            f"Registration number '{reg}' already exists for this institution.",
            409,
        )

    user = db.query(User).filter(User.email == email).first()

    row = InstitutionRegistrationNumber(
        institution_id=period.institution_id,
        period_id=period.id,
        reg_number=reg,
        email=email,
        user_id=user.id if user else None,
        source="manual_entry",
        added_by=adder_id,
        is_active=True,
        verified_at=_now() if user else None,
        verified_by=adder_id if user else None,
    )
    db.add(row)
    db.flush()

    if user:
        user.registration_number = reg
        user.registration_number_verified = True

    _audit(
        db, adder_id, "InstitutionRegistrationNumber", row.id, "MANUAL_ADD",
        new_value=f"reg_number={reg} email={email}",
    )
    db.commit()
    db.refresh(row)
    return row


# ============================================================================
# READ — roster
# ============================================================================

def list_roster_entries(
    db: Session,
    institution_id: str | None = None,
    period_id: str | None = None,
    unverified_only: bool = False,
    user_id: str | None = None,
) -> list[InstitutionRegistrationNumber]:
    q = db.query(InstitutionRegistrationNumber)
    if institution_id:
        q = q.filter(InstitutionRegistrationNumber.institution_id == institution_id)
    if period_id:
        q = q.filter(InstitutionRegistrationNumber.period_id == period_id)
    if user_id:
        q = q.filter(InstitutionRegistrationNumber.user_id == user_id)
    if unverified_only:
        q = q.filter(InstitutionRegistrationNumber.verified_at.is_(None))
    return q.order_by(InstitutionRegistrationNumber.created_at.desc()).all()


# ============================================================================
# USER ACCESS — checking whether to restrict
# ============================================================================

def user_access_restricted_by_verification(
    db: Session, user: User,
) -> tuple[bool, str | None]:
    """
    Returns (restricted, reason).

    A user is restricted when:
      - their institution has a completed/lapsed verification period
      - they have a registration_number on file
      - the pair has not been verified

    When no period is open and no verification is required, the user is
    not restricted.
    """
    if user.user_type != "student":
        return False, None
    if not user.institution_id:
        return False, None
    if user.registration_number_verified:
        return False, None
    if not user.registration_number:
        # No number on file — the institution may not require verification.
        return False, None

    period = (
        db.query(InstitutionVerificationPeriod)
        .filter(
            InstitutionVerificationPeriod.institution_id == user.institution_id,
            InstitutionVerificationPeriod.status.in_(("completed", "expired")),
        )
        .order_by(InstitutionVerificationPeriod.end_date.desc())
        .first()
    )
    if not period:
        return False, None

    # Period ended and the user is still unverified.
    return True, (
        "Your registration number could not be verified. "
        "Access is restricted until you re-verify."
    )