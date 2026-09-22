"""
Unit issue lifecycle + escalation — Module 004.

Reps raise issues. Non-reps see public summaries + outcomes.
Escalation follows the defined ladder.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.unit_offering import UnitOffering
from app.models.unit_representation import (
    UnitIssue, UnitIssueEscalation, UnitRepresentative,
    REP_ACTIVE,
    ISSUE_IDENTIFIED, ISSUE_UNDER_NETWORK_DISCUSSION, ISSUE_ESCALATED,
    ISSUE_UNDER_REVIEW, ISSUE_RESOLVED, ISSUE_DISMISSED, ISSUE_WITHDRAWN,
    ISSUE_CATEGORIES,
    LEVEL_NETWORK, LEVEL_SUPERVISOR, LEVEL_LECTURER, LEVEL_SCHOOL,
    LEVEL_INSTITUTION,
    ALL_ESCALATION_LEVELS,
)


logger = logging.getLogger(__name__)


class UnitIssueError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────

def create_issue(
    db: Session,
    *,
    unit_offering_id: str,
    raised_by_user_id: str,
    category: str,
    title: str,
    description: str,
    is_anonymous: bool = False,
    anonymous_student_reference: str | None = None,
    is_public: bool = True,
    public_summary: str | None = None,
) -> UnitIssue:
    """
    Raise an issue. Must be raised by an active rep for this offering.
    """
    if category not in ISSUE_CATEGORIES:
        raise UnitIssueError(f"Invalid category '{category}'.", 400)

    offering = db.query(UnitOffering).filter(
        UnitOffering.id == unit_offering_id,
    ).first()
    if not offering:
        raise UnitIssueError("Unit offering not found.", 404)

    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.user_id == raised_by_user_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if not rep:
        raise UnitIssueError(
            "Only active Unit Representatives may raise unit issues.", 403,
        )

    issue = UnitIssue(
        unit_offering_id=unit_offering_id,
        raised_by_representative_id=rep.id,
        raised_by_user_id=raised_by_user_id,
        is_anonymous=is_anonymous,
        anonymous_student_reference=anonymous_student_reference,
        category=category,
        title=title,
        description=description,
        status=ISSUE_IDENTIFIED,
        current_escalation_level=LEVEL_NETWORK,
        is_public=is_public,
        public_summary=public_summary,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


# ─────────────────────────────────────────────────────────────────────────
# ESCALATION
# ─────────────────────────────────────────────────────────────────────────

def escalate_issue(
    db: Session,
    *,
    issue_id: str,
    to_level: str,
    actor_id: str,
    notes: str | None = None,
) -> UnitIssue:
    """
    Move the issue up the ladder. Only an active rep for the offering
    (or the current escalation target) may escalate.
    """
    if to_level not in ALL_ESCALATION_LEVELS:
        raise UnitIssueError(f"Invalid escalation level '{to_level}'.", 400)

    issue = db.query(UnitIssue).filter(UnitIssue.id == issue_id).first()
    if not issue:
        raise UnitIssueError("Issue not found.", 404)

    if issue.status in (ISSUE_RESOLVED, ISSUE_DISMISSED, ISSUE_WITHDRAWN):
        raise UnitIssueError(
            f"Cannot escalate an issue in status '{issue.status}'.", 409,
        )

    from_level = issue.current_escalation_level
    if from_level == to_level:
        raise UnitIssueError(
            f"Issue is already at level '{to_level}'.", 409,
        )

    # Record the escalation
    esc = UnitIssueEscalation(
        issue_id=issue.id,
        from_level=from_level,
        to_level=to_level,
        escalated_by_user_id=actor_id,
        escalated_at=_now(),
        notes=notes,
    )
    db.add(esc)

    issue.current_escalation_level = to_level
    issue.status = ISSUE_ESCALATED
    if to_level == LEVEL_SUPERVISOR:
        issue.status = ISSUE_UNDER_REVIEW

    db.commit()
    db.refresh(issue)
    return issue


# ─────────────────────────────────────────────────────────────────────────
# RESOLUTION
# ─────────────────────────────────────────────────────────────────────────

def resolve_issue(
    db: Session,
    *,
    issue_id: str,
    actor_id: str,
    resolution_notes: str,
) -> UnitIssue:
    issue = db.query(UnitIssue).filter(UnitIssue.id == issue_id).first()
    if not issue:
        raise UnitIssueError("Issue not found.", 404)

    issue.status = ISSUE_RESOLVED
    issue.resolved_at = _now()
    issue.resolution_notes = resolution_notes
    db.commit()
    db.refresh(issue)
    return issue


def dismiss_issue(
    db: Session,
    *,
    issue_id: str,
    actor_id: str,
    resolution_notes: str,
) -> UnitIssue:
    issue = db.query(UnitIssue).filter(UnitIssue.id == issue_id).first()
    if not issue:
        raise UnitIssueError("Issue not found.", 404)

    issue.status = ISSUE_DISMISSED
    issue.resolved_at = _now()
    issue.resolution_notes = resolution_notes
    db.commit()
    db.refresh(issue)
    return issue


def withdraw_issue(
    db: Session,
    *,
    issue_id: str,
    actor_id: str,
) -> UnitIssue:
    """The original raiser withdraws the issue."""
    issue = db.query(UnitIssue).filter(UnitIssue.id == issue_id).first()
    if not issue:
        raise UnitIssueError("Issue not found.", 404)
    if issue.raised_by_user_id != actor_id:
        raise UnitIssueError(
            "Only the rep who raised the issue may withdraw it.", 403,
        )
    issue.status = ISSUE_WITHDRAWN
    issue.resolved_at = _now()
    db.commit()
    db.refresh(issue)
    return issue


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_issue(db: Session, issue_id: str) -> UnitIssue:
    issue = db.query(UnitIssue).filter(UnitIssue.id == issue_id).first()
    if not issue:
        raise UnitIssueError("Issue not found.", 404)
    return issue


def list_issues(
    db: Session,
    *,
    unit_offering_id: str,
    status: str | None = None,
    category: str | None = None,
    limit: int = 200,
) -> list[UnitIssue]:
    q = db.query(UnitIssue).filter(
        UnitIssue.unit_offering_id == unit_offering_id,
    )
    if status:
        q = q.filter(UnitIssue.status == status)
    if category:
        q = q.filter(UnitIssue.category == category)
    return q.order_by(UnitIssue.created_at.desc()).limit(limit).all()


def list_public_issues(
    db: Session,
    *,
    unit_offering_id: str,
    limit: int = 200,
) -> list[UnitIssue]:
    """Non-rep view — only public issues."""
    return db.query(UnitIssue).filter(
        UnitIssue.unit_offering_id == unit_offering_id,
        UnitIssue.is_public.is_(True),
    ).order_by(UnitIssue.created_at.desc()).limit(limit).all()


def list_escalations(
    db: Session, issue_id: str,
) -> list[UnitIssueEscalation]:
    return db.query(UnitIssueEscalation).filter(
        UnitIssueEscalation.issue_id == issue_id,
    ).order_by(UnitIssueEscalation.escalated_at).all()