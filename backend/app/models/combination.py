"""
Combination model — Module 002 completion.

A Combination is a course-bound pairing of subjects used by programmes
like Bachelor of Education Science, where students choose combinations
such as Mathematics/Geography or Physics/Chemistry.

Design (from canonical spec):
  - Combinations are bound to exactly one course.
  - No formal approval workflow is required.
  - A notification is sent to Regional + Super only, skipping County.
  - Field appears in the registration cascade only when the course has
    at least one combination defined.
"""
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Combination(Base, UUIDMixin, TimestampMixin):
    """A subject pairing offered within a specific course."""
    __tablename__ = "combinations"
    __table_args__ = (
        UniqueConstraint("course_id", "code", name="uq_combination_course_code"),
        UniqueConstraint("course_id", "name", name="uq_combination_course_name"),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_combination_status",
        ),
        Index("ix_combinations_course_id", "course_id"),
    )

    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True,
    )

    # Creator — kept for audit and for the "notification to higher admins"
    # behaviour defined in the canonical spec.
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    course = relationship("Course", backref="combinations")

    def __repr__(self) -> str:
        return f"<Combination {self.code} - {self.name}>"