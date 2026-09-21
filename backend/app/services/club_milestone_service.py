"""
Club milestone service — Module 003 Phase 10.

Flow:
  declare (founder/leader) → period runs → report submitted
    → Institution Rep approves → forward to Regional Rep
    → Regional Rep accepts → milestone status = evaluated
"""
import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.activity_club import (
    ActivityClub, ActivityClubMilestone, ActivityClubMilestoneReport,
    ActivityClubMembership,
)
from app.services.club_audit_service import log_club_event


logger = logging.getLogger(__name__)


class ClubMilestoneError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# DECLARE
# ─────────────────────────────────────────────────────────────────────────

def declare_milestone(
    db: Session, club_id: str, actor_id: str, data,
) -> ActivityClubMilestone:
    club = _get_club(db, club_id)
    _assert_leader(db, club, actor_id)

    if data.period_start >= data.period_end:
        raise ClubMilestoneError(
            "period_start must be before period_end.", 400,
        )

    m = ActivityClubMilestone(
        club_id=club.id,
        title=data.title.strip(),
        description=data.description,
        period_start=data.period_start,
        period_end=data.period_end,
        target_metric=data.target_metric.strip(),
        target_value=data.target_value,
        target_unit=data.target_unit,
        status="declared",
        declared_by=actor_id,
        declared_at=_now(),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def update_milestone(
    db: Session, milestone_id: str, actor_id: str, data,
) -> ActivityClubMilestone:
    m = _get_milestone(db, milestone_id)
    if m.status in ("evaluated", "missed"):
        raise ClubMilestoneError(
            "Cannot edit a milestone after it has been evaluated.", 409,
        )
    club = _get_club(db, m.club_id)
    _assert_leader(db, club, actor_id)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(m, field, value)

    db.commit()
    db.refresh(m)
    return m


# ─────────────────────────────────────────────────────────────────────────
# REPORT SUBMISSION
# ─────────────────────────────────────────────────────────────────────────

def submit_milestone_report(
    db: Session, milestone_id: str, actor_id: str, data,
) -> ActivityClubMilestoneReport:
    m = _get_milestone(db, milestone_id)
    if m.status not in ("declared", "active", "report_pending"):
        raise ClubMilestoneError(
            f"Milestone is not reportable (status={m.status}).", 409,
        )
    club = _get_club(db, m.club_id)
    _assert_leader(db, club, actor_id)

    existing = db.query(ActivityClubMilestoneReport).filter(
        ActivityClubMilestoneReport.milestone_id == m.id,
    ).first()
    if existing:
        raise ClubMilestoneError(
            "A report already exists for this milestone.", 409,
        )

    r = ActivityClubMilestoneReport(
        club_id=club.id,
        milestone_id=m.id,
        actual_value=data.actual_value,
        actual_unit=data.actual_unit,
        outcome_note=data.outcome_note.strip(),
        completion_pdf_url=data.completion_pdf_url,
        completion_pdf_hash=data.completion_pdf_hash,
        supporting_urls_json=data.supporting_urls,
        status="submitted",
        submitted_by=actor_id,
        submitted_at=_now(),
    )
    db.add(r)
    db.flush()

    m.status = "reported"
    m.report_id = r.id

    log_club_event(
        db, club.id, "club.milestone_report_submitted", actor_id=actor_id,
        details={"milestone_id": m.id, "report_id": r.id},
    )
    db.commit()
    db.refresh(r)
    return r


# ─────────────────────────────────────────────────────────────────────────
# INSTITUTION REP REVIEW
# ─────────────────────────────────────────────────────────────────────────

def institution_rep_review_report(
    db: Session, report_id: str, actor_id: str, data,
) -> ActivityClubMilestoneReport:
    r = db.query(ActivityClubMilestoneReport).filter(
        ActivityClubMilestoneReport.id == report_id,
    ).first()
    if not r:
        raise ClubMilestoneError("Milestone report not found.", 404)
    if r.status != "submitted":
        raise ClubMilestoneError(
            f"Report is not awaiting Institution Rep review "
            f"(status={r.status}).", 409,
        )

    r.institution_rep_id = actor_id
    r.institution_rep_decided_at = _now()
    r.institution_rep_notes = data.notes

    if data.approve:
        r.status = "institution_approved"
        r.institution_rep_report_url = data.institution_rep_report_url
    else:
        r.status = "institution_rejected"

    m = db.query(ActivityClubMilestone).filter(
        ActivityClubMilestone.id == r.milestone_id,
    ).first()
    if m and data.approve:
        m.status = "report_pending"

    log_club_event(
        db, r.club_id,
        "club.milestone_report_institution_approved" if data.approve
        else "club.milestone_report_institution_rejected",
        actor_id=actor_id,
        details={"report_id": r.id, "notes": data.notes},
    )
    db.commit()
    db.refresh(r)
    return r


# ─────────────────────────────────────────────────────────────────────────
# REGIONAL REP FORWARDING
# ─────────────────────────────────────────────────────────────────────────

def forward_to_regional(
    db: Session, report_id: str, actor_id: str,
    notes: str | None = None,
) -> ActivityClubMilestoneReport:
    """
    Called by the Institution Rep or a scheduled job once their report
    is written. Marks the report forwarded to Regional Rep and stamps
    cc notifications for County Rep + Super Admin.
    """
    r = db.query(ActivityClubMilestoneReport).filter(
        ActivityClubMilestoneReport.id == report_id,
    ).first()
    if not r:
        raise ClubMilestoneError("Milestone report not found.", 404)
    if r.status != "institution_approved":
        raise ClubMilestoneError(
            "Institution Rep approval is required before forwarding.", 409,
        )

    now = _now()
    r.status = "regional_forwarded"
    r.regional_rep_id = actor_id
    r.regional_rep_received_at = now
    r.regional_rep_notes = notes
    r.cc_county_rep_notified_at = now
    r.cc_super_admin_notified_at = now

    m = db.query(ActivityClubMilestone).filter(
        ActivityClubMilestone.id == r.milestone_id,
    ).first()
    if m:
        m.status = "evaluated"

    log_club_event(
        db, r.club_id, "club.milestone_report_regional_forwarded",
        actor_id=actor_id,
        details={"report_id": r.id, "notes": notes},
    )
    db.commit()
    db.refresh(r)
    return r


def close_report(
    db: Session, report_id: str, actor_id: str,
) -> ActivityClubMilestoneReport:
    r = db.query(ActivityClubMilestoneReport).filter(
        ActivityClubMilestoneReport.id == report_id,
    ).first()
    if not r:
        raise ClubMilestoneError("Milestone report not found.", 404)
    if r.status != "regional_forwarded":
        raise ClubMilestoneError(
            "Only forwarded reports can be closed.", 409,
        )
    r.status = "closed"
    log_club_event(
        db, r.club_id, "club.milestone_report_closed", actor_id=actor_id,
        details={"report_id": r.id},
    )
    db.commit()
    db.refresh(r)
    return r


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def list_milestones(
    db: Session, club_id: str, status: str | None = None,
) -> list[ActivityClubMilestone]:
    q = db.query(ActivityClubMilestone).filter(
        ActivityClubMilestone.club_id == club_id,
    )
    if status:
        q = q.filter(ActivityClubMilestone.status == status)
    return q.order_by(ActivityClubMilestone.period_start).all()


def list_reports(
    db: Session, club_id: str, status: str | None = None,
) -> list[ActivityClubMilestoneReport]:
    q = db.query(ActivityClubMilestoneReport).filter(
        ActivityClubMilestoneReport.club_id == club_id,
    )
    if status:
        q = q.filter(ActivityClubMilestoneReport.status == status)
    return q.order_by(ActivityClubMilestoneReport.submitted_at.desc()).all()


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _get_club(db: Session, club_id: str) -> ActivityClub:
    c = db.query(ActivityClub).filter(ActivityClub.id == club_id).first()
    if not c:
        raise ClubMilestoneError("Club not found.", 404)
    return c


def _get_milestone(db: Session, milestone_id: str) -> ActivityClubMilestone:
    m = db.query(ActivityClubMilestone).filter(
        ActivityClubMilestone.id == milestone_id,
    ).first()
    if not m:
        raise ClubMilestoneError("Milestone not found.", 404)
    return m


def _assert_leader(db: Session, club: ActivityClub, actor_id: str) -> None:
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club.id,
        ActivityClubMembership.user_id == actor_id,
        ActivityClubMembership.status == "active",
    ).first()
    if not m or m.role != "leader":
        raise ClubMilestoneError(
            "Only the elected leader may perform this action.", 403,
        )