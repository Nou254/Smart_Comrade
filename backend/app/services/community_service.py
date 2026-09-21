"""
Community service — Module 003 Phase 11.

Manages the three auto-membership community types (course_year, school,
institution) and their lifecycle.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.academic import (
    AcademicYear, Course, Institution, School,
)
from app.models.community import Community, CommunityMembership
from app.models.user import User


logger = logging.getLogger(__name__)


INSTITUTION = "institution"
SCHOOL = "school"
COURSE_YEAR = "course_year"


class CommunityError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# GET OR CREATE
# ============================================================================

def get_or_create_institution_community(db: Session, institution_id: str) -> Community:
    existing = db.query(Community).filter(
        Community.community_type == INSTITUTION,
        Community.institution_id == institution_id,
    ).first()
    if existing:
        return existing

    inst = db.query(Institution).filter(Institution.id == institution_id).first()
    if not inst:
        raise CommunityError("Institution not found.", 404)

    c = Community(
        community_type=INSTITUTION,
        institution_id=institution_id,
        name=inst.name,
        description=f"Institution community for {inst.name}",
        is_active=True,
    )
    db.add(c)
    db.flush()
    return c


def get_or_create_school_community(db: Session, school_id: str) -> Community:
    existing = db.query(Community).filter(
        Community.community_type == SCHOOL,
        Community.school_id == school_id,
    ).first()
    if existing:
        return existing

    s = db.query(School).filter(School.id == school_id).first()
    if not s:
        raise CommunityError("School not found.", 404)

    c = Community(
        community_type=SCHOOL,
        institution_id=s.institution_id,
        school_id=s.id,
        name=s.name,
        description=f"School community for {s.name}",
        is_active=True,
    )
    db.add(c)
    db.flush()
    return c


def get_or_create_course_year_community(
    db: Session,
    institution_id: str,
    school_id: str,
    course_id: str,
    year_level: int,
    academic_year_id: str,
    combination_id: str | None = None,
) -> Community:
    existing = db.query(Community).filter(
        Community.community_type == COURSE_YEAR,
        Community.institution_id == institution_id,
        Community.school_id == school_id,
        Community.course_id == course_id,
        Community.year_level == year_level,
        Community.academic_year_id == academic_year_id,
        Community.combination_id == combination_id,
    ).first()
    if existing:
        return existing

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise CommunityError("Course not found.", 404)

    ay = db.query(AcademicYear).filter(AcademicYear.id == academic_year_id).first()
    ay_name = ay.name if ay else ""

    combo_suffix = ""
    if combination_id:
        combo_suffix = " (combination)"

    c = Community(
        community_type=COURSE_YEAR,
        institution_id=institution_id,
        school_id=school_id,
        course_id=course_id,
        year_level=year_level,
        combination_id=combination_id,
        academic_year_id=academic_year_id,
        name=f"{course.name} — Year {year_level}{combo_suffix} — {ay_name}".strip(" —"),
        description=(
            f"Course-year community for {course.name} Year {year_level}"
            f"{' / ' + ay_name if ay_name else ''}"
        ),
        is_active=True,
    )
    db.add(c)
    db.flush()
    return c


# ============================================================================
# AUTO-MEMBERSHIP SYNC
# ============================================================================

def ensure_user_memberships_for_enrollment(
    db: Session,
    user_id: str,
    institution_id: str,
    school_id: str,
    course_id: str,
    year_level: int,
    academic_year_id: str,
    combination_id: str | None = None,
) -> dict:
    """
    Called after a student's enrollment becomes active. Idempotent.

    Joins the user to:
      - course-year community
      - school community
      - institution community

    Deactivates old course-year memberships when the user's academic
    context has changed (year advanced, course changed, etc.).
    """
    institution_comm = get_or_create_institution_community(db, institution_id)
    school_comm = get_or_create_school_community(db, school_id)
    course_year_comm = get_or_create_course_year_community(
        db, institution_id, school_id, course_id, year_level,
        academic_year_id, combination_id,
    )

    # Deactivate old course-year memberships for this user that no longer
    # match their current academic context.
    current_target_ids = {course_year_comm.id}
    old_course_year = (
        db.query(CommunityMembership)
        .join(Community, CommunityMembership.community_id == Community.id)
        .filter(
            CommunityMembership.user_id == user_id,
            CommunityMembership.is_active.is_(True),
            Community.community_type == COURSE_YEAR,
            CommunityMembership.community_id.notin_(current_target_ids),
        )
        .all()
    )
    for m in old_course_year:
        m.is_active = False
        m.left_at = _now()

    # Deactivate old school memberships that don't match current school.
    old_school = (
        db.query(CommunityMembership)
        .join(Community, CommunityMembership.community_id == Community.id)
        .filter(
            CommunityMembership.user_id == user_id,
            CommunityMembership.is_active.is_(True),
            Community.community_type == SCHOOL,
            Community.school_id != school_id,
        )
        .all()
    )
    for m in old_school:
        m.is_active = False
        m.left_at = _now()

    joined = []
    for comm in (institution_comm, school_comm, course_year_comm):
        joined.append(_ensure_membership(db, comm, user_id))

    db.flush()
    for comm in (institution_comm, school_comm, course_year_comm):
        refresh_member_count(db, comm.id)

    return {
        "institution_community": institution_comm.id,
        "school_community": school_comm.id,
        "course_year_community": course_year_comm.id,
        "memberships_created": sum(1 for m in joined if m.id),
    }


def _ensure_membership(db: Session, community: Community, user_id: str) -> CommunityMembership:
    existing = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community.id,
        CommunityMembership.user_id == user_id,
    ).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.left_at = None
            existing.joined_at = _now()
        return existing

    m = CommunityMembership(
        community_id=community.id,
        user_id=user_id,
        role="member",
        is_active=True,
        joined_at=_now(),
    )
    db.add(m)
    db.flush()
    return m


def refresh_member_count(db: Session, community_id: str) -> int:
    comm = db.query(Community).filter(Community.id == community_id).first()
    if not comm:
        raise CommunityError("Community not found.", 404)
    count = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.is_active.is_(True),
    ).count()
    comm.member_count = count
    db.flush()
    return count


# ============================================================================
# READ
# ============================================================================

def get_community(db: Session, community_id: str) -> Community:
    c = db.query(Community).filter(Community.id == community_id).first()
    if not c:
        raise CommunityError("Community not found.", 404)
    return c


def list_communities_for_user(
    db: Session,
    user_id: str,
    community_type: str | None = None,
    active_only: bool = True,
) -> list[Community]:
    q = (
        db.query(Community)
        .join(CommunityMembership, CommunityMembership.community_id == Community.id)
        .filter(CommunityMembership.user_id == user_id)
    )
    if active_only:
        q = q.filter(CommunityMembership.is_active.is_(True))
    if community_type:
        q = q.filter(Community.community_type == community_type)
    return q.order_by(Community.community_type, Community.name).all()


def list_all_communities(
    db: Session,
    community_type: str | None = None,
    institution_id: str | None = None,
    is_active: bool | None = None,
) -> list[Community]:
    q = db.query(Community)
    if community_type:
        q = q.filter(Community.community_type == community_type)
    if institution_id:
        q = q.filter(Community.institution_id == institution_id)
    if is_active is not None:
        q = q.filter(Community.is_active.is_(is_active))
    return q.order_by(Community.name).all()


# ============================================================================
# LEAVE / REJOIN
# ============================================================================

def leave_community(db: Session, community_id: str, user_id: str) -> CommunityMembership:
    comm = get_community(db, community_id)

    if comm.community_type == INSTITUTION:
        raise CommunityError(
            "You cannot leave the institution community.", 403,
        )

    m = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == user_id,
        CommunityMembership.is_active.is_(True),
    ).first()
    if not m:
        raise CommunityError("You are not an active member.", 404)

    m.is_active = False
    m.left_at = _now()
    refresh_member_count(db, community_id)
    db.commit()
    db.refresh(m)
    return m


def rejoin_community(db: Session, community_id: str, user_id: str) -> CommunityMembership:
    comm = get_community(db, community_id)
    m = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == user_id,
    ).first()
    if not m:
        # Fresh join
        m = CommunityMembership(
            community_id=community_id,
            user_id=user_id,
            role="member",
            is_active=True,
            joined_at=_now(),
        )
        db.add(m)
    else:
        if m.banned_at:
            raise CommunityError("You are banned from this community.", 403)
        m.is_active = True
        m.left_at = None
        m.joined_at = _now()

    refresh_member_count(db, community_id)
    db.commit()
    db.refresh(m)
    return m


# ============================================================================
# ARCHIVE
# ============================================================================

def archive_community(db: Session, community_id: str) -> Community:
    comm = get_community(db, community_id)
    if comm.community_type == INSTITUTION:
        raise CommunityError(
            "Institution communities are not archived.", 409,
        )
    comm.is_active = False
    comm.archived_at = _now()
    db.commit()
    db.refresh(comm)
    return comm