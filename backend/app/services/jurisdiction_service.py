"""
Jurisdiction resolution for authorization.

Walks the resource hierarchy and checks user_roles.

Two role categories are distinguished:
  - APPOINTED_ADMIN_ROLES        — N.O.U.-appointed staff (super, regional)
  - ELECTED_REPRESENTATIVE_ROLES — elected student representatives
                                   (group, school, institution, county)
  - PRIVILEGED_ROLE_CODES        — union of the two
                                   (used for elevated session policy:
                                    12h sessions, mandatory MFA, strict lockout)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.role import UserRole, Role
from app.models.academic import (
    Institution, School, Course, Unit, County,
    AcademicYear, Semester, StudentEnrollment, UnitMembership,
)
from app.models.group import Group


# ============================================================================
# Role classification
# ============================================================================

APPOINTED_ADMIN_ROLES: set[str] = {
    "super_admin",
    "regional_admin",
}

ELECTED_REPRESENTATIVE_ROLES: set[str] = {
    "county_representative",
    "assistant_county_rep",
    "institution_representative",
    "assistant_institution_rep",
    "school_representative",
    "assistant_school_rep",
    "group_leader",
    "group_secretary",
    "group_treasurer",
    "unit_representative",
}

PRIVILEGED_ROLE_CODES: set[str] = (
    APPOINTED_ADMIN_ROLES | ELECTED_REPRESENTATIVE_ROLES
)

# Backward-compatible alias. Existing code that imports ADMIN_ROLE_CODES
# continues to work; new code should prefer the split constants above.
ADMIN_ROLE_CODES: set[str] = PRIVILEGED_ROLE_CODES


# ============================================================================
# Active role resolution
# ============================================================================

def get_active_roles(db: Session, user_id: str) -> list[UserRole]:
    """Return UserRole rows that are active and not yet expired."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.status == "active")
        .all()
    )
    return [r for r in rows if r.end_date is None or r.end_date > now]


def is_privileged_user(db: Session, user_id: str) -> bool:
    """
    True if the user has any privileged role (appointed admin OR
    elected representative). Used for security policy tier selection.
    """
    roles = get_active_roles(db, user_id)
    return any(
        r.role and r.role.code in PRIVILEGED_ROLE_CODES for r in roles
    )


def is_appointed_admin(db: Session, user_id: str) -> bool:
    """True if the user has an N.O.U.-appointed admin role."""
    roles = get_active_roles(db, user_id)
    return any(
        r.role and r.role.code in APPOINTED_ADMIN_ROLES for r in roles
    )


def is_elected_representative(db: Session, user_id: str) -> bool:
    """True if the user has any elected representative role."""
    roles = get_active_roles(db, user_id)
    return any(
        r.role and r.role.code in ELECTED_REPRESENTATIVE_ROLES for r in roles
    )


def is_admin_user(db: Session, user_id: str) -> bool:
    """
    Deprecated alias — use is_privileged_user() or the more specific
    helpers above. Retained so existing imports continue to work.
    """
    return is_privileged_user(db, user_id)


# ============================================================================
# Ancestor chain
# ============================================================================

def _ancestors(
    db: Session, resource_type: str, resource_id: str,
) -> list[tuple[str, str]]:
    """
    Return [(type, id), ...] representing the resource and all of its
    ancestors. The first element is the resource itself. The last element
    is always ("platform", "*").
    """
    chain: list[tuple[str, str]] = [(resource_type, resource_id)]

    try:
        if resource_type == "institution":
            inst = (
                db.query(Institution)
                .filter(Institution.id == resource_id)
                .first()
            )
            if inst:
                if inst.county_id:
                    chain.append(("county", inst.county_id))
                    c = db.query(County).filter(County.id == inst.county_id).first()
                    if c and c.region_id:
                        chain.append(("region", c.region_id))
                if inst.parent_institution_id:
                    chain.extend(
                        _ancestors(db, "institution", inst.parent_institution_id)
                    )

        elif resource_type == "school":
            s = db.query(School).filter(School.id == resource_id).first()
            if s:
                chain.extend(_ancestors(db, "institution", s.institution_id))

        elif resource_type == "course":
            c = db.query(Course).filter(Course.id == resource_id).first()
            if c:
                chain.extend(_ancestors(db, "school", c.school_id))

        elif resource_type == "unit":
            u = db.query(Unit).filter(Unit.id == resource_id).first()
            if u:
                chain.extend(_ancestors(db, "course", u.course_id))

        elif resource_type == "group":
            g = db.query(Group).filter(Group.id == resource_id).first()
            if g:
                chain.extend(_ancestors(db, "institution", g.institution_id))

        elif resource_type == "academic_year":
            ay = (
                db.query(AcademicYear)
                .filter(AcademicYear.id == resource_id)
                .first()
            )
            if ay:
                chain.extend(_ancestors(db, "institution", ay.institution_id))

        elif resource_type == "semester":
            sem = (
                db.query(Semester)
                .filter(Semester.id == resource_id)
                .first()
            )
            if sem:
                chain.extend(
                    _ancestors(db, "academic_year", sem.academic_year_id)
                )

        elif resource_type == "student_enrollment":
            enr = (
                db.query(StudentEnrollment)
                .filter(StudentEnrollment.id == resource_id)
                .first()
            )
            if enr:
                chain.extend(
                    _ancestors(db, "institution", enr.institution_id)
                )

        elif resource_type == "unit_membership":
            um = (
                db.query(UnitMembership)
                .filter(UnitMembership.id == resource_id)
                .first()
            )
            if um:
                chain.extend(_ancestors(db, "unit", um.unit_id))

        elif resource_type == "county":
            c = db.query(County).filter(County.id == resource_id).first()
            if c and c.region_id:
                chain.append(("region", c.region_id))

        elif resource_type == "region":
            # Region is a top-level resource; only platform overrides it.
            pass

    except Exception:
        # Ancestor resolution must not raise; the chain will simply be
        # shorter than expected and the authorization check will fail
        # closed (deny) if no match is found.
        pass

    chain.append(("platform", "*"))
    return chain


# ============================================================================
# Authorization
# ============================================================================

def user_has_jurisdiction(
    db: Session, user_id: str, resource_type: str, resource_id: str,
) -> bool:
    """
    True if the user has an active role whose (jurisdiction_type,
    jurisdiction_id) covers the given resource.

    A platform-level role always passes.
    """
    roles = get_active_roles(db, user_id)
    if not roles:
        return False

    # Platform jurisdiction short-circuits.
    for r in roles:
        if r.jurisdiction_type == "platform":
            return True

    chain_set = set(_ancestors(db, resource_type, resource_id))

    for r in roles:
        if r.jurisdiction_type and r.jurisdiction_id:
            if (r.jurisdiction_type, r.jurisdiction_id) in chain_set:
                return True

    return False