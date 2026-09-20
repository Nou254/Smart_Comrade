"""
Academic structure models — Module 002.
Full hierarchy: Region → County → Institution → School → Course → Unit
Plus temporal: AcademicYear → Semester
Plus relationships: StudentEnrollment, UnitMembership
Plus institutional: InstitutionTransition, InstitutionTransitionRequest
"""
from datetime import date, datetime
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


# ============================================================================
# GEOGRAPHY
# ============================================================================

class Region(Base, UUIDMixin, TimestampMixin):
    """Geographical region (e.g., Western, Nyanza, Rift Valley)."""
    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    counties: Mapped[list["County"]] = relationship(
        "County", back_populates="region", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Region {self.code} - {self.name}>"


class County(Base, UUIDMixin, TimestampMixin):
    """County within a region (e.g., Kisumu, Nairobi)."""
    __tablename__ = "counties"
    __table_args__ = (
        UniqueConstraint("region_id", "name", name="uq_county_region_name"),
    )

    region_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("regions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    region: Mapped[Region] = relationship("Region", back_populates="counties")
    institutions: Mapped[list["Institution"]] = relationship(
        "Institution", back_populates="county"
    )

    def __repr__(self) -> str:
        return f"<County {self.code} - {self.name}>"


# ============================================================================
# INSTITUTION HIERARCHY
# ============================================================================

class Institution(Base, UUIDMixin, TimestampMixin):
    """
    Educational institution.

    type        : one of UNIVERSITY | UNIVERSITY_COLLEGE | COLLEGE |
                  POLYTECHNIC | TVET | TECHNICAL_INSTITUTE | KMTC | TTC | OTHER
    campus_role : 'main' (standalone) or 'branch' (references a main campus)
    """
    __tablename__ = "institutions"
    __table_args__ = (
        CheckConstraint(
            "type IN ("
            "'UNIVERSITY','UNIVERSITY_COLLEGE','COLLEGE',"
            "'POLYTECHNIC','TVET','TECHNICAL_INSTITUTE',"
            "'KMTC','TTC','OTHER'"
            ")",
            name="ck_institution_type",
        ),
        CheckConstraint(
            "status IN ('pending','active','suspended','deactivated','rejected')",
            name="ck_institution_status",
        ),
        CheckConstraint(
            "campus_role IN ('main','branch')",
            name="ck_institution_campus_role",
        ),
        UniqueConstraint("code", name="uq_institution_code"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # --- Campus role ---
    # 'main'   : standalone campus (or one that has been promoted)
    # 'branch' : a campus that must reference a main campus via parent_institution_id
    campus_role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="main", index=True,
    )

    county_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("counties.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    parent_institution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    physical_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    county: Mapped[County] = relationship("County", back_populates="institutions")
    parent: Mapped["Institution | None"] = relationship(
        "Institution", remote_side="Institution.id", back_populates="branches"
    )
    branches: Mapped[list["Institution"]] = relationship(
        "Institution", back_populates="parent", cascade="all, delete-orphan"
    )
    schools: Mapped[list["School"]] = relationship(
        "School", back_populates="institution", cascade="all, delete-orphan"
    )
    academic_years: Mapped[list["AcademicYear"]] = relationship(
        "AcademicYear", back_populates="institution", cascade="all, delete-orphan"
    )
    transitions: Mapped[list["InstitutionTransition"]] = relationship(
        "InstitutionTransition", back_populates="institution",
        cascade="all, delete-orphan",
        foreign_keys="InstitutionTransition.institution_id",
    )

    def __repr__(self) -> str:
        return f"<Institution {self.code} ({self.campus_role}) - {self.name}>"


class InstitutionTransition(Base, UUIDMixin, TimestampMixin):
    """
    Immutable history of every accepted structural change to an institution.
    Created when a Regional Admin or Super Admin performs a transition
    directly, OR when a pending request is approved.
    """
    __tablename__ = "institution_transitions"

    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # 'promote_to_main' | 'change_type' | 'promote_and_change_type'
    # | 'set_parent' | 'remove_parent' | 'rename' | 'merge' | 'other'
    transition_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Snapshot of pre-change state
    old_campus_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    old_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    old_parent_institution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True,
    )

    # Post-change state
    new_campus_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_parent_institution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True,
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Charter number, gazette reference, regulatory body reference, etc.
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    changed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # Optionally link back to the request that triggered this transition
    source_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("institution_transition_requests.id", ondelete="SET NULL"),
        nullable=True,
    )

    institution: Mapped[Institution] = relationship(
        "Institution", back_populates="transitions",
        foreign_keys=[institution_id],
    )

    def __repr__(self) -> str:
        return (
            f"<InstitutionTransition {self.transition_type} "
            f"institution={self.institution_id}>"
        )


class InstitutionTransitionRequest(Base, UUIDMixin, TimestampMixin):
    """
    A pending request by an Institution Admin to change campus role and/or
    institution type. Regional Admin reviews; Super Admin is cc'd.
    """
    __tablename__ = "institution_transition_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','withdrawn')",
            name="ck_transition_request_status",
        ),
    )

    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    requested_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False, index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    # What the requester wants to happen
    desired_campus_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    desired_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    desired_parent_institution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True,
    )

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    institution: Mapped[Institution] = relationship(
        "Institution", foreign_keys=[institution_id],
    )

    def __repr__(self) -> str:
        return (
            f"<InstitutionTransitionRequest {self.id} status={self.status}>"
        )


class School(Base, UUIDMixin, TimestampMixin):
    """School/faculty within an institution."""
    __tablename__ = "schools"
    __table_args__ = (
        UniqueConstraint("institution_id", "name", name="uq_school_institution_name"),
        UniqueConstraint("institution_id", "code", name="uq_school_institution_code"),
        CheckConstraint("status IN ('active','inactive')", name="ck_school_status"),
    )

    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    institution: Mapped[Institution] = relationship("Institution", back_populates="schools")
    courses: Mapped[list["Course"]] = relationship(
        "Course", back_populates="school", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<School {self.code} - {self.name}>"


class Course(Base, UUIDMixin, TimestampMixin):
    """Academic programme offered by a school."""
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_course_school_code"),
        CheckConstraint("status IN ('active','inactive')", name="ck_course_status"),
    )

    school_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    school: Mapped[School] = relationship("School", back_populates="courses")
    units: Mapped[list["Unit"]] = relationship(
        "Unit", back_populates="course", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Course {self.code} - {self.name}>"


class Unit(Base, UUIDMixin, TimestampMixin):
    """Individual subject/module within a course."""
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("course_id", "code", name="uq_unit_course_code"),
        CheckConstraint("status IN ('active','inactive')", name="ck_unit_status"),
    )

    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    course: Mapped[Course] = relationship("Course", back_populates="units")

    def __repr__(self) -> str:
        return f"<Unit {self.code} - {self.name}>"


# ============================================================================
# TEMPORAL PERIODS
# ============================================================================

class AcademicYear(Base, UUIDMixin, TimestampMixin):
    """Academic year (e.g., 2026/2027)."""
    __tablename__ = "academic_years"
    __table_args__ = (
        UniqueConstraint("institution_id", "name", name="uq_academic_year_institution_name"),
        CheckConstraint(
            "status IN ('upcoming','active','completed','archived')",
            name="ck_academic_year_status",
        ),
    )

    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="upcoming", nullable=False)

    institution: Mapped[Institution] = relationship(
        "Institution", back_populates="academic_years"
    )
    semesters: Mapped[list["Semester"]] = relationship(
        "Semester", back_populates="academic_year", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AcademicYear {self.name}>"


class Semester(Base, UUIDMixin, TimestampMixin):
    """Semester within an academic year."""
    __tablename__ = "semesters"
    __table_args__ = (
        UniqueConstraint("academic_year_id", "number", name="uq_semester_year_number"),
        CheckConstraint("number IN (1,2,3)", name="ck_semester_number"),
        CheckConstraint(
            "status IN ('upcoming','active','completed','archived')",
            name="ck_semester_status",
        ),
    )

    academic_year_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="upcoming", nullable=False)

    academic_year: Mapped[AcademicYear] = relationship(
        "AcademicYear", back_populates="semesters"
    )

    def __repr__(self) -> str:
        return f"<Semester {self.name}>"


# ============================================================================
# STUDENT ACADEMIC RELATIONSHIPS
# ============================================================================

class StudentEnrollment(Base, UUIDMixin, TimestampMixin):
    """Student ↔ Course ↔ AcademicYear ↔ Semester enrollment record."""
    __tablename__ = "student_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "academic_year_id", "semester_id",
            name="uq_student_enrollment_period",
        ),
        CheckConstraint(
            "status IN ('active','completed','withdrawn','suspended')",
            name="ck_enrollment_status",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    academic_year_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    semester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("semesters.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<StudentEnrollment user={self.user_id} course={self.course_id}>"


class UnitMembership(Base, UUIDMixin, TimestampMixin):
    """Student ↔ Unit ↔ Semester membership."""
    __tablename__ = "unit_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "unit_id", "semester_id", name="uq_unit_membership"),
        CheckConstraint(
            "status IN ('active','completed','withdrawn')",
            name="ck_unit_membership_status",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    semester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("semesters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    def __repr__(self) -> str:
        return f"<UnitMembership user={self.user_id} unit={self.unit_id}>"


# ============================================================================
# AUDIT
# ============================================================================

class AcademicStructureAudit(Base, UUIDMixin, TimestampMixin):
    """Audit log for changes to academic structure."""
    __tablename__ = "academic_structure_audit"

    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Audit {self.action} {self.entity_type}:{self.entity_id}>"