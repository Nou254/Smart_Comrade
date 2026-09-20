"""
Lecturer affiliation endpoints.

  Self-service (any authenticated lecturer):
    GET    /lecturers/me/affiliations           list own affiliations
    POST   /lecturers/me/affiliations           add one
    DELETE /lecturers/me/affiliations/{id}      mark own affiliation ended

  Admin (Super Admin for now):
    GET    /lecturers/affiliations/pending?institution_id=X
    POST   /lecturers/affiliations/{id}/verify
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user, require_super_admin,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.lecturer import (
    LecturerAffiliationCreate,
    LecturerAffiliationResponse,
    LecturerAffiliationListResponse,
)
from app.services import lecturer_service as svc
from app.services.lecturer_service import LecturerError

router = APIRouter(prefix="/lecturers", tags=["Lecturers - Affiliations"])


# ============================================================================
# Self-service
# ============================================================================

@router.get(
    "/me/affiliations",
    response_model=LecturerAffiliationListResponse,
)
def list_my_affiliations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.user_type != "lecturer":
        raise HTTPException(status_code=403, detail="Lecturer account required.")
    rows = svc.list_my_affiliations(db, current_user.id)
    return LecturerAffiliationListResponse(
        affiliations=[LecturerAffiliationResponse.model_validate(r) for r in rows],
    )


@router.post(
    "/me/affiliations",
    response_model=LecturerAffiliationResponse,
    status_code=201,
)
def add_affiliation(
    payload: LecturerAffiliationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        aff = svc.add_affiliation(db, current_user, payload)
    except LecturerError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return LecturerAffiliationResponse.model_validate(aff)


@router.delete(
    "/me/affiliations/{affiliation_id}",
    response_model=LecturerAffiliationResponse,
)
def end_affiliation(
    affiliation_id: str,
    reason: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        aff = svc.end_affiliation(db, current_user, affiliation_id, reason=reason)
    except LecturerError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return LecturerAffiliationResponse.model_validate(aff)


# ============================================================================
# Admin
# ============================================================================

@router.get(
    "/affiliations/pending",
    response_model=LecturerAffiliationListResponse,
)
def list_pending_affiliations(
    institution_id: str = Query(..., min_length=1),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    rows = svc.list_pending_for_institution(db, institution_id)
    return LecturerAffiliationListResponse(
        affiliations=[LecturerAffiliationResponse.model_validate(r) for r in rows],
    )


@router.post(
    "/affiliations/{affiliation_id}/verify",
    response_model=LecturerAffiliationResponse,
)
def verify_affiliation(
    affiliation_id: str,
    approve: bool,
    notes: str | None = None,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        aff = svc.verify_affiliation(
            db, affiliation_id, actor_id=current_user.id,
            approve=approve, notes=notes,
        )
    except LecturerError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return LecturerAffiliationResponse.model_validate(aff)