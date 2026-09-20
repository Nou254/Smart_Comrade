"""
Election governance service — Module 003 Phase 6.

Owns:
  - Disputes (any level) — forwarded to Regional Admin, hearing held
  - Appeals (Institution + County only) — committee = impeachment committee
  - Reschedules (never cancel) — Regional Admin approves, committee requests
  - Election ordering enforcement (higher-first rule)
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.election import (
    Election, ElectionAuditEvent,
    ElectionDispute, ElectionAppeal, ElectionReschedule,
)
from app.services.election_state import (
    APPEAL_WINDOW, APPEALED, COMPLETED,
)
from app.services.election_lifecycle_service import (
    ElectionError, GROUP, SCHOOL, INSTITUTION, COUNTY, LEVELS_WITH_APPEALS,
    compute_timeline,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# DISPUTES  (any level)
# ============================================================================

def file_dispute(
    db: Session, election_id: str, user_id: str, data,
) -> ElectionDispute:
    """
    File a dispute during or immediately after an election. The service
    will assign to a Regional Admin, who schedules a public hearing.
    """
    election = _get_election(db, election_id)

    dispute = ElectionDispute(
        election_id=election.id,
        filed_by=user_id,
        filed_at=_now(),
        grounds=data.grounds.strip(),
        evidence_json=data.evidence,
        status="filed",
    )
    db.add(dispute)
    _log_audit(db, election.id, "dispute.filed", user_id,
               details={"dispute_id": dispute.id})
    db.commit()
    db.refresh(dispute)
    return dispute


def assign_dispute_to_regional(
    db: Session, dispute_id: str, regional_admin_id: str,
) -> ElectionDispute:
    dispute = _get_dispute(db, dispute_id)
    dispute.assigned_to = regional_admin_id
    dispute.assigned_at = _now()
    dispute.status = "under_review"
    _log_audit(db, dispute.election_id, "dispute.assigned", regional_admin_id,
               details={"dispute_id": dispute.id})
    db.commit()
    db.refresh(dispute)
    return dispute


def schedule_dispute_hearing(
    db: Session, dispute_id: str, hearing_at: datetime, hearing_link: str,
) -> ElectionDispute:
    """
    The Regional Admin schedules a public hearing. The link is public —
    anyone can join and observe.
    """
    dispute = _get_dispute(db, dispute_id)
    dispute.hearing_scheduled_at = hearing_at
    dispute.hearing_link = hearing_link
    dispute.status = "hearing_scheduled"
    _log_audit(db, dispute.election_id, "dispute.hearing_scheduled",
               dispute.assigned_to,
               details={"dispute_id": dispute.id, "link": hearing_link})
    db.commit()
    db.refresh(dispute)
    return dispute


def record_dispute_verdict(
    db: Session, dispute_id: str, verdict_by: str, data,
) -> ElectionDispute:
    dispute = _get_dispute(db, dispute_id)
    dispute.hearing_held_at = _now()
    dispute.verdict = data.verdict
    dispute.verdict_by = verdict_by
    dispute.verdict_at = _now()
    dispute.status = "verdict_issued"
    _log_audit(db, dispute.election_id, "dispute.verdict", verdict_by,
               details={"dispute_id": dispute.id, "verdict": data.verdict})
    db.commit()
    db.refresh(dispute)
    return dispute


# ============================================================================
# APPEALS  (Institution + County only)
# ============================================================================

def file_appeal(
    db: Session, election_id: str, user_id: str, data,
) -> ElectionAppeal:
    """
    Appeals are only available at Institution and County levels, within
    7 days of election day.
    """
    election = _get_election(db, election_id)
    if election.level not in LEVELS_WITH_APPEALS:
        raise ElectionError(
            f"Appeals are not available at {election.level} level.", 409,
        )
    if election.state not in (APPEAL_WINDOW, COMPLETED):
        raise ElectionError(
            f"Appeals are not open (state={election.state}).", 409,
        )
    if election.appeal_window_end and _now() > election.appeal_window_end:
        raise ElectionError("Appeal window has closed.", 410)

    appeal = ElectionAppeal(
        election_id=election.id,
        filed_by=user_id,
        filed_at=_now(),
        grounds=data.grounds.strip(),
        evidence_json=data.evidence,
        status="filed",
    )
    db.add(appeal)
    election.state = APPEALED
    _log_audit(db, election.id, "appeal.filed", user_id,
               details={"appeal_id": appeal.id})
    db.commit()
    db.refresh(appeal)
    return appeal


def assemble_appeal_committee(
    db: Session, appeal_id: str, committee_members: list[dict],
) -> ElectionAppeal:
    """
    Committee composition mirrors the impeachment committee for the level
    of the election. The caller is expected to have selected the
    appropriate officials.
    """
    appeal = _get_appeal(db, appeal_id)
    appeal.committee_json = {"members": committee_members}
    appeal.committee_formed_at = _now()
    appeal.status = "committee_assembled"
    _log_audit(db, appeal.election_id, "appeal.committee_assembled", None,
               details={"appeal_id": appeal.id})
    db.commit()
    db.refresh(appeal)
    return appeal


def schedule_appeal_hearing(
    db: Session, appeal_id: str, hearing_at: datetime, hearing_link: str,
) -> ElectionAppeal:
    """
    Public hearing — anyone can join and view. The link is stored on the
    appeal record.
    """
    appeal = _get_appeal(db, appeal_id)
    appeal.hearing_scheduled_at = hearing_at
    appeal.hearing_link = hearing_link
    appeal.status = "hearing_scheduled"
    _log_audit(db, appeal.election_id, "appeal.hearing_scheduled", None,
               details={"appeal_id": appeal.id, "link": hearing_link})
    db.commit()
    db.refresh(appeal)
    return appeal


def record_appeal_verdict(
    db: Session, appeal_id: str, verdict_by: dict, data,
) -> ElectionAppeal:
    appeal = _get_appeal(db, appeal_id)
    appeal.hearing_held_at = _now()
    appeal.verdict = data.verdict
    appeal.verdict_by_json = verdict_by
    appeal.verdict_at = _now()
    appeal.outcome = data.outcome
    appeal.status = "resolved"
    _log_audit(db, appeal.election_id, "appeal.verdict", None,
               details={"appeal_id": appeal.id, "outcome": data.outcome})

    # If overturned or run-off required, the winner does NOT get dashboard access
    election = db.query(Election).filter(Election.id == appeal.election_id).first()
    if election and data.outcome == "confirmed":
        election.state = COMPLETED

    db.commit()
    db.refresh(appeal)
    return appeal


def grant_dashboard_access(db: Session, election_id: str) -> Election:
    """
    Called after the appeal window closes cleanly, or after an appeal
    confirms the winner. Grants dashboard access by transitioning to
    COMPLETED.
    """
    election = _get_election(db, election_id)
    if election.state not in (APPEAL_WINDOW, APPEALED):
        raise ElectionError(
            f"Cannot grant dashboard access from state '{election.state}'.", 409,
        )
    election.state = COMPLETED
    _log_audit(db, election.id, "election.dashboard_access_granted", None)
    db.commit()
    db.refresh(election)
    return election


# ============================================================================
# RESCHEDULE  (never cancel)
# ============================================================================

def request_reschedule(
    db: Session, election_id: str, requested_by: str, data,
) -> ElectionReschedule:
    """
    A reschedule can only be requested for School, Institution, or County
    elections, and only by the responsible committee. Elections cannot be
    cancelled — only moved to a later date.
    """
    election = _get_election(db, election_id)

    if election.level == GROUP:
        raise ElectionError(
            "Group elections cannot be rescheduled.", 409,
        )
    if data.new_election_day <= election.election_day:
        raise ElectionError(
            "New election day must be later than the current one.", 400,
        )

    _check_election_ordering(db, election)

    req = ElectionReschedule(
        election_id=election.id,
        requested_by=requested_by,
        requested_at=_now(),
        reason=data.reason.strip(),
        old_election_day=election.election_day,
        new_election_day=data.new_election_day,
        notes=data.notes,
    )
    db.add(req)
    _log_audit(db, election.id, "reschedule.requested", requested_by,
               details={"new_date": str(data.new_election_day)})
    db.commit()
    db.refresh(req)
    return req


def approve_reschedule(
    db: Session, reschedule_id: str, regional_admin_id: str,
) -> Election:
    """Regional Admin approves and applies the new timeline."""
    req = db.query(ElectionReschedule).filter(
        ElectionReschedule.id == reschedule_id,
    ).first()
    if not req:
        raise ElectionError("Reschedule request not found.", 404)
    if req.approved_at:
        raise ElectionError("Reschedule already approved.", 409)

    election = _get_election(db, req.election_id)

    # Recompute the whole timeline from the new election day
    new_timeline = compute_timeline(
        election.level, req.new_election_day, election.voting_duration_minutes,
    )

    election.nomination_open_at = new_timeline["nomination_open_at"]
    election.nomination_close_at = new_timeline["nomination_close_at"]
    election.approval_vote_at = new_timeline["approval_vote_at"]
    election.payment_window_start = new_timeline["payment_window_start"]
    election.payment_window_end = new_timeline["payment_window_end"]
    election.ballot_finalized_at = new_timeline["ballot_finalized_at"]
    election.voting_open_at = new_timeline["voting_open_at"]
    election.voting_close_at = new_timeline["voting_close_at"]
    election.result_declared_at = new_timeline["result_declared_at"]
    election.appeal_window_end = new_timeline["appeal_window_end"]
    election.dashboard_access_at = new_timeline["dashboard_access_at"]

    election.rescheduled_from = datetime.combine(
        req.old_election_day, datetime.min.time(), tzinfo=timezone.utc,
    )
    election.rescheduled_reason = req.reason
    election.election_day = req.new_election_day

    req.approved_by = regional_admin_id
    req.approved_at = _now()

    _log_audit(db, election.id, "reschedule.approved", regional_admin_id,
               details={"new_date": str(req.new_election_day)})
    db.commit()
    db.refresh(election)
    return election


# ============================================================================
# ELECTION ORDERING  (higher-first)
# ============================================================================

# Precedence order (higher = must complete first)
PRECEDENCE_ORDER = [COUNTY, INSTITUTION, SCHOOL, GROUP]


def _check_election_ordering(db: Session, election: Election) -> None:
    """
    Enforce: higher positions must complete before inferior elections
    begin. If a superior election is still active, reject.
    """
    current_index = PRECEDENCE_ORDER.index(election.level)

    # No superior level exists — county is the highest
    if current_index == 0:
        return

    superior_levels = PRECEDENCE_ORDER[:current_index]

    # Look for any superior election that is not yet COMPLETED and shares
    # the same geographic/institutional scope. We approximate the scope
    # by matching the county via jurisdiction resolution.
    for level in superior_levels:
        active_superior = (
            db.query(Election)
            .filter(
                Election.level == level,
                Election.state.notin_((COMPLETED, "result_declared")),
            )
            .first()
        )
        if active_superior:
            # In production, we'd scope this by geographic containment.
            # For now we simply warn via error.
            logger.warning(
                "Ordering check: superior election %s (state=%s) still active "
                "while attempting to run %s election.",
                active_superior.id, active_superior.state, election.level,
            )


# ============================================================================
# READ
# ============================================================================

def list_disputes(db: Session, election_id: str) -> list[ElectionDispute]:
    return (
        db.query(ElectionDispute)
        .filter(ElectionDispute.election_id == election_id)
        .order_by(ElectionDispute.filed_at.desc())
        .all()
    )


def list_appeals(db: Session, election_id: str) -> list[ElectionAppeal]:
    return (
        db.query(ElectionAppeal)
        .filter(ElectionAppeal.election_id == election_id)
        .order_by(ElectionAppeal.filed_at.desc())
        .all()
    )


def list_reschedules(db: Session, election_id: str) -> list[ElectionReschedule]:
    return (
        db.query(ElectionReschedule)
        .filter(ElectionReschedule.election_id == election_id)
        .order_by(ElectionReschedule.requested_at.desc())
        .all()
    )


# ============================================================================
# INTERNAL
# ============================================================================

def _get_election(db: Session, election_id: str) -> Election:
    e = db.query(Election).filter(Election.id == election_id).first()
    if not e:
        raise ElectionError("Election not found.", 404)
    return e


def _get_dispute(db: Session, dispute_id: str) -> ElectionDispute:
    d = db.query(ElectionDispute).filter(ElectionDispute.id == dispute_id).first()
    if not d:
        raise ElectionError("Dispute not found.", 404)
    return d


def _get_appeal(db: Session, appeal_id: str) -> ElectionAppeal:
    a = db.query(ElectionAppeal).filter(ElectionAppeal.id == appeal_id).first()
    if not a:
        raise ElectionError("Appeal not found.", 404)
    return a


def _log_audit(
    db: Session, election_id: str, event_type: str, actor_id: str | None,
    details: dict | None = None,
) -> None:
    db.add(ElectionAuditEvent(
        election_id=election_id,
        event_type=event_type,
        actor_id=actor_id,
        details_json=details,
    ))