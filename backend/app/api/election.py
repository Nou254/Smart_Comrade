"""
Election endpoints — Module 003 Phase 6.

Covers the full lifecycle for all four levels (group, school, institution,
county), plus disputes, appeals, reschedules, and dashboard views.

Route order note: literal prefixes (/eligibility/, /candidates/) come
before dynamic segments (/elections/{id}/...) to avoid path collisions.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user, require_permission, require_super_admin,
)
from app.db.session import get_db
from app.models.user import User
from app.models.election import (
    Election, ElectionCandidate, ElectionPosition, ElectionTicket,
    ElectionVoterRoll, ElectionResult, ElectionDispute, ElectionAppeal,
    ElectionReschedule, ElectionNoPayerEvent, ElectionAuditEvent,
)
from app.schemas.election import (
    ElectionCreate, ElectionResponse, ElectionListResponse,
    ElectionPositionResponse, ElectionTicketResponse,
    ElectionCandidateRegister, ElectionCandidateResponse,
    ElectionVoterRollResponse, ElectionApprovalVoteRequest,
    ElectionBallotCast, ElectionBallotResponse,
    ElectionResultResponse, ElectionStateTransitionRequest,
    ElectionRunOffRequest,
    ElectionDisputeFile, ElectionDisputeVerdict, ElectionDisputeResponse,
    ElectionAppealFile, ElectionAppealVerdict, ElectionAppealResponse,
    ElectionRescheduleRequest, ElectionRescheduleResponse,
    ElectionNoPayerEventResponse, ElectionAuditEventResponse,
    ElectionDetailResponse, ElectionCandidateApprovalStatus,
    ElectionEligibilityResponse, ElectionDashboardResponse,
)
from app.services.election_lifecycle_service import (
    ElectionError,
    create_election, schedule_election, transition_state,
    close_voting_window, start_live_stream, end_live_stream_and_start_suspense,
    declare_result_after_suspense, get_election, list_elections,
)
from app.services.election_candidate_service import (
    register_candidacy, record_approval_vote, record_nomination_fee,
    finalize_ballot, apply_no_payer_fallback, withdraw_candidacy,
    list_candidates, list_tickets, candidate_approval_status,
)
from app.services.election_voting_service import (
    freeze_voter_roll, cast_ballot,
    tally_position, tally_all_positions,
    schedule_run_off, declare_winner_and_provision,
)
from app.services.election_governance_service import (
    file_dispute, assign_dispute_to_regional, schedule_dispute_hearing,
    record_dispute_verdict,
    file_appeal, assemble_appeal_committee, schedule_appeal_hearing,
    record_appeal_verdict, grant_dashboard_access,
    request_reschedule, approve_reschedule,
    list_disputes, list_appeals, list_reschedules,
)
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/elections", tags=["Elections"])


def _err(e: ElectionError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


# ============================================================================
# ELIGIBILITY  (literal prefix — must come before /{election_id})
# ============================================================================

@router.get("/eligibility/{level}/{constituency_id}",
            response_model=ElectionEligibilityResponse)
def get_election_eligibility(
    level: str,
    constituency_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    """
    Explain whether the constituency currently meets the trigger
    conditions for an election at this level.
    """
    from app.services.group_subscription_service import check_election_eligibility
    from app.services.election_lifecycle_service import (
        GROUP, SCHOOL, INSTITUTION, COUNTY,
    )

    blockers: list[str] = []
    compliant_groups = 0
    compliant_institutions = 0
    required_groups = 0
    required_institutions = 0

    if level == GROUP:
        status = check_election_eligibility(db, constituency_id)
        blockers = status["blockers"]
        required_groups = 1
        compliant_groups = 1 if status["eligible"] else 0

    elif level == SCHOOL:
        # 15 compliant groups with ≥10 members + active subscription
        from app.models.group import Group
        from app.services.group_subscription_service import is_subscription_current
        groups = db.query(Group).filter(Group.school_id == constituency_id).all()
        required_groups = 15
        for g in groups:
            if g.member_count >= 10:
                ok, _ = is_subscription_current(db, g.id)
                if ok:
                    compliant_groups += 1
        if compliant_groups < required_groups:
            blockers.append(
                f"{required_groups - compliant_groups} more compliant group(s) needed."
            )

    elif level == INSTITUTION:
        # All schools (or ≥ all but 3) with reps
        from app.models.academic import School
        schools = db.query(School).filter(School.institution_id == constituency_id).all()
        required_groups = len(schools)
        # Approximation: count schools that have an active school_representative
        # role assignment scoped to them.
        from app.models.role import Role, UserRole
        rep_role = db.query(Role).filter(Role.code == "school_representative").first()
        if rep_role:
            for s in schools:
                exists = db.query(UserRole).filter(
                    UserRole.role_id == rep_role.id,
                    UserRole.jurisdiction_type == "school",
                    UserRole.jurisdiction_id == s.id,
                    UserRole.status == "active",
                ).first()
                if exists:
                    compliant_groups += 1
        if compliant_groups < required_groups - 3:
            blockers.append(
                f"{max(0, (required_groups - 3) - compliant_groups)} more "
                f"school representative(s) needed."
            )

    elif level == COUNTY:
        # 15 institutions
        from app.models.academic import Institution
        institutions = db.query(Institution).filter(
            Institution.county_id == constituency_id,
        ).all()
        required_institutions = 15
        compliant_institutions = len(institutions)
        if compliant_institutions < required_institutions:
            blockers.append(
                f"{required_institutions - compliant_institutions} more "
                f"institution(s) needed."
            )

    else:
        raise HTTPException(400, f"Unknown level '{level}'.")

    return ElectionEligibilityResponse(
        level=level,
        constituency_id=constituency_id,
        eligible=len(blockers) == 0,
        current_compliant_groups=compliant_groups,
        required_groups=required_groups,
        current_compliant_institutions=compliant_institutions,
        required_institutions=required_institutions,
        blockers=blockers,
    )


# ============================================================================
# CREATE + LIST
# ============================================================================

@router.post("", response_model=ElectionResponse, status_code=201)
def post_election(
    payload: ElectionCreate,
    current_user: User = Depends(require_permission("election.create")),
    db: Session = Depends(get_db),
):
    try:
        result = create_election(db, payload, actor_id=current_user.id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.create",
        target_type="election", target_id=result.id,
        new_value=f"{payload.level}:{payload.constituency_id}",
    )
    return result


@router.get("", response_model=list[ElectionListResponse])
def get_elections(
    level: str | None = Query(None),
    constituency_id: str | None = Query(None),
    state: str | None = Query(None),
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return list_elections(
        db, level=level, constituency_id=constituency_id, state=state,
    )


# ============================================================================
# DETAIL (with positions, tickets, candidates)
# ============================================================================

@router.get("/{election_id}", response_model=ElectionDetailResponse)
def get_election_detail(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    try:
        election = get_election(db, election_id)
    except ElectionError as e:
        _err(e)
    positions = db.query(ElectionPosition).filter(
        ElectionPosition.election_id == election.id,
    ).all()
    tickets = list_tickets(db, election.id)
    candidates = list_candidates(db, election.id)
    return ElectionDetailResponse(
        election=ElectionResponse.model_validate(election),
        positions=[ElectionPositionResponse.model_validate(p) for p in positions],
        tickets=[ElectionTicketResponse.model_validate(t) for t in tickets],
        candidates=[ElectionCandidateResponse.model_validate(c) for c in candidates],
    )


# ============================================================================
# STATE TRANSITIONS
# ============================================================================

@router.post("/{election_id}/transition", response_model=ElectionResponse)
def post_transition(
    election_id: str,
    payload: ElectionStateTransitionRequest,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = transition_state(
            db, election_id, payload.to_state,
            actor_id=current_user.id, reason=payload.reason,
        )
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.transition",
        target_type="election", target_id=election_id,
        new_value=payload.to_state, reason=payload.reason,
    )
    return result


@router.post("/{election_id}/schedule", response_model=ElectionResponse)
def post_schedule(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = schedule_election(db, election_id, actor_id=current_user.id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.schedule",
        target_type="election", target_id=election_id,
    )
    return result


@router.post("/{election_id}/close-voting", response_model=ElectionResponse)
def post_close_voting(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = close_voting_window(db, election_id, actor_id=current_user.id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.close_voting",
        target_type="election", target_id=election_id,
    )
    return result


# ============================================================================
# LIVE STREAM
# ============================================================================

@router.post("/{election_id}/stream/start", response_model=ElectionResponse)
def post_stream_start(
    election_id: str,
    stream_url: str = Query(..., min_length=5, max_length=500),
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = start_live_stream(db, election_id, stream_url=stream_url)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.stream_start",
        target_type="election", target_id=election_id,
        new_value=stream_url,
    )
    return result


@router.post("/{election_id}/stream/end-and-suspense", response_model=ElectionResponse)
def post_stream_end(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = end_live_stream_and_start_suspense(db, election_id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.suspense_started",
        target_type="election", target_id=election_id,
    )
    return result


@router.post("/{election_id}/declare-result", response_model=ElectionResponse)
def post_declare_result(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = declare_result_after_suspense(
            db, election_id, actor_id=current_user.id,
        )
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.result_declared",
        target_type="election", target_id=election_id,
    )
    return result


# ============================================================================
# VOTER ROLL
# ============================================================================

@router.post("/{election_id}/freeze-roll")
def post_freeze_roll(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        count = freeze_voter_roll(db, election_id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.freeze_roll",
        target_type="election", target_id=election_id,
        new_value=str(count),
    )
    return {"frozen": count}


@router.get("/{election_id}/roll", response_model=list[ElectionVoterRollResponse])
def get_roll(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return (
        db.query(ElectionVoterRoll)
        .filter(ElectionVoterRoll.election_id == election_id)
        .order_by(ElectionVoterRoll.frozen_at)
        .all()
    )


# ============================================================================
# CANDIDATES
# ============================================================================

@router.post(
    "/{election_id}/candidates",
    response_model=ElectionCandidateResponse,
    status_code=201,
)
def post_candidate(
    election_id: str,
    payload: ElectionCandidateRegister,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return register_candidacy(db, election_id, current_user.id, payload)
    except ElectionError as e:
        _err(e)


@router.get(
    "/{election_id}/candidates",
    response_model=list[ElectionCandidateResponse],
)
def get_candidates(
    election_id: str,
    position_id: str | None = Query(None),
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return list_candidates(db, election_id, position_id=position_id)


@router.get(
    "/{election_id}/candidates/{candidate_id}/status",
    response_model=ElectionCandidateApprovalStatus,
)
def get_candidate_status(
    election_id: str,
    candidate_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    try:
        return ElectionCandidateApprovalStatus(**candidate_approval_status(db, candidate_id))
    except ElectionError as e:
        _err(e)


@router.post("/{election_id}/candidates/{candidate_id}/approve")
def post_approve_candidate(
    election_id: str,
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return record_approval_vote(
            db, election_id, candidate_id, voter_id=current_user.id,
        )
    except ElectionError as e:
        _err(e)


@router.post(
    "/{election_id}/candidates/{candidate_id}/fee",
    response_model=ElectionCandidateResponse,
)
def post_candidate_fee(
    election_id: str,
    candidate_id: str,
    payment_reference: str = Query(..., min_length=3, max_length=128),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Record a nomination fee payment. Stub until M-Pesa integration lands
    — in production this only succeeds when a verified webhook arrives.
    """
    try:
        candidate = db.query(ElectionCandidate).filter(
            ElectionCandidate.id == candidate_id,
            ElectionCandidate.election_id == election_id,
        ).first()
        if not candidate:
            raise ElectionError("Candidate not found.", 404)
        if candidate.user_id != current_user.id:
            raise HTTPException(
                403, "You can only pay your own nomination fee.",
            )
        return record_nomination_fee(db, candidate_id, payment_reference)
    except ElectionError as e:
        _err(e)


@router.post(
    "/{election_id}/candidates/{candidate_id}/withdraw",
    response_model=ElectionCandidateResponse,
)
def post_withdraw_candidate(
    election_id: str,
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return withdraw_candidacy(db, candidate_id, actor_id=current_user.id)
    except ElectionError as e:
        _err(e)


@router.post("/{election_id}/finalize-ballot")
def post_finalize_ballot(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = finalize_ballot(db, election_id, actor_id=current_user.id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.finalize_ballot",
        target_type="election", target_id=election_id,
        new_value=result.get("state"),
    )
    return result


# ============================================================================
# VOTING
# ============================================================================

@router.post(
    "/{election_id}/vote",
    response_model=ElectionBallotResponse,
    status_code=201,
)
def post_vote(
    election_id: str,
    payload: ElectionBallotCast,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cast_ballot(
            db, election_id, user_id=current_user.id,
            position_id=payload.position_id,
            ticket_id=payload.ticket_id,
        )
    except ElectionError as e:
        _err(e)


# ============================================================================
# RESULTS
# ============================================================================

@router.post("/{election_id}/tally")
def post_tally(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        results = tally_all_positions(db, election_id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.tally",
        target_type="election", target_id=election_id,
        new_value=str(len(results)),
    )
    return {"tallied": len(results)}


@router.post(
    "/{election_id}/positions/{position_id}/tally",
    response_model=ElectionResultResponse,
)
def post_tally_one(
    election_id: str,
    position_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return tally_position(db, election_id, position_id)
    except ElectionError as e:
        _err(e)


@router.get(
    "/{election_id}/results",
    response_model=list[ElectionResultResponse],
)
def get_results(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return (
        db.query(ElectionResult)
        .filter(ElectionResult.election_id == election_id)
        .all()
    )


@router.post("/{election_id}/runoff", response_model=ElectionResponse)
def post_runoff(
    election_id: str,
    payload: ElectionRunOffRequest,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = schedule_run_off(
            db, election_id, payload.position_id,
            payload.tied_ticket_ids, scheduled_for=payload.scheduled_for,
        )
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.runoff_scheduled",
        target_type="election", target_id=election_id,
        new_value=result.id,
    )
    return result


@router.post("/{election_id}/provision")
def post_provision(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    """
    Provision the elected roles to winners. Moves the election to the
    appeal window (Institution/County) or COMPLETED (Group/School).
    """
    try:
        return declare_winner_and_provision(db, election_id, actor_id=current_user.id)
    except ElectionError as e:
        _err(e)


# ============================================================================
# DISPUTES
# ============================================================================

@router.post(
    "/{election_id}/disputes",
    response_model=ElectionDisputeResponse,
    status_code=201,
)
def post_dispute(
    election_id: str,
    payload: ElectionDisputeFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return file_dispute(db, election_id, current_user.id, payload)
    except ElectionError as e:
        _err(e)


@router.get(
    "/{election_id}/disputes",
    response_model=list[ElectionDisputeResponse],
)
def get_disputes(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return list_disputes(db, election_id)


@router.post(
    "/{election_id}/disputes/{dispute_id}/assign",
    response_model=ElectionDisputeResponse,
)
def post_assign_dispute(
    election_id: str,
    dispute_id: str,
    regional_admin_id: str = Query(..., min_length=36, max_length=36),
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return assign_dispute_to_regional(db, dispute_id, regional_admin_id)
    except ElectionError as e:
        _err(e)


@router.post(
    "/{election_id}/disputes/{dispute_id}/hearing",
    response_model=ElectionDisputeResponse,
)
def post_dispute_hearing(
    election_id: str,
    dispute_id: str,
    hearing_at: datetime = Query(...),
    hearing_link: str = Query(..., min_length=5, max_length=500),
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return schedule_dispute_hearing(db, dispute_id, hearing_at, hearing_link)
    except ElectionError as e:
        _err(e)


@router.post(
    "/{election_id}/disputes/{dispute_id}/verdict",
    response_model=ElectionDisputeResponse,
)
def post_dispute_verdict(
    election_id: str,
    dispute_id: str,
    payload: ElectionDisputeVerdict,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return record_dispute_verdict(db, dispute_id, current_user.id, payload)
    except ElectionError as e:
        _err(e)


# ============================================================================
# APPEALS
# ============================================================================

@router.post(
    "/{election_id}/appeals",
    response_model=ElectionAppealResponse,
    status_code=201,
)
def post_appeal(
    election_id: str,
    payload: ElectionAppealFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return file_appeal(db, election_id, current_user.id, payload)
    except ElectionError as e:
        _err(e)


@router.get(
    "/{election_id}/appeals",
    response_model=list[ElectionAppealResponse],
)
def get_appeals(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return list_appeals(db, election_id)


@router.post(
    "/{election_id}/appeals/{appeal_id}/committee",
    response_model=ElectionAppealResponse,
)
def post_appeal_committee(
    election_id: str,
    appeal_id: str,
    members: list[dict],
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return assemble_appeal_committee(db, appeal_id, members)
    except ElectionError as e:
        _err(e)


@router.post(
    "/{election_id}/appeals/{appeal_id}/hearing",
    response_model=ElectionAppealResponse,
)
def post_appeal_hearing(
    election_id: str,
    appeal_id: str,
    hearing_at: datetime = Query(...),
    hearing_link: str = Query(..., min_length=5, max_length=500),
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return schedule_appeal_hearing(db, appeal_id, hearing_at, hearing_link)
    except ElectionError as e:
        _err(e)


@router.post(
    "/{election_id}/appeals/{appeal_id}/verdict",
    response_model=ElectionAppealResponse,
)
def post_appeal_verdict(
    election_id: str,
    appeal_id: str,
    payload: ElectionAppealVerdict,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return record_appeal_verdict(
            db, appeal_id,
            verdict_by={"by": current_user.id, "at": datetime.utcnow().isoformat()},
            data=payload,
        )
    except ElectionError as e:
        _err(e)


@router.post("/{election_id}/grant-dashboard", response_model=ElectionResponse)
def post_grant_dashboard(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = grant_dashboard_access(db, election_id)
    except ElectionError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="election.dashboard_granted",
        target_type="election", target_id=election_id,
    )
    return result


# ============================================================================
# RESCHEDULE
# ============================================================================

@router.post(
    "/{election_id}/reschedule",
    response_model=ElectionRescheduleResponse,
    status_code=201,
)
def post_reschedule(
    election_id: str,
    payload: ElectionRescheduleRequest,
    current_user: User = Depends(require_permission("election.reschedule.request")),
    db: Session = Depends(get_db),
):
    try:
        return request_reschedule(db, election_id, current_user.id, payload)
    except ElectionError as e:
        _err(e)


@router.post(
    "/{election_id}/reschedule/{reschedule_id}/approve",
    response_model=ElectionResponse,
)
def post_approve_reschedule(
    election_id: str,
    reschedule_id: str,
    current_user: User = Depends(require_permission("election.reschedule.approve")),
    db: Session = Depends(get_db),
):
    try:
        return approve_reschedule(db, reschedule_id, regional_admin_id=current_user.id)
    except ElectionError as e:
        _err(e)


@router.get(
    "/{election_id}/reschedules",
    response_model=list[ElectionRescheduleResponse],
)
def get_reschedules(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return list_reschedules(db, election_id)


# ============================================================================
# NO-PAYER FALLBACK
# ============================================================================

@router.post("/{election_id}/no-payer-fallback")
def post_no_payer_fallback(
    election_id: str,
    current_user: User = Depends(require_permission("election.manage")),
    db: Session = Depends(get_db),
):
    try:
        return apply_no_payer_fallback(db, election_id, actor_id=current_user.id)
    except ElectionError as e:
        _err(e)


@router.get(
    "/{election_id}/no-payer-events",
    response_model=list[ElectionNoPayerEventResponse],
)
def get_no_payer_events(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return (
        db.query(ElectionNoPayerEvent)
        .filter(ElectionNoPayerEvent.election_id == election_id)
        .order_by(ElectionNoPayerEvent.triggered_at.desc())
        .all()
    )


# ============================================================================
# AUDIT
# ============================================================================

@router.get(
    "/{election_id}/audit",
    response_model=list[ElectionAuditEventResponse],
)
def get_audit(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return (
        db.query(ElectionAuditEvent)
        .filter(ElectionAuditEvent.election_id == election_id)
        .order_by(ElectionAuditEvent.created_at.desc())
        .all()
    )


# ============================================================================
# DASHBOARD
# ============================================================================

@router.get("/{election_id}/dashboard", response_model=ElectionDashboardResponse)
def get_dashboard(
    election_id: str,
    _: User = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    from datetime import date as _date
    try:
        election = get_election(db, election_id)
    except ElectionError as e:
        _err(e)

    positions_count = db.query(ElectionPosition).filter(
        ElectionPosition.election_id == election.id,
    ).count()
    candidates_qualified = db.query(ElectionCandidate).filter(
        ElectionCandidate.election_id == election.id,
        ElectionCandidate.status == "qualified",
    ).count()
    votes_cast = db.query(ElectionResult).filter(
        ElectionResult.election_id == election.id,
    ).count()

    # Detect tie from results
    has_tie = db.query(ElectionResult).filter(
        ElectionResult.election_id == election.id,
        ElectionResult.is_tie.is_(True),
    ).count() > 0

    # Detect appeals
    under_appeal = db.query(ElectionAppeal).filter(
        ElectionAppeal.election_id == election.id,
        ElectionAppeal.status.notin_(("resolved", "dismissed")),
    ).count() > 0

    days_until = (election.election_day - _date.today()).days

    return ElectionDashboardResponse(
        election_id=election.id,
        title=election.title,
        level=election.level,
        state=election.state,
        election_day=election.election_day,
        days_until_election=max(0, days_until),
        positions_count=positions_count,
        candidates_qualified=candidates_qualified,
        electorate_size=election.electorate_size,
        votes_cast=election.votes_cast,
        total_votes_expected=election.electorate_size,
        has_tie=has_tie,
        under_appeal=under_appeal,
        under_regional_admin=election.under_regional_admin,
    )