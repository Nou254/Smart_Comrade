"""
System-wide assessment catalog — Module 005.

Discovery surface for voluntary, public assessments. Only system-wide
assessments appear in the catalog.
"""
import logging
from sqlalchemy.orm import Session

from app.models.assessment import (
    Assessment, AssessmentCatalogEntry,
    MODE_SYSTEM_WIDE, STATUS_PUBLISHED, STATUS_IN_PROGRESS,
)


logger = logging.getLogger(__name__)


class CatalogError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def list_catalog(
    db: Session, *,
    unit_id: str | None = None,
    creator_id: str | None = None,
    creator_role: str | None = None,
    difficulty: str | None = None,
    category: str | None = None,
    min_rating: float | None = None,
    featured_only: bool = False,
    limit: int = 100,
) -> list[tuple[Assessment, AssessmentCatalogEntry]]:
    q = db.query(Assessment, AssessmentCatalogEntry).join(
        AssessmentCatalogEntry,
        AssessmentCatalogEntry.assessment_id == Assessment.id,
    ).filter(
        Assessment.assessment_mode == MODE_SYSTEM_WIDE,
        Assessment.status.in_((STATUS_PUBLISHED, STATUS_IN_PROGRESS)),
    )
    if creator_id:
        q = q.filter(Assessment.created_by == creator_id)
    if creator_role:
        q = q.filter(Assessment.created_by_role == creator_role)
    if category:
        q = q.filter(Assessment.category == category)
    if difficulty:
        q = q.filter(AssessmentCatalogEntry.difficulty == difficulty)
    if min_rating is not None:
        q = q.filter(
            AssessmentCatalogEntry.average_rating >= min_rating,
        )
    if featured_only:
        q = q.filter(AssessmentCatalogEntry.is_featured.is_(True))
    if unit_id:
        # Best effort — filter by primary_unit_id; specialty matches in V2
        q = q.filter(AssessmentCatalogEntry.primary_unit_id == unit_id)

    return q.order_by(
        AssessmentCatalogEntry.is_featured.desc(),
        AssessmentCatalogEntry.average_rating.desc().nulls_last(),
        Assessment.published_at.desc(),
    ).limit(limit).all()


def get_entry(
    db: Session, assessment_id: str,
) -> tuple[Assessment, AssessmentCatalogEntry]:
    row = db.query(Assessment, AssessmentCatalogEntry).join(
        AssessmentCatalogEntry,
        AssessmentCatalogEntry.assessment_id == Assessment.id,
    ).filter(Assessment.id == assessment_id).first()
    if not row:
        raise CatalogError("Catalog entry not found.", 404)
    return row


def record_view(db: Session, assessment_id: str) -> None:
    entry = db.query(AssessmentCatalogEntry).filter(
        AssessmentCatalogEntry.assessment_id == assessment_id,
    ).first()
    if entry:
        entry.view_count = (entry.view_count or 0) + 1
        db.commit()


def record_take(db: Session, assessment_id: str) -> None:
    entry = db.query(AssessmentCatalogEntry).filter(
        AssessmentCatalogEntry.assessment_id == assessment_id,
    ).first()
    if entry:
        entry.take_count = (entry.take_count or 0) + 1
        db.commit()


def record_rating(
    db: Session, assessment_id: str, rating: int,
) -> None:
    """Update the rolling average when a feedback row is created."""
    entry = db.query(AssessmentCatalogEntry).filter(
        AssessmentCatalogEntry.assessment_id == assessment_id,
    ).first()
    if not entry:
        return
    old_count = entry.rating_count or 0
    old_avg = entry.average_rating or 0.0
    new_count = old_count + 1
    new_avg = (old_avg * old_count + rating) / new_count
    entry.rating_count = new_count
    entry.average_rating = round(new_avg, 3)
    db.commit()


def set_featured(
    db: Session, assessment_id: str, featured: bool,
) -> AssessmentCatalogEntry:
    entry = db.query(AssessmentCatalogEntry).filter(
        AssessmentCatalogEntry.assessment_id == assessment_id,
    ).first()
    if not entry:
        raise CatalogError("Catalog entry not found.", 404)
    entry.is_featured = featured
    db.commit()
    db.refresh(entry)
    return entry