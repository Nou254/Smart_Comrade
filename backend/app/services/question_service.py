"""
Question + question bank management — Module 005.
"""
import logging
from sqlalchemy.orm import Session

from app.models.assessment import (
    Assessment, QuestionBank, Question, AssessmentAuditLog,
    ALL_QUESTION_TYPES, ALL_DIFFICULTIES,
    AI_VALIDATION_PASSED, AI_VALIDATION_FAILED, AI_VALIDATION_NEEDS_REVIEW,
)


logger = logging.getLogger(__name__)


class QuestionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────

def _validate_question_shape(
    question_type: str,
    options_json: list | None,
    correct_answer_json: dict | list | None,
) -> None:
    if question_type not in ALL_QUESTION_TYPES:
        raise QuestionError(f"Unknown question_type '{question_type}'.", 400)

    if question_type == "mcq":
        if not options_json or len(options_json) < 2:
            raise QuestionError(
                "MCQ questions require at least 2 options.", 400,
            )
    elif question_type == "true_false":
        if not options_json or len(options_json) != 2:
            raise QuestionError(
                "True/False questions require exactly 2 options.", 400,
            )
    elif question_type == "fill_blank":
        if not correct_answer_json:
            raise QuestionError(
                "Fill-in-the-blank requires a correct answer.", 400,
            )


# ─────────────────────────────────────────────────────────────────────────
# QUESTION BANKS
# ─────────────────────────────────────────────────────────────────────────

def create_bank(
    db: Session, *, unit_id: str, name: str,
    created_by: str, description: str | None = None,
) -> QuestionBank:
    bank = QuestionBank(
        unit_id=unit_id,
        name=name,
        description=description,
        created_by=created_by,
        is_active=True,
    )
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


def get_bank(db: Session, bank_id: str) -> QuestionBank:
    b = db.query(QuestionBank).filter(QuestionBank.id == bank_id).first()
    if not b:
        raise QuestionError("Question bank not found.", 404)
    return b


def list_banks_for_unit(db: Session, unit_id: str) -> list[QuestionBank]:
    return db.query(QuestionBank).filter(
        QuestionBank.unit_id == unit_id,
        QuestionBank.is_active.is_(True),
    ).order_by(QuestionBank.created_at.desc()).all()


def update_bank(
    db: Session, *, bank_id: str, name: str | None = None,
    description: str | None = None, is_active: bool | None = None,
) -> QuestionBank:
    bank = get_bank(db, bank_id)
    if name is not None:
        bank.name = name
    if description is not None:
        bank.description = description
    if is_active is not None:
        bank.is_active = is_active
    db.commit()
    db.refresh(bank)
    return bank


# ─────────────────────────────────────────────────────────────────────────
# QUESTIONS
# ─────────────────────────────────────────────────────────────────────────

def add_question_to_assessment(
    db: Session, *, assessment_id: str, creator_id: str,
    question_type: str, text: str,
    options_json: list | None = None,
    correct_answer_json: dict | list | None = None,
    point_value: float = 1.0,
    order_index: int = 0,
    difficulty: str = "intermediate",
    topic_tags: list[str] | None = None,
    ai_draft_id: str | None = None,
    ai_generated_content: bool = False,
    ai_validation_status: str | None = None,
    ai_validation_notes: str | None = None,
) -> Question:
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id,
    ).first()
    if not assessment:
        raise QuestionError("Assessment not found.", 404)
    if assessment.status not in ("draft", "published"):
        raise QuestionError(
            f"Cannot add questions to assessment in status "
            f"'{assessment.status}'.", 409,
        )

    _validate_question_shape(question_type, options_json, correct_answer_json)
    if difficulty not in ALL_DIFFICULTIES:
        raise QuestionError(f"Unknown difficulty '{difficulty}'.", 400)

    q = Question(
        assessment_id=assessment_id,
        question_bank_id=None,
        question_type=question_type,
        text=text,
        options_json=options_json,
        correct_answer_json=correct_answer_json,
        point_value=point_value,
        order_index=order_index,
        difficulty=difficulty,
        topic_tags=topic_tags,
        ai_draft_id=ai_draft_id,
        ai_generated_content=ai_generated_content,
        ai_validation_status=ai_validation_status,
        ai_validation_notes=ai_validation_notes,
        created_by=creator_id,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def add_question_to_bank(
    db: Session, *, bank_id: str, creator_id: str,
    question_type: str, text: str, **kwargs,
) -> Question:
    _validate_question_shape(
        question_type,
        kwargs.get("options_json"),
        kwargs.get("correct_answer_json"),
    )
    q = Question(
        assessment_id=None,
        question_bank_id=bank_id,
        question_type=question_type,
        text=text,
        created_by=creator_id,
        **kwargs,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def clone_from_bank(
    db: Session, *, bank_id: str, assessment_id: str,
    creator_id: str, question_ids: list[str],
) -> list[Question]:
    """Clone selected questions from a bank into a specific assessment."""
    source_qs = db.query(Question).filter(
        Question.question_bank_id == bank_id,
        Question.id.in_(question_ids),
    ).all()
    if len(source_qs) != len(question_ids):
        raise QuestionError("Some questions not found in bank.", 404)

    # Determine next order_index
    max_order = db.query(Question).filter(
        Question.assessment_id == assessment_id,
    ).count()

    clones: list[Question] = []
    for i, src in enumerate(source_qs):
        clone = Question(
            assessment_id=assessment_id,
            question_bank_id=None,
            question_type=src.question_type,
            text=src.text,
            options_json=src.options_json,
            correct_answer_json=src.correct_answer_json,
            point_value=src.point_value,
            order_index=max_order + i,
            difficulty=src.difficulty,
            topic_tags=src.topic_tags,
            ai_draft_id=src.ai_draft_id,
            ai_generated_content=src.ai_generated_content,
            ai_validation_status=src.ai_validation_status,
            ai_validation_notes=src.ai_validation_notes,
            created_by=creator_id,
        )
        db.add(clone)
        clones.append(clone)
    db.commit()
    for c in clones:
        db.refresh(c)
    return clones


def get_question(db: Session, question_id: str) -> Question:
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise QuestionError("Question not found.", 404)
    return q


def list_assessment_questions(
    db: Session, assessment_id: str,
) -> list[Question]:
    return db.query(Question).filter(
        Question.assessment_id == assessment_id,
    ).order_by(Question.order_index).all()


def list_bank_questions(db: Session, bank_id: str) -> list[Question]:
    return db.query(Question).filter(
        Question.question_bank_id == bank_id,
    ).order_by(Question.created_at).all()


def update_question(
    db: Session, *, question_id: str, actor_id: str, **updates,
) -> Question:
    q = get_question(db, question_id)
    for key, value in updates.items():
        if value is not None and hasattr(q, key):
            setattr(q, key, value)
    db.commit()
    db.refresh(q)
    return q


def delete_question(db: Session, *, question_id: str, actor_id: str) -> None:
    q = get_question(db, question_id)
    # Only deletable in draft state
    if q.assessment_id:
        assessment = db.query(Assessment).filter(
            Assessment.id == q.assessment_id,
        ).first()
        if assessment and assessment.status != "draft":
            raise QuestionError(
                "Cannot delete questions from a published assessment.", 409,
            )
    db.delete(q)
    db.commit()


def reorder_questions(
    db: Session, *, assessment_id: str, ordered_question_ids: list[str],
) -> list[Question]:
    for idx, qid in enumerate(ordered_question_ids):
        q = db.query(Question).filter(
            Question.id == qid,
            Question.assessment_id == assessment_id,
        ).first()
        if q:
            q.order_index = idx
    db.commit()
    return list_assessment_questions(db, assessment_id)


def set_ai_validation(
    db: Session, *, question_id: str,
    status: str, notes: str | None = None,
) -> Question:
    if status not in (
        AI_VALIDATION_PASSED, AI_VALIDATION_FAILED, AI_VALIDATION_NEEDS_REVIEW,
    ):
        raise QuestionError(f"Unknown AI validation status '{status}'.", 400)
    q = get_question(db, question_id)
    q.ai_validation_status = status
    if notes is not None:
        q.ai_validation_notes = notes
    db.commit()
    db.refresh(q)
    return q