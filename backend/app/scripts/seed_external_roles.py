"""
Seed the roles and permissions required by Module 001 external user types.

Idempotent — safe to run multiple times.

Run:
    python -m app.scripts.seed_external_roles
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.role import Role, Permission, RolePermission

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ── Data ───────────────────────────────────────────────────────

# (code, display_name, description, role_class, is_leadership)
EXTERNAL_ROLES = [
    ("investor",     "Investor",       "Investor — external funding participants",       "external_base", False),
    ("organization", "Organization",   "Organization / Employer — external providers",    "external_base", False),
    ("alumni",       "Alumni",         "Alumni — former students",                        "external_base", False),
    ("mentor",       "Mentor",         "Mentor — external guidance providers",            "external_addon", False),
    ("specialist",   "Specialist",     "Specialist / Researcher — external experts",      "external_base", False),
]

# (code, name, category, description)
NEW_PERMISSIONS = [
    ("external.register",       "Register External",          "external",
     "Register as an external user"),
    ("external.view_self",      "View Own External Profile",  "external",
     "View own external profile"),
    ("external.edit_self",      "Edit Own External Profile",  "external",
     "Edit own external profile"),
    ("external.verify",         "Verify External Users",      "external",
     "Verify external user applications"),
    ("transfer.initiate",       "Initiate Transfers",         "transfer",
     "Initiate inter-group transfers"),
    ("combination.manage",      "Manage Combinations",        "academic",
     "Manage programme combinations"),
    ("mentor.assess",           "Take Mentor Assessment",     "mentorship",
     "Take the mentor assessment"),
    ("unit.propose",            "Propose Units",              "academic",
     "Propose units via upload"),
    ("unit.approve",            "Approve Units",              "academic",
     "Approve unit proposals"),
    ("notification.manage",     "Manage Notifications",       "notification",
     "Manage own notification preferences"),
]


# Role → permission grants
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "investor": [
        "external.view_self",
        "external.edit_self",
        "notification.manage",
    ],
    "organization": [
        "external.view_self",
        "external.edit_self",
        "notification.manage",
    ],
    "alumni": [
        "external.view_self",
        "external.edit_self",
        "notification.manage",
    ],
    "mentor": [
        "external.view_self",
        "external.edit_self",
        "notification.manage",
        "mentor.assess",
    ],
    "specialist": [
        "external.view_self",
        "external.edit_self",
        "notification.manage",
    ],
    "institution_admin": [
        "external.verify",
    ],
    "county_admin": [
        "external.verify",
    ],
    "super_admin": [
        "external.verify",
        "transfer.initiate",
        "combination.manage",
        "unit.propose",
        "unit.approve",
        "notification.manage",
    ],
    "regional_admin": [
        "transfer.initiate",
        "combination.manage",
    ],
    "student": [
        "notification.manage",
    ],
    "lecturer": [
        "notification.manage",
    ],
}


# ── Helpers ────────────────────────────────────────────────────

def _get_or_create_permission(
    db: Session, code: str, name: str, category: str, description: str,
) -> Permission:
    perm = db.query(Permission).filter(Permission.code == code).first()
    if perm:
        # Update missing fields on existing rows
        updated = False
        if not perm.name:
            perm.name = name
            updated = True
        if not perm.category:
            perm.category = category
            updated = True
        if not perm.description:
            perm.description = description
            updated = True
        if updated:
            db.flush()
        return perm

    perm = Permission(
        id=str(uuid.uuid4()),
        code=code,
        name=name,
        category=category,
        description=description,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(perm)
    db.flush()
    logger.info("+ permission %s", code)
    return perm


def _get_or_create_role(
    db: Session, code: str, display_name: str, description: str,
    role_class: str, is_leadership: bool,
) -> Role:
    role = db.query(Role).filter(Role.code == code).first()
    if role:
        updated = False
        # Fix mis-set fields
        if role.role_class != role_class:
            role.role_class = role_class
            updated = True
        if role.is_leadership != is_leadership:
            role.is_leadership = is_leadership
            updated = True
        if not role.name:
            role.name = display_name
            updated = True
        if not role.description:
            role.description = description
            updated = True
        if updated:
            db.flush()
            logger.info("~ role %s updated", code)
        return role

    role = Role(
        id=str(uuid.uuid4()),
        code=code,
        name=display_name,
        description=description,
        role_class=role_class,
        is_leadership=is_leadership,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(role)
    db.flush()
    logger.info("+ role %s", code)
    return role


def _link(db: Session, role: Role, perm: Permission) -> None:
    exists = (
        db.query(RolePermission)
        .filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == perm.id,
        )
        .first()
    )
    if exists:
        return
    db.add(RolePermission(
        id=str(uuid.uuid4()),
        role_id=role.id,
        permission_id=perm.id,
        created_at=datetime.now(timezone.utc),
    ))
    logger.info("  → linked %s ⇄ %s", role.code, perm.code)


# ── Main ───────────────────────────────────────────────────────

def main() -> None:
    db = SessionLocal()
    try:
        logger.info("=== Seeding external roles ===")
        for code, display_name, description, role_class, is_leadership in EXTERNAL_ROLES:
            _get_or_create_role(db, code, display_name, description,
                                role_class, is_leadership)

        logger.info("=== Seeding new permissions ===")
        perms: dict[str, Permission] = {}
        for code, name, category, desc in NEW_PERMISSIONS:
            perms[code] = _get_or_create_permission(db, code, name, category, desc)

        logger.info("=== Linking role-permission mappings ===")
        for role_code, perm_codes in ROLE_PERMISSIONS.items():
            role = db.query(Role).filter(Role.code == role_code).first()
            if not role:
                logger.warning("Role %s not found; skipping", role_code)
                continue
            for pc in perm_codes:
                perm = perms.get(pc)
                if not perm:
                    continue
                _link(db, role, perm)

        db.commit()
        logger.info("=== Seed complete ===")
    except Exception:
        db.rollback()
        logger.exception("Seed failed")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()