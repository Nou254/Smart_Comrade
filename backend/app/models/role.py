"""
Role, Permission, and Role Assignment models — Module 001: RBAC.
"""
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Role(Base, UUIDMixin, TimestampMixin):
    """A role defines a set of permissions (Student, Lecturer, etc.)."""
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Role classification (NEW) ---
    # student_base | student_leadership | external_base | external_addon | platform
    role_class: Mapped[str] = mapped_column(
        String(32), nullable=False, default="student_base", index=True,
    )
    # --- Leadership flag (NEW) ---
    # At most one active leadership role per user is enforced at the service layer.
    is_leadership: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole", back_populates="role"
    )

    def __repr__(self) -> str:
        return f"<Role {self.code}>"


class Permission(Base, UUIDMixin, TimestampMixin):
    """A granular permission that can be granted to a role."""
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="permission", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"


class RolePermission(Base, UUIDMixin, TimestampMixin):
    """Junction table linking roles to permissions."""
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[Role] = relationship("Role", back_populates="role_permissions")
    permission: Mapped[Permission] = relationship("Permission", back_populates="role_permissions")


class UserRole(Base, UUIDMixin, TimestampMixin):
    """
    Assignment of a role to a user, scoped to a jurisdiction.
    jurisdiction_type: platform | region | county | institution | school | group | self
    jurisdiction_id: UUID of the entity (nullable for platform/self)
    """
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            "jurisdiction_type",
            "jurisdiction_id",
            name="uq_user_role_jurisdiction",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    jurisdiction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    jurisdiction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # active | pending | expired | suspended | revoked
    # | ended_by_new_assignment | vacated_for_higher_office | ended_by_election | resigned

    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    granted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revoked_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    role: Mapped[Role] = relationship("Role", back_populates="user_roles")

    def __repr__(self) -> str:
        return f"<UserRole user={self.user_id} role={self.role_id} status={self.status}>"