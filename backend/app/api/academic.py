"""
Academic structure endpoints — Module 002.

Module 002 additions:
  - campus_role validation on institution create
  - GET  /academic/institutions/main-campuses   (dropdown helper)
  - POST /academic/institutions/{id}/transition (Regional Admin / Super Admin)
  - GET  /academic/institutions/{id}/transitions (history)
  - POST /academic/institutions/{id}/transition-requests  (Institution Admin)
  - GET  /academic/institution-transition-requests?institution_id=...
  - POST /academic/institution-transition-requests/{id}/approve
  - POST /academic/institution-transition-requests/{id}/reject
  - POST /academic/institution-transition-requests/{id}/withdraw
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user, require_permission, require_super_admin,
)
from app.db.session import get_db
from app.models.user import User
from app.models.academic import AcademicYear, Semester, School, Course, Unit
from app.schemas.academic import (
    RegionCreate, RegionResponse,
    CountyCreate, CountyResponse,
    InstitutionCreate, InstitutionUpdate, InstitutionResponse,
    MainCampusOption,
    InstitutionTransitionCreate, InstitutionTransitionResponse,
    InstitutionTransitionRequestCreate, InstitutionTransitionRequestResponse,
    TransitionReviewRequest,
    SchoolCreate, SchoolUpdate, SchoolResponse,
    CourseCreate, CourseUpdate, CourseResponse,
    UnitCreate, UnitUpdate, UnitResponse,
    AcademicYearCreate, AcademicYearUpdate, AcademicYearResponse,
    SemesterCreate, SemesterUpdate, SemesterResponse,
    StudentEnrollmentCreate, StudentEnrollmentUpdate, StudentEnrollmentResponse,
    UnitMembershipCreate, UnitMembershipUpdate, UnitMembershipResponse,
)
from app.services.academic_service import (
    AcademicError,
    # Region / County
    create_region, list_regions,
    create_county, list_counties,
    # Institution
    create_institution, list_institutions, get_institution, update_institution,
    approve_institution, reject_institution,
    suspend_institution, reactivate_institution, deactivate_institution,
    list_main_campuses,
    # Institution transitions
    transition_institution, list_institution_transitions,
    request_transition, list_pending_transition_requests,
    get_transition_request,
    approve_transition_request, reject_transition_request,
    withdraw_transition_request,
    # School
    create_school, list_schools, update_school,
    deactivate_school, reactivate_school,
    # Course
    create_course, list_courses, update_course,
    deactivate_course, reactivate_course,
    # Unit
    create_unit, list_units, update_unit,
    deactivate_unit, reactivate_unit,
    # Academic Year
    create_academic_year, list_academic_years, update_academic_year,
    deactivate_academic_year, activate_academic_year, complete_academic_year,
    # Semester
    create_semester, list_semesters, update_semester,
    deactivate_semester, activate_semester, complete_semester,
    # Enrollment / Membership
    create_student_enrollment, list_student_enrollments,
    create_unit_membership, list_unit_memberships,
)
from app.services.jurisdiction_service import user_has_jurisdiction
from app.services.admin_audit_service import log_admin_action

router = APIRouter(prefix="/academic", tags=["Academic Structure"])


def _err(e: AcademicError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _guard_jurisdiction(db: Session, user: User, resource_type: str, resource_id: str):
    """Raise 403 if the user does not have jurisdiction over the given resource."""
    if not user_has_jurisdiction(db, user.id, resource_type, resource_id):
        raise HTTPException(
            status_code=403,
            detail=f"You do not have jurisdiction over this {resource_type}.",
        )


# ============================================================================
# REGION  (Super Admin only)
# ============================================================================

@router.post("/regions", response_model=RegionResponse, status_code=201)
def post_region(
    payload: RegionCreate,
    current_user: User = Depends(require_permission("region.create")),
    db: Session = Depends(get_db),
):
    try:
        result = create_region(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="region.create",
        target_type="region", target_id=result.id,
        new_value=getattr(result, "name", None),
    )
    return result


@router.get("/regions", response_model=list[RegionResponse])
def get_regions(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list_regions(db)


# ============================================================================
# COUNTY  (Super Admin only)
# ============================================================================

@router.post("/counties", response_model=CountyResponse, status_code=201)
def post_county(
    payload: CountyCreate,
    current_user: User = Depends(require_permission("county.create")),
    db: Session = Depends(get_db),
):
    try:
        result = create_county(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="county.create",
        target_type="county", target_id=result.id,
        new_value=getattr(result, "name", None),
    )
    return result


@router.get("/counties", response_model=list[CountyResponse])
def get_counties(
    region_id: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_counties(db, region_id=region_id)


# ============================================================================
# INSTITUTION
# ============================================================================

@router.post("/institutions", response_model=InstitutionResponse, status_code=201)
def post_institution(
    payload: InstitutionCreate,
    current_user: User = Depends(require_permission("institution.create")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "county", payload.county_id)
    try:
        result = create_institution(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.create",
        target_type="institution", target_id=result.id,
        new_value=f"{getattr(result, 'name', None)} ({result.campus_role})",
    )
    return result


@router.get("/institutions", response_model=list[InstitutionResponse])
def get_institutions(
    county_id: str | None = Query(None),
    type_filter: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
    campus_role: str | None = Query(None),
    parent_institution_id: str | None = Query(None),
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    return list_institutions(
        db,
        county_id=county_id,
        type_filter=type_filter,
        status_filter=status_filter,
        campus_role=campus_role,
        parent_institution_id=parent_institution_id,
    )


@router.get("/institutions/main-campuses", response_model=list[MainCampusOption])
def get_main_campuses(
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    """
    Returns all main campuses for the branch-creation dropdown.
    Kept deliberately small — id, code, name, type, county_id only.
    """
    return list_main_campuses(db)


@router.get("/institutions/{institution_id}", response_model=InstitutionResponse)
def get_one_institution(
    institution_id: str,
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    try:
        return get_institution(db, institution_id)
    except AcademicError as e:
        _err(e)


@router.patch("/institutions/{institution_id}", response_model=InstitutionResponse)
def patch_institution(
    institution_id: str,
    payload: InstitutionUpdate,
    current_user: User = Depends(require_permission("institution.edit")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "institution", institution_id)
    try:
        result = update_institution(db, institution_id, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.update",
        target_type="institution", target_id=institution_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


# ─── Institution lifecycle (Super Admin only) ────────────────────────────────

@router.post("/institutions/{institution_id}/approve", response_model=InstitutionResponse)
def post_institution_approve(
    institution_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = approve_institution(db, institution_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.approve",
        target_type="institution", target_id=institution_id,
    )
    return result


@router.post("/institutions/{institution_id}/reject", response_model=InstitutionResponse)
def post_institution_reject(
    institution_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = reject_institution(db, institution_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.reject",
        target_type="institution", target_id=institution_id, reason=reason,
    )
    return result


@router.post("/institutions/{institution_id}/suspend", response_model=InstitutionResponse)
def post_institution_suspend(
    institution_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = suspend_institution(db, institution_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.suspend",
        target_type="institution", target_id=institution_id, reason=reason,
    )
    return result


@router.post("/institutions/{institution_id}/reactivate", response_model=InstitutionResponse)
def post_institution_reactivate(
    institution_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = reactivate_institution(db, institution_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.reactivate",
        target_type="institution", target_id=institution_id,
    )
    return result


@router.post("/institutions/{institution_id}/deactivate", response_model=InstitutionResponse)
def post_institution_deactivate(
    institution_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        result = deactivate_institution(db, institution_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.deactivate",
        target_type="institution", target_id=institution_id, reason=reason,
    )
    return result


# ─── Institution transitions (Regional Admin / Super Admin) ──────────────────
#
# Regional Admin or Super Admin applies a transition directly.
# Institution Admin uses the request workflow below.

@router.post(
    "/institutions/{institution_id}/transition",
    response_model=InstitutionTransitionResponse,
)
def post_institution_transition(
    institution_id: str,
    payload: InstitutionTransitionCreate,
    current_user: User = Depends(require_permission("institution.edit")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "institution", institution_id)
    try:
        _inst, transition = transition_institution(
            db,
            institution_id=institution_id,
            actor_id=current_user.id,
            new_campus_role=payload.new_campus_role,
            new_type=payload.new_type,
            new_parent_institution_id=payload.new_parent_institution_id,
            reason=payload.reason,
            reference=payload.reference,
        )
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.transition",
        target_type="institution", target_id=institution_id,
        new_value=transition.transition_type, reason=payload.reason,
    )
    return transition


@router.get(
    "/institutions/{institution_id}/transitions",
    response_model=list[InstitutionTransitionResponse],
)
def get_institution_transitions(
    institution_id: str,
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    return list_institution_transitions(db, institution_id)


# ─── Institution transition requests (Institution Admin → Regional Admin) ────

@router.post(
    "/institutions/{institution_id}/transition-requests",
    response_model=InstitutionTransitionRequestResponse,
    status_code=201,
)
def post_transition_request(
    institution_id: str,
    payload: InstitutionTransitionRequestCreate,
    current_user: User = Depends(require_permission("institution.edit")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "institution", institution_id)
    try:
        req = request_transition(
            db, institution_id, requester_id=current_user.id,
            desired_campus_role=payload.desired_campus_role,
            desired_type=payload.desired_type,
            desired_parent_institution_id=payload.desired_parent_institution_id,
            reason=payload.reason,
            reference=payload.reference,
        )
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.transition_request",
        target_type="institution_transition_request", target_id=req.id,
        new_value=f"institution={institution_id}", reason=payload.reason,
    )
    return req


@router.get(
    "/institution-transition-requests",
    response_model=list[InstitutionTransitionRequestResponse],
)
def get_transition_requests(
    institution_id: str | None = Query(None),
    current_user: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    return list_pending_transition_requests(db, institution_id=institution_id)


@router.post(
    "/institution-transition-requests/{request_id}/approve",
    response_model=InstitutionTransitionRequestResponse,
)
def approve_request(
    request_id: str,
    payload: TransitionReviewRequest,
    current_user: User = Depends(require_permission("institution.edit")),
    db: Session = Depends(get_db),
):
    """
    Approve a pending transition request.
    Regional Admin / Super Admin. Applies the transition immediately.
    """
    try:
        _inst, transition, req = approve_transition_request(
            db, request_id, reviewer_id=current_user.id, notes=payload.notes,
        )
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.transition_request.approve",
        target_type="institution_transition_request", target_id=request_id,
        new_value=transition.transition_type, reason=payload.notes,
    )
    return req


@router.post(
    "/institution-transition-requests/{request_id}/reject",
    response_model=InstitutionTransitionRequestResponse,
)
def reject_request(
    request_id: str,
    payload: TransitionReviewRequest,
    current_user: User = Depends(require_permission("institution.edit")),
    db: Session = Depends(get_db),
):
    try:
        req = reject_transition_request(
            db, request_id, reviewer_id=current_user.id, notes=payload.notes,
        )
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.transition_request.reject",
        target_type="institution_transition_request", target_id=request_id,
        reason=payload.notes,
    )
    return req


@router.post(
    "/institution-transition-requests/{request_id}/withdraw",
    response_model=InstitutionTransitionRequestResponse,
)
def withdraw_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        req = withdraw_transition_request(db, request_id, requester_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="institution.transition_request.withdraw",
        target_type="institution_transition_request", target_id=request_id,
    )
    return req


# ============================================================================
# SCHOOL
# ============================================================================

@router.post("/schools", response_model=SchoolResponse, status_code=201)
def post_school(
    payload: SchoolCreate,
    current_user: User = Depends(require_permission("school.create")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "institution", payload.institution_id)
    try:
        result = create_school(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="school.create",
        target_type="school", target_id=result.id,
        new_value=getattr(result, "name", None),
    )
    return result


@router.get("/schools", response_model=list[SchoolResponse])
def get_schools(
    institution_id: str | None = Query(None),
    _: User = Depends(require_permission("school.view")),
    db: Session = Depends(get_db),
):
    return list_schools(db, institution_id=institution_id)


@router.patch("/schools/{school_id}", response_model=SchoolResponse)
def patch_school(
    school_id: str,
    payload: SchoolUpdate,
    current_user: User = Depends(require_permission("school.edit")),
    db: Session = Depends(get_db),
):
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(404, "School not found.")
    _guard_jurisdiction(db, current_user, "institution", school.institution_id)
    try:
        result = update_school(db, school_id, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="school.update",
        target_type="school", target_id=school_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/schools/{school_id}/deactivate", response_model=SchoolResponse)
def post_school_deactivate(
    school_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_permission("school.edit")),
    db: Session = Depends(get_db),
):
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(404, "School not found.")
    _guard_jurisdiction(db, current_user, "institution", school.institution_id)
    try:
        result = deactivate_school(db, school_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="school.deactivate",
        target_type="school", target_id=school_id, reason=reason,
    )
    return result


@router.post("/schools/{school_id}/reactivate", response_model=SchoolResponse)
def post_school_reactivate(
    school_id: str,
    current_user: User = Depends(require_permission("school.edit")),
    db: Session = Depends(get_db),
):
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(404, "School not found.")
    _guard_jurisdiction(db, current_user, "institution", school.institution_id)
    try:
        result = reactivate_school(db, school_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="school.reactivate",
        target_type="school", target_id=school_id,
    )
    return result


# ============================================================================
# COURSE
# ============================================================================

@router.post("/courses", response_model=CourseResponse, status_code=201)
def post_course(
    payload: CourseCreate,
    current_user: User = Depends(require_permission("course.create")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "school", payload.school_id)
    try:
        result = create_course(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="course.create",
        target_type="course", target_id=result.id,
        new_value=getattr(result, "name", None),
    )
    return result


@router.get("/courses", response_model=list[CourseResponse])
def get_courses(
    school_id: str | None = Query(None),
    _: User = Depends(require_permission("course.view")),
    db: Session = Depends(get_db),
):
    return list_courses(db, school_id=school_id)


@router.patch("/courses/{course_id}", response_model=CourseResponse)
def patch_course(
    course_id: str,
    payload: CourseUpdate,
    current_user: User = Depends(require_permission("course.edit")),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found.")
    _guard_jurisdiction(db, current_user, "school", course.school_id)
    try:
        result = update_course(db, course_id, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="course.update",
        target_type="course", target_id=course_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/courses/{course_id}/deactivate", response_model=CourseResponse)
def post_course_deactivate(
    course_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_permission("course.edit")),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found.")
    _guard_jurisdiction(db, current_user, "school", course.school_id)
    try:
        result = deactivate_course(db, course_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="course.deactivate",
        target_type="course", target_id=course_id, reason=reason,
    )
    return result


@router.post("/courses/{course_id}/reactivate", response_model=CourseResponse)
def post_course_reactivate(
    course_id: str,
    current_user: User = Depends(require_permission("course.edit")),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found.")
    _guard_jurisdiction(db, current_user, "school", course.school_id)
    try:
        result = reactivate_course(db, course_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="course.reactivate",
        target_type="course", target_id=course_id,
    )
    return result


# ============================================================================
# UNIT
# ============================================================================

@router.post("/units", response_model=UnitResponse, status_code=201)
def post_unit(
    payload: UnitCreate,
    current_user: User = Depends(require_permission("unit.create")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "course", payload.course_id)
    try:
        result = create_unit(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit.create",
        target_type="unit", target_id=result.id,
        new_value=getattr(result, "name", None),
    )
    return result


@router.get("/units", response_model=list[UnitResponse])
def get_units(
    course_id: str | None = Query(None),
    year_level: int | None = Query(None),
    semester_number: int | None = Query(None),
    _: User = Depends(require_permission("unit.view")),
    db: Session = Depends(get_db),
):
    return list_units(db, course_id=course_id,
                      year_level=year_level,
                      semester_number=semester_number)


@router.patch("/units/{unit_id}", response_model=UnitResponse)
def patch_unit(
    unit_id: str,
    payload: UnitUpdate,
    current_user: User = Depends(require_permission("unit.edit")),
    db: Session = Depends(get_db),
):
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(404, "Unit not found.")
    _guard_jurisdiction(db, current_user, "course", unit.course_id)
    try:
        result = update_unit(db, unit_id, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit.update",
        target_type="unit", target_id=unit_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/units/{unit_id}/deactivate", response_model=UnitResponse)
def post_unit_deactivate(
    unit_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_permission("unit.edit")),
    db: Session = Depends(get_db),
):
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(404, "Unit not found.")
    _guard_jurisdiction(db, current_user, "course", unit.course_id)
    try:
        result = deactivate_unit(db, unit_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit.deactivate",
        target_type="unit", target_id=unit_id, reason=reason,
    )
    return result


@router.post("/units/{unit_id}/reactivate", response_model=UnitResponse)
def post_unit_reactivate(
    unit_id: str,
    current_user: User = Depends(require_permission("unit.edit")),
    db: Session = Depends(get_db),
):
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(404, "Unit not found.")
    _guard_jurisdiction(db, current_user, "course", unit.course_id)
    try:
        result = reactivate_unit(db, unit_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit.reactivate",
        target_type="unit", target_id=unit_id,
    )
    return result


# ============================================================================
# ACADEMIC YEAR
# ============================================================================

@router.post("/academic-years", response_model=AcademicYearResponse, status_code=201)
def post_academic_year(
    payload: AcademicYearCreate,
    current_user: User = Depends(require_permission("academic_year.create")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "institution", payload.institution_id)
    try:
        result = create_academic_year(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="academic_year.create",
        target_type="academic_year", target_id=result.id,
        new_value=getattr(result, "name", None),
    )
    return result


@router.get("/academic-years", response_model=list[AcademicYearResponse])
def get_academic_years(
    institution_id: str | None = Query(None),
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    return list_academic_years(db, institution_id=institution_id)


@router.patch("/academic-years/{ay_id}", response_model=AcademicYearResponse)
def patch_academic_year(
    ay_id: str,
    payload: AcademicYearUpdate,
    current_user: User = Depends(require_permission("academic_year.edit")),
    db: Session = Depends(get_db),
):
    ay = db.query(AcademicYear).filter(AcademicYear.id == ay_id).first()
    if not ay:
        raise HTTPException(404, "Academic year not found.")
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = update_academic_year(db, ay_id, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="academic_year.update",
        target_type="academic_year", target_id=ay_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/academic-years/{ay_id}/activate", response_model=AcademicYearResponse)
def post_academic_year_activate(
    ay_id: str,
    current_user: User = Depends(require_permission("academic_year.edit")),
    db: Session = Depends(get_db),
):
    ay = db.query(AcademicYear).filter(AcademicYear.id == ay_id).first()
    if not ay:
        raise HTTPException(404, "Academic year not found.")
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = activate_academic_year(db, ay_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="academic_year.activate",
        target_type="academic_year", target_id=ay_id,
    )
    return result


@router.post("/academic-years/{ay_id}/complete", response_model=AcademicYearResponse)
def post_academic_year_complete(
    ay_id: str,
    current_user: User = Depends(require_permission("academic_year.edit")),
    db: Session = Depends(get_db),
):
    ay = db.query(AcademicYear).filter(AcademicYear.id == ay_id).first()
    if not ay:
        raise HTTPException(404, "Academic year not found.")
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = complete_academic_year(db, ay_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="academic_year.complete",
        target_type="academic_year", target_id=ay_id,
    )
    return result


@router.post("/academic-years/{ay_id}/deactivate", response_model=AcademicYearResponse)
def post_academic_year_deactivate(
    ay_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_permission("academic_year.edit")),
    db: Session = Depends(get_db),
):
    ay = db.query(AcademicYear).filter(AcademicYear.id == ay_id).first()
    if not ay:
        raise HTTPException(404, "Academic year not found.")
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = deactivate_academic_year(db, ay_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="academic_year.deactivate",
        target_type="academic_year", target_id=ay_id, reason=reason,
    )
    return result


# ============================================================================
# SEMESTER
# ============================================================================

@router.post("/semesters", response_model=SemesterResponse, status_code=201)
def post_semester(
    payload: SemesterCreate,
    current_user: User = Depends(require_permission("semester.create")),
    db: Session = Depends(get_db),
):
    ay = db.query(AcademicYear).filter(AcademicYear.id == payload.academic_year_id).first()
    if not ay:
        raise HTTPException(404, "Academic year not found.")
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = create_semester(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="semester.create",
        target_type="semester", target_id=result.id,
        new_value=getattr(result, "name", None),
    )
    return result


@router.get("/semesters", response_model=list[SemesterResponse])
def get_semesters(
    academic_year_id: str | None = Query(None),
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    return list_semesters(db, academic_year_id=academic_year_id)


@router.patch("/semesters/{semester_id}", response_model=SemesterResponse)
def patch_semester(
    semester_id: str,
    payload: SemesterUpdate,
    current_user: User = Depends(require_permission("semester.edit")),
    db: Session = Depends(get_db),
):
    sem = db.query(Semester).filter(Semester.id == semester_id).first()
    if not sem:
        raise HTTPException(404, "Semester not found.")
    ay = db.query(AcademicYear).filter(AcademicYear.id == sem.academic_year_id).first()
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = update_semester(db, semester_id, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="semester.update",
        target_type="semester", target_id=semester_id,
        new_value=str(payload.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/semesters/{semester_id}/activate", response_model=SemesterResponse)
def post_semester_activate(
    semester_id: str,
    current_user: User = Depends(require_permission("semester.edit")),
    db: Session = Depends(get_db),
):
    sem = db.query(Semester).filter(Semester.id == semester_id).first()
    if not sem:
        raise HTTPException(404, "Semester not found.")
    ay = db.query(AcademicYear).filter(AcademicYear.id == sem.academic_year_id).first()
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = activate_semester(db, semester_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="semester.activate",
        target_type="semester", target_id=semester_id,
    )
    return result


@router.post("/semesters/{semester_id}/complete", response_model=SemesterResponse)
def post_semester_complete(
    semester_id: str,
    current_user: User = Depends(require_permission("semester.edit")),
    db: Session = Depends(get_db),
):
    sem = db.query(Semester).filter(Semester.id == semester_id).first()
    if not sem:
        raise HTTPException(404, "Semester not found.")
    ay = db.query(AcademicYear).filter(AcademicYear.id == sem.academic_year_id).first()
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = complete_semester(db, semester_id, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="semester.complete",
        target_type="semester", target_id=semester_id,
    )
    return result


@router.post("/semesters/{semester_id}/deactivate", response_model=SemesterResponse)
def post_semester_deactivate(
    semester_id: str,
    reason: str | None = Query(None),
    current_user: User = Depends(require_permission("semester.edit")),
    db: Session = Depends(get_db),
):
    sem = db.query(Semester).filter(Semester.id == semester_id).first()
    if not sem:
        raise HTTPException(404, "Semester not found.")
    ay = db.query(AcademicYear).filter(AcademicYear.id == sem.academic_year_id).first()
    _guard_jurisdiction(db, current_user, "institution", ay.institution_id)
    try:
        result = deactivate_semester(db, semester_id, reason=reason, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="semester.deactivate",
        target_type="semester", target_id=semester_id, reason=reason,
    )
    return result


# ============================================================================
# STUDENT ENROLLMENT
# ============================================================================

@router.post("/student-enrollments", response_model=StudentEnrollmentResponse, status_code=201)
def post_student_enrollment(
    payload: StudentEnrollmentCreate,
    current_user: User = Depends(require_permission("enrollment.create")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "institution", payload.institution_id)
    try:
        result = create_student_enrollment(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="enrollment.create",
        target_type="student_enrollment", target_id=result.id,
        new_value=f"user={payload.user_id} semester={payload.semester_id}",
    )
    return result


@router.get("/student-enrollments", response_model=list[StudentEnrollmentResponse])
def get_student_enrollments(
    user_id: str | None = Query(None),
    semester_id: str | None = Query(None),
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    return list_student_enrollments(db, user_id=user_id, semester_id=semester_id)


# ============================================================================
# UNIT MEMBERSHIP
# ============================================================================

@router.post("/unit-memberships", response_model=UnitMembershipResponse, status_code=201)
def post_unit_membership(
    payload: UnitMembershipCreate,
    current_user: User = Depends(require_permission("unit_membership.create")),
    db: Session = Depends(get_db),
):
    _guard_jurisdiction(db, current_user, "unit", payload.unit_id)
    try:
        result = create_unit_membership(db, payload, user_id=current_user.id)
    except AcademicError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_membership.create",
        target_type="unit_membership", target_id=result.id,
        new_value=f"user={payload.user_id} unit={payload.unit_id}",
    )
    return result


@router.get("/unit-memberships", response_model=list[UnitMembershipResponse])
def get_unit_memberships(
    user_id: str | None = Query(None),
    unit_id: str | None = Query(None),
    semester_id: str | None = Query(None),
    _: User = Depends(require_permission("institution.view")),
    db: Session = Depends(get_db),
):
    return list_unit_memberships(db, user_id=user_id, unit_id=unit_id, semester_id=semester_id)