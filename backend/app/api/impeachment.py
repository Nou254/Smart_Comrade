"""
Impeachment endpoints — Module 003 Phase 9.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.impeachment import (
    ImpeachmentCaseCreate, ImpeachmentCaseResponse, ImpeachmentListResponse,
    ReconciliationAttempt, PetitionStatusResponse, PetitionSignatureResponse,
    FormCommitteeRequest, CommitteeResponse,
    SessionScheduleRequest, SessionStartRequest, SessionMinutesRequest,
    ImpeachmentSessionResponse,
    VerdictVoteRequest, ImpeachmentVoteResponse, VerdictSummary,
    VerdictVotingStatusResponse,
    ReplacementElectionResponse,
)
from app.services.impeachment_service import (
    ImpeachmentError,
    file_complaint, attempt_reconciliation,
    sign_petition, petition_status,
    form_committee, committee_detail,
    schedule_all_sessions, start_session, record_session_minutes,
    complete_session, list_sessions,
    open_verdict_voting, close_verdict_voting, verdict_voting_status,
    cast_verdict_vote, verdict_summary,
    start_disclosure_period, trigger_replacement_election, finalize_removal,
    get_case, list_cases,
)

router = APIRouter(prefix="/impeachments", tags=["Impeachment"])


def _err(e: ImpeachmentError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ── filing + listing ─────────────────────────────────────────────────────

@router.post("", response_model=ImpeachmentCaseResponse, status_code=201)
def post_case(
    payload: ImpeachmentCaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return file_complaint(
            db,
            target_user_id=payload.target_user_id,
            target_role_code=payload.target_role_code,
            target_level=payload.target_level,
            constituency_id=payload.constituency_id,
            filed_by=current_user.id,
            grounds=payload.grounds,
            evidence=payload.evidence,
        )
    except ImpeachmentError as e:
        _err(e)


@router.get("", response_model=list[ImpeachmentListResponse])
def get_cases(
    target_level: str | None = Query(None),
    constituency_id: str | None = Query(None),
    status: str | None = Query(None),
    target_user_id: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_cases(
        db,
        target_level=target_level,
        constituency_id=constituency_id,
        status=status,
        target_user_id=target_user_id,
    )


@router.get("/{case_id}", response_model=ImpeachmentCaseResponse)
def get_one_case(
    case_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_case(db, case_id)
    except ImpeachmentError as e:
        _err(e)


# ── reconciliation ───────────────────────────────────────────────────────

@router.post("/{case_id}/reconciliation", response_model=ImpeachmentCaseResponse)
def post_reconciliation(
    case_id: str,
    payload: ReconciliationAttempt,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return attempt_reconciliation(
            db, case_id, mediator_id=current_user.id,
            outcome=payload.outcome, notes=payload.notes,
        )
    except ImpeachmentError as e:
        _err(e)


# ── petition ─────────────────────────────────────────────────────────────

@router.post("/{case_id}/petition/sign", response_model=PetitionSignatureResponse)
def post_petition_sign(
    case_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return sign_petition(
            db, case_id, signer_id=current_user.id,
            ip=_ip(request), user_agent=request.headers.get("user-agent"),
        )
    except ImpeachmentError as e:
        _err(e)


@router.get("/{case_id}/petition", response_model=PetitionStatusResponse)
def get_petition_status(
    case_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return PetitionStatusResponse(**petition_status(db, case_id))
    except ImpeachmentError as e:
        _err(e)


# ── committee ────────────────────────────────────────────────────────────

@router.post("/{case_id}/committee", response_model=CommitteeResponse)
def post_committee(
    case_id: str,
    payload: FormCommitteeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        form_committee(
            db, case_id,
            member_user_ids=payload.member_user_ids,
            moderator_user_id=payload.moderator_user_id,
            formed_by=current_user.id,
        )
        return CommitteeResponse(**committee_detail(db, case_id))
    except ImpeachmentError as e:
        _err(e)


@router.get("/{case_id}/committee", response_model=CommitteeResponse)
def get_committee(
    case_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return CommitteeResponse(**committee_detail(db, case_id))
    except ImpeachmentError as e:
        _err(e)


# ── hearing sessions ─────────────────────────────────────────────────────

@router.post(
    "/{case_id}/hearing/schedule",
    response_model=list[ImpeachmentSessionResponse],
    status_code=201,
)
def post_schedule_sessions(
    case_id: str,
    payload: SessionScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return schedule_all_sessions(
            db, case_id,
            accusation_at=payload.accusation_at,
            evidence_at=payload.evidence_at,
            defense_at=payload.defense_at,
            verdict_at=payload.verdict_at,
            is_live_streamed=payload.is_live_streamed,
            is_closed=payload.is_closed,
        )
    except ImpeachmentError as e:
        _err(e)


@router.get(
    "/{case_id}/hearing/sessions",
    response_model=list[ImpeachmentSessionResponse],
)
def get_sessions(
    case_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_sessions(db, case_id)


@router.post(
    "/{case_id}/hearing/sessions/{number}/start",
    response_model=ImpeachmentSessionResponse,
)
def post_start_session(
    case_id: str,
    number: int,
    payload: SessionStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return start_session(
            db, case_id, number, actor_id=current_user.id,
            is_live_streamed=payload.is_live_streamed,
            is_closed=payload.is_closed,
        )
    except ImpeachmentError as e:
        _err(e)


@router.post(
    "/{case_id}/hearing/sessions/{number}/minutes",
    response_model=ImpeachmentSessionResponse,
)
def post_session_minutes(
    case_id: str,
    number: int,
    payload: SessionMinutesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return record_session_minutes(
            db, case_id, number, actor_id=current_user.id,
            transcript_text=payload.transcript_text,
            minutes_text=payload.minutes_text,
            audio_url=payload.audio_url,
            audio_hash=payload.audio_hash,
        )
    except ImpeachmentError as e:
        _err(e)


@router.post(
    "/{case_id}/hearing/sessions/{number}/complete",
    response_model=ImpeachmentSessionResponse,
)
def post_complete_session(
    case_id: str,
    number: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return complete_session(
            db, case_id, number, actor_id=current_user.id,
        )
    except ImpeachmentError as e:
        _err(e)


# ── verdict voting control (moderator-gated) ─────────────────────────────

@router.get(
    "/{case_id}/verdict/voting-status",
    response_model=VerdictVotingStatusResponse,
)
def get_verdict_voting_status(
    case_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return VerdictVotingStatusResponse(
            message="", **verdict_voting_status(db, case_id),
        )
    except ImpeachmentError as e:
        _err(e)


@router.post(
    "/{case_id}/verdict/open",
    response_model=VerdictVotingStatusResponse,
)
def post_open_verdict_voting(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Moderator's green light. Only the moderator (initializer) may call
    this, and only while Session 4 is in progress with sessions 1-3
    already completed.
    """
    try:
        open_verdict_voting(db, case_id, actor_id=current_user.id)
        status = verdict_voting_status(db, case_id)
        return VerdictVotingStatusResponse(
            message="Verdict voting is now open.",
            **status,
        )
    except ImpeachmentError as e:
        _err(e)


@router.post(
    "/{case_id}/verdict/close",
    response_model=VerdictVotingStatusResponse,
)
def post_close_verdict_voting(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Moderator closes voting. If no verdict was finalized yet, one is
    forced: removal only if the threshold had been met; otherwise the
    incumbent is reinstated.
    """
    try:
        close_verdict_voting(db, case_id, actor_id=current_user.id)
        status = verdict_voting_status(db, case_id)
        return VerdictVotingStatusResponse(
            message="Verdict voting is now closed.",
            **status,
        )
    except ImpeachmentError as e:
        _err(e)


# ── verdict voting ───────────────────────────────────────────────────────

@router.post("/{case_id}/verdict/vote", response_model=ImpeachmentVoteResponse)
def post_verdict_vote(
    case_id: str,
    payload: VerdictVoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return cast_verdict_vote(
            db, case_id, voter_id=current_user.id, vote=payload.vote,
        )
    except ImpeachmentError as e:
        _err(e)


@router.get("/{case_id}/verdict", response_model=VerdictSummary)
def get_verdict(
    case_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return VerdictSummary(**verdict_summary(db, case_id))
    except ImpeachmentError as e:
        _err(e)


# ── disclosure + replacement ─────────────────────────────────────────────

@router.post(
    "/{case_id}/disclosure/start",
    response_model=ImpeachmentCaseResponse,
)
def post_start_disclosure(
    case_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return start_disclosure_period(db, case_id, actor_id=current_user.id)
    except ImpeachmentError as e:
        _err(e)


@router.post(
    "/{case_id}/replacement-election",
    response_model=ReplacementElectionResponse,
)
def post_replacement_election(
    case_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        case = trigger_replacement_election(
            db, case_id, actor_id=current_user.id,
        )
        return ReplacementElectionResponse(
            case_id=case.id,
            replacement_election_id=case.replacement_election_id,
            disclosure_period_ends_at=case.disclosure_period_ends_at,
            replacement_winner_user_id=case.replacement_winner_user_id,
        )
    except ImpeachmentError as e:
        _err(e)


@router.post(
    "/{case_id}/finalize-removal",
    response_model=ImpeachmentCaseResponse,
)
def post_finalize_removal(
    case_id: str,
    winner_user_id: str = Query(..., min_length=36, max_length=36),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return finalize_removal(
            db, case_id, winner_user_id=winner_user_id,
            actor_id=current_user.id,
        )
    except ImpeachmentError as e:
        _err(e)