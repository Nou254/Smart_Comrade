"""
Jurisdiction resolution for admin authorization.
Walks the resource hierarchy and checks user_roles.
"""
from sqlalchemy.orm import Session

from app.models.role import UserRole, Role
from app.models.academic import Institution, School, Course, Unit, County
from app.models.group import Group


ADMIN_ROLE_CODES = {
    "super_admin", "regional_admin", "county_admin",
    "institution_admin", "deputy_institution_admin",
    "school_representative", "assistant_school_rep",
}


def get_active_roles(db: Session, user_id: str) -> list[UserRole]:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    rows = (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.status == "active")
        .all()
    )
    return [r for r in rows if r.end_date is None or r.end_date > now]


def is_admin_user(db: Session, user_id: str) -> bool:
    roles = get_active_roles(db, user_id)
    return any(r.role and r.role.code in ADMIN_ROLE_CODES for r in roles)


def _ancestors(db: Session, resource_type: str, resource_id: str) -> list[tuple[str, str]]:
    """
    Return a list of (type, id) tuples representing the resource and all its ancestors.
    The first element is the resource itself.
    """
    chain: list[tuple[str, str]] = [(resource_type, resource_id)]

    try:
        if resource_type == "institution":
            inst = db.query(Institution).filter(Institution.id == resource_id).first()
            if inst:
                chain.append(("county", inst.county_id))
                c = db.query(County).filter(County.id == inst.county_id).first()
                if c:
                    chain.append(("region", c.region_id))
                if inst.parent_institution_id:
                    chain.extend(_ancestors(db, "institution", inst.parent_institution_id))
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
    except Exception:
        pass

    chain.append(("platform", "*"))
    return chain


def user_has_jurisdiction(db: Session, user_id: str, resource_type: str, resource_id: str) -> bool:
    """
    True if the user has an active role covering the given resource.
    """
    roles = get_active_roles(db, user_id)
    if not roles:
        return False

    # Super admin (platform) passes everything
    for r in roles:
        if r.jurisdiction_type == "platform":
            return True

    # Build the ancestors chain of the target resource
    chain_set = set(_ancestors(db, resource_type, resource_id))

    # Any role whose (jurisdiction_type, jurisdiction_id) is in the chain qualifies
    for r in roles:
        if r.jurisdiction_type and r.jurisdiction_id:
            if (r.jurisdiction_type, r.jurisdiction_id) in chain_set:
                return True

    return False