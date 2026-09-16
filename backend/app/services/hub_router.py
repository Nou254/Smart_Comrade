"""
Login redirect logic.

Maps a user's roles/type to the hub they should land in after login.
Spec §3.2.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.role import UserRole


@dataclass(frozen=True)
class HubTarget:
    hub: str            # canonical hub name
    redirect_to: str    # frontend path


# Order matters — first match wins. Higher authority first.
_ROLE_TO_HUB: list[tuple[str, HubTarget]] = [
    ("super_admin",               HubTarget("super_admin",     "/hub/super-admin")),
    ("regional_admin",            HubTarget("regional_admin",  "/hub/regional-admin")),
    ("county_admin",              HubTarget("county_admin",    "/hub/county-admin")),
    ("assistant_county_admin",    HubTarget("county_admin",    "/hub/county-admin")),
    ("institution_admin",         HubTarget("institution_admin","/hub/institution-admin")),
    ("assistant_institution_admin", HubTarget("institution_admin", "/hub/institution-admin")),
    ("school_representative",     HubTarget("school_rep",      "/hub/school-rep")),
    ("assistant_school_rep",      HubTarget("school_rep",      "/hub/school-rep")),
    ("group_leader",              HubTarget("student",         "/hub/student")),
    ("student",                   HubTarget("student",         "/hub/student")),
    ("lecturer",                  HubTarget("academic",        "/hub/academic")),
    ("investor",                  HubTarget("investor",        "/hub/investor")),
    ("organization",              HubTarget("organization",    "/hub/organization")),
    ("alumni",                    HubTarget("alumni",          "/hub/alumni")),
    ("mentor",                    HubTarget("mentor",          "/hub/mentor")),
    ("specialist",                HubTarget("specialist",      "/hub/specialist")),
]

# Fallback for user_types not covered above
_USER_TYPE_FALLBACK: dict[str, HubTarget] = {
    "student":      HubTarget("student",      "/hub/student"),
    "lecturer":     HubTarget("academic",     "/hub/academic"),
    "external":     HubTarget("external",     "/hub/external"),
    "admin":        HubTarget("admin",        "/hub/admin"),
}


def resolve_hub(db: Session, user_id: str, user_type: str | None) -> HubTarget:
    """
    Determine the correct hub for a user.

    Priority:
      1. Active role codes (most specific first)
      2. user_type fallback
      3. generic default
    """
    active_role_codes = {
        r.role.code
        for r in db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.status == "active")
        .all()
        if r.role
    }

    for role_code, target in _ROLE_TO_HUB:
        if role_code in active_role_codes:
            return target

    if user_type and user_type in _USER_TYPE_FALLBACK:
        return _USER_TYPE_FALLBACK[user_type]

    return HubTarget("default", "/hub")