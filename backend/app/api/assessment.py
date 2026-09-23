"""
Assessment endpoints — Module 005.

The App-awareness / PWA-execution boundary is enforced at the routing
level by path design:

  App-awareness  →  /me/assessments/*
  PWA-execution  →  /assessments/{id}/attempts/*, /attempts/*

A client can call either path set, but the semantics are unambiguous.
The awareness layer NEVER returns question text or correct answers.
The attempt layer NEVER runs outside a valid PWA session.

Route ordering note:
  Static literal paths (public, catalog, pending-grading, ai-logs,
  cost-summary) are declared before dynamic /{id} segments at the
  same depth.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.models.assessment import (
    Assessment,
    Question,
    Attempt,
    Response as AssessmentResponseRow,
    Result,
    Appeal,
    AssessmentAuditLog,
    AssessmentAudienceSnapshot,
    AssessmentCatalogEntry,
    AIAssistanceLog,
    MODE_DIRECTED,
    MODE_SYSTEM_WIDE,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUS_CLOSED,
)
from app.models.unit_offering import UnitOffering
from app.models.group import Group
from app.models.academic import Unit
from app.schemas.assessment import (
    AssessmentDirectedCreate, AssessmentSystemWideCreate,
    AssessmentUpdate, AssessmentPublishRequest,
    AssessmentResponse, AssessmentListItem,
    AssessmentAwarenessItem, AssessmentAwarenessSummary,
    AssessmentDeepLink,
    QuestionBankCreate, QuestionBankUpdate, QuestionBankResponse,
    QuestionBankDetailResponse,
    QuestionCreate, QuestionUpdate, QuestionResponse,
    QuestionAttemptView,
    AttemptStartResponse, AttemptResponse, AttemptStatusResponse,
    ResponseSubmit, ResponseUpdate, ResponseResponse,
    SubmissionCreate, SubmissionResponse,
    ResponseGradeSubmit, ResultFinaliseSubmit, ResultCorrectSubmit,
    ResultResponse, ResultListItem, ResultSummaryForApp,
    ResultDetailResponse,
    FeedbackCreate, FeedbackResponse,
    AppealCreate, AppealReviewSubmit, AppealResponse,
    AudienceSnapshotResponse,
    CatalogListItem, CatalogDetailResponse, CatalogFilter,
    AssessmentAuditLogResponse,
    AIAssistanceLogResponse,
    AssessmentAnalyticsResponse,
)
from app.services.assessment_service import (
    AssessmentError,
    create_directed_assessment, create_system_wide_assessment,
    publish_assessment, close_assessment, archive_assessment,
    get_assessment, list_assessments, list_available_for_student,
    resolve_audience,
)
from app.services.question_service import (
    QuestionError,
    create_bank, get_bank, list_banks_for_unit, update_bank,
    add_question_to_assessment, add_question_to_bank, clone_from_bank,
    get_question, list_assessment_questions, list_bank_questions,
    update_question, delete_question, reorder_questions,
    set_ai_validation,
)
from app.services.attempt_service import (
    AttemptError,
    start_attempt, submit_response, submit_attempt,
    get_attempt, get_attempt_status,
    list_attempts_for_student, list_attempts_for_assessment,
)
from app.services.grading_service import (
    GradingError,
    auto_grade_objective, grade_response, list_pending_grading,
    finalise_result, mark_result_official, correct_result,
    get_result, list_results_for_student, list_results_for_assessment,
)
from app.services.ai_assistance_service import (
    AIError,
    draft_questions, validate_question, preliminary_grade,
    summarize_analytics, list_logs, cost_summary,
)
from app.services.appeal_service import (
    AppealError,
    submit_appeal, review_appeal, get_appeal,
    list_appeals_for_student, list_appeals_for_result,
)
from app.services.assessment_catalog_service import (
    CatalogError,
    list_catalog, get_entry, record_view, record_take,
    record_rating, set_featured,
)
from app.services.assessment_analytics_service import (
    assessment_analytics, unit_analytics, institution_analytics,
)
from app.services.subscription_gate_service import (
    GateError, check_student_gate,
)
from app.core.config import settings


logger = logging.getLogger(__name__)


router = APIRouter(tags=["Assessments"])


# ═════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════

def _err(e):
    """Translate any assessment-related service exception into HTTP."""
    raise HTTPException(
        status_code=getattr(e, "status_code", 400),
        detail=getattr(e, "message", str(e)),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pwa_base_url() -> str:
    """Resolve the PWA base URL from settings or fall back."""
    return getattr(settings, "PWA_BASE_URL", "https://pwa.smartcomrade.app")


def _creator_display_name(db: Session, user_id: str) -> str | None:
    """Look up a user's display name for awareness notifications."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        return None
    first = getattr(u, "first_name", "") or ""
    last = getattr(u, "last_name", "") or ""
    name = f"{first} {last}".strip()
    return name or getattr(u, "email", None)


def _unit_display(db: Session, unit_offering_id: str | None) -> tuple[str | None, str | None]:
    """Return (unit_name, unit_code) for a given offering, if resolvable."""
    if not unit_offering_id:
        return (None, None)
    offering = db.query(UnitOffering).filter(
        UnitOffering.id == unit_offering_id,
    ).first()
    if not offering:
        return (None, None)
    unit = db.query(Unit).filter(Unit.id == offering.unit_id).first()
    if not unit:
        return (None, None)
    return (getattr(unit, "name", None), getattr(unit, "code", None))


def _build_awareness_item(
    db: Session, assessment: Assessment, student_id: str,
) -> dict:
    creator_name = _creator_display_name(db, assessment.created_by)
    unit_name, unit_code = _unit_display(db, assessment.unit_offering_id)

    # Student's own attempt status
    active = db.query(Attempt).filter(
        Attempt.assessment_id == assessment.id,
        Attempt.student_id == student_id,
    ).order_by(Attempt.attempt_number.desc()).first()

    attempt_status = None
    if active:
        attempt_status = active.status

    return {
        "id": assessment.id,
        "title": assessment.title,
        "category": assessment.category,
        "type": assessment.type,
        "creator_name": creator_name,
        "creator_role": assessment.created_by_role,
        "unit_name": unit_name,
        "unit_code": unit_code,
        "start_at": assessment.start_at,
        "end_at": assessment.end_at,
        "duration_minutes": assessment.duration_minutes,
        "status": assessment.status,
        "attempt_status": attempt_status,
    }


def _require_not_gated(
    db: Session, student_id: str, assessment: Assessment,
) -> None:
    """Raise 403 if the student's subscription gates them out."""
    try:
        decision = check_student_gate(
            db, student_id=student_id, assessment=assessment,
        )
    except GateError as e:
        _err(e)
    if decision["gated"]:
        raise HTTPException(
            status_code=403,
            detail=decision.get("reason") or "Subscription required.",
        )


# ═════════════════════════════════════════════════════════════════════════
# GROUP 1 — APP AWARENESS
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/me/assessments",
    response_model=list[AssessmentAwarenessItem],
)
def list_my_assessments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    App awareness: list assessments this student is in the audience of.
    Never returns question content.
    """
    rows = list_available_for_student(db, student_id=current_user.id)
    return [_build_awareness_item(db, a, current_user.id) for a in rows]


@router.get(
    "/me/assessments/{assessment_id}/summary",
    response_model=AssessmentAwarenessSummary,
)
def my_assessment_summary(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """App awareness: summary of a single assessment (no content)."""
    try:
        assessment = get_assessment(db, assessment_id)
    except AssessmentError as e:
        _err(e)

    base = _build_awareness_item(db, assessment, current_user.id)

    # Result availability
    result = db.query(Result).filter(
        Result.assessment_id == assessment_id,
        Result.student_id == current_user.id,
        Result.is_official.is_(True),
    ).first()

    return {
        **base,
        "result_available": bool(result),
        "result_percentage": float(result.percentage) if result else None,
        "result_passed": result.passed if result else None,
    }


@router.get(
    "/me/assessments/{assessment_id}/deep-link",
    response_model=AssessmentDeepLink,
)
def my_assessment_deep_link(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the PWA URL for this assessment. The App opens this URL
    to transition the student into the assessment execution environment.
    """
    try:
        assessment = get_assessment(db, assessment_id)
    except AssessmentError as e:
        _err(e)

    if assessment.status not in (STATUS_PUBLISHED, "in_progress"):
        raise HTTPException(
            status_code=409,
            detail=f"Assessment is not open. Status: {assessment.status}.",
        )

    _require_not_gated(db, current_user.id, assessment)

    url = f"{_pwa_base_url()}/assessment/{assessment_id}"
    return AssessmentDeepLink(
        assessment_id=assessment_id,
        pwa_url=url,
        expires_at=_now() + timedelta(hours=6),
    )


# ═════════════════════════════════════════════════════════════════════════
# GROUP 2 — ASSESSMENT MANAGEMENT (creators)
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/assessments/directed",
    response_model=AssessmentResponse,
    status_code=201,
)
def post_directed_assessment(
    payload: AssessmentDirectedCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a directed assessment (audienced + notified)."""
    try:
        return create_directed_assessment(
            db,
            creator_id=current_user.id,
            creator_role=_resolve_creator_role(db, current_user.id),
            title=payload.title,
            category=payload.category,
            type=payload.type,
            audience_scope=payload.audience_scope,
            audience_ref_id=payload.audience_ref_id,
            description=payload.description,
            audience_resolution=payload.audience_resolution,
            start_at=payload.start_at,
            end_at=payload.end_at,
            duration_minutes=payload.duration_minutes,
            wall_clock_hard_end=payload.wall_clock_hard_end,
            max_attempts=payload.max_attempts,
            passing_score=payload.passing_score,
            auto_grading_enabled=payload.auto_grading_enabled,
        )
    except AssessmentError as e:
        _err(e)


@router.post(
    "/assessments/system-wide",
    response_model=AssessmentResponse,
    status_code=201,
)
def post_system_wide_assessment(
    payload: AssessmentSystemWideCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a system-wide (public, voluntary, catalog) assessment."""
    try:
        return create_system_wide_assessment(
            db,
            creator_id=current_user.id,
            creator_role=_resolve_creator_role(db, current_user.id),
            title=payload.title,
            category=payload.category,
            type=payload.type,
            description=payload.description,
            specialty_unit_ids=payload.specialty_unit_ids,
            difficulty=payload.difficulty,
            estimated_duration_minutes=payload.estimated_duration_minutes,
            start_at=payload.start_at,
            end_at=payload.end_at,
            duration_minutes=payload.duration_minutes,
            max_attempts=payload.max_attempts,
            passing_score=payload.passing_score,
            auto_grading_enabled=payload.auto_grading_enabled,
        )
    except AssessmentError as e:
        _err(e)


@router.get(
    "/assessments",
    response_model=list[AssessmentListItem],
)
def list_assessments_endpoint(
    mode: str | None = Query(None, description="directed | system_wide"),
    status: str | None = Query(None),
    unit_offering_id: str | None = Query(None),
    group_id: str | None = Query(None),
    institution_id: str | None = Query(None),
    mine: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List assessments with filters. `mine=true` scopes to creator."""
    return list_assessments(
        db,
        creator_id=current_user.id if mine else None,
        mode=mode,
        status=status,
        unit_offering_id=unit_offering_id,
        group_id=group_id,
        institution_id=institution_id,
        limit=limit,
    )


@router.get(
    "/assessments/{assessment_id}",
    response_model=AssessmentResponse,
)
def get_assessment_endpoint(
    assessment_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_assessment(db, assessment_id)
    except AssessmentError as e:
        _err(e)


@router.patch(
    "/assessments/{assessment_id}",
    response_model=AssessmentResponse,
)
def patch_assessment(
    assessment_id: str,
    payload: AssessmentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        a = get_assessment(db, assessment_id)
        if a.status != STATUS_DRAFT:
            raise HTTPException(
                status_code=409,
                detail="Only draft assessments can be edited.",
            )
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(a, field, value)
        db.commit()
        db.refresh(a)
        return a
    except AssessmentError as e:
        _err(e)


@router.post(
    "/assessments/{assessment_id}/publish",
    response_model=AssessmentResponse,
)
def publish_assessment_endpoint(
    assessment_id: str,
    payload: AssessmentPublishRequest = AssessmentPublishRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return publish_assessment(
            db,
            assessment_id=assessment_id,
            actor_id=current_user.id,
            notify_audience=payload.notify_audience,
        )
    except AssessmentError as e:
        _err(e)


@router.post(
    "/assessments/{assessment_id}/close",
    response_model=AssessmentResponse,
)
def close_assessment_endpoint(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return close_assessment(
            db, assessment_id=assessment_id, actor_id=current_user.id,
        )
    except AssessmentError as e:
        _err(e)


@router.post(
    "/assessments/{assessment_id}/archive",
    response_model=AssessmentResponse,
)
def archive_assessment_endpoint(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return archive_assessment(
            db, assessment_id=assessment_id, actor_id=current_user.id,
        )
    except AssessmentError as e:
        _err(e)


@router.get(
    "/assessments/{assessment_id}/audience",
    response_model=list[AudienceSnapshotResponse],
)
def list_assessment_audience(
    assessment_id: str,
    include_removed: bool = Query(False),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creator view of the audience snapshot."""
    q = db.query(AssessmentAudienceSnapshot).filter(
        AssessmentAudienceSnapshot.assessment_id == assessment_id,
    )
    if not include_removed:
        q = q.filter(AssessmentAudienceSnapshot.is_still_eligible.is_(True))
    return q.order_by(AssessmentAudienceSnapshot.captured_at).all()


# ═════════════════════════════════════════════════════════════════════════
# GROUP 3 — QUESTION MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/assessments/{assessment_id}/questions",
    response_model=list[QuestionResponse],
)
def list_questions_endpoint(
    assessment_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_assessment_questions(db, assessment_id)


@router.post(
    "/assessments/{assessment_id}/questions",
    response_model=QuestionResponse,
    status_code=201,
)
def add_question_endpoint(
    assessment_id: str,
    payload: QuestionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return add_question_to_assessment(
            db,
            assessment_id=assessment_id,
            creator_id=current_user.id,
            **payload.model_dump(),
        )
    except QuestionError as e:
        _err(e)


@router.get(
    "/assessments/{assessment_id}/questions/{question_id}",
    response_model=QuestionResponse,
)
def get_question_endpoint(
    assessment_id: str,
    question_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_question(db, question_id)
    except QuestionError as e:
        _err(e)


@router.patch(
    "/assessments/{assessment_id}/questions/{question_id}",
    response_model=QuestionResponse,
)
def patch_question_endpoint(
    assessment_id: str,
    question_id: str,
    payload: QuestionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_question(
            db, question_id=question_id, actor_id=current_user.id,
            **payload.model_dump(exclude_unset=True),
        )
    except QuestionError as e:
        _err(e)


@router.delete(
    "/assessments/{assessment_id}/questions/{question_id}",
    status_code=204,
)
def delete_question_endpoint(
    assessment_id: str,
    question_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        delete_question(
            db, question_id=question_id, actor_id=current_user.id,
        )
    except QuestionError as e:
        _err(e)


@router.post(
    "/assessments/{assessment_id}/questions/reorder",
    response_model=list[QuestionResponse],
)
def reorder_questions_endpoint(
    assessment_id: str,
    ordered_question_ids: list[str],
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return reorder_questions(
        db,
        assessment_id=assessment_id,
        ordered_question_ids=ordered_question_ids,
    )


# ═════════════════════════════════════════════════════════════════════════
# GROUP 4 — QUESTION BANKS
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/question-banks",
    response_model=QuestionBankResponse,
    status_code=201,
)
def create_bank_endpoint(
    payload: QuestionBankCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_bank(
            db,
            unit_id=payload.unit_id,
            name=payload.name,
            created_by=current_user.id,
            description=payload.description,
        )
    except QuestionError as e:
        _err(e)


@router.get(
    "/units/{unit_id}/question-banks",
    response_model=list[QuestionBankResponse],
)
def list_banks_endpoint(
    unit_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_banks_for_unit(db, unit_id)


@router.get(
    "/question-banks/{bank_id}",
    response_model=QuestionBankDetailResponse,
)
def get_bank_endpoint(
    bank_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        bank = get_bank(db, bank_id)
    except QuestionError as e:
        _err(e)
    questions = list_bank_questions(db, bank_id)
    return QuestionBankDetailResponse(
        bank=QuestionBankResponse.model_validate(bank),
        question_count=len(questions),
    )


@router.patch(
    "/question-banks/{bank_id}",
    response_model=QuestionBankResponse,
)
def patch_bank_endpoint(
    bank_id: str,
    payload: QuestionBankUpdate,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_bank(
            db, bank_id=bank_id,
            **payload.model_dump(exclude_unset=True),
        )
    except QuestionError as e:
        _err(e)


@router.get(
    "/question-banks/{bank_id}/questions",
    response_model=list[QuestionResponse],
)
def list_bank_questions_endpoint(
    bank_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_bank_questions(db, bank_id)


@router.post(
    "/question-banks/{bank_id}/questions",
    response_model=QuestionResponse,
    status_code=201,
)
def add_bank_question_endpoint(
    bank_id: str,
    payload: QuestionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return add_question_to_bank(
            db,
            bank_id=bank_id,
            creator_id=current_user.id,
            **payload.model_dump(),
        )
    except QuestionError as e:
        _err(e)


@router.post(
    "/question-banks/{bank_id}/clone",
    response_model=list[QuestionResponse],
)
def clone_bank_endpoint(
    bank_id: str,
    assessment_id: str = Query(...),
    question_ids: list[str] = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return clone_from_bank(
            db,
            bank_id=bank_id,
            assessment_id=assessment_id,
            creator_id=current_user.id,
            question_ids=question_ids,
        )
    except QuestionError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# GROUP 5 — PWA ATTEMPT FLOW
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/assessments/{assessment_id}/attempts",
    response_model=AttemptStartResponse,
    status_code=201,
)
def start_attempt_endpoint(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_client_type: str | None = Header(None, alias="X-Client-Type"),
):
    """
    Start an attempt. This is the PWA entry point.
    If X-Client-Type is present and not 'pwa', the request is rejected.
    """
    if x_client_type and x_client_type.lower() != "pwa":
        raise HTTPException(
            status_code=403,
            detail="Assessment execution is PWA-only. Please open the PWA.",
        )

    try:
        attempt, questions = start_attempt(
            db,
            assessment_id=assessment_id,
            student_id=current_user.id,
        )
    except (AttemptError, GateError) as e:
        _err(e)

    # Strip correct answers — deliver only attempt-safe view
    question_views = [
        QuestionAttemptView(
            id=q.id,
            question_type=q.question_type,
            text=q.text,
            options_json=q.options_json,
            point_value=float(q.point_value),
            order_index=q.order_index,
            character_limit=None,
        )
        for q in questions
    ]

    return AttemptStartResponse(
        attempt_id=attempt.id,
        assessment_id=attempt.assessment_id,
        attempt_number=attempt.attempt_number,
        started_at=attempt.started_at,
        timer_expires_at=attempt.timer_expires_at,
        questions=question_views,
    )


@router.get(
    "/attempts/{attempt_id}",
    response_model=AttemptResponse,
)
def get_attempt_endpoint(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        attempt = get_attempt(db, attempt_id)
    except AttemptError as e:
        _err(e)
    if attempt.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your attempt.")
    return attempt


@router.get(
    "/attempts/{attempt_id}/status",
    response_model=AttemptStatusResponse,
)
def attempt_status_endpoint(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_attempt_status(
            db, attempt_id=attempt_id, student_id=current_user.id,
        )
    except AttemptError as e:
        _err(e)


@router.get(
    "/attempts/{attempt_id}/questions",
    response_model=list[QuestionAttemptView],
)
def attempt_questions_endpoint(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deliver questions during an active attempt (PWA only)."""
    try:
        attempt = get_attempt(db, attempt_id)
    except AttemptError as e:
        _err(e)
    if attempt.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your attempt.")
    if attempt.status != "in_progress":
        raise HTTPException(status_code=409, detail="Attempt is not active.")

    questions = list_assessment_questions(db, attempt.assessment_id)
    return [
        QuestionAttemptView(
            id=q.id, question_type=q.question_type, text=q.text,
            options_json=q.options_json, point_value=float(q.point_value),
            order_index=q.order_index, character_limit=None,
        )
        for q in questions
    ]


@router.post(
    "/attempts/{attempt_id}/responses",
    response_model=ResponseResponse,
    status_code=201,
)
def submit_response_endpoint(
    attempt_id: str,
    payload: ResponseSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return submit_response(
            db,
            attempt_id=attempt_id,
            student_id=current_user.id,
            question_id=payload.question_id,
            response_text=payload.response_text,
            response_file_url=payload.response_file_url,
            response_json=payload.response_json,
        )
    except AttemptError as e:
        _err(e)


@router.patch(
    "/attempts/{attempt_id}/responses/{response_id}",
    response_model=ResponseResponse,
)
def update_response_endpoint(
    attempt_id: str,
    response_id: str,
    payload: ResponseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = db.query(AssessmentResponseRow).filter(
        AssessmentResponseRow.id == response_id,
        AssessmentResponseRow.attempt_id == attempt_id,
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Response not found.")
    attempt = get_attempt(db, attempt_id)
    if attempt.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your attempt.")
    if attempt.status != "in_progress":
        raise HTTPException(
            status_code=409, detail="Attempt is no longer editable.",
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(r, field, value)
    db.commit()
    db.refresh(r)
    return r


@router.post(
    "/attempts/{attempt_id}/submit",
    response_model=AttemptResponse,
)
def submit_attempt_endpoint(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return submit_attempt(
            db, attempt_id=attempt_id, student_id=current_user.id,
        )
    except AttemptError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# GROUP 6 — GRADING
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/assessments/{assessment_id}/pending-grading",
    response_model=list[ResponseResponse],
)
def pending_grading_endpoint(
    assessment_id: str,
    limit: int = Query(500, ge=1, le=1000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_pending_grading(
        db, assessment_id=assessment_id, limit=limit,
    )


@router.post(
    "/responses/{response_id}/grade",
    response_model=ResponseResponse,
)
def grade_response_endpoint(
    response_id: str,
    payload: ResponseGradeSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return grade_response(
            db,
            response_id=response_id,
            grader_id=current_user.id,
            score_earned=payload.score_earned,
            feedback=payload.feedback,
            is_correct=payload.is_correct,
        )
    except GradingError as e:
        _err(e)


@router.post(
    "/attempts/{attempt_id}/auto-grade",
    response_model=dict,
)
def auto_grade_endpoint(
    attempt_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        count = auto_grade_objective(db, attempt_id=attempt_id)
    except GradingError as e:
        _err(e)
    return {"attempt_id": attempt_id, "responses_graded": count}


@router.post(
    "/attempts/{attempt_id}/finalise",
    response_model=ResultResponse,
)
def finalise_attempt_endpoint(
    attempt_id: str,
    payload: ResultFinaliseSubmit = ResultFinaliseSubmit(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return finalise_result(
            db,
            attempt_id=attempt_id,
            actor_id=current_user.id,
            competence_level=payload.competence_level,
        )
    except GradingError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# GROUP 7 — RESULTS
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/me/results",
    response_model=list[ResultListItem],
)
def my_results_endpoint(
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = list_results_for_student(
        db, student_id=current_user.id, limit=limit,
    )
    out: list[dict] = []
    for r in rows:
        a = db.query(Assessment).filter(Assessment.id == r.assessment_id).first()
        out.append({
            "id": r.id,
            "assessment_id": r.assessment_id,
            "assessment_title": a.title if a else None,
            "percentage": float(r.percentage),
            "passed": r.passed,
            "competence_level": r.competence_level,
            "is_official": r.is_official,
            "finalised_at": r.finalised_at,
        })
    return out


@router.get(
    "/results/{result_id}",
    response_model=ResultDetailResponse,
)
def get_result_endpoint(
    result_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = get_result(db, result_id)
    except GradingError as e:
        _err(e)
    if result.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your result.")
    responses = db.query(AssessmentResponseRow).filter(
        AssessmentResponseRow.attempt_id == result.best_attempt_id,
    ).all() if result.best_attempt_id else []
    return ResultDetailResponse(
        result=ResultResponse.model_validate(result),
        responses=[
            ResponseResponse.model_validate(r) for r in responses
        ],
    )


@router.post(
    "/results/{result_id}/finalise",
    response_model=ResultResponse,
)
def mark_result_official_endpoint(
    result_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return mark_result_official(
            db, result_id=result_id, actor_id=current_user.id,
        )
    except GradingError as e:
        _err(e)


@router.post(
    "/results/{result_id}/correct",
    response_model=ResultResponse,
)
def correct_result_endpoint(
    result_id: str,
    payload: ResultCorrectSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return correct_result(
            db,
            result_id=result_id,
            actor_id=current_user.id,
            final_score=payload.final_score,
            percentage=payload.percentage,
            passed=payload.passed,
            reason=payload.reason,
        )
    except GradingError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# GROUP 8 — APPEALS
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/results/{result_id}/appeals",
    response_model=AppealResponse,
    status_code=201,
)
def submit_appeal_endpoint(
    result_id: str,
    payload: AppealCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return submit_appeal(
            db,
            result_id=result_id,
            student_id=current_user.id,
            grounds=payload.grounds,
            evidence_json=payload.evidence_json,
        )
    except AppealError as e:
        _err(e)


@router.get(
    "/appeals/{appeal_id}",
    response_model=AppealResponse,
)
def get_appeal_endpoint(
    appeal_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_appeal(db, appeal_id)
    except AppealError as e:
        _err(e)


@router.get(
    "/me/appeals",
    response_model=list[AppealResponse],
)
def my_appeals_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_appeals_for_student(db, student_id=current_user.id)


@router.post(
    "/appeals/{appeal_id}/review",
    response_model=AppealResponse,
)
def review_appeal_endpoint(
    appeal_id: str,
    payload: AppealReviewSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return review_appeal(
            db,
            appeal_id=appeal_id,
            reviewer_id=current_user.id,
            status=payload.status,
            review_notes=payload.review_notes,
            corrected_result_json=payload.corrected_result_json,
        )
    except AppealError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# GROUP 9 — CATALOG (system-wide discovery)
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/assessment-catalog",
    response_model=list[CatalogListItem],
)
def catalog_list_endpoint(
    unit_id: str | None = Query(None),
    creator_id: str | None = Query(None),
    creator_role: str | None = Query(None),
    difficulty: str | None = Query(None),
    category: str | None = Query(None),
    min_rating: float | None = Query(None, ge=0, le=5),
    featured_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=300),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = list_catalog(
        db,
        unit_id=unit_id, creator_id=creator_id, creator_role=creator_role,
        difficulty=difficulty, category=category, min_rating=min_rating,
        featured_only=featured_only, limit=limit,
    )
    out: list[dict] = []
    for assessment, entry in rows:
        creator_name = _creator_display_name(db, assessment.created_by)
        out.append({
            "assessment_id": assessment.id,
            "title": assessment.title,
            "description": assessment.description,
            "creator_name": creator_name,
            "creator_role": assessment.created_by_role,
            "category": assessment.category,
            "difficulty": entry.difficulty,
            "estimated_duration_minutes": entry.estimated_duration_minutes,
            "specialty_tags": entry.specialty_tags,
            "average_rating": entry.average_rating,
            "rating_count": entry.rating_count,
            "take_count": entry.take_count,
            "is_featured": entry.is_featured,
        })
    return out


@router.get(
    "/assessment-catalog/{assessment_id}",
    response_model=CatalogDetailResponse,
)
def catalog_detail_endpoint(
    assessment_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        assessment, entry = get_entry(db, assessment_id)
    except CatalogError as e:
        _err(e)
    record_view(db, assessment_id)
    creator_name = _creator_display_name(db, assessment.created_by)
    return CatalogDetailResponse(
        entry=CatalogListItem(
            assessment_id=assessment.id,
            title=assessment.title,
            description=assessment.description,
            creator_name=creator_name,
            creator_role=assessment.created_by_role,
            category=assessment.category,
            difficulty=entry.difficulty,
            estimated_duration_minutes=entry.estimated_duration_minutes,
            specialty_tags=entry.specialty_tags,
            average_rating=entry.average_rating,
            rating_count=entry.rating_count,
            take_count=entry.take_count,
            is_featured=entry.is_featured,
        ),
        full_assessment=AssessmentResponse.model_validate(assessment),
    )


@router.post(
    "/assessment-catalog/{assessment_id}/start",
    response_model=AttemptStartResponse,
    status_code=201,
)
def catalog_start_endpoint(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_client_type: str | None = Header(None, alias="X-Client-Type"),
):
    """Voluntary attempt on a system-wide assessment (PWA only)."""
    if x_client_type and x_client_type.lower() != "pwa":
        raise HTTPException(
            status_code=403,
            detail="Assessment execution is PWA-only.",
        )
    try:
        assessment, _entry = get_entry(db, assessment_id)
    except CatalogError as e:
        _err(e)

    try:
        attempt, questions = start_attempt(
            db,
            assessment_id=assessment.id,
            student_id=current_user.id,
        )
    except AttemptError as e:
        _err(e)

    record_take(db, assessment.id)

    return AttemptStartResponse(
        attempt_id=attempt.id,
        assessment_id=attempt.assessment_id,
        attempt_number=attempt.attempt_number,
        started_at=attempt.started_at,
        timer_expires_at=attempt.timer_expires_at,
        questions=[
            QuestionAttemptView(
                id=q.id, question_type=q.question_type, text=q.text,
                options_json=q.options_json, point_value=float(q.point_value),
                order_index=q.order_index, character_limit=None,
            )
            for q in questions
        ],
    )


@router.post(
    "/assessment-catalog/{assessment_id}/rate",
    response_model=FeedbackResponse,
    status_code=201,
)
def catalog_rate_endpoint(
    assessment_id: str,
    payload: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rate a system-wide assessment. Feeds catalog's rolling average."""
    from app.models.assessment import Feedback
    fb = Feedback(
        assessment_id=assessment_id,
        student_id=current_user.id,
        rating=payload.rating,
        comment=payload.comment,
        is_anonymous=payload.is_anonymous,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)

    if payload.rating:
        record_rating(db, assessment_id, payload.rating)

    return fb


# ═════════════════════════════════════════════════════════════════════════
# GROUP 10 — ANALYTICS + AI
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/assessments/{assessment_id}/analytics",
    response_model=AssessmentAnalyticsResponse,
)
def assessment_analytics_endpoint(
    assessment_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return assessment_analytics(db, assessment_id=assessment_id)


@router.get(
    "/unit-offerings/{unit_offering_id}/assessment-analytics",
)
def unit_analytics_endpoint(
    unit_offering_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return unit_analytics(db, unit_offering_id=unit_offering_id)


@router.get(
    "/institutions/{institution_id}/assessment-analytics",
)
def institution_analytics_endpoint(
    institution_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return institution_analytics(db, institution_id=institution_id)


@router.post(
    "/assessments/{assessment_id}/ai/draft-questions",
)
def ai_draft_endpoint(
    assessment_id: str,
    unit_title: str = Query(...),
    learning_outcomes: list[str] = Query(...),
    count: int = Query(5, ge=1, le=20),
    difficulty: str = Query("intermediate"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return draft_questions(
            db,
            actor_id=current_user.id,
            assessment_id=assessment_id,
            unit_title=unit_title,
            learning_outcomes=learning_outcomes,
            count=count,
            difficulty=difficulty,
        )
    except AIError as e:
        _err(e)


@router.post(
    "/questions/{question_id}/ai/validate",
)
def ai_validate_endpoint(
    question_id: str,
    text: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return validate_question(
            db,
            actor_id=current_user.id,
            question_id=question_id,
            text=text,
        )
    except AIError as e:
        _err(e)


@router.post(
    "/responses/{response_id}/ai/preliminary-grade",
)
def ai_preliminary_grade_endpoint(
    response_id: str,
    question_text: str = Query(...),
    student_answer: str = Query(...),
    rubric: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return preliminary_grade(
            db,
            actor_id=current_user.id,
            response_id=response_id,
            question_text=question_text,
            student_answer=student_answer,
            rubric=rubric,
        )
    except AIError as e:
        _err(e)


@router.post(
    "/assessments/{assessment_id}/ai/summarize",
)
def ai_summarize_endpoint(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stats = assessment_analytics(db, assessment_id=assessment_id)
    try:
        return summarize_analytics(
            db,
            actor_id=current_user.id,
            assessment_id=assessment_id,
            stats=stats,
        )
    except AIError as e:
        _err(e)


@router.get(
    "/ai-logs",
    response_model=list[AIAssistanceLogResponse],
)
def ai_logs_endpoint(
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return list_logs(
        db, entity_type=entity_type, entity_id=entity_id, limit=limit,
    )


@router.get(
    "/ai-logs/cost-summary",
)
def ai_cost_endpoint(
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return cost_summary(db)


# ═════════════════════════════════════════════════════════════════════════
# ROLE RESOLUTION HELPER
# ═════════════════════════════════════════════════════════════════════════

def _resolve_creator_role(db: Session, user_id: str) -> str:
    """
    Resolve the user's creator role. Priority (highest first):
      1. Super Admin
      2. Regional Admin
      3. Lecturer (teaching assignment)
      4. Unit Supervisor
      5. Unit Representative (active)
      6. Mentor
    Falls back to 'student' → caller will reject.
    """
    from app.models.assessment import (
        CREATOR_SUPER_ADMIN, CREATOR_REGIONAL_ADMIN, CREATOR_LECTURER,
        CREATOR_UNIT_SUPERVISOR, CREATOR_UNIT_REPRESENTATIVE, CREATOR_MENTOR,
    )
    from app.services.role_service import resolve_user_permissions

    try:
        _role, perms = resolve_user_permissions(db, user_id)
    except Exception:
        perms = set()

    if "super_admin.*" in perms or "system.admin" in perms:
        return CREATOR_SUPER_ADMIN
    if "regional.admin" in perms:
        return CREATOR_REGIONAL_ADMIN

    # Unit Representative
    from app.models.unit_representation import UnitRepresentative, REP_ACTIVE
    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.user_id == user_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if rep:
        return CREATOR_UNIT_REPRESENTATIVE

    # Lecturer — check teaching assignment
    # V1: presence of any lecturer role in permissions is the signal
    if "lecturer.*" in perms or "lecturer.teach" in perms:
        return CREATOR_LECTURER

    # Unit Supervisor
    if "unit.supervise" in perms:
        return CREATOR_UNIT_SUPERVISOR

    # Mentor
    if "mentor.*" in perms or "mentor.active" in perms:
        return CREATOR_MENTOR

    return "student"