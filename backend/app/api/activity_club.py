"""
Activity Club endpoints — Module 003 Phase 10.

Route order matters: literal prefixes (e.g. /revival-petitions/) come
before dynamic /{club_id}/... paths to avoid collisions.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.models.activity_club import (
    ActivityClub, ActivityClubMembership, ActivityClubPosition,
    ActivityClubMilestone, ActivityClubMilestoneReport,
    ActivityClubElectionCycle, ActivityClubElectionCandidate,
    ActivityClubElectionVote,
    ActivityClubPositionApprovalVote, ActivityClubPositionApprovalBallot,
    ActivityClubDissolutionEvent, ActivityClubRevivalPetition,
    ActivityClubApprovalEvent,
    ELECTION_FEE, PROMOTION_FEE,
    MAX_CLUBS_PER_STUDENT,
    INSTITUTION_CLUB_MEMBER_CAP, COUNTY_CLUB_MEMBER_CAP,
)
from app.schemas.activity_club import (
    # club
    ActivityClubCreate, ActivityClubUpdate, ActivityClubResponse,
    ActivityClubListResponse, ActivityClubDetailResponse,
    # membership
    ActivityClubMembershipResponse, ActivityClubJoinRequest,
    # positions
    ActivityClubPositionResponse,
    ActivityClubCustomPositionProposal,
    ActivityClubPositionRetirementProposal,
    ActivityClubPositionApprovalResponse,
    ActivityClubPositionApprovalBallotRequest,
    # milestones
    ActivityClubMilestoneCreate, ActivityClubMilestoneResponse,
    ActivityClubMilestoneReportCreate,
    ActivityClubMilestoneReportInstitutionReview,
    ActivityClubMilestoneReportResponse,
    # elections
    ActivityClubElectionCycleInitiate, ActivityClubElectionCycleResponse,
    ActivityClubElectionFeeRecord,
    ActivityClubCandidateRegister, ActivityClubCandidateResponse,
    ActivityClubVoteCast, ActivityClubVoteResponse,
    # dissolution + revival
    ActivityClubDissolutionEventResponse,
    ActivityClubRevivalPetitionCreate, ActivityClubRevivalPetitionReview,
    ActivityClubRevivalPetitionResponse,
    # audit
    ActivityClubApprovalEventResponse,
    # promotion
    ActivityClubCountyPromotionRequest,
)
from app.services.club_lifecycle_service import (
    ClubError,
    create_club_request, institution_rep_approve, institution_rep_reject,
    regional_rep_approve, regional_rep_reject,
    publish_positions, dissolve_club,
    file_revival_petition, review_revival_petition,
    promote_to_county, remove_founder,
    get_club, list_clubs,
)
from app.services.club_membership_service import (
    ClubMembershipError,
    join_public_club, request_private_join,
    approve_join_request, reject_join_request,
    leave_club, remove_member, mark_member_graduated,
    count_user_active_clubs, list_club_members,
)
from app.services.club_position_service import (
    ClubPositionError,
    add_custom_position_by_founder,
    propose_custom_position, propose_position_retirement,
    vote_on_position_proposal, list_positions,
)
from app.services.club_election_service import (
    ClubElectionError,
    initiate_cycle, record_election_fee,
    register_candidate, cast_vote, open_voting, tally_cycle,
    handle_dissolution_if_recovery_expired,
    list_cycles, list_candidates,
)
from app.services.club_milestone_service import (
    ClubMilestoneError,
    declare_milestone, update_milestone,
    submit_milestone_report, institution_rep_review_report,
    forward_to_regional, close_report,
    list_milestones, list_reports,
)

router = APIRouter(prefix="/clubs", tags=["Activity Clubs"])


# ── helpers ─────────────────────────────────────────────────────────────

def _err(e):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


# ═════════════════════════════════════════════════════════════════════════
# CLUB — creation + listing
# ═════════════════════════════════════════════════════════════════════════

@router.post("", response_model=ActivityClubResponse, status_code=201)
def post_club(
    payload: ActivityClubCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Founder files a club request. Enters dual-approval chain."""
    try:
        return create_club_request(
            db, payload, founder_id=current_user.id,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


@router.get("", response_model=list[ActivityClubListResponse])
def get_clubs(
    institution_id: str | None = Query(None),
    status: str | None = Query(None),
    level: str | None = Query(None, description="institution | county"),
    membership_visibility: str | None = Query(None, description="public | private"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_clubs(
        db,
        institution_id=institution_id,
        status=status,
        level=level,
        membership_visibility=membership_visibility,
    )


@router.get("/{club_id}", response_model=ActivityClubDetailResponse)
def get_one_club(
    club_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        club = get_club(db, club_id)
    except ClubError as e:
        _err(e)

    viewer_m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club.id,
        ActivityClubMembership.user_id == current_user.id,
    ).first()

    positions = list_positions(db, club.id, status="active")
    milestones = list_milestones(db, club.id)

    return ActivityClubDetailResponse(
        club=ActivityClubResponse.model_validate(club),
        viewer_membership=(
            ActivityClubMembershipResponse.model_validate(viewer_m)
            if viewer_m else None
        ),
        positions=[ActivityClubPositionResponse.model_validate(p) for p in positions],
        milestones=[ActivityClubMilestoneResponse.model_validate(m) for m in milestones],
    )


@router.patch("/{club_id}", response_model=ActivityClubResponse)
def patch_club(
    club_id: str,
    payload: ActivityClubUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        club = get_club(db, club_id)
    except ClubError as e:
        _err(e)

    _ensure_leader_or_founder(db, club, current_user.id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(club, field, value)

    db.commit()
    db.refresh(club)
    return club


# ═════════════════════════════════════════════════════════════════════════
# CLUB — dual approval chain
# ═════════════════════════════════════════════════════════════════════════

@router.post("/{club_id}/institution-rep/approve", response_model=ActivityClubResponse)
def post_institution_rep_approve(
    club_id: str,
    request: Request,
    notes: str | None = Query(None, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return institution_rep_approve(
            db, club_id, actor_id=current_user.id, notes=notes,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


@router.post("/{club_id}/institution-rep/reject", response_model=ActivityClubResponse)
def post_institution_rep_reject(
    club_id: str,
    request: Request,
    reason: str = Query(..., min_length=5, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return institution_rep_reject(
            db, club_id, actor_id=current_user.id, reason=reason,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


@router.post("/{club_id}/regional-rep/approve", response_model=ActivityClubResponse)
def post_regional_rep_approve(
    club_id: str,
    request: Request,
    notes: str | None = Query(None, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return regional_rep_approve(
            db, club_id, actor_id=current_user.id, notes=notes,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


@router.post("/{club_id}/regional-rep/reject", response_model=ActivityClubResponse)
def post_regional_rep_reject(
    club_id: str,
    request: Request,
    reason: str = Query(..., min_length=5, max_length=2000),
    required_changes: list[str] | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return regional_rep_reject(
            db, club_id, actor_id=current_user.id, reason=reason,
            required_changes=required_changes,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# CLUB — lifecycle events
# ═════════════════════════════════════════════════════════════════════════

@router.post("/{club_id}/publish-positions", response_model=ActivityClubResponse)
def post_publish_positions(
    club_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return publish_positions(db, club_id, actor_id=current_user.id)
    except ClubError as e:
        _err(e)


@router.post("/{club_id}/dissolve", response_model=ActivityClubResponse)
def post_dissolve_club(
    club_id: str,
    trigger: str = Query(..., description="failed_election | halted_recovery_expired | admin_dissolved | other"),
    reason: str = Query(..., min_length=5, max_length=2000),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return dissolve_club(
            db, club_id, trigger=trigger, reason=reason,
            actor_id=current_user.id,
        )
    except ClubError as e:
        _err(e)


@router.post("/{club_id}/promote-to-county", response_model=ActivityClubResponse)
def post_promote_to_county(
    club_id: str,
    payload: ActivityClubCountyPromotionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return promote_to_county(
            db, club_id, actor_id=current_user.id,
            payment_reference=payload.payment_reference,
            method=payload.method,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


@router.post("/{club_id}/remove-founder", response_model=ActivityClubResponse)
def post_remove_founder(
    club_id: str,
    votes_for: int = Query(..., ge=0),
    votes_against: int = Query(..., ge=0),
    reason: str = Query(..., min_length=5, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return remove_founder(
            db, club_id, actor_id=current_user.id,
            votes_for=votes_for, votes_against=votes_against,
            reason=reason,
        )
    except ClubError as e:
        _err(e)


@router.get(
    "/{club_id}/approval-events",
    response_model=list[ActivityClubApprovalEventResponse],
)
def get_approval_events(
    club_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(ActivityClubApprovalEvent)
        .filter(ActivityClubApprovalEvent.club_id == club_id)
        .order_by(ActivityClubApprovalEvent.created_at.desc())
        .all()
    )


# ═════════════════════════════════════════════════════════════════════════
# MEMBERSHIP
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/{club_id}/join",
    response_model=ActivityClubMembershipResponse,
    status_code=201,
)
def post_join_public(
    club_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return join_public_club(db, club_id, user_id=current_user.id)
    except ClubMembershipError as e:
        _err(e)


@router.post(
    "/{club_id}/request-join",
    response_model=ActivityClubMembershipResponse,
    status_code=201,
)
def post_request_private_join(
    club_id: str,
    payload: ActivityClubJoinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return request_private_join(
            db, club_id, user_id=current_user.id,
            message=payload.message,
        )
    except ClubMembershipError as e:
        _err(e)


@router.post(
    "/{club_id}/memberships/{membership_id}/approve",
    response_model=ActivityClubMembershipResponse,
)
def post_approve_join(
    club_id: str,
    membership_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return approve_join_request(db, membership_id, actor_id=current_user.id)
    except ClubMembershipError as e:
        _err(e)


@router.post(
    "/{club_id}/memberships/{membership_id}/reject",
    response_model=ActivityClubMembershipResponse,
)
def post_reject_join(
    club_id: str,
    membership_id: str,
    reason: str = Query(..., min_length=3, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return reject_join_request(
            db, membership_id, actor_id=current_user.id, reason=reason,
        )
    except ClubMembershipError as e:
        _err(e)


@router.get(
    "/{club_id}/members",
    response_model=list[ActivityClubMembershipResponse],
)
def get_club_members(
    club_id: str,
    status: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_club_members(db, club_id, status=status)


@router.post(
    "/{club_id}/leave",
    response_model=ActivityClubMembershipResponse,
)
def post_leave_club(
    club_id: str,
    reason: str | None = Query(None, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return leave_club(
            db, club_id, user_id=current_user.id, reason=reason,
        )
    except ClubMembershipError as e:
        _err(e)


@router.delete(
    "/{club_id}/members/{target_user_id}",
    response_model=ActivityClubMembershipResponse,
)
def delete_member(
    club_id: str,
    target_user_id: str,
    reason: str = Query(..., min_length=3, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        club = get_club(db, club_id)
    except ClubError as e:
        _err(e)
    _ensure_leader_or_founder(db, club, current_user.id)
    try:
        return remove_member(
            db, club_id, target_user_id=target_user_id,
            actor_id=current_user.id, reason=reason,
        )
    except ClubMembershipError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# POSITIONS
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/{club_id}/positions",
    response_model=list[ActivityClubPositionResponse],
)
def get_positions(
    club_id: str,
    status: str | None = Query("active"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_positions(db, club_id, status=status)


@router.post(
    "/{club_id}/positions/founder-add",
    response_model=ActivityClubPositionResponse,
    status_code=201,
)
def post_founder_add_position(
    club_id: str,
    payload: ActivityClubCustomPositionProposal,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return add_custom_position_by_founder(
            db, club_id, actor_id=current_user.id, data=payload,
        )
    except ClubPositionError as e:
        _err(e)


@router.post(
    "/{club_id}/positions/propose-custom",
    response_model=ActivityClubPositionApprovalResponse,
    status_code=201,
)
def post_propose_custom_position(
    club_id: str,
    payload: ActivityClubCustomPositionProposal,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return propose_custom_position(
            db, club_id, actor_id=current_user.id, data=payload,
        )
    except ClubPositionError as e:
        _err(e)


@router.post(
    "/{club_id}/positions/propose-retirement",
    response_model=ActivityClubPositionApprovalResponse,
    status_code=201,
)
def post_propose_retirement(
    club_id: str,
    payload: ActivityClubPositionRetirementProposal,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return propose_position_retirement(
            db, club_id, actor_id=current_user.id, data=payload,
        )
    except ClubPositionError as e:
        _err(e)


@router.get(
    "/{club_id}/positions/proposals",
    response_model=list[ActivityClubPositionApprovalResponse],
)
def get_position_proposals(
    club_id: str,
    status: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(ActivityClubPositionApprovalVote).filter(
        ActivityClubPositionApprovalVote.club_id == club_id,
    )
    if status:
        q = q.filter(ActivityClubPositionApprovalVote.status == status)
    return q.order_by(
        ActivityClubPositionApprovalVote.proposed_at.desc(),
    ).all()


@router.post(
    "/positions/proposals/{proposal_id}/vote",
    response_model=ActivityClubPositionApprovalResponse,
)
def post_vote_on_position_proposal(
    proposal_id: str,
    payload: ActivityClubPositionApprovalBallotRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return vote_on_position_proposal(
            db, proposal_id, voter_id=current_user.id, vote=payload.vote,
        )
    except ClubPositionError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# ELECTION CYCLES
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/{club_id}/cycles",
    response_model=ActivityClubElectionCycleResponse,
    status_code=201,
)
def post_initiate_cycle(
    club_id: str,
    payload: ActivityClubElectionCycleInitiate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return initiate_cycle(
            db, club_id, actor_id=current_user.id,
            term_months=payload.term_months,
        )
    except ClubElectionError as e:
        _err(e)


@router.get(
    "/{club_id}/cycles",
    response_model=list[ActivityClubElectionCycleResponse],
)
def get_cycles(
    club_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_cycles(db, club_id)


@router.post(
    "/{club_id}/cycles/{cycle_id}/fee",
    response_model=ActivityClubElectionCycleResponse,
)
def post_record_election_fee(
    club_id: str,
    cycle_id: str,
    payload: ActivityClubElectionFeeRecord,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return record_election_fee(
            db, cycle_id,
            payment_reference=payload.payment_reference,
            method=payload.method,
        )
    except ClubElectionError as e:
        _err(e)


@router.post(
    "/{club_id}/cycles/{cycle_id}/candidates",
    response_model=ActivityClubCandidateResponse,
    status_code=201,
)
def post_register_candidate(
    club_id: str,
    cycle_id: str,
    payload: ActivityClubCandidateRegister,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return register_candidate(
            db, cycle_id, user_id=current_user.id, data=payload,
        )
    except ClubElectionError as e:
        _err(e)


@router.get(
    "/{club_id}/cycles/{cycle_id}/candidates",
    response_model=list[ActivityClubCandidateResponse],
)
def get_cycle_candidates(
    club_id: str,
    cycle_id: str,
    position_id: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_candidates(db, cycle_id, position_id=position_id)


@router.post(
    "/{club_id}/cycles/{cycle_id}/open-voting",
    response_model=ActivityClubElectionCycleResponse,
)
def post_open_voting(
    club_id: str,
    cycle_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return open_voting(db, cycle_id, actor_id=current_user.id)
    except ClubElectionError as e:
        _err(e)


@router.post(
    "/{club_id}/cycles/{cycle_id}/vote",
    response_model=ActivityClubVoteResponse,
    status_code=201,
)
def post_cast_vote(
    club_id: str,
    cycle_id: str,
    payload: ActivityClubVoteCast,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cast_vote(
            db, cycle_id, voter_id=current_user.id, data=payload,
        )
    except ClubElectionError as e:
        _err(e)


@router.post("/{club_id}/cycles/{cycle_id}/tally")
def post_tally_cycle(
    club_id: str,
    cycle_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return tally_cycle(db, cycle_id, actor_id=current_user.id)
    except ClubElectionError as e:
        _err(e)


@router.post("/{club_id}/handle-recovery")
def post_handle_recovery(
    club_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return handle_dissolution_if_recovery_expired(db, club_id)
    except ClubElectionError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# MILESTONES
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/{club_id}/milestones",
    response_model=ActivityClubMilestoneResponse,
    status_code=201,
)
def post_declare_milestone(
    club_id: str,
    payload: ActivityClubMilestoneCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return declare_milestone(
            db, club_id, actor_id=current_user.id, data=payload,
        )
    except ClubMilestoneError as e:
        _err(e)


@router.patch(
    "/{club_id}/milestones/{milestone_id}",
    response_model=ActivityClubMilestoneResponse,
)
def patch_milestone(
    club_id: str,
    milestone_id: str,
    payload: ActivityClubMilestoneCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_milestone(
            db, milestone_id, actor_id=current_user.id, data=payload,
        )
    except ClubMilestoneError as e:
        _err(e)


@router.get(
    "/{club_id}/milestones",
    response_model=list[ActivityClubMilestoneResponse],
)
def get_milestones(
    club_id: str,
    status: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_milestones(db, club_id, status=status)


@router.post(
    "/{club_id}/milestones/{milestone_id}/reports",
    response_model=ActivityClubMilestoneReportResponse,
    status_code=201,
)
def post_submit_milestone_report(
    club_id: str,
    milestone_id: str,
    payload: ActivityClubMilestoneReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return submit_milestone_report(
            db, milestone_id, actor_id=current_user.id, data=payload,
        )
    except ClubMilestoneError as e:
        _err(e)


@router.get(
    "/{club_id}/milestones/reports",
    response_model=list[ActivityClubMilestoneReportResponse],
)
def get_milestone_reports(
    club_id: str,
    status: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_reports(db, club_id, status=status)


@router.post(
    "/milestones/reports/{report_id}/institution-review",
    response_model=ActivityClubMilestoneReportResponse,
)
def post_institution_review(
    report_id: str,
    payload: ActivityClubMilestoneReportInstitutionReview,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return institution_rep_review_report(
            db, report_id, actor_id=current_user.id, data=payload,
        )
    except ClubMilestoneError as e:
        _err(e)


@router.post(
    "/milestones/reports/{report_id}/forward-to-regional",
    response_model=ActivityClubMilestoneReportResponse,
)
def post_forward_to_regional(
    report_id: str,
    notes: str | None = Query(None, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return forward_to_regional(
            db, report_id, actor_id=current_user.id, notes=notes,
        )
    except ClubMilestoneError as e:
        _err(e)


@router.post(
    "/milestones/reports/{report_id}/close",
    response_model=ActivityClubMilestoneReportResponse,
)
def post_close_report(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return close_report(db, report_id, actor_id=current_user.id)
    except ClubMilestoneError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# REVIVAL PETITIONS
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/{club_id}/revival-petitions",
    response_model=ActivityClubRevivalPetitionResponse,
    status_code=201,
)
def post_file_revival_petition(
    club_id: str,
    payload: ActivityClubRevivalPetitionCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return file_revival_petition(
            db, club_id, filer_id=current_user.id, data=payload,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


@router.get(
    "/{club_id}/revival-petitions",
    response_model=list[ActivityClubRevivalPetitionResponse],
)
def get_revival_petitions(
    club_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(ActivityClubRevivalPetition)
        .filter(ActivityClubRevivalPetition.club_id == club_id)
        .order_by(ActivityClubRevivalPetition.filed_at.desc())
        .all()
    )


@router.get(
    "/{club_id}/dissolution-events",
    response_model=list[ActivityClubDissolutionEventResponse],
)
def get_dissolution_events(
    club_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(ActivityClubDissolutionEvent)
        .filter(ActivityClubDissolutionEvent.club_id == club_id)
        .order_by(ActivityClubDissolutionEvent.triggered_at.desc())
        .all()
    )


@router.post(
    "/revival-petitions/{petition_id}/review",
    response_model=ActivityClubRevivalPetitionResponse,
)
def post_review_revival_petition(
    petition_id: str,
    payload: ActivityClubRevivalPetitionReview,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return review_revival_petition(
            db, petition_id, actor_id=current_user.id, data=payload,
            ip=_ip(request), ua=_ua(request),
        )
    except ClubError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# ADMIN — graduation hook
# ═════════════════════════════════════════════════════════════════════════

@router.post("/admin/mark-graduate/{user_id}")
def post_mark_graduate(
    user_id: str,
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Called by the graduation pipeline. Flips every active club membership
    for a user to 'alumni_readonly'.
    """
    count = mark_member_graduated(db, user_id)
    return {"user_id": user_id, "memberships_flipped": count}


# ═════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═════════════════════════════════════════════════════════════════════════

def _ensure_leader_or_founder(
    db: Session, club: ActivityClub, user_id: str,
) -> None:
    if club.founder_id == user_id:
        return
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club.id,
        ActivityClubMembership.user_id == user_id,
        ActivityClubMembership.status == "active",
    ).first()
    if m and m.role in ("leader", "officer"):
        return
    raise HTTPException(
        status_code=403,
        detail="Only the founder or current leader may perform this action.",
    )