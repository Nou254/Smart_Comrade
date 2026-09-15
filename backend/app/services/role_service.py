"""
Role management business logic + permission resolution.
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.role import Role, Permission, RolePermission, UserRole


class RoleError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def list_roles(db: Session) -> list[Role]:
    return db.query(Role).order_by(Role.level.desc(), Role.code).all()


def get_role_by_code(db: Session, code: str) -> Role | None:
    return db.query(Role).filter(Role.code == code).first()


def list_permissions(db: Session, category: str | None = None) -> list[Permission]:
    q = db.query(Permission)
    if category:
        q = q.filter(Permission.category == category)
    return q.order_by(Permission.category, Permission.code).all()


def get_user_roles(db: Session, user_id: str) -> list[UserRole]:
    return (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id)
        .order_by(UserRole.created_at.desc())
        .all()
    )


def assign_role(
    db: Session,
    user_id: str,
    role_code: str,
    jurisdiction_type: str,
    jurisdiction_id: str | None,
    granted_by: str,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    notes: str | None = None,
) -> UserRole:
    role = get_role_by_code(db, role_code)
    if not role:
        raise RoleError(f"Role '{role_code}' does not exist.", 404)

    # Prevent duplicate active assignment for the same (user, role, jurisdiction)
    existing = (
        db.query(UserRole)
        .filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
            UserRole.jurisdiction_type == jurisdiction_type,
            UserRole.jurisdiction_id == jurisdiction_id,
            UserRole.status == "active",
        )
        .first()
    )
    if existing:
        raise RoleError(
            f"User already has active role '{role_code}' in this jurisdiction.", 409
        )

    assignment = UserRole(
        user_id=user_id,
        role_id=role.id,
        jurisdiction_type=jurisdiction_type,
        jurisdiction_id=jurisdiction_id,
        status="active",
        start_date=start_date or datetime.now(timezone.utc),
        end_date=end_date,
        granted_by=granted_by,
        granted_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def revoke_role(
    db: Session,
    user_role_id: str,
    revoked_by: str,
    reason: str | None = None,
) -> UserRole:
    assignment = db.query(UserRole).filter(UserRole.id == user_role_id).first()
    if not assignment:
        raise RoleError("Role assignment not found.", 404)
    if assignment.status == "revoked":
        raise RoleError("Role is already revoked.", 409)

    assignment.status = "revoked"
    assignment.revoked_by = revoked_by
    assignment.revoked_at = datetime.now(timezone.utc)
    if reason:
        assignment.notes = (assignment.notes or "") + f"\n[REVOKED] {reason}"
    db.commit()
    db.refresh(assignment)
    return assignment


def resolve_user_permissions(db: Session, user_id: str) -> tuple[list[str], list[str]]:
    """
    Return (role_codes, permission_codes) for a user's ACTIVE roles.
    A role is active if: status == 'active'
                         AND (end_date is None OR end_date > now)
    """
    now = datetime.now(timezone.utc)
    rows = (
        db.query(UserRole)
        .filter(UserRole.user_id == user_id, UserRole.status == "active")
        .all()
    )

    active_roles = [
        r for r in rows if r.end_date is None or r.end_date > now
    ]

    role_codes = list({r.role.code for r in active_roles if r.role})

    permission_codes: set[str] = set()
    if active_roles:
        role_ids = [r.role_id for r in active_roles]
        perms = (
            db.query(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .filter(RolePermission.role_id.in_(role_ids))
            .all()
        )
        permission_codes = {p[0] for p in perms}

    return sorted(role_codes), sorted(permission_codes)


def user_has_permission(db: Session, user_id: str, required: str) -> bool:
    """True if user has the required permission under any active role."""
    _, perms = resolve_user_permissions(db, user_id)
    return required in perms