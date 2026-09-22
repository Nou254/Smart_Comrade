"""
Educational questions with AI-assisted research — Module 004.

Design:
  - A rep (or supervisor) poses an educational question.
  - An AI assistant silently researches and responds within 5 minutes.
  - A supervisor may later override the AI response.
  - A rep may pose a question on behalf of an anonymous student.

In V1 the AI research call is STUBBED — it returns a placeholder
response immediately. Wiring the real LLM provider is a Wave D+ task.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.unit_offering import UnitOffering
from app.models.unit_representation import (
    UnitQuestion, UnitQuestionResponse, UnitRepresentative,
    REP_ACTIVE,
    QUESTION_POSED, QUESTION_AI_RESPONDED, QUESTION_SUPERVISOR_REVIEW,
    QUESTION_RESOLVED, QUESTION_DISMISSED,
    QUESTION_CATEGORIES, QUESTION_AI_RESPONSE_MINUTES,
)


logger = logging.getLogger(__name__)


class UnitQuestionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# POSE A QUESTION
# ─────────────────────────────────────────────────────────────────────────

def pose_question(
    db: Session,
    *,
    unit_offering_id: str,
    raised_by_user_id: str,
    subject: str,
    question_text: str,
    category: str = "educational",
    is_anonymous: bool = False,
    anonymous_student_reference: str | None = None,
) -> UnitQuestion:
    """
    Pose an educational question. Must come from an active rep.
    Category must be one of the educational categories.
    """
    if category not in QUESTION_CATEGORIES:
        raise UnitQuestionError(
            f"Category '{category}' is not an educational category. "
            f"Allowed: {QUESTION_CATEGORIES}.", 400,
        )

    offering = db.query(UnitOffering).filter(
        UnitOffering.id == unit_offering_id,
    ).first()
    if not offering:
        raise UnitQuestionError("Unit offering not found.", 404)

    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.user_id == raised_by_user_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if not rep:
        raise UnitQuestionError(
            "Only active Unit Representatives may pose unit questions.", 403,
        )

    now = _now()
    question = UnitQuestion(
        unit_offering_id=unit_offering_id,
        raised_by_representative_id=rep.id,
        raised_by_user_id=raised_by_user_id,
        is_anonymous=is_anonymous,
        anonymous_student_reference=anonymous_student_reference,
        subject=subject,
        question_text=question_text,
        category=category,
        status=QUESTION_POSED,
        posed_at=now,
        ai_response_deadline=now + timedelta(
            minutes=QUESTION_AI_RESPONSE_MINUTES,
        ),
    )
    db.add(question)
    db.commit()
    db.refresh(question)

    # Fire the AI research stub synchronously for now.
    # In production this becomes a background task.
    _ai_research_and_respond(db, question)
    db.refresh(question)
    return question


# ─────────────────────────────────────────────────────────────────────────
# AI RESEARCH STUB
# ─────────────────────────────────────────────────────────────────────────

def _ai_research_and_respond(
    db: Session, question: UnitQuestion,
) -> UnitQuestionResponse:
    """
    Stub for the AI research + response flow. In production this hits an
    LLM provider with a structured prompt grounded in the unit's learning
    materials. For V1 it returns a placeholder immediately.

    The 5-minute deadline is enforced by the service contract:
    ai_responded_at is stamped at write time, and the analytics layer
    alerts if any question's response lands after ai_response_deadline.
    """
    now = _now()
    response = UnitQuestionResponse(
        question_id=question.id,
        responder_type="ai",
        responder_user_id=None,
        content=(
            "[AI Assistant — V1 stub]\n\n"
            f"Question received: {question.subject}\n\n"
            "The AI research module is not yet wired to an LLM provider. "
            "Once enabled, this response will contain a researched answer "
            "with citations from the unit's learning materials and "
            "reference sources.\n\n"
            "A Unit Supervisor has been notified and may override this "
            "response."
        ),
        research_sources_json=[],
        confidence_score=0.0,
    )
    db.add(response)
    question.ai_responded_at = now
    question.status = QUESTION_AI_RESPONDED
    db.commit()
    db.refresh(response)
    return response


# ─────────────────────────────────────────────────────────────────────────
# SUPERVISOR RESPONSE
# ─────────────────────────────────────────────────────────────────────────

def supervisor_respond(
    db: Session,
    *,
    question_id: str,
    supervisor_user_id: str,
    content: str,
    supersedes_response_id: str | None = None,
) -> UnitQuestionResponse:
    """
    Supervisor posts a response. If supersedes_response_id is set, the
    earlier response (usually AI) is marked as superseded.
    """
    question = db.query(UnitQuestion).filter(
        UnitQuestion.id == question_id,
    ).first()
    if not question:
        raise UnitQuestionError("Question not found.", 404)

    # Verify the user is the supervisor for this offering
    from app.models.unit_representation import UnitNetwork
    network = db.query(UnitNetwork).filter(
        UnitNetwork.unit_offering_id == question.unit_offering_id,
    ).first()
    if not network or network.supervisor_user_id != supervisor_user_id:
        raise UnitQuestionError(
            "Only the assigned Unit Supervisor may post supervisor responses.",
            403,
        )

    response = UnitQuestionResponse(
        question_id=question.id,
        responder_type="supervisor",
        responder_user_id=supervisor_user_id,
        content=content,
    )
    db.add(response)
    db.flush()

    if supersedes_response_id:
        earlier = db.query(UnitQuestionResponse).filter(
            UnitQuestionResponse.id == supersedes_response_id,
            UnitQuestionResponse.question_id == question.id,
        ).first()
        if earlier:
            earlier.superseded_by_response_id = response.id

    question.status = QUESTION_SUPERVISOR_REVIEW
    db.commit()
    db.refresh(response)
    return response


# ─────────────────────────────────────────────────────────────────────────
# RESOLUTION
# ─────────────────────────────────────────────────────────────────────────

def resolve_question(
    db: Session,
    *,
    question_id: str,
    actor_id: str,
    resolution_notes: str,
) -> UnitQuestion:
    question = db.query(UnitQuestion).filter(
        UnitQuestion.id == question_id,
    ).first()
    if not question:
        raise UnitQuestionError("Question not found.", 404)

    question.status = QUESTION_RESOLVED
    question.resolved_at = _now()
    question.resolution_notes = resolution_notes
    db.commit()
    db.refresh(question)
    return question


def dismiss_question(
    db: Session,
    *,
    question_id: str,
    actor_id: str,
    resolution_notes: str,
) -> UnitQuestion:
    question = db.query(UnitQuestion).filter(
        UnitQuestion.id == question_id,
    ).first()
    if not question:
        raise UnitQuestionError("Question not found.", 404)

    question.status = QUESTION_DISMISSED
    question.resolved_at = _now()
    question.resolution_notes = resolution_notes
    db.commit()
    db.refresh(question)
    return question


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_question(db: Session, question_id: str) -> UnitQuestion:
    q = db.query(UnitQuestion).filter(UnitQuestion.id == question_id).first()
    if not q:
        raise UnitQuestionError("Question not found.", 404)
    return q


def list_questions(
    db: Session,
    *,
    unit_offering_id: str,
    status: str | None = None,
    limit: int = 200,
) -> list[UnitQuestion]:
    q = db.query(UnitQuestion).filter(
        UnitQuestion.unit_offering_id == unit_offering_id,
    )
    if status:
        q = q.filter(UnitQuestion.status == status)
    return q.order_by(UnitQuestion.posed_at.desc()).limit(limit).all()


def list_responses(
    db: Session, question_id: str,
) -> list[UnitQuestionResponse]:
    return db.query(UnitQuestionResponse).filter(
        UnitQuestionResponse.question_id == question_id,
    ).order_by(UnitQuestionResponse.created_at).all()


def find_late_ai_responses(
    db: Session, *, limit: int = 100,
) -> list[UnitQuestion]:
    """
    Analytics helper — returns questions where the AI responded after
    the deadline. Used to monitor the 5-minute SLA.
    """
    return db.query(UnitQuestion).filter(
        UnitQuestion.ai_responded_at.isnot(None),
        UnitQuestion.ai_responded_at > UnitQuestion.ai_response_deadline,
    ).limit(limit).all()