"""
Election cascade trigger endpoints — Module 003 Phase 7.

Detects threshold compliance and auto-schedules parent elections.
Higher-first ordering is enforced — child triggers queue when a parent
election is active.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.election_trigger_event import ElectionTriggerEvent
from app.models.user import User
from app.schemas.cascade import (
    CascadeCheckResponse, ElectionTriggerEventResponse,
)
from app.services.cascade_trigger_service import (
    CascadeError,
    check_school_threshold, check_institution_threshold, check_county_threshold,
    try_trigger_school_election, try_trigger_institution_election,
    try_trigger_county_election,
    run_sweep, process_queued_triggers,
)

router = APIRouter(prefix="/cascade", tags=["Election Cascade"])


def _err(e: CascadeError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


# ============================================================================
# CHECK THRESHOLD
# ============================================================================

@router.get("/check/school/{school_id}", response_model=CascadeCheckResponse)
def check_school(
    school_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return check_school_threshold(db, school_id)
    except CascadeError as e:
        _err(e)


@router.get("/check/institution/{institution_id}", response_model=CascadeCheckResponse)
def check_institution(
    institution_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return check_institution_threshold(db, institution_id)
    except CascadeError as e:
        _err(e)


@router.get("/check/county/{county_id}", response_model=CascadeCheckResponse)
def check_county(
    county_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return check_county_threshold(db, county_id)
    except CascadeError as e:
        _err(e)


# ============================================================================
# MANUAL TRIGGER (Super Admin)
# ============================================================================

@router.post("/trigger/school/{school_id}")
def post_trigger_school(
    school_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        election = try_trigger_school_election(
            db, school_id, actor_id=current_user.id,
        )
    except CascadeError as e:
        _err(e)
    if not election:
        return {
            "triggered": False,
            "message": "Threshold not met, or election already active, "
                       "or queued behind a parent election.",
        }
    return {"triggered": True, "election_id": election.id}


@router.post("/trigger/institution/{institution_id}")
def post_trigger_institution(
    institution_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        election = try_trigger_institution_election(
            db, institution_id, actor_id=current_user.id,
        )
    except CascadeError as e:
        _err(e)
    if not election:
        return {
            "triggered": False,
            "message": "Threshold not met, or election already active, "
                       "or queued behind a parent election.",
        }
    return {"triggered": True, "election_id": election.id}


@router.post("/trigger/county/{county_id}")
def post_trigger_county(
    county_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        election = try_trigger_county_election(
            db, county_id, actor_id=current_user.id,
        )
    except CascadeError as e:
        _err(e)
    if not election:
        return {
            "triggered": False,
            "message": "Threshold not met or election already active.",
        }
    return {"triggered": True, "election_id": election.id}


# ============================================================================
# SWEEP
# ============================================================================

@router.post("/sweep")
def post_sweep(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Run a full sweep over every school, institution, and county. Triggers
    any newly-compliant parent election. Idempotent.
    """
    return run_sweep(db)


@router.post("/process-queued/{parent_election_id}")
def post_process_queued(
    parent_election_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Called when a parent election completes. Retries the child triggers
    that were blocked during that election.
    """
    return process_queued_triggers(db, parent_election_id)


# ============================================================================
# TRIGGER EVENTS (audit view)
# ============================================================================

@router.get("/events", response_model=list[ElectionTriggerEventResponse])
def get_trigger_events(
    level: str | None = Query(None),
    constituency_id: str | None = Query(None),
    status: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(ElectionTriggerEvent)
    if level:
        q = q.filter(ElectionTriggerEvent.level == level)
    if constituency_id:
        q = q.filter(ElectionTriggerEvent.constituency_id == constituency_id)
    if status:
        q = q.filter(ElectionTriggerEvent.status == status)
    return q.order_by(ElectionTriggerEvent.triggered_at.desc()).all()