"""
Assessment analytics — Module 005.
"""
import logging
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.assessment import (
    Assessment, Question, Attempt, Response, Result,
    ATTEMPT_GRADED, ATTEMPT_SUBMITTED, ATTEMPT_TIMED_OUT,
)


logger = logging.getLogger(__name__)


def assessment_analytics(db: Session, *, assessment_id: str) -> dict:
    total_attempts = db.query(func.count(Attempt.id)).filter(
        Attempt.assessment_id == assessment_id,
    ).scalar() or 0

    distinct_students = db.query(
        func.count(func.distinct(Attempt.student_id))
    ).filter(
        Attempt.assessment_id == assessment_id,
    ).scalar() or 0

    graded = db.query(func.count(Attempt.id)).filter(
        Attempt.assessment_id == assessment_id,
        Attempt.status == ATTEMPT_GRADED,
    ).scalar() or 0

    avg_score = db.query(func.avg(Attempt.percentage)).filter(
        Attempt.assessment_id == assessment_id,
        Attempt.status == ATTEMPT_GRADED,
    ).scalar()

    pass_rate = None
    if graded:
        passes = db.query(func.count(Result.id)).filter(
            Result.assessment_id == assessment_id,
            Result.passed.is_(True),
        ).scalar() or 0
        pass_rate = round(passes / graded * 100, 2)

    completion_rate = None
    if total_attempts:
        finished = db.query(func.count(Attempt.id)).filter(
            Attempt.assessment_id == assessment_id,
            Attempt.status.in_((ATTEMPT_SUBMITTED, ATTEMPT_TIMED_OUT, ATTEMPT_GRADED)),
        ).scalar() or 0
        completion_rate = round(finished / total_attempts * 100, 2)

    per_question = _per_question_stats(db, assessment_id)

    return {
        "assessment_id": assessment_id,
        "total_attempts": int(total_attempts),
        "distinct_students": int(distinct_students),
        "average_score": round(float(avg_score), 2) if avg_score else None,
        "pass_rate": pass_rate,
        "completion_rate": completion_rate,
        "difficulty_index": _difficulty_index(avg_score),
        "per_question_stats": per_question,
    }


def _per_question_stats(db: Session, assessment_id: str) -> list[dict]:
    from sqlalchemy import case

    rows = db.query(
        Question.id,
        Question.order_index,
        Question.question_type,
        Question.difficulty,
        func.count(Response.id).label("attempts"),
        func.avg(Response.score_earned).label("avg_score"),
        func.sum(
            case((Response.is_correct.is_(True), 1), else_=0)
        ).label("correct_count"),
    ).outerjoin(
        Response, Response.question_id == Question.id,
    ).filter(
        Question.assessment_id == assessment_id,
    ).group_by(
        Question.id, Question.order_index, Question.question_type, Question.difficulty,
    ).order_by(Question.order_index).all()

    out: list[dict] = []
    for r in rows:
        out.append({
            "question_id": r[0],
            "order_index": r[1],
            "question_type": r[2],
            "difficulty": r[3],
            "attempts": int(r[4] or 0),
            "avg_score": float(r[5]) if r[5] is not None else None,
        })
    return out


def _difficulty_index(avg_score) -> float | None:
    if avg_score is None:
        return None
    # Higher avg_score → lower difficulty. Map 0-100 to 1.0-0.0
    return round(max(0.0, (100 - float(avg_score)) / 100.0), 3)


def unit_analytics(db: Session, *, unit_offering_id: str) -> dict:
    assessments = db.query(Assessment).filter(
        Assessment.unit_offering_id == unit_offering_id,
    ).all()
    ids = [a.id for a in assessments]
    if not ids:
        return {
            "unit_offering_id": unit_offering_id,
            "assessment_count": 0,
            "aggregate_attempts": 0,
            "aggregate_avg_score": None,
        }

    total_attempts = db.query(func.count(Attempt.id)).filter(
        Attempt.assessment_id.in_(ids),
    ).scalar() or 0

    avg = db.query(func.avg(Attempt.percentage)).filter(
        Attempt.assessment_id.in_(ids),
        Attempt.status == ATTEMPT_GRADED,
    ).scalar()

    return {
        "unit_offering_id": unit_offering_id,
        "assessment_count": len(ids),
        "aggregate_attempts": int(total_attempts),
        "aggregate_avg_score": round(float(avg), 2) if avg else None,
    }


def institution_analytics(db: Session, *, institution_id: str) -> dict:
    assessments = db.query(Assessment).filter(
        Assessment.institution_id == institution_id,
    ).all()
    ids = [a.id for a in assessments]
    if not ids:
        return {
            "institution_id": institution_id,
            "assessment_count": 0,
            "aggregate_attempts": 0,
        }

    total_attempts = db.query(func.count(Attempt.id)).filter(
        Attempt.assessment_id.in_(ids),
    ).scalar() or 0

    distinct_students = db.query(
        func.count(func.distinct(Attempt.student_id))
    ).filter(
        Attempt.assessment_id.in_(ids),
    ).scalar() or 0

    return {
        "institution_id": institution_id,
        "assessment_count": len(ids),
        "aggregate_attempts": int(total_attempts),
        "distinct_students": int(distinct_students),
    }