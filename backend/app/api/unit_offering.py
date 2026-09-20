"""
Unit offering endpoints — Module 002 completion.

An offering is a specific occurrence of a Unit during one academic
year and semester. Offerings can be created in advance of the semester.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.user import User
from app.schemas.unit_offering import (
    UnitOfferingCreate, UnitOfferingUpdate, UnitOfferingResponse,
)
from app.services.unit_offering_service import (
    UnitOfferingError,
    create_unit_offering, list_unit_offerings, get_unit_offering,
    update_unit_offering, activate_unit_offering,
    complete_unit_offering, archive_unit_offering,
)
from app.services.jurisdiction_service import user_has_jurisdiction
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/unit-offerings", tags=["Unit Offerings"])


def _err(e: UnitOfferingError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _guard_unit_jurisdiction(db: Session, user: User, unit_id: str) -> None:
    if not user_has_jurisdiction(db, user.id, "unit", unit_id):
        raise HTTPException(
            status_code=403,
            detail="You do not have jurisdiction over this unit.",
        )


# ============================================================================
# CREATE
# ============================================================================

@router.post("", response_model=UnitOfferingResponse, status_code=201)
def post_unit_offering(
    payload: UnitOfferingCreate,
    current_user: User = Depends(require_permission("unit_offering.create")),
    db: Session = Depends(get_db),
):
    _guard_unit_jurisdiction(db, current_user, payload.unit_id)
    try:
        result = create_unit_offering(db, payload, user_id=current_user.id)
    except UnitOfferingError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_offering.create",
        target_type="unit_offering", target_id=result.id,
        new_value=f"unit={payload.unit_id} semester={payload.semester_id}",
    )
    return result


# ============================================================================
# READ
# ============================================================================

@router.get("", response_model=list[UnitOfferingResponse])
def get_unit_offerings(
    course_id: str | None = Query(None),
    semester_id: str | None = Query(None),
    institution_id: str | None = Query(None),
    academic_year_id: str | None = Query(None),
    status: str | None = Query(None),
    _: User = Depends(require_permission("unit_offering.view")),
    db: Session = Depends(get_db),
):
    return list_unit_offerings(
        db,
        course_id=course_id,
        semester_id=semester_id,
        institution_id=institution_id,
        academic_year_id=academic_year_id,
        status=status,
    )


@router.get("/{offering_id}", response_model=UnitOfferingResponse)
def get_one_unit_offering(
    offering_id: str,
    _: User = Depends(require_permission("unit_offering.view")),
    db: Session = Depends(get_db),
):
    try:
        return get_unit_offering(db, offering_id)
    except UnitOfferingError as e:
        _err(e)


# ============================================================================
# LIFECYCLE
# ============================================================================

@router.patch("/{offering_id}", response_model=UnitOfferingResponse)
def patch_unit_offering(
    offering_id: str,
    payload: UnitOfferingUpdate,
    current_user: User = Depends(require_permission("unit_offering.edit")),
    db: Session = Depends(get_db),
):
    try:
        offering = get_unit_offering(db, offering_id)
    except UnitOfferingError as e:
        _err(e)
    _guard_unit_jurisdiction(db, current_user, offering.unit_id)
    try:
        result = update_unit_offering(
            db, offering_id, payload, user_id=current_user.id,
        )
    except UnitOfferingError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_offering.update",
        target_type="unit_offering", target_id=offering_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/{offering_id}/activate", response_model=UnitOfferingResponse)
def post_unit_offering_activate(
    offering_id: str,
    current_user: User = Depends(require_permission("unit_offering.edit")),
    db: Session = Depends(get_db),
):
    try:
        offering = get_unit_offering(db, offering_id)
    except UnitOfferingError as e:
        _err(e)
    _guard_unit_jurisdiction(db, current_user, offering.unit_id)
    try:
        result = activate_unit_offering(db, offering_id, user_id=current_user.id)
    except UnitOfferingError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_offering.activate",
        target_type="unit_offering", target_id=offering_id,
    )
    return result


@router.post("/{offering_id}/complete", response_model=UnitOfferingResponse)
def post_unit_offering_complete(
    offering_id: str,
    current_user: User = Depends(require_permission("unit_offering.edit")),
    db: Session = Depends(get_db),
):
    try:
        offering = get_unit_offering(db, offering_id)
    except UnitOfferingError as e:
        _err(e)
    _guard_unit_jurisdiction(db, current_user, offering.unit_id)
    try:
        result = complete_unit_offering(db, offering_id, user_id=current_user.id)
    except UnitOfferingError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_offering.complete",
        target_type="unit_offering", target_id=offering_id,
    )
    return result


@router.post("/{offering_id}/archive", response_model=UnitOfferingResponse)
def post_unit_offering_archive(
    offering_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_permission("unit_offering.edit")),
    db: Session = Depends(get_db),
):
    try:
        offering = get_unit_offering(db, offering_id)
    except UnitOfferingError as e:
        _err(e)
    _guard_unit_jurisdiction(db, current_user, offering.unit_id)
    try:
        result = archive_unit_offering(
            db, offering_id, user_id=current_user.id, reason=reason,
        )
    except UnitOfferingError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_offering.archive",
        target_type="unit_offering", target_id=offering_id, reason=reason,
    )
    return result