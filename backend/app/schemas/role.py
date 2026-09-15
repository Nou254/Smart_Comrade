"""
Pydantic schemas for Role, Permission, and UserRole.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ---------- Role ----------

class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    description: str | None
    is_system: bool
    level: int
    created_at: datetime


# ---------- Permission ----------

class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    category: str
    description: str | None


# ---------- User Role Assignment ----------

class UserRoleAssign(BaseModel):
    user_id: str = Field(..., description="Target user UUID")
    role_code: str = Field(..., description="Role code (e.g., 'lecturer')")
    jurisdiction_type: str = Field(
        default="self",
        description="platform | region | county | institution | school | group | self",
    )
    jurisdiction_id: str | None = Field(
        default=None, description="UUID of the scoped entity (nullable)"
    )
    start_date: datetime | None = None
    end_date: datetime | None = None
    notes: str | None = None


class UserRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    role_id: str
    role_code: str | None = None
    role_name: str | None = None
    jurisdiction_type: str
    jurisdiction_id: str | None
    status: str
    start_date: datetime | None
    end_date: datetime | None
    granted_at: datetime | None
    created_at: datetime


class UserPermissionsResponse(BaseModel):
    user_id: str
    roles: list[str]
    permissions: list[str]