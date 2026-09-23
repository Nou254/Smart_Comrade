"""
Pydantic schemas for the Assessment module — Module 005.

Two audiences:
  - PWA admin/evaluator surfaces: full detail
  - App awareness surfaces: summary only, no questions, no answers

The App-facing schemas deliberately exclude content that would let
the App execute any part of the assessment.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ═════════════════════════════════════════════════════════════════════════
# ASSESSMENT — CREATE / UPDATE
# ═════════════════════════════════════════════════════════════════════════

class AssessmentDirectedCreate(BaseModel):
    """Create a directed assessment (has a specific audience)."""
    title: str = Field(..., min_length=3, max_length=255)
    description: str | None = Field(None, max_length=5000)
    category: str = Field(
        ...,
        description=(
            "knowledge | written | practical | programming | "
            "logic | skills | project | practice"
        ),
    )
    type: str = Field(
        ...,
        description="quiz | assignment | examination | practical | practice",
    )

    # Audience
    audience_scope: str = Field(
        ...,
        description=(
            "group | unit_offering | course_year | institution | "
            "county | region | custom"
        ),
    )
    audience_ref_id: str | None = Field(
        None,
        description="ID of the target (group, unit_offering, etc.). "
                    "Required unless scope is 'custom'.",
    )
    audience_resolution: str = Field(
        "snapshot",
        description="snapshot | live",
    )

    # Timeline (all optional — NULL = open assessment)
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_minutes: int | None = Field(None, ge=1, le=1440)
    wall_clock_hard_end: bool = True

    # Attempt rules
    max_attempts: int = Field(1, ge=1, le=20)
    passing_score: float | None = Field(None, ge=0, le=100)

    # Auto-grading
    auto_grading_enabled: bool = False


class AssessmentSystemWideCreate(BaseModel):
    """Create a system-wide assessment (public, voluntary, catalog-discovered)."""
    title: str = Field(..., min_length=3, max_length=255)
    description: str | None = Field(None, max_length=5000)
    category: str = Field(
        ...,
        description=(
            "knowledge | written | practical | programming | "
            "logic | skills | project | practice"
        ),
    )
    type: str = Field(
        ...,
        description="quiz | assignment | examination | practical | practice",
    )

    # Catalog metadata
    specialty_unit_ids: list[str] | None = Field(
        None,
        description="Mentor: units this assessment covers.",
    )
    difficulty: str = Field(
        "intermediate",
        description="beginner | intermediate | advanced",
    )
    estimated_duration_minutes: int | None = Field(None, ge=1, le=1440)

    # Timeline
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_minutes: int | None = Field(None, ge=1, le=1440)

    # Attempt rules
    max_attempts: int = Field(1, ge=1, le=20)
    passing_score: float | None = Field(None, ge=0, le=100)

    # Auto-grading
    auto_grading_enabled: bool = False


class AssessmentUpdate(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = Field(None, max_length=5000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_minutes: int | None = Field(None, ge=1, le=1440)
    wall_clock_hard_end: bool | None = None
    max_attempts: int | None = Field(None, ge=1, le=20)
    passing_score: float | None = Field(None, ge=0, le=100)
    auto_grading_enabled: bool | None = None


class AssessmentPublishRequest(BaseModel):
    """Explicit publish request — no approval workflow, just a formal transition."""
    notify_audience: bool = True


# ═════════════════════════════════════════════════════════════════════════
# ASSESSMENT — RESPONSES
# ═════════════════════════════════════════════════════════════════════════

class AssessmentResponse(BaseModel):
    """Full assessment detail (admin / creator view)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    assessment_mode: str
    category: str
    type: str

    created_by: str
    created_by_role: str

    unit_offering_id: str | None
    group_id: str | None
    institution_id: str | None
    specialty_unit_ids: list | None

    mandate_type: str
    subscription_gated: bool

    audience_scope: str | None
    audience_ref_id: str | None
    audience_snapshot_at: datetime | None
    audience_resolution: str

    start_at: datetime | None
    end_at: datetime | None
    duration_minutes: int | None
    wall_clock_hard_end: bool

    max_attempts: int
    passing_score: float | None
    auto_grading_enabled: bool

    ai_assisted_creation: bool
    ai_model_used: str | None

    status: str
    published_at: datetime | None
    closed_at: datetime | None

    created_at: datetime
    updated_at: datetime


class AssessmentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    assessment_mode: str
    category: str
    type: str
    created_by: str
    created_by_role: str
    status: str
    start_at: datetime | None
    end_at: datetime | None
    published_at: datetime | None


# ═════════════════════════════════════════════════════════════════════════
# APP AWARENESS (deliberately minimal — no questions, no answers)
# ═════════════════════════════════════════════════════════════════════════

class AssessmentAwarenessItem(BaseModel):
    """
    One row in the App's awareness list.

    Deliberately excludes: question text, correct answers, evaluator
    feedback, or any content that would let the App execute any part
    of the assessment.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    category: str
    type: str
    creator_name: str | None
    creator_role: str
    unit_name: str | None
    unit_code: str | None

    start_at: datetime | None
    end_at: datetime | None
    duration_minutes: int | None

    status: str
    attempt_status: str | None = Field(
        None,
        description=(
            "Student's own status: not_attempted | in_progress | "
            "submitted | graded"
        ),
    )


class AssessmentAwarenessSummary(BaseModel):
    """The App's summary of a single assessment (no content)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    category: str
    type: str
    creator_name: str | None
    creator_role: str
    unit_name: str | None
    unit_code: str | None
    start_at: datetime | None
    end_at: datetime | None
    duration_minutes: int | None
    attempt_status: str | None
    result_available: bool
    result_percentage: float | None
    result_passed: bool | None


class AssessmentDeepLink(BaseModel):
    """The URL the App hands to the PWA to start the assessment."""
    assessment_id: str
    pwa_url: str
    expires_at: datetime | None = None


# ═════════════════════════════════════════════════════════════════════════
# QUESTION BANK
# ═════════════════════════════════════════════════════════════════════════

class QuestionBankCreate(BaseModel):
    unit_id: str
    name: str = Field(..., min_length=3, max_length=200)
    description: str | None = Field(None, max_length=5000)


class QuestionBankUpdate(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=200)
    description: str | None = Field(None, max_length=5000)
    is_active: bool | None = None


class QuestionBankResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    unit_id: str
    name: str
    description: str | None
    created_by: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class QuestionBankDetailResponse(BaseModel):
    bank: QuestionBankResponse
    question_count: int


# ═════════════════════════════════════════════════════════════════════════
# QUESTION
# ═════════════════════════════════════════════════════════════════════════

class QuestionCreate(BaseModel):
    question_type: str = Field(
        ...,
        description=(
            "mcq | true_false | fill_blank | essay | file_upload"
        ),
    )
    text: str = Field(..., min_length=1, max_length=10000)
    options_json: list | None = None
    correct_answer_json: dict | list | None = None
    point_value: float = Field(1.0, ge=0)
    order_index: int = Field(0, ge=0)
    difficulty: str = Field(
        "intermediate",
        description="beginner | intermediate | advanced",
    )
    topic_tags: list[str] | None = None


class QuestionUpdate(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=10000)
    options_json: list | None = None
    correct_answer_json: dict | list | None = None
    point_value: float | None = Field(None, ge=0)
    order_index: int | None = Field(None, ge=0)
    difficulty: str | None = None
    topic_tags: list[str] | None = None


class QuestionResponse(BaseModel):
    """Full question detail — creator / evaluator view."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str | None
    question_bank_id: str | None
    question_type: str
    text: str
    options_json: list | None
    correct_answer_json: dict | list | None
    point_value: float
    order_index: int
    difficulty: str
    topic_tags: list | None

    ai_draft_id: str | None
    ai_generated_content: bool
    ai_validation_status: str | None
    ai_validation_notes: str | None

    created_by: str
    created_at: datetime
    updated_at: datetime


class QuestionAttemptView(BaseModel):
    """
    Question as presented to a student during an attempt.
    Excludes correct_answer_json and AI metadata.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str
    question_type: str
    text: str
    options_json: list | None
    point_value: float
    order_index: int
    character_limit: int | None = None


# ═════════════════════════════════════════════════════════════════════════
# ATTEMPT
# ═════════════════════════════════════════════════════════════════════════

class AttemptStartResponse(BaseModel):
    """Returned when a student starts an attempt (PWA only)."""
    attempt_id: str
    assessment_id: str
    attempt_number: int
    started_at: datetime
    timer_expires_at: datetime | None
    questions: list[QuestionAttemptView]


class AttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str
    student_id: str
    attempt_number: int
    started_at: datetime
    submitted_at: datetime | None
    timer_expires_at: datetime | None
    score: float | None
    percentage: float | None
    passed: bool | None
    status: str
    created_at: datetime
    updated_at: datetime


class AttemptStatusResponse(BaseModel):
    """Polled by the PWA during an attempt."""
    attempt_id: str
    status: str
    seconds_remaining: int | None
    answered_count: int
    total_questions: int


# ═════════════════════════════════════════════════════════════════════════
# RESPONSE (per-question answer)
# ═════════════════════════════════════════════════════════════════════════

class ResponseSubmit(BaseModel):
    question_id: str
    response_text: str | None = None
    response_file_url: str | None = None
    response_json: dict | None = None


class ResponseUpdate(BaseModel):
    response_text: str | None = None
    response_file_url: str | None = None
    response_json: dict | None = None


class ResponseResponse(BaseModel):
    """Full response (evaluator view — includes grading)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt_id: str
    question_id: str
    response_text: str | None
    response_file_url: str | None
    response_json: dict | None

    is_correct: bool | None
    score_earned: float | None
    feedback: str | None
    graded_by: str | None
    graded_at: datetime | None

    ai_preliminary_score: float | None
    ai_score_rationale: str | None
    ai_graded_at: datetime | None
    ai_grade_model: str | None

    created_at: datetime
    updated_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# SUBMISSION
# ═════════════════════════════════════════════════════════════════════════

class SubmissionCreate(BaseModel):
    file_url: str = Field(..., max_length=500)
    file_name: str = Field(..., max_length=255)
    file_size_bytes: int = Field(..., ge=0)
    mime_type: str = Field(..., max_length=128)


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt_id: str
    file_url: str
    file_name: str
    file_size_bytes: int
    mime_type: str
    uploaded_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# GRADING
# ═════════════════════════════════════════════════════════════════════════

class ResponseGradeSubmit(BaseModel):
    score_earned: float = Field(..., ge=0)
    feedback: str | None = Field(None, max_length=5000)
    is_correct: bool | None = None


class ResultFinaliseSubmit(BaseModel):
    competence_level: str | None = Field(
        None,
        description="introductory | developing | competent | advanced",
    )


class ResultCorrectSubmit(BaseModel):
    final_score: float = Field(..., ge=0)
    percentage: float = Field(..., ge=0, le=100)
    passed: bool
    reason: str = Field(..., min_length=5, max_length=2000)


# ═════════════════════════════════════════════════════════════════════════
# RESULT
# ═════════════════════════════════════════════════════════════════════════

class ResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str
    student_id: str
    best_attempt_id: str | None
    final_score: float
    percentage: float
    grade: str | None
    passed: bool
    competence_level: str | None
    is_official: bool
    finalised_at: datetime | None
    finalised_by: str | None
    created_at: datetime
    updated_at: datetime


class ResultListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str
    assessment_title: str | None
    percentage: float
    passed: bool
    competence_level: str | None
    is_official: bool
    finalised_at: datetime | None


class ResultSummaryForApp(BaseModel):
    """
    The summary view the App shows. Full breakdown lives in the PWA.
    """
    assessment_id: str
    assessment_title: str
    percentage: float
    passed: bool
    competence_level: str | None
    is_official: bool
    finalised_at: datetime | None
    full_result_pwa_url: str


class ResultDetailResponse(BaseModel):
    """Full result — PWA view."""
    result: ResultResponse
    responses: list[ResponseResponse]


# ═════════════════════════════════════════════════════════════════════════
# FEEDBACK
# ═════════════════════════════════════════════════════════════════════════

class FeedbackCreate(BaseModel):
    rating: int | None = Field(None, ge=1, le=5)
    comment: str = Field(..., min_length=1, max_length=5000)
    is_anonymous: bool = False


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str
    student_id: str
    rating: int | None
    comment: str
    is_anonymous: bool
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# APPEAL
# ═════════════════════════════════════════════════════════════════════════

class AppealCreate(BaseModel):
    grounds: str = Field(..., min_length=10, max_length=5000)
    evidence_json: list | None = None


class AppealReviewSubmit(BaseModel):
    status: str = Field(
        ...,
        description=(
            "resolved_confirmed | resolved_corrected | "
            "reassessment_authorised | rejected"
        ),
    )
    review_notes: str = Field(..., min_length=5, max_length=5000)
    corrected_result_json: dict | None = None


class AppealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    result_id: str
    student_id: str
    grounds: str
    evidence_json: list | None
    status: str
    reviewer_id: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    original_result_json: dict | None
    corrected_result_json: dict | None
    created_at: datetime
    updated_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# AUDIENCE SNAPSHOT
# ═════════════════════════════════════════════════════════════════════════

class AudienceSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str
    user_id: str
    captured_at: datetime
    is_still_eligible: bool
    removed_at: datetime | None
    removed_reason: str | None


# ═════════════════════════════════════════════════════════════════════════
# CATALOG (system-wide discovery)
# ═════════════════════════════════════════════════════════════════════════

class CatalogListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assessment_id: str
    title: str
    description: str | None
    creator_name: str | None
    creator_role: str
    category: str
    difficulty: str
    estimated_duration_minutes: int | None
    specialty_tags: list | None
    average_rating: float | None
    rating_count: int
    take_count: int
    is_featured: bool


class CatalogDetailResponse(BaseModel):
    entry: CatalogListItem
    full_assessment: AssessmentResponse


class CatalogFilter(BaseModel):
    unit_id: str | None = None
    creator_id: str | None = None
    creator_role: str | None = None
    difficulty: str | None = None
    category: str | None = None
    min_rating: float | None = Field(None, ge=0, le=5)
    featured_only: bool = False


# ═════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═════════════════════════════════════════════════════════════════════════

class AssessmentAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str | None
    actor_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    old_value: str | None
    new_value: str | None
    reason: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# AI ASSISTANCE LOG
# ═════════════════════════════════════════════════════════════════════════

class AIAssistanceLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    entity_type: str
    entity_id: str | None
    action: str
    model_used: str
    actor_id: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    request_summary: str | None
    response_summary: str | None
    succeeded: bool
    error_message: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═════════════════════════════════════════════════════════════════════════

class AssessmentAnalyticsResponse(BaseModel):
    assessment_id: str
    total_attempts: int
    distinct_students: int
    average_score: float | None
    pass_rate: float | None
    completion_rate: float | None
    difficulty_index: float | None
    per_question_stats: list[dict] | None