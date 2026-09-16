"""
Seed permission codes introduced by Module 001 completeness work.

Adds:
  - notification.manage
  - external.register
  - external.verify
  - auth.deactivate_self
  - auth.delete_self
  - session.limit.manage

Idempotent. Safe to run repeatedly.

Run:
    python -m app.scripts.seed_permissions_module_001
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


# (code, name, category, description)
PERMISSIONS = [
    ("notification.manage",   "Manage Notifications",         "notification",
     "Manage own notification preferences"),
    ("external.register",     "Register External",            "external",
     "Register as an external user"),
    ("external.verify",       "Verify External Users",        "external",
     "Approve or reject external registrations"),
    ("auth.deactivate_self",  "Deactivate Own Account",       "auth",
     "Deactivate own account"),
    ("auth.delete_self",      "Delete Own Account",           "auth",
     "Permanently delete own account"),
    ("session.limit.manage",  "Manage Session Limits",        "auth",
     "Configure per-user session limits"),
]


# Default role → permission grants
ROLE_GRANTS = {
    "student":           ["notification.manage", "auth.deactivate_self"],
    "lecturer":          ["notification.manage", "auth.deactivate_self"],
    "investor":          ["notification.manage", "auth.deactivate_self"],
    "organization":      ["notification.manage", "auth.deactivate_self"],
    "alumni":            ["notification.manage", "auth.deactivate_self"],
    "mentor":            ["notification.manage", "auth.deactivate_self"],
    "specialist":        ["notification.manage", "auth.deactivate_self"],
    "institution_admin": ["notification.manage", "external.verify"],
    "county_admin":      ["notification.manage", "external.verify"],
    "super_admin":       ["notification.manage", "external.verify",
                          "session.limit.manage"],
}


def _get_or_create_permission(
    db: Session, code: str, name: str, category: str, description: str,
) -> Permission:
    p = db.query(Permission).filter(Permission.code == code).first()
    if p:
        updated = False
        if not p.name:
            p.name = name
            updated = True
        if not p.category:
            p.category = category
            updated = True
        if not p.description:
            p.description = description
            updated = True
        if updated:
            db.flush()
        return p

    p = Permission(
        id=str(uuid.uuid4()),
        code=code,
        name=name,
        category=category,
        description=description,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(p)
    db.flush()
    logger.info("+ permission %s", code)
    return p


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


def main() -> None:
    db = SessionLocal()
    try:
        logger.info("=== Seeding Module 001 permissions ===")
        perms: dict[str, Permission] = {}
        for code, name, category, desc in PERMISSIONS:
            perms[code] = _get_or_create_permission(db, code, name, category, desc)

        logger.info("=== Linking to roles ===")
        for role_code, perm_codes in ROLE_GRANTS.items():
            role = db.query(Role).filter(Role.code == role_code).first()
            if not role:
                logger.warning("Role %s not found; skipping", role_code)
                continue
            for pc in perm_codes:
                perm = perms.get(pc)
                if perm:
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