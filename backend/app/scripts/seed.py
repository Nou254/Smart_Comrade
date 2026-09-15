"""
Seed the database with system roles, base permissions, and role→permission mappings.

Usage:
    python -m scripts.seed                # seed roles + permissions only
    python -m scripts.seed --super-admin  # also create a Super Admin
                                          # (email: super@smartcomrade.local,
                                          #  password: ChangeMe@123)
"""
import sys
import argparse
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.role import Role, Permission, RolePermission, UserRole
from app.models.user import User
from app.core.security import hash_password


# --- Permission catalog ------------------------------------------------------

PERMISSIONS: list[tuple[str, str, str, str]] = [
    # (code, name, category, description)
    ("user.view",              "View users",                 "user",   "View user profiles and directories"),
    ("user.edit",              "Edit users",                 "user",   "Modify user profile information"),
    ("user.delete",            "Delete users",               "user",   "Permanently remove users"),
    ("user.suspend",           "Suspend users",              "user",   "Temporarily suspend accounts"),
    ("user.reactivate",        "Reactivate users",           "user",   "Restore suspended accounts"),

    ("role.view",              "View roles",                 "role",   "View roles and permissions catalog"),
    ("role.assign",            "Assign roles",               "role",   "Grant roles to users"),
    ("role.revoke",            "Revoke roles",               "role",   "Remove roles from users"),

    ("institution.create",     "Create institution",         "institution", "Create educational institutions"),
    ("institution.edit",       "Edit institution",           "institution", "Modify institution details"),
    ("institution.delete",     "Delete institution",         "institution", "Remove institutions"),
    ("institution.view",       "View institutions",          "institution", "Read institution data"),

    ("school.create",          "Create school",              "school", "Create schools / faculties"),
    ("school.edit",            "Edit school",                "school", "Modify school details"),
    ("school.delete",          "Delete school",              "school", "Remove schools"),
    ("school.view",            "View schools",               "school", "Read school data"),

    ("course.create",          "Create course",              "course", "Create academic programmes"),
    ("course.edit",            "Edit course",                "course", "Modify course details"),
    ("course.delete",          "Delete course",              "course", "Remove courses"),
    ("course.view",            "View courses",               "course", "Read course data"),

    ("unit.create",            "Create unit",                "unit",   "Create academic units"),
    ("unit.edit",              "Edit unit",                  "unit",   "Modify unit details"),
    ("unit.delete",            "Delete unit",                "unit",   "Remove units"),
    ("unit.view",              "View units",                 "unit",   "Read unit data"),

    ("group.create",           "Create group",               "group",  "Create student groups"),
    ("group.manage",           "Manage group",               "group",  "Manage group membership & activities"),
    ("group.delete",           "Delete group",               "group",  "Remove student groups"),
    ("group.view",             "View groups",                "group",  "Read group data"),

    ("assessment.create",      "Create assessment",          "assessment", "Create assessments"),
    ("assessment.publish",     "Publish assessment",         "assessment", "Publish assessments to students"),
    ("assessment.grade",       "Grade assessment",           "assessment", "Evaluate and grade submissions"),
    ("assessment.review",      "Review assessment",          "assessment", "Review flags and appeals"),

    ("project.create",         "Create project",             "project", "Create student projects"),
    ("project.review",         "Review project",             "project", "Review project submissions"),
    ("project.grade",          "Grade project",              "project", "Grade project work"),

    ("election.create",        "Create election",            "election", "Create elections"),
    ("election.manage",        "Manage election",            "election", "Manage election lifecycle"),
    ("election.vote",          "Vote",                       "election", "Cast a vote"),

    ("event.create",           "Create event",               "event",  "Create events and activities"),
    ("event.approve",          "Approve event",              "event",  "Approve or reject events"),
    ("event.manage",           "Manage event",               "event",  "Manage event lifecycle"),

    ("announcement.create",    "Create announcement",        "announcement", "Publish official announcements"),
    ("announcement.moderate",  "Moderate announcements",     "announcement", "Moderate communication"),

    ("audit.view",             "View audit logs",            "audit",  "View audit and security logs"),
    ("analytics.view",         "View analytics",             "audit",  "View platform analytics"),

    ("system.configure",       "Configure system",           "system", "Configure platform settings"),
    ("feature_flag.manage",    "Manage feature flags",       "system", "Toggle feature flags"),
]


# --- Role catalog (with level for hierarchy) --------------------------------

ROLES: list[tuple[str, str, int, str]] = [
    # (code, name, level, description)
    ("super_admin",                "Super Administrator",                 100, "Highest platform authority"),
    ("regional_admin",             "Regional Administrator",               90, "Coordinates a region"),
    ("county_admin",               "County Administrator",                 80, "Coordinates a county"),
    ("institution_admin",          "Institution Administrator",            70, "Manages an institution"),
    ("deputy_institution_admin",   "Deputy Institution Administrator",     65, "Supports the institution admin"),
    ("school_representative",      "School Representative",                60, "Represents a school"),
    ("assistant_school_rep",       "Assistant School Representative",      55, "Supports the school representative"),
    ("lecturer",                   "Lecturer",                             50, "Academic staff"),
    ("group_leader",               "Group Leader",                         40, "Leads a student group"),
    ("group_secretary",            "Group Secretary",                      38, "Group records & admin"),
    ("group_treasurer",            "Group Treasurer",                      38, "Group financial records"),
    ("unit_representative",        "Unit Representative",                  35, "Coordinates a unit"),
    ("mentor",                     "Mentor",                               30, "Provides mentorship"),
    ("student",                    "Student",                              20, "Ordinary student"),
    ("external_user",              "External User",                        10, "Non-academic participant"),
]


# --- Role → permission mappings ---------------------------------------------

def role_permissions_map() -> dict[str, list[str]]:
    all_codes = [p[0] for p in PERMISSIONS]

    return {
        "super_admin": all_codes,
        "regional_admin": [
            "institution.create", "institution.edit", "institution.view",
            "school.create", "school.edit", "school.view",
            "course.create", "course.edit", "course.view",
            "unit.create", "unit.edit", "unit.view",
            "event.approve", "audit.view", "analytics.view",
        ],
        "county_admin": [
            "institution.create", "institution.edit", "institution.view",
            "school.create", "school.edit", "school.view",
            "course.create", "course.edit", "course.view",
            "unit.create", "unit.edit", "unit.view",
            "event.approve", "analytics.view",
        ],
        "institution_admin": [
            "school.create", "school.edit", "school.view",
            "course.create", "course.edit", "course.view",
            "unit.create", "unit.edit", "unit.view",
            "group.view", "assessment.review",
            "event.approve", "analytics.view",
        ],
        "deputy_institution_admin": [
            "school.view", "course.view", "unit.view",
            "group.view", "analytics.view",
        ],
        "school_representative": [
            "school.view", "course.view", "unit.view",
            "group.view", "announcement.create",
        ],
        "assistant_school_rep": [
            "school.view", "course.view", "unit.view",
        ],
        "lecturer": [
            "assessment.create", "assessment.publish",
            "assessment.grade", "assessment.review",
            "event.create", "announcement.create",
            "project.review",
        ],
        "group_leader": ["group.manage", "group.view", "announcement.create"],
        "group_secretary": ["group.view", "announcement.create"],
        "group_treasurer": ["group.view"],
        "unit_representative": ["group.view", "announcement.create"],
        "mentor": [],
        "student": ["election.vote"],
        "external_user": [],
    }


# --- Seed routine ------------------------------------------------------------

def seed_roles_and_permissions(db) -> None:
    print("→ Seeding permissions...")
    perm_by_code: dict[str, Permission] = {}
    for code, name, category, desc in PERMISSIONS:
        p = db.query(Permission).filter(Permission.code == code).first()
        if not p:
            p = Permission(code=code, name=name, category=category, description=desc)
            db.add(p)
            db.flush()
            print(f"   + {code}")
        perm_by_code[code] = p

    print("→ Seeding roles...")
    role_by_code: dict[str, Role] = {}
    for code, name, level, desc in ROLES:
        r = db.query(Role).filter(Role.code == code).first()
        if not r:
            r = Role(code=code, name=name, description=desc, is_system=True, level=level)
            db.add(r)
            db.flush()
            print(f"   + {code}")
        role_by_code[code] = r

    print("→ Mapping roles to permissions...")
    rp_map = role_permissions_map()
    for role_code, perm_codes in rp_map.items():
        role = role_by_code[role_code]
        for pc in perm_codes:
            if pc not in perm_by_code:
                continue
            perm = perm_by_code[pc]
            exists = (
                db.query(RolePermission)
                .filter(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                )
                .first()
            )
            if not exists:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    db.commit()
    print("✅ Roles and permissions seeded.")


def create_super_admin(db, email: str, password: str) -> None:
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        print(f"ℹ  Super Admin already exists: {email}")
        user = existing
    else:
        user = User(
            first_name="Super",
            last_name="Admin",
            email=email,
            phone=None,
            password_hash=hash_password(password),
            account_status="active",
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✅ Super Admin created: {email}")

    super_role = db.query(Role).filter(Role.code == "super_admin").first()
    if not super_role:
        print("⚠  super_admin role missing — run seed first.")
        return

    existing_assignment = (
        db.query(UserRole)
        .filter(
            UserRole.user_id == user.id,
            UserRole.role_id == super_role.id,
            UserRole.status == "active",
        )
        .first()
    )
    if not existing_assignment:
        db.add(
            UserRole(
                user_id=user.id,
                role_id=super_role.id,
                jurisdiction_type="platform",
                jurisdiction_id=None,
                status="active",
                start_date=datetime.now(timezone.utc),
                granted_at=datetime.now(timezone.utc),
                notes="Initial Super Admin (seed)",
            )
        )
        db.commit()
        print("✅ Super Admin role granted.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed roles and permissions.")
    parser.add_argument("--super-admin", action="store_true", help="Also create the default Super Admin user")
    parser.add_argument("--email", default="super@smartcomrade.com")
    parser.add_argument("--password", default="ChangeMe@123")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        seed_roles_and_permissions(db)
        if args.super_admin:
            create_super_admin(db, args.email, args.password)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())