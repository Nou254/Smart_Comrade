"""
Registration number verification endpoints — Module 002 completion.

Super Admin initiates periods. Institution Rep executes primary
verification. County Rep collaborates on manual verification and can
add new roster entries.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user, require_permission, require_super_admin,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.registration_verification import (
    InstitutionVerificationPeriodCreate,
    InstitutionVerificationPeriodExtendRequest,
    InstitutionVerificationPeriodResponse,
    RosterBulkUploadRequest,
    InstitutionRegistrationNumberResponse,
    RosterEntryCreate,
    PairVerificationRequest,
    PairVerificationResponse,
    BulkVerificationSummary,
)
from app.services.registration_verification_service import (
    VerificationError,
    initiate_verification_period, list_verification_periods,
    get_verification_period, extend_verification_period,
    complete_verification_period, upload_roster, verify_pair,
    add_manual_roster_entry, list_roster_entries,
    user_access_restricted_by_verification,
)
from app.services.jurisdiction_service import user_has_jurisdiction
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/verification", tags=["Registration Verification"])


def _err(e: VerificationError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _guard_institution(db: Session, user: User, institution_id: str) -> None:
    if not user_has_jurisdiction(db, user.id, "institution", institution_id):
        raise HTTPException(
            status_code=403,
            detail="You do not have jurisdiction over this institution.",
        )


# ============================================================================
# PERIODS — Super Admin lifecycle
# ============================================================================

@router.post(
    "/periods",
    response_model=InstitutionVerificationPeriodResponse,
    status_code=201,
)
def post_verification_period(
    payload: InstitutionVerificationPeriodCreate,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = initiate_verification_period(
            db, payload, super_admin_id=current_user.id,
        )
    except VerificationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="verification.period.create",
        target_type="institution_verification_period", target_id=result.id,
        new_value=f"institution={payload.institution_id}",
    )
    return result


@router.get(
    "/periods",
    response_model=list[InstitutionVerificationPeriodResponse],
)
def get_verification_periods(
    institution_id: str | None = Query(None),
    status: str | None = Query(None),
    _: User = Depends(require_permission("verification.period.view")),
    db: Session = Depends(get_db),
):
    return list_verification_periods(
        db, institution_id=institution_id, status=status,
    )


@router.get(
    "/periods/{period_id}",
    response_model=InstitutionVerificationPeriodResponse,
)
def get_one_verification_period(
    period_id: str,
    _: User = Depends(require_permission("verification.period.view")),
    db: Session = Depends(get_db),
):
    try:
        return get_verification_period(db, period_id)
    except VerificationError as e:
        _err(e)


@router.post(
    "/periods/{period_id}/extend",
    response_model=InstitutionVerificationPeriodResponse,
)
def post_verification_period_extend(
    period_id: str,
    payload: InstitutionVerificationPeriodExtendRequest,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = extend_verification_period(
            db, period_id, payload, reviewer_id=current_user.id,
        )
    except VerificationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="verification.period.extend",
        target_type="institution_verification_period", target_id=period_id,
        new_value=str(payload.new_end_date),
    )
    return result


@router.post(
    "/periods/{period_id}/complete",
    response_model=InstitutionVerificationPeriodResponse,
)
def post_verification_period_complete(
    period_id: str,
    current_user: User = Depends(require_permission("verification.period.complete")),
    db: Session = Depends(get_db),
):
    try:
        period = get_verification_period(db, period_id)
    except VerificationError as e:
        _err(e)
    _guard_institution(db, current_user, period.institution_id)
    try:
        result = complete_verification_period(
            db, period_id, user_id=current_user.id,
        )
    except VerificationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="verification.period.complete",
        target_type="institution_verification_period", target_id=period_id,
    )
    return result


# ============================================================================
# ROSTER — bulk upload (Institution Rep)
# ============================================================================

@router.post(
    "/periods/{period_id}/roster",
    response_model=BulkVerificationSummary,
)
def post_roster_upload(
    period_id: str,
    payload: RosterBulkUploadRequest,
    current_user: User = Depends(require_permission("verification.roster.upload")),
    db: Session = Depends(get_db),
):
    try:
        period = get_verification_period(db, period_id)
    except VerificationError as e:
        _err(e)
    _guard_institution(db, current_user, period.institution_id)
    # Force period_id to match the path.
    payload.period_id = period_id
    try:
        result = upload_roster(db, payload, uploader_id=current_user.id)
    except VerificationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="verification.roster.upload",
        target_type="institution_verification_period", target_id=period_id,
        new_value=f"matched={result['matched']} unmatched={result['unmatched_stored']}",
    )
    return result


@router.get(
    "/periods/{period_id}/roster",
    response_model=list[InstitutionRegistrationNumberResponse],
)
def get_roster(
    period_id: str,
    unverified_only: bool = Query(False),
    current_user: User = Depends(require_permission("verification.period.view")),
    db: Session = Depends(get_db),
):
    try:
        period = get_verification_period(db, period_id)
    except VerificationError as e:
        _err(e)
    _guard_institution(db, current_user, period.institution_id)
    return list_roster_entries(
        db, period_id=period_id, unverified_only=unverified_only,
    )


# ============================================================================
# PAIR VERIFICATION (single)
# ============================================================================

@router.post("/verify-pair", response_model=PairVerificationResponse)
def post_verify_pair(
    payload: PairVerificationRequest,
    current_user: User = Depends(require_permission("verification.pair.verify")),
    db: Session = Depends(get_db),
):
    try:
        result = verify_pair(db, payload, verifier_id=current_user.id)
    except VerificationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="verification.pair.verify",
        target_type="institution_registration_number",
        target_id=result.get("matched_user_id") or "none",
        new_value=f"verified={result['verified']}",
    )
    return result


# ============================================================================
# MANUAL ENTRY (County Rep)
# ============================================================================

@router.post(
    "/periods/{period_id}/roster/manual",
    response_model=InstitutionRegistrationNumberResponse,
    status_code=201,
)
def post_manual_roster_entry(
    period_id: str,
    payload: RosterEntryCreate,
    current_user: User = Depends(require_permission("verification.roster.manual_add")),
    db: Session = Depends(get_db),
):
    try:
        period = get_verification_period(db, period_id)
    except VerificationError as e:
        _err(e)
    _guard_institution(db, current_user, period.institution_id)
    # Attach period_id to the payload.
    from app.schemas.registration_verification import RosterBulkUploadRequest
    wrap = RosterBulkUploadRequest(period_id=period_id, entries=[payload])
    # Reuse the manual entry service (bypassing bulk semantics).
    from app.services.registration_verification_service import (
        _normalise_email,
    )
    # Direct service call for a single manual entry.
    try:
        from app.models.registration_verification import (
            InstitutionRegistrationNumber,
        )
        reg = payload.reg_number.strip()
        email = _normalise_email(payload.email)
        existing = db.query(InstitutionRegistrationNumber).filter(
            InstitutionRegistrationNumber.institution_id == period.institution_id,
            InstitutionRegistrationNumber.reg_number == reg,
        ).first()
        if existing:
            raise VerificationError(
                f"Registration number '{reg}' already exists for this institution.",
                409,
            )
        user_row = db.query(User).filter(User.email == email).first()
        row = InstitutionRegistrationNumber(
            institution_id=period.institution_id,
            period_id=period.id,
            reg_number=reg,
            email=email,
            user_id=user_row.id if user_row else None,
            source="manual_entry",
            added_by=current_user.id,
            is_active=True,
            verified_at=None,
            verified_by=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    except VerificationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="verification.roster.manual_add",
        target_type="institution_registration_number", target_id=row.id,
        new_value=f"reg_number={reg}",
    )
    return row