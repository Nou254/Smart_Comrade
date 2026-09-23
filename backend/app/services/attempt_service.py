"""
Assessment attempt lifecycle — Module 005.

The PWA-only surface. Every state transition is backend-enforced.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.assessment import (
    Assessment, Question, Attempt, Response, AssessmentAuditLog,
    STATUS_PUBLISHED, STATUS_IN_PROGRESS,
    ATTEMPT_IN_PROGRESS, ATTEMPT_SUBMITTED, ATTEMPT_TIMED_OUT,
    ATTEMPT_ABANDONED,
    AUDIT_OPEN,
)
from app.services.subscription_gate_service import ensure_student_can_start


logger = logging.getLogger(__name__)


class AttemptError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────────────────────

def start_attempt(
    db: Session, *, assessment_id: str, student_id: str,
    ip_address: str | None = None, user_agent: str | None = None,
) -> tuple[Attempt, list[Question]]:
    """
    Start an attempt. Enforces:
      - assessment is published (or already in_progress)
      - student is not subscription-gated
      - no active attempt already open
      - attempt limit not exceeded
      - timeline permits (started before end_at)
    """
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id,
    ).first()
    if not assessment:
        raise AttemptError("Assessment not found.", 404)
    if assessment.status not in (STATUS_PUBLISHED, STATUS_IN_PROGRESS):
        raise AttemptError(
            f"Assessment is not open for attempts. Status: "
            f"{assessment.status}.", 409,
        )

    now = _now()

    # Timeline check
    if assessment.start_at and now < assessment.start_at:
        raise AttemptError("Assessment has not opened yet.", 409)
    if assessment.end_at and now >= assessment.end_at:
        raise AttemptError("Assessment has closed.", 409)

    # Subscription gate
    ensure_student_can_start(db, student_id=student_id, assessment=assessment)

    # Active attempt?
    active = db.query(Attempt).filter(
        Attempt.assessment_id == assessment_id,
        Attempt.student_id == student_id,
        Attempt.status == ATTEMPT_IN_PROGRESS,
    ).first()
    if active:
        # Resume — return the same attempt
        questions = _questions_for_assessment(db, assessment_id)
        return active, questions

    # Attempt limit
    count = db.query(Attempt).filter(
        Attempt.assessment_id == assessment_id,
        Attempt.student_id == student_id,
    ).count()
    if count >= assessment.max_attempts:
        raise AttemptError(
            f"Attempt limit reached ({assessment.max_attempts}).", 409,
        )

    # Timer
    timer_expires = _compute_timer(assessment, now)

    attempt = Attempt(
        assessment_id=assessment_id,
        student_id=student_id,
        attempt_number=count + 1,
        started_at=now,
        timer_expires_at=timer_expires,
        status=ATTEMPT_IN_PROGRESS,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(attempt)

    # Flip assessment into in_progress if first attempt
    if assessment.status == STATUS_PUBLISHED:
        assessment.status = STATUS_IN_PROGRESS

    db.flush()
    db.add(AssessmentAuditLog(
        assessment_id=assessment_id, actor_id=student_id,
        action=AUDIT_OPEN,
        new_value=f"attempt={attempt.id} number={attempt.attempt_number}",
    ))
    db.commit()
    db.refresh(attempt)

    questions = _questions_for_assessment(db, assessment_id)
    return attempt, questions


def _compute_timer(
    assessment: Assessment, started_at: datetime,
) -> datetime | None:
    if not assessment.duration_minutes:
        return None
    candidate = started_at + timedelta(minutes=assessment.duration_minutes)
    if assessment.wall_clock_hard_end and assessment.end_at:
        return min(candidate, assessment.end_at)
    return candidate


def _questions_for_assessment(
    db: Session, assessment_id: str,
) -> list[Question]:
    return db.query(Question).filter(
        Question.assessment_id == assessment_id,
    ).order_by(Question.order_index).all()


# ─────────────────────────────────────────────────────────────────────────
# SUBMIT RESPONSE
# ─────────────────────────────────────────────────────────────────────────

def submit_response(
    db: Session, *, attempt_id: str, student_id: str,
    question_id: str,
    response_text: str | None = None,
    response_file_url: str | None = None,
    response_json: dict | None = None,
) -> Response:
    attempt = db.query(Attempt).filter(
        Attempt.id == attempt_id,
        Attempt.student_id == student_id,
    ).first()
    if not attempt:
        raise AttemptError("Attempt not found.", 404)
    if attempt.status != ATTEMPT_IN_PROGRESS:
        raise AttemptError("Attempt is no longer open.", 409)

    now = _now()
    if attempt.timer_expires_at and now >= attempt.timer_expires_at:
        # Auto-submit on expiry
        _finalise_attempt(db, attempt, timed_out=True)
        db.commit()
        raise AttemptError("Attempt has timed out.", 409)

    question = db.query(Question).filter(
        Question.id == question_id,
        Question.assessment_id == attempt.assessment_id,
    ).first()
    if not question:
        raise AttemptError("Question does not belong to this assessment.", 400)

    existing = db.query(Response).filter(
        Response.attempt_id == attempt_id,
        Response.question_id == question_id,
    ).first()

    if existing:
        if response_text is not None:
            existing.response_text = response_text
        if response_file_url is not None:
            existing.response_file_url = response_file_url
        if response_json is not None:
            existing.response_json = response_json
        db.commit()
        db.refresh(existing)
        return existing

    resp = Response(
        attempt_id=attempt_id,
        question_id=question_id,
        response_text=response_text,
        response_file_url=response_file_url,
        response_json=response_json,
    )
    db.add(resp)
    db.commit()
    db.refresh(resp)
    return resp


# ─────────────────────────────────────────────────────────────────────────
# SUBMIT ATTEMPT
# ─────────────────────────────────────────────────────────────────────────

def submit_attempt(
    db: Session, *, attempt_id: str, student_id: str,
) -> Attempt:
    attempt = db.query(Attempt).filter(
        Attempt.id == attempt_id,
        Attempt.student_id == student_id,
    ).first()
    if not attempt:
        raise AttemptError("Attempt not found.", 404)
    if attempt.status != ATTEMPT_IN_PROGRESS:
        raise AttemptError("Attempt has already been submitted.", 409)

    _finalise_attempt(db, attempt, timed_out=False)
    db.commit()
    db.refresh(attempt)
    return attempt


def _finalise_attempt(
    db: Session, attempt: Attempt, *, timed_out: bool,
) -> None:
    now = _now()
    attempt.submitted_at = now
    attempt.status = ATTEMPT_TIMED_OUT if timed_out else ATTEMPT_SUBMITTED
    # Auto-grade hook — grading_service consumes SUBMITTED attempts
    db.flush()


# ─────────────────────────────────────────────────────────────────────────
# STATUS / POLLING
# ─────────────────────────────────────────────────────────────────────────

def get_attempt_status(
    db: Session, *, attempt_id: str, student_id: str,
) -> dict:
    attempt = db.query(Attempt).filter(
        Attempt.id == attempt_id,
        Attempt.student_id == student_id,
    ).first()
    if not attempt:
        raise AttemptError("Attempt not found.", 404)

    now = _now()
    seconds_remaining: int | None = None
    if attempt.timer_expires_at and attempt.status == ATTEMPT_IN_PROGRESS:
        delta = (attempt.timer_expires_at - now).total_seconds()
        seconds_remaining = max(0, int(delta))

    total_q = db.query(Question).filter(
        Question.assessment_id == attempt.assessment_id,
    ).count()
    answered = db.query(Response).filter(
        Response.attempt_id == attempt_id,
    ).count()

    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "seconds_remaining": seconds_remaining,
        "answered_count": answered,
        "total_questions": total_q,
    }


def get_attempt(db: Session, attempt_id: str) -> Attempt:
    a = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if not a:
        raise AttemptError("Attempt not found.", 404)
    return a


def list_attempts_for_student(
    db: Session, *, student_id: str, assessment_id: str | None = None,
    limit: int = 100,
) -> list[Attempt]:
    q = db.query(Attempt).filter(Attempt.student_id == student_id)
    if assessment_id:
        q = q.filter(Attempt.assessment_id == assessment_id)
    return q.order_by(Attempt.started_at.desc()).limit(limit).all()


def list_attempts_for_assessment(
    db: Session, *, assessment_id: str, status: str | None = None,
    limit: int = 500,
) -> list[Attempt]:
    q = db.query(Attempt).filter(Attempt.assessment_id == assessment_id)
    if status:
        q = q.filter(Attempt.status == status)
    return q.order_by(Attempt.started_at.desc()).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────
# TIMEOUT SWEEP (cron entry point)
# ─────────────────────────────────────────────────────────────────────────

def sweep_expired_attempts(db: Session, *, batch_size: int = 200) -> int:
    """Called by cron to auto-submit attempts whose timer has expired."""
    now = _now()
    expired = db.query(Attempt).filter(
        Attempt.status == ATTEMPT_IN_PROGRESS,
        Attempt.timer_expires_at.isnot(None),
        Attempt.timer_expires_at <= now,
    ).limit(batch_size).all()

    for attempt in expired:
        _finalise_attempt(db, attempt, timed_out=True)
    if expired:
        db.commit()
    return len(expired)