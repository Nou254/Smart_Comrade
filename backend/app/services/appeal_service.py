"""
Appeal lifecycle — Module 005.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.assessment import (
    Result, Appeal, AssessmentAuditLog,
    APPEAL_SUBMITTED, APPEAL_UNDER_REVIEW,
    APPEAL_RESOLVED_CONFIRMED, APPEAL_RESOLVED_CORRECTED,
    APPEAL_REASSESSMENT_AUTHORISED, APPEAL_REJECTED,
    AUDIT_APPEAL_REVIEW,
)


logger = logging.getLogger(__name__)


class AppealError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def submit_appeal(
    db: Session, *, result_id: str, student_id: str,
    grounds: str, evidence_json: list | None = None,
) -> Appeal:
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise AppealError("Result not found.", 404)
    if result.student_id != student_id:
        raise AppealError("You may only appeal your own results.", 403)
    if not result.is_official:
        raise AppealError("Only finalised results can be appealed.", 409)

    existing = db.query(Appeal).filter(
        Appeal.result_id == result_id,
        Appeal.student_id == student_id,
        Appeal.status.in_((APPEAL_SUBMITTED, APPEAL_UNDER_REVIEW)),
    ).first()
    if existing:
        raise AppealError(
            "An appeal is already open for this result.", 409,
        )

    original_snapshot = {
        "final_score": float(result.final_score),
        "percentage": float(result.percentage),
        "passed": result.passed,
        "competence_level": result.competence_level,
    }

    appeal = Appeal(
        result_id=result_id,
        student_id=student_id,
        grounds=grounds,
        evidence_json=evidence_json,
        status=APPEAL_SUBMITTED,
        original_result_json=original_snapshot,
    )
    db.add(appeal)
    db.commit()
    db.refresh(appeal)
    return appeal


def review_appeal(
    db: Session, *, appeal_id: str, reviewer_id: str,
    status: str, review_notes: str,
    corrected_result_json: dict | None = None,
) -> Appeal:
    if status not in (
        APPEAL_RESOLVED_CONFIRMED, APPEAL_RESOLVED_CORRECTED,
        APPEAL_REASSESSMENT_AUTHORISED, APPEAL_REJECTED,
    ):
        raise AppealError(f"Invalid review outcome '{status}'.", 400)

    appeal = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not appeal:
        raise AppealError("Appeal not found.", 404)
    if appeal.status not in (APPEAL_SUBMITTED, APPEAL_UNDER_REVIEW):
        raise AppealError("Appeal is already resolved.", 409)

    appeal.status = status
    appeal.reviewer_id = reviewer_id
    appeal.reviewed_at = _now()
    appeal.review_notes = review_notes
    if corrected_result_json:
        appeal.corrected_result_json = corrected_result_json

    db.add(AssessmentAuditLog(
        assessment_id=None, actor_id=reviewer_id,
        action=AUDIT_APPEAL_REVIEW, target_type="appeal",
        target_id=appeal.id,
        new_value=status,
        reason=review_notes,
    ))
    db.commit()
    db.refresh(appeal)
    return appeal


def get_appeal(db: Session, appeal_id: str) -> Appeal:
    a = db.query(Appeal).filter(Appeal.id == appeal_id).first()
    if not a:
        raise AppealError("Appeal not found.", 404)
    return a


def list_appeals_for_student(
    db: Session, *, student_id: str, limit: int = 200,
) -> list[Appeal]:
    return db.query(Appeal).filter(
        Appeal.student_id == student_id,
    ).order_by(Appeal.created_at.desc()).limit(limit).all()


def list_appeals_for_result(
    db: Session, result_id: str,
) -> list[Appeal]:
    return db.query(Appeal).filter(
        Appeal.result_id == result_id,
    ).order_by(Appeal.created_at.desc()).all()