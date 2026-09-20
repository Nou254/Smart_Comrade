"""
Business logic for Combinations — Module 002 completion.

A Combination is a course-bound pairing of subjects. Design rules:
  - Bound to exactly one course.
  - No formal approval workflow is required.
  - A notification is sent to Regional + Super only (County is skipped).
  - Only appears in the registration cascade when the course has at
    least one active combination.
"""
import logging

from sqlalchemy.orm import Session

from app.models.academic import (
    AcademicStructureAudit, Course, School, Institution,
)
from app.models.combination import Combination

logger = logging.getLogger(__name__)


class CombinationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _audit(
    db: Session, user_id: str | None, entity_type: str, entity_id: str,
    action: str, old_value: str | None = None, new_value: str | None = None,
    reason: str | None = None,
) -> None:
    db.add(AcademicStructureAudit(
        user_id=user_id, entity_type=entity_type, entity_id=entity_id,
        action=action, old_value=old_value, new_value=new_value, reason=reason,
    ))


def _notify_higher_admins_for_combination(
    db: Session, combination: Combination, actor_id: str,
) -> None:
    """
    Notification-only workflow: Regional + Super are informed; County is
    skipped (per canonical spec).

    Currently a stub that logs the event. When the notification service
    exposes a general dispatch helper, replace the log calls with actual
    dispatches to the Regional and Super recipients.
    """
    try:
        course = db.query(Course).filter(Course.id == combination.course_id).first()
        school = db.query(School).filter(School.id == course.school_id).first() if course else None
        institution = (
            db.query(Institution).filter(Institution.id == school.institution_id).first()
            if school else None
        )
    except Exception:
        course = school = institution = None

    logger.info(
        "[combination.notify] combination=%s course=%s institution=%s actor=%s "
        "→ notify: regional_admin, super_admin (county_representative skipped)",
        combination.id,
        getattr(course, "code", None),
        getattr(institution, "code", None),
        actor_id,
    )


# ============================================================================
# CREATE
# ============================================================================

def create_combination(db: Session, data, user_id: str | None = None) -> Combination:
    course = db.query(Course).filter(Course.id == data.course_id).first()
    if not course:
        raise CombinationError("Course not found.", 404)
    if course.status != "active":
        raise CombinationError("Cannot add combinations to an inactive course.", 409)

    code = data.code.strip().upper()
    name = data.name.strip()

    if db.query(Combination).filter(
        Combination.course_id == course.id,
        Combination.code == code,
    ).first():
        raise CombinationError(
            f"Combination code '{code}' already exists for this course.", 409,
        )
    if db.query(Combination).filter(
        Combination.course_id == course.id,
        Combination.name == name,
    ).first():
        raise CombinationError(
            f"Combination '{name}' already exists for this course.", 409,
        )

    combo = Combination(
        course_id=course.id,
        name=name,
        code=code,
        description=data.description,
        status="active",
        created_by=user_id,
    )
    db.add(combo)
    db.flush()

    _audit(
        db, user_id, "Combination", combo.id, "CREATE",
        new_value=f"{combo.code} - {combo.name}",
    )
    db.commit()
    db.refresh(combo)

    _notify_higher_admins_for_combination(db, combo, actor_id=user_id or "system")
    return combo


# ============================================================================
# READ
# ============================================================================

def list_combinations(
    db: Session,
    course_id: str | None = None,
    status: str | None = None,
) -> list[Combination]:
    q = db.query(Combination)
    if course_id:
        q = q.filter(Combination.course_id == course_id)
    if status:
        q = q.filter(Combination.status == status)
    return q.order_by(Combination.name).all()


def get_combination(db: Session, combination_id: str) -> Combination:
    combo = db.query(Combination).filter(Combination.id == combination_id).first()
    if not combo:
        raise CombinationError("Combination not found.", 404)
    return combo


# ============================================================================
# UPDATE
# ============================================================================

def update_combination(
    db: Session, combination_id: str, data, user_id: str | None = None,
) -> Combination:
    combo = get_combination(db, combination_id)
    changes = data.model_dump(exclude_unset=True)

    new_code = changes.get("code")
    if new_code and new_code.strip().upper() != combo.code:
        candidate = new_code.strip().upper()
        if db.query(Combination).filter(
            Combination.course_id == combo.course_id,
            Combination.code == candidate,
            Combination.id != combo.id,
        ).first():
            raise CombinationError(
                f"Combination code '{candidate}' already exists for this course.",
                409,
            )
        combo.code = candidate

    new_name = changes.get("name")
    if new_name and new_name.strip() != combo.name:
        candidate = new_name.strip()
        if db.query(Combination).filter(
            Combination.course_id == combo.course_id,
            Combination.name == candidate,
            Combination.id != combo.id,
        ).first():
            raise CombinationError(
                f"Combination '{candidate}' already exists for this course.",
                409,
            )
        combo.name = candidate

    if "description" in changes:
        combo.description = changes["description"]
    if "status" in changes:
        combo.status = changes["status"]

    _audit(
        db, user_id, "Combination", combo.id, "UPDATE",
        new_value=str(changes),
    )
    db.commit()
    db.refresh(combo)
    return combo


def deactivate_combination(
    db: Session, combination_id: str, reason: str | None = None,
    user_id: str | None = None,
) -> Combination:
    combo = get_combination(db, combination_id)
    if combo.status == "inactive":
        return combo
    combo.status = "inactive"
    _audit(
        db, user_id, "Combination", combo.id, "DEACTIVATE",
        old_value="active", new_value="inactive", reason=reason,
    )
    db.commit()
    db.refresh(combo)
    return combo


def reactivate_combination(
    db: Session, combination_id: str, user_id: str | None = None,
) -> Combination:
    combo = get_combination(db, combination_id)
    if combo.status != "inactive":
        raise CombinationError(
            f"Cannot reactivate combination in status '{combo.status}'.", 409,
        )
    combo.status = "active"
    _audit(
        db, user_id, "Combination", combo.id, "REACTIVATE",
        old_value="inactive", new_value="active",
    )
    db.commit()
    db.refresh(combo)
    return combo