"""
Grading & result finalisation — Module 005.

Auto-grade for objective questions. Human grading for essays.
Result finalisation aggregates per-question scores into a Result.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.assessment import (
    Assessment, Question, Attempt, Response, Result,
    AssessmentAuditLog,
    ATTEMPT_SUBMITTED, ATTEMPT_TIMED_OUT, ATTEMPT_GRADED,
    QTYPE_MCQ, QTYPE_TRUE_FALSE, QTYPE_FILL_BLANK,
    AUDIT_EVALUATE, AUDIT_MODIFY_RESULT,
    LEVEL_INTRODUCTORY, LEVEL_DEVELOPING,
    LEVEL_COMPETENT, LEVEL_ADVANCED,
)


logger = logging.getLogger(__name__)


class GradingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# AUTO-GRADE
# ─────────────────────────────────────────────────────────────────────────

def auto_grade_objective(db: Session, *, attempt_id: str) -> int:
    """
    Auto-grade MCQ, True/False, and Fill-in-the-Blank responses.
    Returns the number of responses auto-graded.
    """
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if not attempt:
        raise GradingError("Attempt not found.", 404)
    if attempt.status not in (ATTEMPT_SUBMITTED, ATTEMPT_TIMED_OUT):
        raise GradingError(
            "Auto-grade only runs on submitted attempts.", 409,
        )

    responses = db.query(Response).filter(
        Response.attempt_id == attempt_id,
        Response.is_correct.is_(None),
    ).all()

    count = 0
    for r in responses:
        question = db.query(Question).filter(
            Question.id == r.question_id,
        ).first()
        if not question:
            continue

        if question.question_type not in (
            QTYPE_MCQ, QTYPE_TRUE_FALSE, QTYPE_FILL_BLANK,
        ):
            continue

        correct = _check_objective(question, r)
        if correct is None:
            continue

        r.is_correct = correct
        r.score_earned = float(question.point_value) if correct else 0.0
        r.graded_at = _now()
        # graded_by stays NULL — indicates system auto-grade
        count += 1

    db.commit()
    return count


def _check_objective(question: Question, response: Response) -> bool | None:
    correct = question.correct_answer_json
    if correct is None:
        return None

    student = response.response_json
    if student is None and response.response_text is not None:
        student = response.response_text.strip()

    if isinstance(correct, dict) and "value" in correct:
        correct = correct["value"]

    if question.question_type == QTYPE_FILL_BLANK:
        if student is None:
            return False
        return str(student).strip().lower() == str(correct).strip().lower()

    # MCQ / TrueFalse
    return student == correct


# ─────────────────────────────────────────────────────────────────────────
# HUMAN GRADING
# ─────────────────────────────────────────────────────────────────────────

def grade_response(
    db: Session, *, response_id: str, grader_id: str,
    score_earned: float, feedback: str | None = None,
    is_correct: bool | None = None,
) -> Response:
    r = db.query(Response).filter(Response.id == response_id).first()
    if not r:
        raise GradingError("Response not found.", 404)

    question = db.query(Question).filter(
        Question.id == r.question_id,
    ).first()
    if question and score_earned > float(question.point_value):
        raise GradingError(
            f"score_earned exceeds question max ({question.point_value}).", 400,
        )

    r.score_earned = score_earned
    r.feedback = feedback
    if is_correct is not None:
        r.is_correct = is_correct
    r.graded_by = grader_id
    r.graded_at = _now()
    db.commit()
    db.refresh(r)
    return r


def list_pending_grading(
    db: Session, *, assessment_id: str, limit: int = 500,
) -> list[Response]:
    """Responses awaiting human grading (not auto-graded, not yet graded)."""
    return db.query(Response).join(
        Attempt, Attempt.id == Response.attempt_id,
    ).filter(
        Attempt.assessment_id == assessment_id,
        Response.graded_at.is_(None),
    ).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────
# RESULT FINALISATION
# ─────────────────────────────────────────────────────────────────────────

def finalise_result(
    db: Session, *, attempt_id: str, actor_id: str,
    competence_level: str | None = None,
) -> Result:
    """
    Aggregate all response scores into a final Result.
    Enforces: all responses graded before finalisation.
    """
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if not attempt:
        raise GradingError("Attempt not found.", 404)

    ungraded = db.query(Response).filter(
        Response.attempt_id == attempt_id,
        Response.graded_at.is_(None),
    ).count()
    if ungraded > 0:
        raise GradingError(
            f"{ungraded} response(s) still ungraded.", 409,
        )

    assessment = db.query(Assessment).filter(
        Assessment.id == attempt.assessment_id,
    ).first()

    total_earned = sum(
        float(r.score_earned or 0)
        for r in db.query(Response).filter(
            Response.attempt_id == attempt_id,
        ).all()
    )
    total_possible = sum(
        float(q.point_value)
        for q in db.query(Question).filter(
            Question.assessment_id == attempt.assessment_id,
        ).all()
    )

    percentage = (
        (total_earned / total_possible * 100) if total_possible else 0.0
    )
    passed = (
        assessment.passing_score is None
        or percentage >= float(assessment.passing_score)
    )

    attempt.score = total_earned
    attempt.percentage = percentage
    attempt.passed = passed
    attempt.status = ATTEMPT_GRADED

    # Upsert Result
    result = db.query(Result).filter(
        Result.assessment_id == attempt.assessment_id,
        Result.student_id == attempt.student_id,
    ).first()

    if result:
        # Keep the best attempt
        if (
            result.best_attempt_id is None
            or percentage > float(result.percentage or 0)
        ):
            result.best_attempt_id = attempt.id
            result.final_score = total_earned
            result.percentage = percentage
            result.passed = passed
    else:
        result = Result(
            assessment_id=attempt.assessment_id,
            student_id=attempt.student_id,
            best_attempt_id=attempt.id,
            final_score=total_earned,
            percentage=percentage,
            passed=passed,
            competence_level=competence_level,
            is_official=False,
        )
        db.add(result)

    if competence_level:
        result.competence_level = competence_level

    db.flush()

    db.add(AssessmentAuditLog(
        assessment_id=attempt.assessment_id,
        actor_id=actor_id,
        action=AUDIT_EVALUATE,
        target_type="attempt", target_id=attempt.id,
        new_value=f"score={total_earned} pct={percentage:.2f} passed={passed}",
    ))

    db.commit()
    db.refresh(result)
    return result


def mark_result_official(
    db: Session, *, result_id: str, actor_id: str,
) -> Result:
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise GradingError("Result not found.", 404)
    result.is_official = True
    result.finalised_at = _now()
    result.finalised_by = actor_id
    db.commit()
    db.refresh(result)
    return result


def correct_result(
    db: Session, *, result_id: str, actor_id: str,
    final_score: float, percentage: float, passed: bool,
    reason: str,
) -> Result:
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise GradingError("Result not found.", 404)

    old = f"score={result.final_score} pct={result.percentage} passed={result.passed}"
    result.final_score = final_score
    result.percentage = percentage
    result.passed = passed
    result.is_official = True
    result.finalised_at = _now()
    result.finalised_by = actor_id

    db.add(AssessmentAuditLog(
        assessment_id=result.assessment_id, actor_id=actor_id,
        action=AUDIT_MODIFY_RESULT, target_type="result",
        target_id=result.id,
        old_value=old,
        new_value=f"score={final_score} pct={percentage} passed={passed}",
        reason=reason,
    ))
    db.commit()
    db.refresh(result)
    return result


def _derive_competence_level(percentage: float) -> str:
    if percentage >= 85:
        return LEVEL_ADVANCED
    if percentage >= 70:
        return LEVEL_COMPETENT
    if percentage >= 50:
        return LEVEL_DEVELOPING
    return LEVEL_INTRODUCTORY


def get_result(db: Session, result_id: str) -> Result:
    r = db.query(Result).filter(Result.id == result_id).first()
    if not r:
        raise GradingError("Result not found.", 404)
    return r


def list_results_for_student(
    db: Session, *, student_id: str, limit: int = 200,
) -> list[Result]:
    return db.query(Result).filter(
        Result.student_id == student_id,
    ).order_by(Result.created_at.desc()).limit(limit).all()


def list_results_for_assessment(
    db: Session, *, assessment_id: str, limit: int = 1000,
) -> list[Result]:
    return db.query(Result).filter(
        Result.assessment_id == assessment_id,
    ).order_by(Result.percentage.desc()).limit(limit).all()