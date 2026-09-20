"""
Business logic for academic structure management.

Includes:
  - Region / County / Institution / School / Course / Unit CRUD
  - Academic Year / Semester
  - Student Enrollment / Unit Membership
  - Institution campus role (main / branch)
  - Institution transitions (promote to main, change type) — immutable history
  - Institution transition requests — Institution Admin → Regional Admin workflow
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.academic import (
    Region, County, Institution, School, Course, Unit,
    AcademicYear, Semester, StudentEnrollment, UnitMembership,
    AcademicStructureAudit,
    InstitutionTransition, InstitutionTransitionRequest,
)


VALID_INSTITUTION_TYPES = {
    "UNIVERSITY", "UNIVERSITY_COLLEGE", "COLLEGE",
    "POLYTECHNIC", "TVET", "TECHNICAL_INSTITUTE",
    "KMTC", "TTC", "OTHER",
}
VALID_CAMPUS_ROLES = {"main", "branch"}


class AcademicError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _audit(db: Session, user_id: str | None, entity_type: str, entity_id: str,
           action: str, old_value: str | None = None, new_value: str | None = None,
           reason: str | None = None) -> None:
    db.add(AcademicStructureAudit(
        user_id=user_id, entity_type=entity_type, entity_id=entity_id,
        action=action, old_value=old_value, new_value=new_value, reason=reason,
    ))


def _apply_update(db: Session, entity, data, *, protected_fields: set[str] | None = None):
    """Apply model_dump(exclude_unset=True) fields onto an ORM entity.
    Skips any field listed in protected_fields."""
    protected = protected_fields or set()
    changes = data.model_dump(exclude_unset=True)
    old_snapshot = {k: getattr(entity, k, None) for k in changes.keys()}
    for field, value in changes.items():
        if field in protected:
            continue
        if field in ("code",) and isinstance(value, str):
            value = value.strip().upper()
        if field in ("name",) and isinstance(value, str):
            value = value.strip()
        setattr(entity, field, value)
    return changes, old_snapshot


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# REGION
# ============================================================================

def create_region(db: Session, data, user_id: str | None = None) -> Region:
    if db.query(Region).filter(Region.code == data.code).first():
        raise AcademicError(f"Region code '{data.code}' already exists.", 409)
    if db.query(Region).filter(Region.name == data.name).first():
        raise AcademicError(f"Region '{data.name}' already exists.", 409)
    region = Region(code=data.code, name=data.name, description=data.description)
    db.add(region); db.flush()
    _audit(db, user_id, "Region", region.id, "CREATE", new_value=region.name)
    db.commit(); db.refresh(region)
    return region


def list_regions(db: Session) -> list[Region]:
    return db.query(Region).order_by(Region.name).all()


# ============================================================================
# COUNTY
# ============================================================================

def create_county(db: Session, data, user_id: str | None = None) -> County:
    if not db.query(Region).filter(Region.id == data.region_id).first():
        raise AcademicError("Region not found.", 404)
    if db.query(County).filter(County.code == data.code).first():
        raise AcademicError(f"County code '{data.code}' already exists.", 409)
    county = County(region_id=data.region_id, code=data.code, name=data.name)
    db.add(county); db.flush()
    _audit(db, user_id, "County", county.id, "CREATE", new_value=county.name)
    db.commit(); db.refresh(county)
    return county


def list_counties(db: Session, region_id: str | None = None) -> list[County]:
    q = db.query(County)
    if region_id:
        q = q.filter(County.region_id == region_id)
    return q.order_by(County.name).all()


# ============================================================================
# INSTITUTION
# ============================================================================

def create_institution(db: Session, data, user_id: str | None = None) -> Institution:
    if db.query(Institution).filter(Institution.code == data.code).first():
        raise AcademicError(f"Institution code '{data.code}' already exists.", 409)
    if not db.query(County).filter(County.id == data.county_id).first():
        raise AcademicError("County not found.", 404)

    if data.type not in VALID_INSTITUTION_TYPES:
        raise AcademicError(
            f"Invalid type. Must be one of: {sorted(VALID_INSTITUTION_TYPES)}"
        )

    campus_role = (getattr(data, "campus_role", None) or "main").lower()
    if campus_role not in VALID_CAMPUS_ROLES:
        raise AcademicError(
            f"Invalid campus_role. Must be one of: {sorted(VALID_CAMPUS_ROLES)}"
        )

    parent_id = getattr(data, "parent_institution_id", None)

    # ─── Campus role / parent validation ──────────────────────────────────
    if campus_role == "branch":
        if not parent_id:
            raise AcademicError(
                "A branch campus must specify its parent main campus.", 400,
            )
        parent = db.query(Institution).filter(Institution.id == parent_id).first()
        if not parent:
            raise AcademicError("Parent institution not found.", 404)
        if parent.campus_role != "main":
            raise AcademicError(
                "The parent institution must itself be a main campus.", 409,
            )
    else:  # main
        if parent_id:
            raise AcademicError(
                "A main campus cannot have a parent institution. "
                "Use campus_role='branch' to reference a parent.",
                400,
            )

    inst = Institution(
        name=data.name.strip(),
        short_name=data.short_name,
        code=data.code.strip().upper(),
        type=data.type,
        campus_role=campus_role,
        county_id=data.county_id,
        parent_institution_id=parent_id,
        physical_address=data.physical_address,
        email=data.email,
        phone=data.phone,
        website=data.website,
        status="pending",
    )
    db.add(inst); db.flush()
    _audit(db, user_id, "Institution", inst.id, "CREATE",
           new_value=f"{inst.name} ({campus_role})")
    db.commit(); db.refresh(inst)
    return inst


def list_institutions(db: Session, county_id: str | None = None,
                      type_filter: str | None = None,
                      status_filter: str | None = None,
                      campus_role: str | None = None,
                      parent_institution_id: str | None = None) -> list[Institution]:
    q = db.query(Institution)
    if county_id:
        q = q.filter(Institution.county_id == county_id)
    if type_filter:
        q = q.filter(Institution.type == type_filter)
    if status_filter:
        q = q.filter(Institution.status == status_filter)
    if campus_role:
        q = q.filter(Institution.campus_role == campus_role)
    if parent_institution_id:
        q = q.filter(Institution.parent_institution_id == parent_institution_id)
    return q.order_by(Institution.name).all()


def list_main_campuses(db: Session) -> list[Institution]:
    """
    All institutions that are main campuses and are not deactivated.
    Used to populate the parent dropdown when creating a branch.
    """
    return (
        db.query(Institution)
        .filter(
            Institution.campus_role == "main",
            Institution.status.in_(["active", "pending", "suspended"]),
        )
        .order_by(Institution.name)
        .all()
    )


def get_institution(db: Session, institution_id: str) -> Institution:
    inst = db.query(Institution).filter(Institution.id == institution_id).first()
    if not inst:
        raise AcademicError("Institution not found.", 404)
    return inst


def update_institution(db: Session, institution_id: str, data,
                       user_id: str | None = None) -> Institution:
    inst = get_institution(db, institution_id)
    old_status = inst.status

    # Protect structural fields — those change only via the transition flow.
    _apply_update(
        db, inst, data,
        protected_fields={
            "campus_role", "parent_institution_id", "type", "code", "county_id",
        },
    )
    _audit(db, user_id, "Institution", inst.id, "UPDATE",
           old_value=f"status={old_status}", new_value=f"status={inst.status}")
    db.commit(); db.refresh(inst)
    return inst


def approve_institution(db: Session, institution_id: str, user_id: str | None = None) -> Institution:
    inst = get_institution(db, institution_id)
    if inst.status != "pending":
        raise AcademicError(f"Cannot approve institution in status '{inst.status}'.", 409)
    inst.status = "active"
    _audit(db, user_id, "Institution", inst.id, "APPROVE",
           old_value="pending", new_value="active")
    db.commit(); db.refresh(inst)
    return inst


def reject_institution(db: Session, institution_id: str, reason: str | None = None,
                       user_id: str | None = None) -> Institution:
    inst = get_institution(db, institution_id)
    if inst.status not in ("pending", "active"):
        raise AcademicError(f"Cannot reject institution in status '{inst.status}'.", 409)
    old = inst.status
    inst.status = "rejected"
    _audit(db, user_id, "Institution", inst.id, "REJECT",
           old_value=old, new_value="rejected", reason=reason)
    db.commit(); db.refresh(inst)
    return inst


def suspend_institution(db: Session, institution_id: str, reason: str | None = None,
                        user_id: str | None = None) -> Institution:
    inst = get_institution(db, institution_id)
    if inst.status == "suspended":
        return inst
    old = inst.status
    inst.status = "suspended"
    _audit(db, user_id, "Institution", inst.id, "SUSPEND",
           old_value=old, new_value="suspended", reason=reason)
    db.commit(); db.refresh(inst)
    return inst


def reactivate_institution(db: Session, institution_id: str,
                           user_id: str | None = None) -> Institution:
    inst = get_institution(db, institution_id)
    if inst.status != "suspended":
        raise AcademicError(f"Cannot reactivate institution in status '{inst.status}'.", 409)
    inst.status = "active"
    _audit(db, user_id, "Institution", inst.id, "REACTIVATE",
           old_value="suspended", new_value="active")
    db.commit(); db.refresh(inst)
    return inst


def deactivate_institution(db: Session, institution_id: str, reason: str | None = None,
                           user_id: str | None = None) -> Institution:
    inst = get_institution(db, institution_id)
    if inst.status == "deactivated":
        return inst
    old = inst.status
    inst.status = "deactivated"
    _audit(db, user_id, "Institution", inst.id, "DEACTIVATE",
           old_value=old, new_value="deactivated", reason=reason)
    db.commit(); db.refresh(inst)
    return inst


# ============================================================================
# INSTITUTION TRANSITIONS (promote / change type / etc.)
# ============================================================================

def _validate_transition_target(
    db: Session,
    institution: Institution,
    new_campus_role: str | None,
    new_type: str | None,
    new_parent_institution_id: str | None,
) -> None:
    """Validate the desired end state."""
    target_role = (new_campus_role or institution.campus_role).lower()
    target_type = (new_type or institution.type).upper()
    target_parent = (
        new_parent_institution_id
        if new_campus_role is not None
        else institution.parent_institution_id
    )

    if target_role not in VALID_CAMPUS_ROLES:
        raise AcademicError(
            f"Invalid campus_role. Must be one of: {sorted(VALID_CAMPUS_ROLES)}"
        )
    if target_type not in VALID_INSTITUTION_TYPES:
        raise AcademicError(
            f"Invalid type. Must be one of: {sorted(VALID_INSTITUTION_TYPES)}"
        )

    if target_role == "branch":
        if not target_parent:
            raise AcademicError("A branch campus must specify a parent.", 400)
        if target_parent == institution.id:
            raise AcademicError("An institution cannot be its own parent.", 400)
        parent = db.query(Institution).filter(Institution.id == target_parent).first()
        if not parent:
            raise AcademicError("Parent institution not found.", 404)
        if parent.campus_role != "main":
            raise AcademicError("Parent must be a main campus.", 409)
    else:  # main
        if target_parent:
            raise AcademicError(
                "A main campus cannot have a parent institution.", 400,
            )

    # Branches cannot have branches
    if institution.campus_role == "branch":
        sub_branches = (
            db.query(Institution)
            .filter(Institution.parent_institution_id == institution.id)
            .count()
        )
        if sub_branches > 0:
            raise AcademicError(
                "This institution has child branches and cannot be changed.", 409,
            )


def transition_institution(
    db: Session,
    institution_id: str,
    actor_id: str,
    *,
    new_campus_role: str | None = None,
    new_type: str | None = None,
    new_parent_institution_id: str | None = None,
    reason: str | None = None,
    reference: str | None = None,
    source_request_id: str | None = None,
) -> tuple[Institution, InstitutionTransition]:
    """
    Apply a structural transition to an institution.

    At least one of {new_campus_role, new_type, new_parent_institution_id}
    must differ from the current state. The change and its history record
    are written atomically.

    Examples:
      - Promote a branch to main: new_campus_role='main'
      - Change type only: new_type='UNIVERSITY'
      - Promote and change type in one action (charter award):
          new_campus_role='main', new_type='UNIVERSITY'
    """
    inst = get_institution(db, institution_id)
    _validate_transition_target(
        db, inst, new_campus_role, new_type, new_parent_institution_id,
    )

    old_campus_role = inst.campus_role
    old_type = inst.type
    old_parent = inst.parent_institution_id

    target_campus_role = (new_campus_role or inst.campus_role).lower()
    target_type = (new_type or inst.type).upper()
    target_parent = (
        new_parent_institution_id
        if new_campus_role is not None
        else inst.parent_institution_id
    )

    # No-op check
    if (
        target_campus_role == old_campus_role
        and target_type == old_type
        and target_parent == old_parent
    ):
        raise AcademicError("No change: target state matches current state.", 409)

    # Determine transition_type label
    if old_campus_role == "branch" and target_campus_role == "main":
        if old_type != target_type:
            transition_type = "promote_and_change_type"
        else:
            transition_type = "promote_to_main"
    elif old_type != target_type and target_campus_role == old_campus_role:
        transition_type = "change_type"
    elif target_parent != old_parent:
        transition_type = "set_parent" if target_parent else "remove_parent"
    else:
        transition_type = "other"

    # Apply the change
    inst.campus_role = target_campus_role
    inst.type = target_type
    inst.parent_institution_id = target_parent

    # Record immutable history
    transition = InstitutionTransition(
        institution_id=inst.id,
        transition_type=transition_type,
        old_campus_role=old_campus_role,
        old_type=old_type,
        old_parent_institution_id=old_parent,
        new_campus_role=target_campus_role,
        new_type=target_type,
        new_parent_institution_id=target_parent,
        reason=reason,
        reference=reference,
        changed_by=actor_id,
        changed_at=_now(),
        source_request_id=source_request_id,
    )
    db.add(transition)

    _audit(
        db, actor_id, "Institution", inst.id, "TRANSITION",
        old_value=f"{old_campus_role}/{old_type}",
        new_value=f"{target_campus_role}/{target_type}",
        reason=reason,
    )
    db.commit(); db.refresh(inst); db.refresh(transition)
    return inst, transition


def list_institution_transitions(
    db: Session, institution_id: str,
) -> list[InstitutionTransition]:
    """History of all accepted transitions for one institution, newest first."""
    return (
        db.query(InstitutionTransition)
        .filter(InstitutionTransition.institution_id == institution_id)
        .order_by(InstitutionTransition.changed_at.desc())
        .all()
    )


# ============================================================================
# INSTITUTION TRANSITION REQUESTS (Institution Admin → Regional Admin)
# ============================================================================

def request_transition(
    db: Session,
    institution_id: str,
    requester_id: str,
    *,
    desired_campus_role: str | None = None,
    desired_type: str | None = None,
    desired_parent_institution_id: str | None = None,
    reason: str,
    reference: str | None = None,
) -> InstitutionTransitionRequest:
    """
    Institution Admin submits a request for a structural transition.

    Validation matches the direct-transition rules, but nothing is applied
    until a Regional Admin reviews and approves.
    """
    inst = get_institution(db, institution_id)

    if not reason or len(reason.strip()) < 5:
        raise AcademicError("A reason of at least 5 characters is required.", 400)

    if not any([desired_campus_role, desired_type, desired_parent_institution_id]):
        raise AcademicError(
            "At least one desired change must be specified.", 400,
        )

    # Pre-validate the target state (fails early if it's obviously invalid)
    _validate_transition_target(
        db, inst,
        desired_campus_role, desired_type, desired_parent_institution_id,
    )

    # Reject if there's already a pending request for this institution
    existing = (
        db.query(InstitutionTransitionRequest)
        .filter(
            InstitutionTransitionRequest.institution_id == institution_id,
            InstitutionTransitionRequest.status == "pending",
        )
        .first()
    )
    if existing:
        raise AcademicError(
            "A pending transition request already exists for this institution.", 409,
        )

    req = InstitutionTransitionRequest(
        institution_id=institution_id,
        requested_by=requester_id,
        requested_at=_now(),
        desired_campus_role=desired_campus_role,
        desired_type=desired_type,
        desired_parent_institution_id=desired_parent_institution_id,
        reason=reason.strip(),
        reference=reference,
        status="pending",
    )
    db.add(req); db.flush()

    _audit(
        db, requester_id, "Institution", institution_id, "TRANSITION_REQUESTED",
        new_value=f"request_id={req.id}",
        reason=reason,
    )
    db.commit(); db.refresh(req)
    return req


def list_pending_transition_requests(
    db: Session, institution_id: str | None = None,
) -> list[InstitutionTransitionRequest]:
    q = db.query(InstitutionTransitionRequest).filter(
        InstitutionTransitionRequest.status == "pending",
    )
    if institution_id:
        q = q.filter(InstitutionTransitionRequest.institution_id == institution_id)
    return q.order_by(InstitutionTransitionRequest.requested_at.asc()).all()


def get_transition_request(
    db: Session, request_id: str,
) -> InstitutionTransitionRequest:
    req = (
        db.query(InstitutionTransitionRequest)
        .filter(InstitutionTransitionRequest.id == request_id)
        .first()
    )
    if not req:
        raise AcademicError("Transition request not found.", 404)
    return req


def approve_transition_request(
    db: Session, request_id: str, reviewer_id: str,
    notes: str | None = None,
) -> tuple[Institution, InstitutionTransition, InstitutionTransitionRequest]:
    """
    Regional Admin approves a pending request. Applies the transition and
    marks the request approved, all in one transaction.
    """
    req = get_transition_request(db, request_id)
    if req.status != "pending":
        raise AcademicError(f"Request is not pending (status={req.status}).", 409)

    inst, transition = transition_institution(
        db,
        institution_id=req.institution_id,
        actor_id=reviewer_id,
        new_campus_role=req.desired_campus_role,
        new_type=req.desired_type,
        new_parent_institution_id=req.desired_parent_institution_id,
        reason=req.reason,
        reference=req.reference,
        source_request_id=req.id,
    )

    req.status = "approved"
    req.reviewed_by = reviewer_id
    req.reviewed_at = _now()
    req.review_notes = notes
    db.commit(); db.refresh(req)

    return inst, transition, req


def reject_transition_request(
    db: Session, request_id: str, reviewer_id: str,
    notes: str | None = None,
) -> InstitutionTransitionRequest:
    req = get_transition_request(db, request_id)
    if req.status != "pending":
        raise AcademicError(f"Request is not pending (status={req.status}).", 409)

    req.status = "rejected"
    req.reviewed_by = reviewer_id
    req.reviewed_at = _now()
    req.review_notes = notes
    db.commit(); db.refresh(req)

    _audit(
        db, reviewer_id, "Institution", req.institution_id, "TRANSITION_REJECTED",
        old_value=f"request_id={req.id}",
        reason=notes,
    )
    return req


def withdraw_transition_request(
    db: Session, request_id: str, requester_id: str,
) -> InstitutionTransitionRequest:
    req = get_transition_request(db, request_id)
    if req.status != "pending":
        raise AcademicError(f"Request is not pending (status={req.status}).", 409)
    if req.requested_by != requester_id:
        raise AcademicError("Only the original requester may withdraw.", 403)

    req.status = "withdrawn"
    req.reviewed_at = _now()
    db.commit(); db.refresh(req)
    return req


# ============================================================================
# SCHOOL
# ============================================================================

def create_school(db: Session, data, user_id: str | None = None) -> School:
    if not db.query(Institution).filter(Institution.id == data.institution_id).first():
        raise AcademicError("Institution not found.", 404)
    exists = db.query(School).filter(
        School.institution_id == data.institution_id,
        School.code == data.code,
    ).first()
    if exists:
        raise AcademicError(f"School code '{data.code}' already exists in this institution.", 409)
    school = School(
        institution_id=data.institution_id,
        name=data.name.strip(),
        code=data.code.strip().upper(),
        description=data.description,
        status="active",
    )
    db.add(school); db.flush()
    _audit(db, user_id, "School", school.id, "CREATE", new_value=school.name)
    db.commit(); db.refresh(school)
    return school


def list_schools(db: Session, institution_id: str | None = None) -> list[School]:
    q = db.query(School)
    if institution_id:
        q = q.filter(School.institution_id == institution_id)
    return q.order_by(School.name).all()


def get_school(db: Session, school_id: str) -> School:
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise AcademicError("School not found.", 404)
    return school


def update_school(db: Session, school_id: str, data, user_id: str | None = None) -> School:
    school = get_school(db, school_id)
    changes = data.model_dump(exclude_unset=True)
    new_code = changes.get("code")
    if new_code and new_code.strip().upper() != school.code:
        exists = db.query(School).filter(
            School.institution_id == school.institution_id,
            School.code == new_code.strip().upper(),
        ).first()
        if exists:
            raise AcademicError(
                f"School code '{new_code}' already exists in this institution.", 409
            )
    _apply_update(db, school, data, protected_fields={"institution_id"})
    _audit(db, user_id, "School", school.id, "UPDATE", new_value=str(changes))
    db.commit(); db.refresh(school)
    return school


def deactivate_school(db: Session, school_id: str, reason: str | None = None,
                      user_id: str | None = None) -> School:
    school = get_school(db, school_id)
    active_courses = db.query(Course).filter(
        Course.school_id == school.id, Course.status == "active"
    ).count()
    if active_courses > 0:
        raise AcademicError(
            f"Cannot deactivate school: {active_courses} active course(s) exist.", 409
        )
    if school.status == "inactive":
        return school
    school.status = "inactive"
    _audit(db, user_id, "School", school.id, "DEACTIVATE",
           old_value="active", new_value="inactive", reason=reason)
    db.commit(); db.refresh(school)
    return school


def reactivate_school(db: Session, school_id: str,
                      user_id: str | None = None) -> School:
    school = get_school(db, school_id)
    if school.status != "inactive":
        raise AcademicError(f"Cannot reactivate school in status '{school.status}'.", 409)
    school.status = "active"
    _audit(db, user_id, "School", school.id, "REACTIVATE",
           old_value="inactive", new_value="active")
    db.commit(); db.refresh(school)
    return school


# ============================================================================
# COURSE
# ============================================================================

def create_course(db: Session, data, user_id: str | None = None) -> Course:
    if not db.query(School).filter(School.id == data.school_id).first():
        raise AcademicError("School not found.", 404)
    exists = db.query(Course).filter(
        Course.school_id == data.school_id,
        Course.code == data.code,
    ).first()
    if exists:
        raise AcademicError(f"Course code '{data.code}' already exists in this school.", 409)
    course = Course(
        school_id=data.school_id,
        name=data.name.strip(),
        code=data.code.strip().upper(),
        duration_years=data.duration_years,
        description=data.description,
        status="active",
    )
    db.add(course); db.flush()
    _audit(db, user_id, "Course", course.id, "CREATE", new_value=course.name)
    db.commit(); db.refresh(course)
    return course


def list_courses(db: Session, school_id: str | None = None) -> list[Course]:
    q = db.query(Course)
    if school_id:
        q = q.filter(Course.school_id == school_id)
    return q.order_by(Course.name).all()


def get_course(db: Session, course_id: str) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise AcademicError("Course not found.", 404)
    return course


def update_course(db: Session, course_id: str, data, user_id: str | None = None) -> Course:
    course = get_course(db, course_id)
    changes = data.model_dump(exclude_unset=True)
    new_code = changes.get("code")
    if new_code and new_code.strip().upper() != course.code:
        exists = db.query(Course).filter(
            Course.school_id == course.school_id,
            Course.code == new_code.strip().upper(),
        ).first()
        if exists:
            raise AcademicError(
                f"Course code '{new_code}' already exists in this school.", 409
            )
    _apply_update(db, course, data, protected_fields={"school_id"})
    _audit(db, user_id, "Course", course.id, "UPDATE", new_value=str(changes))
    db.commit(); db.refresh(course)
    return course


def deactivate_course(db: Session, course_id: str, reason: str | None = None,
                      user_id: str | None = None) -> Course:
    course = get_course(db, course_id)
    active_units = db.query(Unit).filter(
        Unit.course_id == course.id, Unit.status == "active"
    ).count()
    if active_units > 0:
        raise AcademicError(
            f"Cannot deactivate course: {active_units} active unit(s) exist.", 409
        )
    if course.status == "inactive":
        return course
    course.status = "inactive"
    _audit(db, user_id, "Course", course.id, "DEACTIVATE",
           old_value="active", new_value="inactive", reason=reason)
    db.commit(); db.refresh(course)
    return course


def reactivate_course(db: Session, course_id: str,
                      user_id: str | None = None) -> Course:
    course = get_course(db, course_id)
    if course.status != "inactive":
        raise AcademicError(f"Cannot reactivate course in status '{course.status}'.", 409)
    course.status = "active"
    _audit(db, user_id, "Course", course.id, "REACTIVATE",
           old_value="inactive", new_value="active")
    db.commit(); db.refresh(course)
    return course


# ============================================================================
# UNIT
# ============================================================================

def create_unit(db: Session, data, user_id: str | None = None) -> Unit:
    if not db.query(Course).filter(Course.id == data.course_id).first():
        raise AcademicError("Course not found.", 404)
    exists = db.query(Unit).filter(
        Unit.course_id == data.course_id,
        Unit.code == data.code,
    ).first()
    if exists:
        raise AcademicError(f"Unit code '{data.code}' already exists in this course.", 409)
    unit = Unit(
        course_id=data.course_id,
        name=data.name.strip(),
        code=data.code.strip().upper(),
        description=data.description,
        year_level=data.year_level,
        semester_number=data.semester_number,
        status="active",
    )
    db.add(unit); db.flush()
    _audit(db, user_id, "Unit", unit.id, "CREATE", new_value=unit.name)
    db.commit(); db.refresh(unit)
    return unit


def list_units(db: Session, course_id: str | None = None,
               year_level: int | None = None,
               semester_number: int | None = None) -> list[Unit]:
    q = db.query(Unit)
    if course_id:
        q = q.filter(Unit.course_id == course_id)
    if year_level:
        q = q.filter(Unit.year_level == year_level)
    if semester_number:
        q = q.filter(Unit.semester_number == semester_number)
    return q.order_by(Unit.year_level, Unit.semester_number, Unit.name).all()


def get_unit(db: Session, unit_id: str) -> Unit:
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise AcademicError("Unit not found.", 404)
    return unit


def update_unit(db: Session, unit_id: str, data, user_id: str | None = None) -> Unit:
    unit = get_unit(db, unit_id)
    changes = data.model_dump(exclude_unset=True)
    new_code = changes.get("code")
    if new_code and new_code.strip().upper() != unit.code:
        exists = db.query(Unit).filter(
            Unit.course_id == unit.course_id,
            Unit.code == new_code.strip().upper(),
        ).first()
        if exists:
            raise AcademicError(
                f"Unit code '{new_code}' already exists in this course.", 409
            )
    _apply_update(db, unit, data, protected_fields={"course_id"})
    _audit(db, user_id, "Unit", unit.id, "UPDATE", new_value=str(changes))
    db.commit(); db.refresh(unit)
    return unit


def deactivate_unit(db: Session, unit_id: str, reason: str | None = None,
                    user_id: str | None = None) -> Unit:
    unit = get_unit(db, unit_id)
    if unit.status == "inactive":
        return unit
    unit.status = "inactive"
    _audit(db, user_id, "Unit", unit.id, "DEACTIVATE",
           old_value="active", new_value="inactive", reason=reason)
    db.commit(); db.refresh(unit)
    return unit


def reactivate_unit(db: Session, unit_id: str,
                    user_id: str | None = None) -> Unit:
    unit = get_unit(db, unit_id)
    if unit.status != "inactive":
        raise AcademicError(f"Cannot reactivate unit in status '{unit.status}'.", 409)
    unit.status = "active"
    _audit(db, user_id, "Unit", unit.id, "REACTIVATE",
           old_value="inactive", new_value="active")
    db.commit(); db.refresh(unit)
    return unit


# ============================================================================
# ACADEMIC YEAR
# ============================================================================

def create_academic_year(db: Session, data, user_id: str | None = None) -> AcademicYear:
    if not db.query(Institution).filter(Institution.id == data.institution_id).first():
        raise AcademicError("Institution not found.", 404)
    if data.start_date >= data.end_date:
        raise AcademicError("start_date must be before end_date.")
    exists = db.query(AcademicYear).filter(
        AcademicYear.institution_id == data.institution_id,
        AcademicYear.name == data.name,
    ).first()
    if exists:
        raise AcademicError(f"Academic year '{data.name}' already exists.", 409)
    ay = AcademicYear(
        institution_id=data.institution_id,
        name=data.name, start_date=data.start_date, end_date=data.end_date,
        status="upcoming",
    )
    db.add(ay); db.flush()
    _audit(db, user_id, "AcademicYear", ay.id, "CREATE", new_value=ay.name)
    db.commit(); db.refresh(ay)
    return ay


def list_academic_years(db: Session, institution_id: str | None = None) -> list[AcademicYear]:
    q = db.query(AcademicYear)
    if institution_id:
        q = q.filter(AcademicYear.institution_id == institution_id)
    return q.order_by(AcademicYear.start_date.desc()).all()


def get_academic_year(db: Session, ay_id: str) -> AcademicYear:
    ay = db.query(AcademicYear).filter(AcademicYear.id == ay_id).first()
    if not ay:
        raise AcademicError("Academic year not found.", 404)
    return ay


def update_academic_year(db: Session, ay_id: str, data,
                         user_id: str | None = None) -> AcademicYear:
    ay = get_academic_year(db, ay_id)
    changes = data.model_dump(exclude_unset=True)

    start = changes.get("start_date", ay.start_date)
    end = changes.get("end_date", ay.end_date)
    if start >= end:
        raise AcademicError("start_date must be before end_date.")

    new_name = changes.get("name")
    if new_name and new_name != ay.name:
        exists = db.query(AcademicYear).filter(
            AcademicYear.institution_id == ay.institution_id,
            AcademicYear.name == new_name,
        ).first()
        if exists:
            raise AcademicError(f"Academic year '{new_name}' already exists.", 409)

    _apply_update(db, ay, data, protected_fields={"institution_id"})
    _audit(db, user_id, "AcademicYear", ay.id, "UPDATE", new_value=str(changes))
    db.commit(); db.refresh(ay)
    return ay


def deactivate_academic_year(db: Session, ay_id: str, reason: str | None = None,
                             user_id: str | None = None) -> AcademicYear:
    ay = get_academic_year(db, ay_id)
    active_semesters = db.query(Semester).filter(
        Semester.academic_year_id == ay.id, Semester.status == "active"
    ).count()
    if active_semesters > 0:
        raise AcademicError(
            f"Cannot deactivate academic year: {active_semesters} active semester(s).", 409
        )
    if ay.status == "archived":
        return ay
    old = ay.status
    ay.status = "archived"
    _audit(db, user_id, "AcademicYear", ay.id, "DEACTIVATE",
           old_value=old, new_value="archived", reason=reason)
    db.commit(); db.refresh(ay)
    return ay


def complete_academic_year(db: Session, ay_id: str,
                           user_id: str | None = None) -> AcademicYear:
    ay = get_academic_year(db, ay_id)
    if ay.status != "active":
        raise AcademicError(f"Cannot complete academic year in status '{ay.status}'.", 409)
    ay.status = "completed"
    _audit(db, user_id, "AcademicYear", ay.id, "COMPLETE",
           old_value="active", new_value="completed")
    db.commit(); db.refresh(ay)
    return ay


def activate_academic_year(db: Session, ay_id: str,
                           user_id: str | None = None) -> AcademicYear:
    ay = get_academic_year(db, ay_id)
    if ay.status != "upcoming":
        raise AcademicError(f"Cannot activate academic year in status '{ay.status}'.", 409)
    ay.status = "active"
    _audit(db, user_id, "AcademicYear", ay.id, "ACTIVATE",
           old_value="upcoming", new_value="active")
    db.commit(); db.refresh(ay)
    return ay


# ============================================================================
# SEMESTER
# ============================================================================

def create_semester(db: Session, data, user_id: str | None = None) -> Semester:
    ay = db.query(AcademicYear).filter(AcademicYear.id == data.academic_year_id).first()
    if not ay:
        raise AcademicError("Academic year not found.", 404)
    if data.start_date >= data.end_date:
        raise AcademicError("start_date must be before end_date.")
    if data.start_date < ay.start_date or data.end_date > ay.end_date:
        raise AcademicError("Semester dates must fall within the academic year.")
    exists = db.query(Semester).filter(
        Semester.academic_year_id == data.academic_year_id,
        Semester.number == data.number,
    ).first()
    if exists:
        raise AcademicError(f"Semester {data.number} already exists for this year.", 409)
    sem = Semester(
        academic_year_id=data.academic_year_id, number=data.number, name=data.name,
        start_date=data.start_date, end_date=data.end_date, status="upcoming",
    )
    db.add(sem); db.flush()
    _audit(db, user_id, "Semester", sem.id, "CREATE", new_value=sem.name)
    db.commit(); db.refresh(sem)
    return sem


def list_semesters(db: Session, academic_year_id: str | None = None) -> list[Semester]:
    q = db.query(Semester)
    if academic_year_id:
        q = q.filter(Semester.academic_year_id == academic_year_id)
    return q.order_by(Semester.number).all()


def get_semester(db: Session, semester_id: str) -> Semester:
    sem = db.query(Semester).filter(Semester.id == semester_id).first()
    if not sem:
        raise AcademicError("Semester not found.", 404)
    return sem


def update_semester(db: Session, semester_id: str, data,
                    user_id: str | None = None) -> Semester:
    sem = get_semester(db, semester_id)
    changes = data.model_dump(exclude_unset=True)

    ay = get_academic_year(db, sem.academic_year_id)
    start = changes.get("start_date", sem.start_date)
    end = changes.get("end_date", sem.end_date)
    if start >= end:
        raise AcademicError("start_date must be before end_date.")
    if start < ay.start_date or end > ay.end_date:
        raise AcademicError("Semester dates must fall within the academic year.")

    new_number = changes.get("number")
    if new_number and new_number != sem.number:
        exists = db.query(Semester).filter(
            Semester.academic_year_id == sem.academic_year_id,
            Semester.number == new_number,
        ).first()
        if exists:
            raise AcademicError(
                f"Semester {new_number} already exists for this year.", 409
            )

    _apply_update(db, sem, data, protected_fields={"academic_year_id"})
    _audit(db, user_id, "Semester", sem.id, "UPDATE", new_value=str(changes))
    db.commit(); db.refresh(sem)
    return sem


def activate_semester(db: Session, semester_id: str,
                      user_id: str | None = None) -> Semester:
    sem = get_semester(db, semester_id)
    if sem.status != "upcoming":
        raise AcademicError(f"Cannot activate semester in status '{sem.status}'.", 409)
    sem.status = "active"
    _audit(db, user_id, "Semester", sem.id, "ACTIVATE",
           old_value="upcoming", new_value="active")
    db.commit(); db.refresh(sem)
    return sem


def complete_semester(db: Session, semester_id: str,
                      user_id: str | None = None) -> Semester:
    sem = get_semester(db, semester_id)
    if sem.status != "active":
        raise AcademicError(f"Cannot complete semester in status '{sem.status}'.", 409)
    sem.status = "completed"
    _audit(db, user_id, "Semester", sem.id, "COMPLETE",
           old_value="active", new_value="completed")
    db.commit(); db.refresh(sem)
    return sem


def deactivate_semester(db: Session, semester_id: str, reason: str | None = None,
                        user_id: str | None = None) -> Semester:
    sem = get_semester(db, semester_id)
    if sem.status == "archived":
        return sem
    old = sem.status
    sem.status = "archived"
    _audit(db, user_id, "Semester", sem.id, "DEACTIVATE",
           old_value=old, new_value="archived", reason=reason)
    db.commit(); db.refresh(sem)
    return sem


# ============================================================================
# STUDENT ENROLLMENT
# ============================================================================

def create_student_enrollment(db: Session, data, user_id: str | None = None) -> StudentEnrollment:
    for label, model, ident in [
        ("User", None, data.user_id),
        ("Institution", Institution, data.institution_id),
        ("Course", Course, data.course_id),
        ("AcademicYear", AcademicYear, data.academic_year_id),
        ("Semester", Semester, data.semester_id),
    ]:
        if model is None:
            from app.models.user import User
            if not db.query(User).filter(User.id == ident).first():
                raise AcademicError(f"{label} not found.", 404)
        else:
            if not db.query(model).filter(model.id == ident).first():
                raise AcademicError(f"{label} not found.", 404)

    course = db.query(Course).filter(Course.id == data.course_id).first()
    school = db.query(School).filter(School.id == course.school_id).first()
    if school.institution_id != data.institution_id:
        raise AcademicError(
            "Course does not belong to the specified institution.", 409
        )

    semester = db.query(Semester).filter(Semester.id == data.semester_id).first()
    if semester.academic_year_id != data.academic_year_id:
        raise AcademicError(
            "Semester does not belong to the specified academic year.", 409
        )

    exists = db.query(StudentEnrollment).filter(
        StudentEnrollment.user_id == data.user_id,
        StudentEnrollment.academic_year_id == data.academic_year_id,
        StudentEnrollment.semester_id == data.semester_id,
    ).first()
    if exists:
        raise AcademicError("User is already enrolled for this academic period.", 409)

    enroll = StudentEnrollment(
        user_id=data.user_id,
        institution_id=data.institution_id,
        course_id=data.course_id,
        academic_year_id=data.academic_year_id,
        semester_id=data.semester_id,
        status="active",
        start_date=data.start_date,
        end_date=data.end_date,
        notes=data.notes,
    )
    db.add(enroll); db.flush()
    _audit(db, user_id, "StudentEnrollment", enroll.id, "CREATE",
           new_value=f"user={data.user_id} course={data.course_id}")
    db.commit(); db.refresh(enroll)
    return enroll


def list_student_enrollments(db: Session, user_id: str | None = None,
                             semester_id: str | None = None) -> list[StudentEnrollment]:
    q = db.query(StudentEnrollment)
    if user_id:
        q = q.filter(StudentEnrollment.user_id == user_id)
    if semester_id:
        q = q.filter(StudentEnrollment.semester_id == semester_id)
    return q.order_by(StudentEnrollment.created_at.desc()).all()


def get_student_enrollment(db: Session, enrollment_id: str) -> StudentEnrollment:
    e = db.query(StudentEnrollment).filter(StudentEnrollment.id == enrollment_id).first()
    if not e:
        raise AcademicError("Student enrollment not found.", 404)
    return e


def update_student_enrollment(db: Session, enrollment_id: str, data,
                              user_id: str | None = None) -> StudentEnrollment:
    enroll = get_student_enrollment(db, enrollment_id)
    changes = data.model_dump(exclude_unset=True)
    _apply_update(db, enroll, data,
                  protected_fields={"user_id", "institution_id", "course_id",
                                    "academic_year_id", "semester_id"})
    _audit(db, user_id, "StudentEnrollment", enroll.id, "UPDATE",
           new_value=str(changes))
    db.commit(); db.refresh(enroll)
    return enroll


def complete_student_enrollment(db: Session, enrollment_id: str,
                                user_id: str | None = None) -> StudentEnrollment:
    enroll = get_student_enrollment(db, enrollment_id)
    if enroll.status != "active":
        raise AcademicError(f"Cannot complete enrollment in status '{enroll.status}'.", 409)
    enroll.status = "completed"
    _audit(db, user_id, "StudentEnrollment", enroll.id, "COMPLETE",
           old_value="active", new_value="completed")
    db.commit(); db.refresh(enroll)
    return enroll


def withdraw_student_enrollment(db: Session, enrollment_id: str, reason: str | None = None,
                                user_id: str | None = None) -> StudentEnrollment:
    enroll = get_student_enrollment(db, enrollment_id)
    if enroll.status == "withdrawn":
        return enroll
    old = enroll.status
    enroll.status = "withdrawn"
    _audit(db, user_id, "StudentEnrollment", enroll.id, "WITHDRAW",
           old_value=old, new_value="withdrawn", reason=reason)
    db.commit(); db.refresh(enroll)
    return enroll


# ============================================================================
# UNIT MEMBERSHIP
# ============================================================================

def create_unit_membership(db: Session, data, user_id: str | None = None) -> UnitMembership:
    from app.models.user import User
    if not db.query(User).filter(User.id == data.user_id).first():
        raise AcademicError("User not found.", 404)
    if not db.query(Unit).filter(Unit.id == data.unit_id).first():
        raise AcademicError("Unit not found.", 404)
    if not db.query(Semester).filter(Semester.id == data.semester_id).first():
        raise AcademicError("Semester not found.", 404)

    exists = db.query(UnitMembership).filter(
        UnitMembership.user_id == data.user_id,
        UnitMembership.unit_id == data.unit_id,
        UnitMembership.semester_id == data.semester_id,
    ).first()
    if exists:
        raise AcademicError("User is already a member of this unit for this semester.", 409)

    m = UnitMembership(
        user_id=data.user_id, unit_id=data.unit_id,
        semester_id=data.semester_id, status="active",
    )
    db.add(m); db.flush()
    _audit(db, user_id, "UnitMembership", m.id, "CREATE",
           new_value=f"user={data.user_id} unit={data.unit_id}")
    db.commit(); db.refresh(m)
    return m


def list_unit_memberships(db: Session, user_id: str | None = None,
                          unit_id: str | None = None,
                          semester_id: str | None = None) -> list[UnitMembership]:
    q = db.query(UnitMembership)
    if user_id:
        q = q.filter(UnitMembership.user_id == user_id)
    if unit_id:
        q = q.filter(UnitMembership.unit_id == unit_id)
    if semester_id:
        q = q.filter(UnitMembership.semester_id == semester_id)
    return q.order_by(UnitMembership.created_at.desc()).all()


def get_unit_membership(db: Session, membership_id: str) -> UnitMembership:
    m = db.query(UnitMembership).filter(UnitMembership.id == membership_id).first()
    if not m:
        raise AcademicError("Unit membership not found.", 404)
    return m


def update_unit_membership(db: Session, membership_id: str, data,
                           user_id: str | None = None) -> UnitMembership:
    m = get_unit_membership(db, membership_id)
    changes = data.model_dump(exclude_unset=True)
    _apply_update(db, m, data, protected_fields={"user_id", "unit_id", "semester_id"})
    _audit(db, user_id, "UnitMembership", m.id, "UPDATE", new_value=str(changes))
    db.commit(); db.refresh(m)
    return m


def complete_unit_membership(db: Session, membership_id: str,
                             user_id: str | None = None) -> UnitMembership:
    m = get_unit_membership(db, membership_id)
    if m.status != "active":
        raise AcademicError(f"Cannot complete membership in status '{m.status}'.", 409)
    m.status = "completed"
    _audit(db, user_id, "UnitMembership", m.id, "COMPLETE",
           old_value="active", new_value="completed")
    db.commit(); db.refresh(m)
    return m


def withdraw_unit_membership(db: Session, membership_id: str,
                             user_id: str | None = None) -> UnitMembership:
    m = get_unit_membership(db, membership_id)
    if m.status == "withdrawn":
        return m
    old = m.status
    m.status = "withdrawn"
    _audit(db, user_id, "UnitMembership", m.id, "WITHDRAW",
           old_value=old, new_value="withdrawn")
    db.commit(); db.refresh(m)
    return m