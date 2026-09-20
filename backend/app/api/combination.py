"""
Combination endpoints — Module 002 completion.

A combination is a course-bound pairing of subjects (Education Science
Math/Geo, etc.). No formal approval workflow — a notification is sent
to Regional + Super only (County is skipped).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.academic import Course
from app.models.user import User
from app.schemas.combination import (
    CombinationCreate, CombinationUpdate, CombinationResponse,
)
from app.services.combination_service import (
    CombinationError,
    create_combination, list_combinations, get_combination,
    update_combination, deactivate_combination, reactivate_combination,
)
from app.services.jurisdiction_service import user_has_jurisdiction
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/combinations", tags=["Combinations"])


def _err(e: CombinationError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _guard_course_jurisdiction(db: Session, user: User, course_id: str) -> None:
    if not user_has_jurisdiction(db, user.id, "course", course_id):
        raise HTTPException(
            status_code=403,
            detail="You do not have jurisdiction over this course.",
        )


# ============================================================================
# CREATE
# ============================================================================

@router.post("", response_model=CombinationResponse, status_code=201)
def post_combination(
    payload: CombinationCreate,
    current_user: User = Depends(require_permission("combination.create")),
    db: Session = Depends(get_db),
):
    _guard_course_jurisdiction(db, current_user, payload.course_id)
    try:
        result = create_combination(db, payload, user_id=current_user.id)
    except CombinationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="combination.create",
        target_type="combination", target_id=result.id,
        new_value=f"{result.code} - {result.name}",
    )
    return result


# ============================================================================
# READ
# ============================================================================

@router.get("", response_model=list[CombinationResponse])
def get_combinations(
    course_id: str | None = Query(None),
    status: str | None = Query(None),
    _: User = Depends(require_permission("combination.view")),
    db: Session = Depends(get_db),
):
    return list_combinations(db, course_id=course_id, status=status)


@router.get("/{combination_id}", response_model=CombinationResponse)
def get_one_combination(
    combination_id: str,
    _: User = Depends(require_permission("combination.view")),
    db: Session = Depends(get_db),
):
    try:
        return get_combination(db, combination_id)
    except CombinationError as e:
        _err(e)


# ============================================================================
# UPDATE
# ============================================================================

@router.patch("/{combination_id}", response_model=CombinationResponse)
def patch_combination(
    combination_id: str,
    payload: CombinationUpdate,
    current_user: User = Depends(require_permission("combination.edit")),
    db: Session = Depends(get_db),
):
    try:
        combo = get_combination(db, combination_id)
    except CombinationError as e:
        _err(e)
    _guard_course_jurisdiction(db, current_user, combo.course_id)
    try:
        result = update_combination(
            db, combination_id, payload, user_id=current_user.id,
        )
    except CombinationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="combination.update",
        target_type="combination", target_id=combination_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/{combination_id}/deactivate", response_model=CombinationResponse)
def post_combination_deactivate(
    combination_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_permission("combination.edit")),
    db: Session = Depends(get_db),
):
    try:
        combo = get_combination(db, combination_id)
    except CombinationError as e:
        _err(e)
    _guard_course_jurisdiction(db, current_user, combo.course_id)
    try:
        result = deactivate_combination(
            db, combination_id, reason=reason, user_id=current_user.id,
        )
    except CombinationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="combination.deactivate",
        target_type="combination", target_id=combination_id, reason=reason,
    )
    return result


@router.post("/{combination_id}/reactivate", response_model=CombinationResponse)
def post_combination_reactivate(
    combination_id: str,
    current_user: User = Depends(require_permission("combination.edit")),
    db: Session = Depends(get_db),
):
    try:
        combo = get_combination(db, combination_id)
    except CombinationError as e:
        _err(e)
    _guard_course_jurisdiction(db, current_user, combo.course_id)
    try:
        result = reactivate_combination(
            db, combination_id, user_id=current_user.id,
        )
    except CombinationError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="combination.reactivate",
        target_type="combination", target_id=combination_id,
    )
    return result