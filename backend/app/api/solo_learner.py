"""
Solo learner endpoints — Module 003 (Solo Path).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.solo_learner import (
    SoloSubscriptionResponse, SoloSubscribeRequest,
    SoloLearnerListResponse, SoloSessionCreate, SoloSessionResponse,
    SoloSessionDecision,
)
from app.services.solo_learner_service import (
    SoloError,
    subscribe, get_active_subscription, cancel_subscription,
    discover_solo_learners,
    propose_session, respond_to_session, cancel_session,
    complete_session, list_my_sessions,
)

router = APIRouter(prefix="/solo", tags=["Solo Learners"])


def _err(e: SoloError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


# ============================================================================
# SUBSCRIPTION
# ============================================================================

@router.get("/subscription", response_model=SoloSubscriptionResponse | None)
def get_my_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_active_subscription(db, current_user.id)


@router.post("/subscribe", response_model=SoloSubscriptionResponse, status_code=201)
def post_subscribe(
    payload: SoloSubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return subscribe(db, current_user.id, payload.payment_reference)
    except SoloError as e:
        _err(e)


@router.post("/subscription/cancel", response_model=SoloSubscriptionResponse)
def post_cancel_subscription(
    reason: str | None = Query(None, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cancel_subscription(db, current_user.id, reason=reason)
    except SoloError as e:
        _err(e)


# ============================================================================
# DISCOVERY
# ============================================================================

@router.get("/discover", response_model=SoloLearnerListResponse)
def get_discover(
    course_id: str | None = Query(None),
    year_level: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return discover_solo_learners(
            db, current_user.id,
            course_id=course_id, year_level=year_level,
            limit=limit, cursor=cursor,
        )
    except SoloError as e:
        _err(e)


# ============================================================================
# SESSIONS
# ============================================================================

@router.post("/sessions", response_model=SoloSessionResponse, status_code=201)
def post_session(
    payload: SoloSessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return propose_session(db, current_user.id, payload)
    except SoloError as e:
        _err(e)


@router.get("/sessions", response_model=list[SoloSessionResponse])
def get_my_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_my_sessions(db, current_user.id)


@router.post("/sessions/{session_id}/respond", response_model=SoloSessionResponse)
def post_session_respond(
    session_id: str,
    payload: SoloSessionDecision,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return respond_to_session(db, session_id, current_user.id, payload)
    except SoloError as e:
        _err(e)


@router.post("/sessions/{session_id}/cancel", response_model=SoloSessionResponse)
def post_session_cancel(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cancel_session(db, session_id, current_user.id)
    except SoloError as e:
        _err(e)


@router.post("/sessions/{session_id}/complete", response_model=SoloSessionResponse)
def post_session_complete(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return complete_session(db, session_id, current_user.id)
    except SoloError as e:
        _err(e)