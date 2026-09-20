"""
Business logic for UnitOfferings — Module 002 completion.

A UnitOffering is a specific occurrence of a Unit during one academic
year and semester. Offerings can be created in advance of the semester
they belong to.

The service derives institution_id / school_id / course_id / year_level
from the Unit's ancestor chain so those fields don't drift.
"""
import logging

from sqlalchemy.orm import Session

from app.models.academic import (
    AcademicStructureAudit,
    AcademicYear, Course, School, Semester, Unit,
)
from app.models.unit_offering import UnitOffering

logger = logging.getLogger(__name__)


class UnitOfferingError(Exception):
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


def _derive_context(
    db: Session, unit: Unit,
) -> tuple[str, str, str]:
    """Walk unit → course → school → institution and return the triple."""
    course = db.query(Course).filter(Course.id == unit.course_id).first()
    if not course:
        raise UnitOfferingError("Unit has no course (data integrity issue).", 500)
    school = db.query(School).filter(School.id == course.school_id).first()
    if not school:
        raise UnitOfferingError("Course has no school (data integrity issue).", 500)
    return school.institution_id, school.id, course.id


# ============================================================================
# CREATE
# ============================================================================

def create_unit_offering(
    db: Session, data, user_id: str | None = None,
) -> UnitOffering:
    unit = db.query(Unit).filter(Unit.id == data.unit_id).first()
    if not unit:
        raise UnitOfferingError("Unit not found.", 404)

    ay = db.query(AcademicYear).filter(AcademicYear.id == data.academic_year_id).first()
    if not ay:
        raise UnitOfferingError("Academic year not found.", 404)

    sem = db.query(Semester).filter(Semester.id == data.semester_id).first()
    if not sem:
        raise UnitOfferingError("Semester not found.", 404)
    if sem.academic_year_id != ay.id:
        raise UnitOfferingError(
            "Semester does not belong to the specified academic year.", 409,
        )

    existing = db.query(UnitOffering).filter(
        UnitOffering.unit_id == unit.id,
        UnitOffering.semester_id == sem.id,
    ).first()
    if existing:
        raise UnitOfferingError(
            "This unit already has an offering for this semester.", 409,
        )

    institution_id, school_id, course_id = _derive_context(db, unit)

    offering = UnitOffering(
        unit_id=unit.id,
        institution_id=institution_id,
        school_id=school_id,
        course_id=course_id,
        academic_year_id=ay.id,
        semester_id=sem.id,
        year_level=unit.year_level or 1,
        status="scheduled",
        enrolled_count=0,
    )
    db.add(offering)
    db.flush()

    _audit(
        db, user_id, "UnitOffering", offering.id, "CREATE",
        new_value=f"unit={unit.code} semester={sem.id}",
    )
    db.commit()
    db.refresh(offering)
    return offering


def ensure_offering_for_unit(
    db: Session, unit_id: str, academic_year_id: str, semester_id: str,
) -> UnitOffering:
    """
    Idempotent helper used by the proposal approval flow: if an offering
    for this (unit, semester) already exists, return it; otherwise
    create one with status='scheduled'.

    Does not commit — caller owns the transaction.
    """
    existing = db.query(UnitOffering).filter(
        UnitOffering.unit_id == unit_id,
        UnitOffering.semester_id == semester_id,
    ).first()
    if existing:
        return existing

    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise UnitOfferingError("Unit not found.", 404)

    institution_id, school_id, course_id = _derive_context(db, unit)

    offering = UnitOffering(
        unit_id=unit.id,
        institution_id=institution_id,
        school_id=school_id,
        course_id=course_id,
        academic_year_id=academic_year_id,
        semester_id=semester_id,
        year_level=unit.year_level or 1,
        status="scheduled",
        enrolled_count=0,
    )
    db.add(offering)
    db.flush()
    return offering


# ============================================================================
# READ
# ============================================================================

def list_unit_offerings(
    db: Session,
    course_id: str | None = None,
    semester_id: str | None = None,
    institution_id: str | None = None,
    academic_year_id: str | None = None,
    status: str | None = None,
) -> list[UnitOffering]:
    q = db.query(UnitOffering)
    if course_id:
        q = q.filter(UnitOffering.course_id == course_id)
    if semester_id:
        q = q.filter(UnitOffering.semester_id == semester_id)
    if institution_id:
        q = q.filter(UnitOffering.institution_id == institution_id)
    if academic_year_id:
        q = q.filter(UnitOffering.academic_year_id == academic_year_id)
    if status:
        q = q.filter(UnitOffering.status == status)
    return q.order_by(UnitOffering.created_at.desc()).all()


def get_unit_offering(db: Session, offering_id: str) -> UnitOffering:
    offering = db.query(UnitOffering).filter(UnitOffering.id == offering_id).first()
    if not offering:
        raise UnitOfferingError("Unit offering not found.", 404)
    return offering


# ============================================================================
# UPDATE
# ============================================================================

def update_unit_offering(
    db: Session, offering_id: str, data, user_id: str | None = None,
) -> UnitOffering:
    offering = get_unit_offering(db, offering_id)
    changes = data.model_dump(exclude_unset=True)

    if "status" in changes and changes["status"]:
        new_status = changes["status"]
        _validate_status_transition(offering.status, new_status)
        offering.status = new_status

    _audit(
        db, user_id, "UnitOffering", offering.id, "UPDATE",
        new_value=str(changes),
    )
    db.commit()
    db.refresh(offering)
    return offering


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"active", "archived"},
    "active": {"completed", "archived"},
    "completed": {"archived"},
    "archived": set(),
}


def _validate_status_transition(current: str, target: str) -> None:
    if current == target:
        return
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise UnitOfferingError(
            f"Cannot transition offering from '{current}' to '{target}'.", 409,
        )


def activate_unit_offering(
    db: Session, offering_id: str, user_id: str | None = None,
) -> UnitOffering:
    offering = get_unit_offering(db, offering_id)
    _validate_status_transition(offering.status, "active")
    offering.status = "active"
    _audit(
        db, user_id, "UnitOffering", offering.id, "ACTIVATE",
        old_value="scheduled", new_value="active",
    )
    db.commit()
    db.refresh(offering)
    return offering


def complete_unit_offering(
    db: Session, offering_id: str, user_id: str | None = None,
) -> UnitOffering:
    offering = get_unit_offering(db, offering_id)
    _validate_status_transition(offering.status, "completed")
    old = offering.status
    offering.status = "completed"
    _audit(
        db, user_id, "UnitOffering", offering.id, "COMPLETE",
        old_value=old, new_value="completed",
    )
    db.commit()
    db.refresh(offering)
    return offering


def archive_unit_offering(
    db: Session, offering_id: str, user_id: str | None = None,
    reason: str | None = None,
) -> UnitOffering:
    offering = get_unit_offering(db, offering_id)
    if offering.status == "archived":
        return offering
    old = offering.status
    offering.status = "archived"
    _audit(
        db, user_id, "UnitOffering", offering.id, "ARCHIVE",
        old_value=old, new_value="archived", reason=reason,
    )
    db.commit()
    db.refresh(offering)
    return offering