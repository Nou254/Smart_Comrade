"""
Assessment models — Module 005.

The structured evaluation environment that measures what a student knows
and what a student can do with what they know.

Architectural decisions locked:
  - Assessment executes in the PWA; the App is awareness only
  - Two modes: directed (assigned, notified) + system_wide (voluntary, catalog)
  - No approval workflow — created → published → audience notified
  - Creator matrix governs scope + mandate type + subscription gating
  - AI assists every assessment creation with routed model selection
  - Human judgment is final for all consequential academic outcomes
  - Published assessments persist even after their creator leaves office
  - 60-day activity rule does NOT apply to assessment creation or attempts
  - Institution-mandated assessments bypass subscription gating
  - Unit Rep assessments are the only subscription-gated assessments

Tables:
   1. assessments
   2. question_banks
   3. questions
   4. attempts
   5. responses
   6. submissions
   7. results
   8. feedback
   9. appeals
  10. assessment_audit_log
  11. assessment_audience_snapshots
  12. assessment_catalog_entries
  13. ai_assistance_log
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


# ═════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═════════════════════════════════════════════════════════════════════════

# ── Assessment mode ─────────────────────────────────────────────────────
MODE_DIRECTED = "directed"
MODE_SYSTEM_WIDE = "system_wide"

ALL_MODES = (MODE_DIRECTED, MODE_SYSTEM_WIDE)

# ── Category (competency being measured) ────────────────────────────────
CATEGORY_KNOWLEDGE = "knowledge"
CATEGORY_WRITTEN = "written"
CATEGORY_PRACTICAL = "practical"
CATEGORY_PROGRAMMING = "programming"
CATEGORY_LOGIC = "logic"
CATEGORY_SKILLS = "skills"
CATEGORY_PROJECT = "project"
CATEGORY_PRACTICE = "practice"

ALL_CATEGORIES = (
    CATEGORY_KNOWLEDGE, CATEGORY_WRITTEN, CATEGORY_PRACTICAL,
    CATEGORY_PROGRAMMING, CATEGORY_LOGIC, CATEGORY_SKILLS,
    CATEGORY_PROJECT, CATEGORY_PRACTICE,
)

# ── Type (operational format) ───────────────────────────────────────────
TYPE_QUIZ = "quiz"
TYPE_ASSIGNMENT = "assignment"
TYPE_EXAMINATION = "examination"
TYPE_PRACTICAL = "practical"
TYPE_PRACTICE = "practice"

ALL_TYPES = (
    TYPE_QUIZ, TYPE_ASSIGNMENT, TYPE_EXAMINATION,
    TYPE_PRACTICAL, TYPE_PRACTICE,
)

# ── Assessment lifecycle status ─────────────────────────────────────────
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_IN_PROGRESS = "in_progress"
STATUS_CLOSED = "closed"
STATUS_ARCHIVED = "archived"

ALL_ASSESSMENT_STATUSES = (
    STATUS_DRAFT, STATUS_PUBLISHED, STATUS_IN_PROGRESS,
    STATUS_CLOSED, STATUS_ARCHIVED,
)

# ── Attempt status ──────────────────────────────────────────────────────
ATTEMPT_IN_PROGRESS = "in_progress"
ATTEMPT_SUBMITTED = "submitted"
ATTEMPT_TIMED_OUT = "timed_out"
ATTEMPT_GRADED = "graded"
ATTEMPT_ABANDONED = "abandoned"

ALL_ATTEMPT_STATUSES = (
    ATTEMPT_IN_PROGRESS, ATTEMPT_SUBMITTED, ATTEMPT_TIMED_OUT,
    ATTEMPT_GRADED, ATTEMPT_ABANDONED,
)

# ── Mandate type (drives subscription gating) ───────────────────────────
MANDATE_INSTITUTION = "institution_mandated"
MANDATE_PLATFORM = "platform_native"
MANDATE_COMMUNITY = "community_contribution"

ALL_MANDATE_TYPES = (
    MANDATE_INSTITUTION, MANDATE_PLATFORM, MANDATE_COMMUNITY,
)

# ── Audience scope (for directed assessments) ───────────────────────────
AUDIENCE_GROUP = "group"
AUDIENCE_UNIT_OFFERING = "unit_offering"
AUDIENCE_COURSE_YEAR = "course_year"
AUDIENCE_INSTITUTION = "institution"
AUDIENCE_COUNTY = "county"
AUDIENCE_REGION = "region"
AUDIENCE_CUSTOM = "custom"

ALL_AUDIENCE_SCOPES = (
    AUDIENCE_GROUP, AUDIENCE_UNIT_OFFERING, AUDIENCE_COURSE_YEAR,
    AUDIENCE_INSTITUTION, AUDIENCE_COUNTY, AUDIENCE_REGION,
    AUDIENCE_CUSTOM,
)

# ── Creator role snapshot ───────────────────────────────────────────────
CREATOR_SUPER_ADMIN = "super_admin"
CREATOR_REGIONAL_ADMIN = "regional_admin"
CREATOR_LECTURER = "lecturer"
CREATOR_UNIT_SUPERVISOR = "unit_supervisor"
CREATOR_UNIT_REPRESENTATIVE = "unit_representative"
CREATOR_MENTOR = "mentor"

ALL_CREATOR_ROLES = (
    CREATOR_SUPER_ADMIN, CREATOR_REGIONAL_ADMIN, CREATOR_LECTURER,
    CREATOR_UNIT_SUPERVISOR, CREATOR_UNIT_REPRESENTATIVE, CREATOR_MENTOR,
)

# ── Question type ───────────────────────────────────────────────────────
QTYPE_MCQ = "mcq"
QTYPE_TRUE_FALSE = "true_false"
QTYPE_FILL_BLANK = "fill_blank"
QTYPE_ESSAY = "essay"
QTYPE_FILE_UPLOAD = "file_upload"

ALL_QUESTION_TYPES = (
    QTYPE_MCQ, QTYPE_TRUE_FALSE, QTYPE_FILL_BLANK,
    QTYPE_ESSAY, QTYPE_FILE_UPLOAD,
)

# ── Difficulty ──────────────────────────────────────────────────────────
DIFFICULTY_BEGINNER = "beginner"
DIFFICULTY_INTERMEDIATE = "intermediate"
DIFFICULTY_ADVANCED = "advanced"

ALL_DIFFICULTIES = (
    DIFFICULTY_BEGINNER, DIFFICULTY_INTERMEDIATE, DIFFICULTY_ADVANCED,
)

# ── Competence level ────────────────────────────────────────────────────
LEVEL_INTRODUCTORY = "introductory"
LEVEL_DEVELOPING = "developing"
LEVEL_COMPETENT = "competent"
LEVEL_ADVANCED = "advanced"

ALL_COMPETENCE_LEVELS = (
    LEVEL_INTRODUCTORY, LEVEL_DEVELOPING, LEVEL_COMPETENT, LEVEL_ADVANCED,
)

# ── Appeal status ───────────────────────────────────────────────────────
APPEAL_SUBMITTED = "submitted"
APPEAL_UNDER_REVIEW = "under_review"
APPEAL_RESOLVED_CONFIRMED = "resolved_confirmed"
APPEAL_RESOLVED_CORRECTED = "resolved_corrected"
APPEAL_REASSESSMENT_AUTHORISED = "reassessment_authorised"
APPEAL_REJECTED = "rejected"

ALL_APPEAL_STATUSES = (
    APPEAL_SUBMITTED, APPEAL_UNDER_REVIEW, APPEAL_RESOLVED_CONFIRMED,
    APPEAL_RESOLVED_CORRECTED, APPEAL_REASSESSMENT_AUTHORISED,
    APPEAL_REJECTED,
)

# ── AI assistance actions ───────────────────────────────────────────────
AI_ACTION_DRAFT = "draft"
AI_ACTION_VALIDATE = "validate"
AI_ACTION_GRADE = "grade"
AI_ACTION_SUMMARIZE = "summarize"
AI_ACTION_HINT = "hint"

ALL_AI_ACTIONS = (
    AI_ACTION_DRAFT, AI_ACTION_VALIDATE, AI_ACTION_GRADE,
    AI_ACTION_SUMMARIZE, AI_ACTION_HINT,
)

# ── AI validation status ────────────────────────────────────────────────
AI_VALIDATION_PASSED = "passed"
AI_VALIDATION_FAILED = "failed"
AI_VALIDATION_NEEDS_REVIEW = "needs_review"

ALL_AI_VALIDATION_STATUSES = (
    AI_VALIDATION_PASSED, AI_VALIDATION_FAILED, AI_VALIDATION_NEEDS_REVIEW,
)

# ── AI entity types (for the assistance log) ────────────────────────────
AI_ENTITY_ASSESSMENT = "assessment"
AI_ENTITY_QUESTION = "question"
AI_ENTITY_RESPONSE = "response"
AI_ENTITY_RESULT = "result"
AI_ENTITY_REPORT = "report"

ALL_AI_ENTITY_TYPES = (
    AI_ENTITY_ASSESSMENT, AI_ENTITY_QUESTION,
    AI_ENTITY_RESPONSE, AI_ENTITY_RESULT, AI_ENTITY_REPORT,
)

# ── Audit log actions ───────────────────────────────────────────────────
AUDIT_CREATE = "create"
AUDIT_PUBLISH = "publish"
AUDIT_OPEN = "open"
AUDIT_CLOSE = "close"
AUDIT_ARCHIVE = "archive"
AUDIT_EVALUATE = "evaluate"
AUDIT_MODIFY_RESULT = "modify_result"
AUDIT_APPEAL_REVIEW = "appeal_review"
AUDIT_CANCEL = "cancel"
AUDIT_AUDIENCE_CHANGE = "audience_change"
AUDIT_SUBSCRIPTION_GATE = "subscription_gate_decision"

ALL_AUDIT_ACTIONS = (
    AUDIT_CREATE, AUDIT_PUBLISH, AUDIT_OPEN, AUDIT_CLOSE, AUDIT_ARCHIVE,
    AUDIT_EVALUATE, AUDIT_MODIFY_RESULT, AUDIT_APPEAL_REVIEW, AUDIT_CANCEL,
    AUDIT_AUDIENCE_CHANGE, AUDIT_SUBSCRIPTION_GATE,
)


# ═════════════════════════════════════════════════════════════════════════
# 1. assessments
# ═════════════════════════════════════════════════════════════════════════

class Assessment(Base, UUIDMixin, TimestampMixin):
    """
    The core assessment definition.

    Mode determines everything else:
      - directed: has audience_scope + audience_ref_id, notified to students
      - system_wide: audience fields NULL, browsable in catalog

    Mandate type drives subscription gating:
      - institution_mandated → bypassed
      - platform_native → gated
      - community_contribution → bypassed
    """
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint(
            f"assessment_mode IN ({','.join(repr(m) for m in ALL_MODES)})",
            name="ck_assessment_mode",
        ),
        CheckConstraint(
            f"category IN ({','.join(repr(c) for c in ALL_CATEGORIES)})",
            name="ck_assessment_category",
        ),
        CheckConstraint(
            f"type IN ({','.join(repr(t) for t in ALL_TYPES)})",
            name="ck_assessment_type",
        ),
        CheckConstraint(
            f"status IN "
            f"({','.join(repr(s) for s in ALL_ASSESSMENT_STATUSES)})",
            name="ck_assessment_status",
        ),
        CheckConstraint(
            f"mandate_type IN "
            f"({','.join(repr(m) for m in ALL_MANDATE_TYPES)})",
            name="ck_assessment_mandate_type",
        ),
        CheckConstraint(
            f"created_by_role IN "
            f"({','.join(repr(r) for r in ALL_CREATOR_ROLES)})",
            name="ck_assessment_creator_role",
        ),
        CheckConstraint(
            "audience_scope IS NULL OR audience_scope IN "
            f"({','.join(repr(a) for a in ALL_AUDIENCE_SCOPES)})",
            name="ck_assessment_audience_scope",
        ),
        # Mode ↔ audience consistency
        CheckConstraint(
            "(assessment_mode = 'system_wide' AND audience_scope IS NULL "
            " AND audience_ref_id IS NULL) OR "
            "(assessment_mode = 'directed' AND audience_scope IS NOT NULL)",
            name="ck_assessment_mode_audience_consistency",
        ),
        # Timeline consistency: if both set, end must be after start
        CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR end_at > start_at",
            name="ck_assessment_timeline_order",
        ),
        Index("ix_assessments_creator", "created_by"),
        Index("ix_assessments_mode_status", "assessment_mode", "status"),
        Index("ix_assessments_offering", "unit_offering_id"),
        Index("ix_assessments_group", "group_id"),
        Index("ix_assessments_institution", "institution_id"),
        Index("ix_assessments_status_start", "status", "start_at"),
        Index("ix_assessments_open", "assessment_mode", "end_at"),
    )

    # ── Identity ─────────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Classification ───────────────────────────────────────────────
    assessment_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)

    # ── Creator ──────────────────────────────────────────────────────
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    created_by_role: Mapped[str] = mapped_column(String(32), nullable=False)

    # ── Academic context ─────────────────────────────────────────────
    unit_offering_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("unit_offerings.id", ondelete="SET NULL"),
        nullable=True,
    )
    group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    institution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Multiple specialty unit tags (mentor system-wide assessments)
    specialty_unit_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Mandate + gating ─────────────────────────────────────────────
    mandate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subscription_gated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    # ── Audience (directed only) ─────────────────────────────────────
    audience_scope: Mapped[str | None] = mapped_column(String(24), nullable=True)
    audience_ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    audience_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    audience_resolution: Mapped[str] = mapped_column(
        String(16), nullable=False, default="snapshot",
    )  # 'snapshot' | 'live'

    # ── Timeline ─────────────────────────────────────────────────────
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )  # NULL = open assessment
    duration_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )  # NULL = untimed per attempt
    wall_clock_hard_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # ── Attempt rules ────────────────────────────────────────────────
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    passing_score: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True,
    )

    # ── Auto-grading ─────────────────────────────────────────────────
    auto_grading_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # ── AI provenance ────────────────────────────────────────────────
    ai_assisted_creation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    ai_model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Lifecycle ────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_DRAFT, index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<Assessment {self.id} mode={self.assessment_mode} "
            f"status={self.status}>"
        )


# ═════════════════════════════════════════════════════════════════════════
# 2. question_banks
# ═════════════════════════════════════════════════════════════════════════

class QuestionBank(Base, UUIDMixin, TimestampMixin):
    """Reusable repository of questions, scoped to a unit."""
    __tablename__ = "question_banks"
    __table_args__ = (
        Index("ix_question_banks_unit", "unit_id"),
        Index("ix_question_banks_creator", "created_by"),
    )

    unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )


# ═════════════════════════════════════════════════════════════════════════
# 3. questions
# ═════════════════════════════════════════════════════════════════════════

class Question(Base, UUIDMixin, TimestampMixin):
    """
    A single assessment question.

    Storage semantics:
      - assessment_id set + bank_id NULL → authored directly into the assessment
      - assessment_id NULL + bank_id set → lives in the bank only
      - both set → origin is bank, currently assigned to this assessment

    At least one of (assessment_id, question_bank_id) must be set.
    """
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            f"question_type IN "
            f"({','.join(repr(q) for q in ALL_QUESTION_TYPES)})",
            name="ck_question_type",
        ),
        CheckConstraint(
            f"difficulty IN ({','.join(repr(d) for d in ALL_DIFFICULTIES)})",
            name="ck_question_difficulty",
        ),
        CheckConstraint(
            "ai_validation_status IS NULL OR ai_validation_status IN "
            f"({','.join(repr(s) for s in ALL_AI_VALIDATION_STATUSES)})",
            name="ck_question_ai_validation_status",
        ),
        CheckConstraint(
            "assessment_id IS NOT NULL OR question_bank_id IS NOT NULL",
            name="ck_question_has_parent",
        ),
        CheckConstraint(
            "point_value >= 0",
            name="ck_question_point_value_nonneg",
        ),
        Index("ix_questions_assessment", "assessment_id"),
        Index("ix_questions_bank", "question_bank_id"),
        Index("ix_questions_order", "assessment_id", "order_index"),
    )

    assessment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=True,
    )
    question_bank_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("question_banks.id", ondelete="SET NULL"),
        nullable=True,
    )

    question_type: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    options_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    correct_answer_json: Mapped[dict | list | None] = mapped_column(
        JSONB, nullable=True,
    )

    point_value: Mapped[float] = mapped_column(
        Numeric(6, 2), nullable=False, default=1.0,
    )
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DIFFICULTY_INTERMEDIATE,
    )
    topic_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── AI provenance ────────────────────────────────────────────────
    ai_draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_generated_content: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    ai_validation_status: Mapped[str | None] = mapped_column(
        String(24), nullable=True,
    )
    ai_validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )


# ═════════════════════════════════════════════════════════════════════════
# 4. attempts
# ═════════════════════════════════════════════════════════════════════════

class Attempt(Base, UUIDMixin, TimestampMixin):
    """
    One attempt by one student on one assessment.

    Only one attempt per (student, assessment) may be in_progress at a time.
    Historical attempts accumulate freely.
    """
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALL_ATTEMPT_STATUSES)})",
            name="ck_attempt_status",
        ),
        UniqueConstraint(
            "assessment_id", "student_id", "attempt_number",
            name="uq_attempt_number_per_student_assessment",
        ),
        # Only one ACTIVE attempt per (student, assessment) at any time
        Index(
            "uq_active_attempt_per_student_assessment",
            "assessment_id", "student_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
        Index("ix_attempts_student", "student_id"),
        Index("ix_attempts_assessment", "assessment_id"),
        Index("ix_attempts_status", "status"),
        Index("ix_attempts_timer", "timer_expires_at"),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    timer_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    score: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    percentage: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ATTEMPT_IN_PROGRESS, index=True,
    )

    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ═════════════════════════════════════════════════════════════════════════
# 5. responses
# ═════════════════════════════════════════════════════════════════════════

class Response(Base, UUIDMixin, TimestampMixin):
    """
    A single answer to a single question within an attempt.

    AI preliminary grading fields coexist with human grading fields.
    A final score requires human confirmation (or an approved
    auto-grade mechanism).
    """
    __tablename__ = "responses"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "question_id",
            name="uq_response_per_attempt_question",
        ),
        Index("ix_responses_attempt", "attempt_id"),
        Index("ix_responses_question", "question_id"),
        Index("ix_responses_grader", "graded_by"),
    )

    attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )

    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_file_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Grading ──────────────────────────────────────────────────────
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score_earned: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True,
    )
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    graded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    graded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # ── AI preliminary grading ──────────────────────────────────────
    ai_preliminary_score: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True,
    )
    ai_score_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_graded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ai_grade_model: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ═════════════════════════════════════════════════════════════════════════
# 6. submissions
# ═════════════════════════════════════════════════════════════════════════

class Submission(Base, UUIDMixin, TimestampMixin):
    """
    File(s) submitted as part of an attempt — for assignments,
    practicals, and project deliverables. Distinct from per-question
    file uploads (which live on Response.response_file_url).
    """
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_attempt", "attempt_id"),
        Index("ix_submissions_uploaded", "uploaded_at"),
    )

    attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )


# ═════════════════════════════════════════════════════════════════════════
# 7. results
# ═════════════════════════════════════════════════════════════════════════

class Result(Base, UUIDMixin, TimestampMixin):
    """
    The finalised outcome of a student's assessment attempt.

    One result per (assessment, student). The best_attempt_id points
    to the attempt that produced the recognised outcome.
    """
    __tablename__ = "results"
    __table_args__ = (
        CheckConstraint(
            "competence_level IS NULL OR competence_level IN "
            f"({','.join(repr(l) for l in ALL_COMPETENCE_LEVELS)})",
            name="ck_result_competence_level",
        ),
        UniqueConstraint(
            "assessment_id", "student_id",
            name="uq_result_per_student_assessment",
        ),
        Index("ix_results_assessment", "assessment_id"),
        Index("ix_results_student", "student_id"),
        Index("ix_results_passed", "passed"),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    best_attempt_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("attempts.id", ondelete="SET NULL"),
        nullable=True,
    )

    final_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    percentage: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(8), nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    competence_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
    )

    is_official: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    finalised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finalised_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


# ═════════════════════════════════════════════════════════════════════════
# 8. feedback
# ═════════════════════════════════════════════════════════════════════════

class Feedback(Base, UUIDMixin, TimestampMixin):
    """
    Student feedback on an assessment.

    Enabled on system-wide assessments only — the community feedback
    loop that gives mentors and lecturers signal on their public
    contributions.
    """
    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_assessment", "assessment_id"),
        Index("ix_feedback_student", "student_id"),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )


# ═════════════════════════════════════════════════════════════════════════
# 9. appeals
# ═════════════════════════════════════════════════════════════════════════

class Appeal(Base, UUIDMixin, TimestampMixin):
    """Student appeal of a finalised result."""
    __tablename__ = "appeals"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in ALL_APPEAL_STATUSES)})",
            name="ck_appeal_status",
        ),
        Index("ix_appeals_result", "result_id"),
        Index("ix_appeals_student", "student_id"),
        Index("ix_appeals_status", "status"),
        Index("ix_appeals_reviewer", "reviewer_id"),
    )

    result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("results.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    grounds: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=APPEAL_SUBMITTED, index=True,
    )

    reviewer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    original_result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    corrected_result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# ═════════════════════════════════════════════════════════════════════════
# 10. assessment_audit_log
# ═════════════════════════════════════════════════════════════════════════

class AssessmentAuditLog(Base, UUIDMixin, TimestampMixin):
    """
    Immutable log of significant assessment actions.

    Covers creation, publication, evaluation, result modification,
    audience changes, subscription gate decisions, and reviews.
    """
    __tablename__ = "assessment_audit_log"
    __table_args__ = (
        CheckConstraint(
            f"action IN ({','.join(repr(a) for a in ALL_AUDIT_ACTIONS)})",
            name="ck_assessment_audit_action",
        ),
        Index("ix_assessment_audit_assessment", "assessment_id"),
        Index("ix_assessment_audit_actor", "actor_id"),
        Index("ix_assessment_audit_action", "action"),
        Index("ix_assessment_audit_created", "created_at"),
    )

    assessment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ═════════════════════════════════════════════════════════════════════════
# 11. assessment_audience_snapshots
# ═════════════════════════════════════════════════════════════════════════

class AssessmentAudienceSnapshot(Base, UUIDMixin, TimestampMixin):
    """
    Locked audience for a directed assessment at publish time.

    For snapshot-mode assessments, this table is the frozen record of
    who was entitled to attempt. For live-mode assessments, rows are
    refreshed each time the audience re-resolves, with removed rows
    marked via removed_at.
    """
    __tablename__ = "assessment_audience_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "user_id",
            name="uq_audience_snapshot_per_student",
        ),
        Index("ix_audience_snapshot_assessment", "assessment_id"),
        Index("ix_audience_snapshot_user", "user_id"),
        Index("ix_audience_snapshot_active", "assessment_id", "removed_at"),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    is_still_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    removed_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


# ═════════════════════════════════════════════════════════════════════════
# 12. assessment_catalog_entries
# ═════════════════════════════════════════════════════════════════════════

class AssessmentCatalogEntry(Base, UUIDMixin, TimestampMixin):
    """
    Catalog metadata for a system-wide assessment.

    System-wide assessments are discoverable, voluntary, and never
    subscription-gated. Catalog entries carry the discovery-surface
    metadata: unit tags, difficulty, estimated duration, and
    aggregate engagement stats.
    """
    __tablename__ = "assessment_catalog_entries"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", name="uq_catalog_entry_per_assessment",
        ),
        CheckConstraint(
            "difficulty IN ({})".format(
                ",".join(repr(d) for d in ALL_DIFFICULTIES),
            ),
            name="ck_catalog_entry_difficulty",
        ),
        Index("ix_catalog_entries_unit", "primary_unit_id"),
        Index("ix_catalog_entries_featured", "is_featured"),
        Index("ix_catalog_entries_rating", "average_rating"),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )

    primary_unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )
    specialty_unit_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    specialty_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DIFFICULTY_INTERMEDIATE,
    )
    estimated_duration_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    take_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_rating: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_featured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )


# ═════════════════════════════════════════════════════════════════════════
# 13. ai_assistance_log
# ═════════════════════════════════════════════════════════════════════════

class AIAssistanceLog(Base, UUIDMixin, TimestampMixin):
    """
    Every AI-assisted action, for transparency, cost tracking, and audit.

    Records the entity, action, model, token usage, and (where the
    provider exposes it) the cost. Referenced by Assessment,
    Question, Response when the AI is invoked.
    """
    __tablename__ = "ai_assistance_log"
    __table_args__ = (
        CheckConstraint(
            f"action IN ({','.join(repr(a) for a in ALL_AI_ACTIONS)})",
            name="ck_ai_log_action",
        ),
        CheckConstraint(
            f"entity_type IN "
            f"({','.join(repr(e) for e in ALL_AI_ENTITY_TYPES)})",
            name="ck_ai_log_entity_type",
        ),
        Index("ix_ai_log_entity", "entity_type", "entity_id"),
        Index("ix_ai_log_actor", "actor_id"),
        Index("ix_ai_log_model", "model_used"),
        Index("ix_ai_log_action", "action"),
        Index("ix_ai_log_created", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    action: Mapped[str] = mapped_column(String(24), nullable=False)
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)

    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    request_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    succeeded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)