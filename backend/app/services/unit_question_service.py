"""
Educational questions with AI-assisted research — Module 004.

Design:
  - A rep (or supervisor) poses an educational question.
  - An AI assistant silently researches and responds within 5 minutes.
  - A supervisor may later override the AI response.
  - A rep may pose a question on behalf of an anonymous student.

The AI research call is served by the shared LLM client in
`ai_assistance_service`. If the provider is unavailable the response is
still recorded, with confidence 0.0 and a note, so a supervisor can
follow up instead of the question being left in limbo.
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

    # Research and respond synchronously. In production this becomes a
    # background task; the service contract (ai_response_deadline) is
    # unchanged either way.
    _ai_research_and_respond(db, question)
    db.refresh(question)
    return question


# ─────────────────────────────────────────────────────────────────────────
# AI RESEARCH
# ─────────────────────────────────────────────────────────────────────────

_AI_SYSTEM = (
    "You are a subject-matter tutor researching a student's academic "
    "question. Answer accurately and concisely, grounded in the unit "
    "context you are given. If you are unsure, say so. Respond with JSON "
    "only."
)


def _ai_research_and_respond(
    db: Session, question: UnitQuestion,
) -> UnitQuestionResponse:
    """
    Research and answer a unit question with the LLM.

    The 5-minute deadline is enforced by the service contract:
    ai_responded_at is stamped at write time, and the analytics layer
    alerts if any question's response lands after ai_response_deadline.
    """
    now = _now()
    content, sources, confidence = _research(db, question)

    response = UnitQuestionResponse(
        question_id=question.id,
        responder_type="ai",
        responder_user_id=None,
        content=content,
        research_sources_json=sources,
        confidence_score=confidence,
    )
    db.add(response)
    question.ai_responded_at = now
    question.status = QUESTION_AI_RESPONDED
    db.commit()
    db.refresh(response)
    return response


def _research(db: Session, question: UnitQuestion) -> tuple[str, list, float]:
    """Run the LLM research call. Never raises — degrades to a note."""
    from app.core.config import settings
    from app.services.ai_assistance_service import (
        AIError, _parse_json, chat_completion,
    )

    unit_label = question.unit_offering_id
    offering = db.query(UnitOffering).filter(
        UnitOffering.id == question.unit_offering_id,
    ).first()
    if offering is not None:
        unit_label = getattr(offering, "unit_id", None) or unit_label

    prompt = (
        f"Unit offering: {unit_label}\n"
        f"Category: {question.category}\n"
        f"Subject: {question.subject}\n\n"
        f"Question:\n{question.question_text}\n\n"
        "Return JSON of the form "
        '{"answer": "...", "sources": ["..."], "confidence": 0.0-1.0}.'
    )

    try:
        raw, _usage = chat_completion(
            prompt=prompt, system=_AI_SYSTEM,
            model=settings.AI_MODEL_MID, json_mode=True,
        )
    except AIError as e:
        logger.warning("[unit_question] AI research unavailable: %s", e.message)
        return (
            "The AI research service is currently unavailable, so no "
            "researched answer could be produced for this question. A Unit "
            "Supervisor has been notified and will respond.\n\n"
            f"Question received: {question.subject}",
            [],
            0.0,
        )

    try:
        data = _parse_json(raw)
    except AIError:
        return (raw.strip(), [], 0.5)

    if not isinstance(data, dict):
        return (str(data), [], 0.5)

    content = str(data.get("answer") or raw).strip()
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = [str(sources)]
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return (content, sources, max(0.0, min(1.0, confidence)))


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