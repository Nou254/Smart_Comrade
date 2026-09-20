"""
Seed the database with system roles, base permissions, and role→permission mappings.

Usage:
    python -m app.scripts.seed
        # Seeds roles + permissions only.

    python -m app.scripts.seed --super-admin --email boss@example.com --password "StrongPass123!"
        # Also creates (or updates) a Super Admin user.
        # Password must be at least 12 characters. No default password is provided.

Idempotent — safe to run multiple times. Existing roles/permissions are updated in place.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.role import Role, Permission, RolePermission, UserRole
from app.models.user import User
from app.core.security import hash_password


# =============================================================================
# PERMISSION CATALOG
# (code, name, category, description)
# =============================================================================

PERMISSIONS: list[tuple[str, str, str, str]] = [
    # ── User management ──────────────────────────────────────
    ("user.view",                 "View users",                    "user",             "View user profiles and directories"),
    ("user.edit",                 "Edit users",                    "user",             "Modify user profile information"),
    ("user.delete",               "Delete users",                  "user",             "Permanently remove users"),
    ("user.suspend",              "Suspend users",                 "user",             "Temporarily suspend accounts"),
    ("user.reactivate",           "Reactivate users",              "user",             "Restore suspended accounts"),

    # ── Role management ──────────────────────────────────────
    ("role.view",                 "View roles",                    "role",             "View roles and permissions catalog"),
    ("role.assign",               "Assign roles",                  "role",             "Grant roles to users"),
    ("role.revoke",               "Revoke roles",                  "role",             "Remove roles from users"),

    # ── Region ───────────────────────────────────────────────
    ("region.create",             "Create region",                 "region",           "Create geographic regions"),
    ("region.edit",               "Edit region",                   "region",           "Modify region details"),
    ("region.delete",             "Delete region",                 "region",           "Remove regions"),
    ("region.view",               "View regions",                  "region",           "Read region data"),

    # ── County ───────────────────────────────────────────────
    ("county.create",             "Create county",                 "county",           "Create counties"),
    ("county.edit",               "Edit county",                   "county",           "Modify county details"),
    ("county.delete",             "Delete county",                 "county",           "Remove counties"),
    ("county.view",               "View counties",                 "county",           "Read county data"),

    # ── Institution ──────────────────────────────────────────
    ("institution.create",        "Create institution",            "institution",      "Create educational institutions"),
    ("institution.edit",          "Edit institution",              "institution",      "Modify institution details"),
    ("institution.view",          "View institutions",             "institution",      "Read institution data"),
    ("institution.approve",       "Approve institution",           "institution",      "Approve pending institutions"),
    ("institution.reject",        "Reject institution",            "institution",      "Reject pending institutions"),
    ("institution.suspend",       "Suspend institution",           "institution",      "Temporarily suspend institutions"),
    ("institution.reactivate",    "Reactivate institution",        "institution",      "Restore suspended institutions"),
    ("institution.deactivate",    "Deactivate institution",        "institution",      "Deactivate institutions"),
    ("institution.transition.request", "Request Institution Transition", "institution", "Submit a campus role or type change request for review"),
    ("institution.transition.review",  "Review Institution Transition",  "institution", "Approve or reject institution transition requests"),

    # ── School ───────────────────────────────────────────────
    ("school.create",             "Create school",                 "school",           "Create schools / faculties"),
    ("school.edit",               "Edit school",                   "school",           "Modify school details"),
    ("school.view",               "View schools",                  "school",           "Read school data"),
    ("school.deactivate",         "Deactivate school",             "school",           "Deactivate schools"),
    ("school.reactivate",         "Reactivate school",             "school",           "Restore deactivated schools"),

    # ── Course ───────────────────────────────────────────────
    ("course.create",             "Create course",                 "course",           "Create academic programmes"),
    ("course.edit",               "Edit course",                   "course",           "Modify course details"),
    ("course.view",               "View courses",                  "course",           "Read course data"),
    ("course.deactivate",         "Deactivate course",             "course",           "Deactivate courses"),
    ("course.reactivate",         "Reactivate course",             "course",           "Restore deactivated courses"),

    # ── Unit ─────────────────────────────────────────────────
    ("unit.create",               "Create unit",                   "unit",             "Create academic units"),
    ("unit.edit",                 "Edit unit",                     "unit",             "Modify unit details"),
    ("unit.view",                 "View units",                    "unit",             "Read unit data"),
    ("unit.deactivate",           "Deactivate unit",               "unit",             "Deactivate units"),
    ("unit.reactivate",           "Reactivate unit",               "unit",             "Restore deactivated units"),
    ("unit.propose",              "Propose units",                 "unit",             "Propose units via upload"),
    ("unit.approve",              "Approve units",                 "unit",             "Approve unit proposals"),

    # ── Academic Year ────────────────────────────────────────
    ("academic_year.create",      "Create academic year",          "academic_year",    "Create academic years"),
    ("academic_year.edit",        "Edit academic year",            "academic_year",    "Modify academic year details"),
    ("academic_year.view",        "View academic years",           "academic_year",    "Read academic year data"),
    ("academic_year.activate",    "Activate academic year",        "academic_year",    "Activate upcoming academic years"),
    ("academic_year.complete",    "Complete academic year",        "academic_year",    "Mark academic years completed"),
    ("academic_year.deactivate",  "Deactivate academic year",      "academic_year",    "Archive academic years"),

    # ── Semester ─────────────────────────────────────────────
    ("semester.create",           "Create semester",               "semester",         "Create semesters"),
    ("semester.edit",             "Edit semester",                 "semester",         "Modify semester details"),
    ("semester.view",             "View semesters",                "semester",         "Read semester data"),
    ("semester.activate",         "Activate semester",             "semester",         "Activate upcoming semesters"),
    ("semester.complete",         "Complete semester",             "semester",         "Mark semesters completed"),
    ("semester.deactivate",       "Deactivate semester",           "semester",         "Archive semesters"),

    # ── Enrollment & Membership ──────────────────────────────
    ("enrollment.create",         "Create student enrollment",     "enrollment",       "Create student enrollment records"),
    ("enrollment.edit",           "Edit student enrollment",       "enrollment",       "Modify enrollment records"),
    ("enrollment.view",           "View student enrollments",      "enrollment",       "Read enrollment records"),
    ("unit_membership.create",    "Create unit membership",        "unit_membership",  "Create unit membership records"),
    ("unit_membership.edit",      "Edit unit membership",          "unit_membership",  "Modify unit membership records"),
    ("unit_membership.view",      "View unit memberships",         "unit_membership",  "Read unit membership records"),

    # ── Group ────────────────────────────────────────────────
    ("group.create",              "Create group",                  "group",            "Create student groups"),
    ("group.manage",              "Manage group",                  "group",            "Manage group membership & activities"),
    ("group.delete",              "Delete group",                  "group",            "Remove student groups"),
    ("group.view",                "View groups",                   "group",            "Read group data"),

    # ── Assessment ───────────────────────────────────────────
    ("assessment.create",         "Create assessment",             "assessment",       "Create assessments"),
    ("assessment.publish",        "Publish assessment",            "assessment",       "Publish assessments to students"),
    ("assessment.grade",          "Grade assessment",              "assessment",       "Evaluate and grade submissions"),
    ("assessment.review",         "Review assessment",             "assessment",       "Review flags and appeals"),

    # ── Project ──────────────────────────────────────────────
    ("project.create",            "Create project",                "project",          "Create student projects"),
    ("project.review",            "Review project",                "project",          "Review project submissions"),
    ("project.grade",             "Grade project",                 "project",          "Grade project work"),

    # ── Election ─────────────────────────────────────────────
    ("election.create",           "Create election",               "election",         "Create elections"),
    ("election.manage",           "Manage election",               "election",         "Manage election lifecycle"),
    ("election.approve",          "Approve election results",      "election",         "Approve final election results"),
    ("election.vote",             "Vote",                          "election",         "Cast a vote"),

    # ── Event ────────────────────────────────────────────────
    ("event.create",              "Create event",                  "event",            "Create events and activities"),
    ("event.approve",             "Approve event",                 "event",            "Approve or reject events"),
    ("event.manage",              "Manage event",                  "event",            "Manage event lifecycle"),

    # ── Announcement ─────────────────────────────────────────
    ("announcement.create",       "Create announcement",           "announcement",     "Publish official announcements"),
    ("announcement.moderate",     "Moderate announcements",        "announcement",     "Moderate communication"),

    # ── External / PWA ───────────────────────────────────────
    ("external.register",         "Register External",             "external",         "Register as an external user"),
    ("external.view_self",        "View Own External Profile",     "external",         "View own external profile"),
    ("external.edit_self",        "Edit Own External Profile",     "external",         "Edit own external profile"),
    ("external.verify",           "Verify External Users",         "external",         "Verify external user applications"),

    # ── Transfer & Combination ───────────────────────────────
    ("transfer.initiate",         "Initiate Transfers",            "transfer",         "Initiate inter-group transfers"),
    ("combination.manage",        "Manage Combinations",           "academic",         "Manage programme combinations"),

    # ── Mentor ───────────────────────────────────────────────
    ("mentor.assess",             "Take Mentor Assessment",        "mentorship",       "Take the mentor assessment"),

    # ── Notification ─────────────────────────────────────────
    ("notification.manage",       "Manage Notifications",          "notification",     "Manage own notification preferences"),

    # ── Upload pipeline ──────────────────────────────────────
    ("upload.create",             "Create upload",                 "upload",           "Create timetable upload sessions"),
    ("upload.scan",               "Trigger scan",                  "upload",           "Trigger OCR on selected pages"),

    # ── Audit ────────────────────────────────────────────────
    ("audit.view",                "View audit logs",               "audit",            "View audit and security logs"),
    ("analytics.view",            "View analytics",                "audit",            "View platform analytics"),

    # ── System ───────────────────────────────────────────────
    ("system.configure",          "Configure system",              "system",           "Configure platform settings"),
    ("feature_flag.manage",       "Manage feature flags",          "system",           "Toggle feature flags"),

    # ── Self-service auth ────────────────────────────────────
    ("auth.deactivate_self",      "Deactivate Own Account",        "auth",             "Deactivate own account"),
    ("auth.delete_self",          "Delete Own Account",            "auth",             "Permanently delete own account"),
    ("session.limit.manage",      "Manage Session Limits",         "auth",             "Configure per-user session limits"),
]


# =============================================================================
# ROLE CATALOG
# (code, name, level, role_class, is_leadership, description)
#
# role_class values:
#   platform             — N.O.U. platform-appointed staff
#   student_leadership   — elected/appointed student representatives
#   student_base         — ordinary student
#   staff                — academic staff (lecturers, etc.)
#   external_base        — non-academic external participants
#   external_addon       — specialised external roles (mentors)
#
# is_leadership=True triggers exclusivity: at most one active
# leadership role per user (enforced by role_service).
# =============================================================================

ROLES: list[tuple[str, str, int, str, bool, str]] = [
    # ── Platform-appointed admins (N.O.U. staff) ────────────
    ("super_admin",                 "Super Administrator",                    100, "platform",           False,
     "Highest platform authority — N.O.U. appointed"),
    ("regional_admin",              "Regional Administrator",                  90, "platform",           False,
     "N.O.U. appointed — coordinates a region"),

    # ── Elected representatives (student leadership) ────────
    ("county_representative",       "County Representative",                   80, "student_leadership", True,
     "Elected representative for a county"),
    ("assistant_county_rep",        "Assistant County Representative",         78, "student_leadership", False,
     "Elected with County Rep — supports and acts on vacancy"),
    ("institution_representative",  "Institution Representative",              70, "student_leadership", True,
     "Elected representative for an institution"),
    ("assistant_institution_rep",   "Assistant Institution Representative",    68, "student_leadership", False,
     "Elected with Institution Rep — supports and acts on vacancy"),
    ("school_representative",       "School Representative",                   60, "student_leadership", True,
     "Elected representative for a school"),
    ("assistant_school_rep",        "Assistant School Representative",         58, "student_leadership", False,
     "Elected with School Rep — supports and acts on vacancy"),

    # ── Academic staff ───────────────────────────────────────
    ("lecturer",                    "Lecturer",                                50, "staff",              False,
     "Academic staff"),

    # ── Group-level officials (elected within a group) ───────
    ("group_leader",                "Group Leader",                            40, "student_leadership", True,
     "Elected leader of a student group"),
    ("group_secretary",             "Group Secretary",                         38, "student_leadership", False,
     "Elected — group records & admin"),
    ("group_treasurer",             "Group Treasurer",                         38, "student_leadership", False,
     "Elected — group financial records"),

    # ── Unit-level coordination (appointed by Group Leader) ─
    ("unit_representative",         "Unit Representative",                     35, "student_leadership", False,
     "Appointed by Group Leader to coordinate a specific unit"),

    # ── External participants ────────────────────────────────
    ("mentor",                      "Mentor",                                  30, "external_addon",     False,
     "External guidance providers"),
    ("student",                     "Student",                                 20, "student_base",       False,
     "Ordinary student"),
    ("external_user",               "External User",                           10, "external_base",      False,
     "Generic non-academic external participant"),

    # ── External subtypes (from seed_external_roles) ─────────
    ("investor",                    "Investor",                                30, "external_base",      False,
     "Investor — external funding participants"),
    ("organization",                "Organization",                            30, "external_base",      False,
     "Organization / Employer — external providers"),
    ("alumni",                      "Alumni",                                  25, "external_base",      False,
     "Alumni — former students"),
    ("specialist",                  "Specialist",                              30, "external_base",      False,
     "Specialist / Researcher — external experts"),
]


# =============================================================================
# ROLE → PERMISSION MAPPING
# =============================================================================

def role_permissions_map() -> dict[str, list[str]]:
    all_codes = [p[0] for p in PERMISSIONS]

    return {
        # ── Platform admins ──────────────────────────────────
        "super_admin": all_codes,

        "regional_admin": [
            "institution.view", "institution.approve", "institution.reject",
            "institution.suspend", "institution.reactivate", "institution.deactivate",
            "institution.transition.request", "institution.transition.review",
            "school.view", "course.view", "unit.view",
            "academic_year.view", "semester.view",
            "enrollment.view", "unit_membership.view",
            "group.view",
            "event.approve",
            "external.verify",
            "transfer.initiate", "combination.manage",
            "audit.view", "analytics.view",
            "notification.manage",
        ],

        # ── Elected county-level reps ────────────────────────
        "county_representative": [
            "institution.view",
            "school.view", "course.view", "unit.view",
            "academic_year.view", "semester.view",
            "enrollment.view", "unit_membership.view",
            "group.view",
            "event.create", "event.manage",
            "announcement.create",
            "election.create", "election.manage",
            "analytics.view",
            "notification.manage",
        ],

        "assistant_county_rep": [
            "institution.view", "school.view", "course.view", "unit.view",
            "group.view",
            "notification.manage",
        ],

        # ── Elected institution-level reps ───────────────────
        "institution_representative": [
            "school.create", "school.edit", "school.view",
            "school.deactivate", "school.reactivate",
            "course.create", "course.edit", "course.view",
            "course.deactivate", "course.reactivate",
            "unit.create", "unit.edit", "unit.view",
            "unit.deactivate", "unit.reactivate",
            "unit.propose", "unit.approve",
            "institution.transition.request",
            "academic_year.create", "academic_year.edit", "academic_year.view",
            "semester.create", "semester.edit", "semester.view",
            "enrollment.create", "enrollment.edit", "enrollment.view",
            "unit_membership.create", "unit_membership.edit", "unit_membership.view",
            "group.view",
            "event.create", "event.manage",
            "announcement.create",
            "election.create", "election.manage",
            "external.verify",
            "analytics.view",
            "notification.manage",
        ],

        "assistant_institution_rep": [
            "school.view", "course.view", "unit.view",
            "academic_year.view", "semester.view",
            "enrollment.view", "unit_membership.view",
            "institution.transition.request",
            "group.view",
            "notification.manage",
        ],

        # ── Elected school-level reps ────────────────────────
        "school_representative": [
            "school.view",
            "course.view", "unit.view",
            "academic_year.view", "semester.view",
            "group.view",
            "event.create", "event.manage",
            "announcement.create",
            "election.create", "election.manage",
            "notification.manage",
        ],

        "assistant_school_rep": [
            "school.view", "course.view", "unit.view",
            "group.view",
            "notification.manage",
        ],

        # ── Academic staff ───────────────────────────────────
        "lecturer": [
            "assessment.create", "assessment.publish",
            "assessment.grade", "assessment.review",
            "project.review",
            "event.create",
            "announcement.create",
            "notification.manage",
        ],

        # ── Group-level elected officials ────────────────────
        "group_leader": [
            "group.manage", "group.view",
            "announcement.create",
            "event.create",
            "election.create", "election.manage",
            "unit.propose",
            "upload.create", "upload.scan",
            "notification.manage",
        ],

        "group_secretary": [
            "group.view",
            "announcement.create",
            "upload.create", "upload.scan",
            "notification.manage",
        ],

        "group_treasurer": [
            "group.view",
            "notification.manage",
        ],

        # ── Unit rep (appointed by Group Leader) ─────────────
        "unit_representative": [
            "group.view",
            "announcement.create",
            "unit.propose",
            "upload.create", "upload.scan",
            "notification.manage",
        ],

        # ── External ─────────────────────────────────────────
        "mentor": [
            "external.view_self", "external.edit_self",
            "mentor.assess",
            "notification.manage",
            "auth.deactivate_self",
        ],

        "investor": [
            "external.view_self", "external.edit_self",
            "notification.manage",
        ],

        "organization": [
            "external.view_self", "external.edit_self",
            "notification.manage",
        ],

        "alumni": [
            "external.view_self", "external.edit_self",
            "notification.manage",
        ],

        "specialist": [
            "external.view_self", "external.edit_self",
            "notification.manage",
        ],

        # ── Students ─────────────────────────────────────────
        "student": [
            "election.vote",
            "upload.create", "upload.scan",
            "notification.manage",
            "auth.deactivate_self",
        ],

        # ── Generic external ─────────────────────────────────
        "external_user": [
            "external.view_self", "external.edit_self",
            "notification.manage",
            "auth.deactivate_self",
        ],
    }


# =============================================================================
# SEEDING
# =============================================================================

def seed_roles_and_permissions(db) -> None:
    print("→ Seeding permissions...")
    perm_by_code: dict[str, Permission] = {}
    for code, name, category, desc in PERMISSIONS:
        p = db.query(Permission).filter(Permission.code == code).first()
        if not p:
            p = Permission(
                code=code, name=name, category=category, description=desc,
            )
            db.add(p)
            db.flush()
            print(f"   + {code}")
        else:
            # Keep display fields in sync
            p.name = name
            p.category = category
            p.description = desc
        perm_by_code[code] = p

    print("→ Seeding roles...")
    role_by_code: dict[str, Role] = {}
    for code, name, level, role_class, is_leadership, desc in ROLES:
        r = db.query(Role).filter(Role.code == code).first()
        if not r:
            r = Role(
                code=code, name=name, description=desc,
                is_system=True, level=level,
                role_class=role_class, is_leadership=is_leadership,
            )
            db.add(r)
            db.flush()
            print(f"   + {code}")
        else:
            # Keep display fields in sync
            r.name = name
            r.description = desc
            r.level = level
            r.role_class = role_class
            r.is_leadership = is_leadership
        role_by_code[code] = r

    print("→ Mapping roles to permissions...")
    rp_map = role_permissions_map()
    for role_code, perm_codes in rp_map.items():
        role = role_by_code.get(role_code)
        if not role:
            print(f"   ⚠  role {role_code} missing; skipping")
            continue
        for pc in perm_codes:
            perm = perm_by_code.get(pc)
            if not perm:
                print(f"   ⚠  permission {pc} missing; skipping")
                continue
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
    print(f"✅ Seeded {len(perm_by_code)} permissions, {len(role_by_code)} roles.")


def create_super_admin(db, email: str, password: str) -> None:
    if not email or "@" not in email:
        raise ValueError("A valid email is required.")
    if not password or len(password) < 12:
        raise ValueError("Super Admin password must be at least 12 characters.")

    existing = db.query(User).filter(User.email == email.lower().strip()).first()
    if existing:
        print(f"ℹ  Super Admin already exists: {email}")
        user = existing
    else:
        user = User(
            first_name="Super",
            last_name="Admin",
            email=email.lower().strip(),
            phone=None,
            password_hash=hash_password(password),
            user_type="admin",
            account_status="active",
            email_verified=True,
            two_factor_enabled=False,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed roles and permissions.")
    parser.add_argument(
        "--super-admin", action="store_true",
        help="Also create a Super Admin user (requires --email and --password).",
    )
    parser.add_argument(
        "--email", default=None,
        help="Super Admin email. Required with --super-admin.",
    )
    parser.add_argument(
        "--password", default=None,
        help="Super Admin password (min 12 chars). Required with --super-admin.",
    )
    args = parser.parse_args()

    if args.super_admin and (not args.email or not args.password):
        print("ERROR: --super-admin requires both --email and --password.")
        print("       Example:")
        print('       python -m app.scripts.seed --super-admin \\')
        print('           --email super@smartcomrade.com \\')
        print('           --password "ChangeMe-At-Once-123!"')
        return 1

    if args.super_admin and len(args.password) < 12:
        print("ERROR: Super Admin password must be at least 12 characters.")
        return 1

    db = SessionLocal()
    try:
        seed_roles_and_permissions(db)
        if args.super_admin:
            create_super_admin(db, args.email, args.password)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())