"""
Unit offering model — Module 002 completion.

An academic Unit (e.g., "DB201 Database Systems") exists independent of
any specific period. An Offering is a specific occurrence of that Unit
during one academic year and semester.

From the canonical spec:
  - Offerings are per semester.
  - The same unit code may appear again in later semesters as a distinct
    offering.
  - Offerings can be created in advance of the semester they belong to.

Downstream services (assessments, resources, discussions, unit-level
communities) attach to the offering, not to the abstract Unit.
"""
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class UnitOffering(Base, UUIDMixin, TimestampMixin):
    """A specific occurrence of a unit in an academic year + semester."""
    __tablename__ = "unit_offerings"
    __table_args__ = (
        UniqueConstraint(
            "unit_id", "semester_id",
            name="uq_unit_offering_per_semester",
        ),
        CheckConstraint(
            "status IN ('scheduled','active','completed','archived')",
            name="ck_unit_offering_status",
        ),
        Index("ix_unit_offerings_course_semester", "course_id", "semester_id"),
        Index("ix_unit_offerings_institution", "institution_id"),
    )

    unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Denormalised context for fast filtering. All three are derivable
    # from `unit_id` but stored explicitly to avoid deep joins.
    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    school_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    academic_year_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    semester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("semesters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    year_level: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="scheduled", index=True,
    )
    # Cached count of active confirmations for the offering. Updated by the
    # service layer whenever a UnitMembership with confirmation is created
    # or removed.
    enrolled_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    unit = relationship("Unit", backref="offerings")
    academic_year = relationship("AcademicYear")
    semester = relationship("Semester")

    def __repr__(self) -> str:
        return (
            f"<UnitOffering unit={self.unit_id} "
            f"semester={self.semester_id} status={self.status}>"
        )