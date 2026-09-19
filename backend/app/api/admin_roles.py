"""
Admin endpoints for role management.
All routes require authentication; write routes require 'role.assign' or
'role.revoke' PLUS a fresh step-up token for the corresponding scope.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission, require_step_up
from app.db.session import get_db
from app.models.user import User
from app.models.role import UserRole
from app.schemas.role import (
    RoleResponse,
    PermissionResponse,
    UserRoleAssign,
    UserRoleResponse,
    UserPermissionsResponse,
)
from app.services.role_service import (
    RoleError,
    list_roles,
    list_permissions,
    assign_role,
    revoke_role,
    get_user_roles,
    resolve_user_permissions,
)

router = APIRouter(prefix="/admin", tags=["Admin - Roles & Permissions"])


# ---------- Read: role & permission catalogs ----------

@router.get("/roles", response_model=list[RoleResponse])
def get_roles(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_roles(db)


@router.get("/permissions", response_model=list[PermissionResponse])
def get_permissions(
    category: str | None = None,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_permissions(db, category=category)


# ---------- Read: a user's roles & effective permissions ----------

@router.get("/users/{user_id}/roles", response_model=list[UserRoleResponse])
def get_user_role_assignments(
    user_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = get_user_roles(db, user_id)
    return [
        UserRoleResponse(
            id=r.id,
            user_id=r.user_id,
            role_id=r.role_id,
            role_code=r.role.code if r.role else None,
            role_name=r.role.name if r.role else None,
            jurisdiction_type=r.jurisdiction_type,
            jurisdiction_id=r.jurisdiction_id,
            status=r.status,
            start_date=r.start_date,
            end_date=r.end_date,
            granted_at=r.granted_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/users/{user_id}/permissions", response_model=UserPermissionsResponse)
def get_user_effective_permissions(
    user_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roles, perms = resolve_user_permissions(db, user_id)
    return UserPermissionsResponse(user_id=user_id, roles=roles, permissions=perms)


# ---------- Write: assign / revoke roles ----------
# Both require a fresh step-up token scoped to the corresponding action.

@router.post("/users/roles/assign", response_model=UserRoleResponse, status_code=201)
def assign_user_role(
    payload: UserRoleAssign,
    current_user: User = Depends(require_permission("role.assign")),
    _step_up: User = Depends(require_step_up("role.assign")),
    db: Session = Depends(get_db),
):
    try:
        assignment = assign_role(
            db=db,
            user_id=payload.user_id,
            role_code=payload.role_code,
            jurisdiction_type=payload.jurisdiction_type,
            jurisdiction_id=payload.jurisdiction_id,
            granted_by=current_user.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            notes=payload.notes,
        )
    except RoleError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return UserRoleResponse(
        id=assignment.id,
        user_id=assignment.user_id,
        role_id=assignment.role_id,
        role_code=assignment.role.code if assignment.role else None,
        role_name=assignment.role.name if assignment.role else None,
        jurisdiction_type=assignment.jurisdiction_type,
        jurisdiction_id=assignment.jurisdiction_id,
        status=assignment.status,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        granted_at=assignment.granted_at,
        created_at=assignment.created_at,
    )


@router.delete("/user-roles/{user_role_id}", response_model=UserRoleResponse)
def revoke_user_role(
    user_role_id: str,
    reason: str | None = None,
    current_user: User = Depends(require_permission("role.revoke")),
    _step_up: User = Depends(require_step_up("role.revoke")),
    db: Session = Depends(get_db),
):
    try:
        assignment = revoke_role(
            db=db,
            user_role_id=user_role_id,
            revoked_by=current_user.id,
            reason=reason,
        )
    except RoleError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return UserRoleResponse(
        id=assignment.id,
        user_id=assignment.user_id,
        role_id=assignment.role_id,
        role_code=assignment.role.code if assignment.role else None,
        role_name=assignment.role.name if assignment.role else None,
        jurisdiction_type=assignment.jurisdiction_type,
        jurisdiction_id=assignment.jurisdiction_id,
        status=assignment.status,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        granted_at=assignment.granted_at,
        created_at=assignment.created_at,
    )