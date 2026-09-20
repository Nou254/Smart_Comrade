"""
Election lifecycle service — Module 003 Phase 6.

Owns election creation, timeline computation, state transitions,
live-stream lifecycle, and result-after-suspense transitions.

Timeline rules:
  Group (7-day cycle, election_day = day 4):
    day 1  → nomination open
    day 2  → nomination close (approval threshold irrelevant — no fee)
    day 3  → campaigning
    day 4  → voting (12h, 06:00–18:00)
    day 5  → result_declared
    day 6  → dashboard access (or tie-break if tie)
    day 7  → tie-break resolution

  School/Institution/County (14-day cycle, election_day = E):
    E−14 → nomination open
    E−7  → nomination close + approval vote + payment window open
    E−4  → payment window close + ballot finalized
    E−4..E → campaigning
    E    → voting (School 24h; Institution 12h; County 24h)
    E+1  → result_declared (after counting)
    E+7  → appeal window end (Institution / County only)
    E+8  → dashboard access
"""
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.election import (
    Election, ElectionPosition, ElectionAuditEvent,
)
from app.services.election_state import (
    ALL_STATES, DRAFT, SCHEDULED, NOMINATING, NOMINATIONAL_VOTING,
    PAYMENT_WINDOW, AWAITING_PAYMENT, REGIONAL_ADMIN_INTERIM,
    BALLOT_FINALIZED, CAMPAIGNING, VOTING, COUNTING,
    SUSPENSE_BLACKOUT, RESULT_DECLARED, RUN_OFF_SCHEDULED,
    RUN_OFF_VOTING, APPEAL_WINDOW, APPEALED, DISPUTED, COMPLETED,
    can_transition, InvalidStateTransition,
)

logger = logging.getLogger(__name__)


# ============================================================================
# LEVEL CONSTANTS
# ============================================================================

GROUP = "group"
SCHOOL = "school"
INSTITUTION = "institution"
COUNTY = "county"

LEVELS_WITH_FEE = {SCHOOL, INSTITUTION, COUNTY}
LEVELS_WITH_APPEALS = {INSTITUTION, COUNTY}

# Fee per level (KSh). Confirmed by the user in Phase 6 design.
FEE_TABLE = {
    GROUP: 0,
    SCHOOL: 100,
    INSTITUTION: 150,
    COUNTY: 300,
}

# Voting window durations in minutes
VOTING_DURATION_TABLE = {
    GROUP: 720,        # 12h
    SCHOOL: 1440,      # 24h
    INSTITUTION: 720,  # 12h
    COUNTY: 1440,      # 24h
}

# Election day-of-cycle → offset in days from "cycle start" (nomination open).
# For group, nomination opens day 1; for higher levels it opens E−14.
GROUP_NOMINATION_OPEN_OFFSET = 0
GROUP_NOMINATION_CLOSE_OFFSET = 1
GROUP_CAMPAIGNING_OFFSET = 2
GROUP_VOTING_OFFSET = 3
GROUP_RESULT_OFFSET = 4
GROUP_DASHBOARD_OFFSET = 5
GROUP_RUNOFF_OFFSET = 6

HIGHER_NOMINATION_OPEN_OFFSET = -14
HIGHER_NOMINATION_CLOSE_OFFSET = -7
HIGHER_PAYMENT_WINDOW_END_OFFSET = -4
HIGHER_BALLOT_FINALIZED_OFFSET = -3
HIGHER_RESULT_OFFSET = 1
HIGHER_APPEAL_WINDOW_END_OFFSET = 7
HIGHER_DASHBOARD_OFFSET = 8

SUSPENSE_WINDOW_HOURS = 2


class ElectionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# TIMELINE COMPUTATION
# ============================================================================

def compute_timeline(
    level: str, election_day: date, voting_duration_minutes: int | None = None,
) -> dict:
    """
    Return a dict of timeline datetimes (all UTC) for the given level
    and election day. `voting_duration_minutes` overrides the level
    default when provided.
    """
    if level == GROUP:
        return _compute_group_timeline(election_day)
    return _compute_higher_timeline(
        level, election_day, voting_duration_minutes,
    )


def _compute_group_timeline(election_day: date) -> dict:
    # Cycle: day 1 = election_day − 3
    day1 = election_day - timedelta(days=3)

    def _at(d: date, hh: int, mm: int = 0) -> datetime:
        return datetime.combine(d, time(hh, mm), tzinfo=timezone.utc)

    return {
        "nomination_open_at": _at(day1, 0, 0),
        "nomination_close_at": _at(day1 + timedelta(days=1), 23, 59),
        "approval_vote_at": None,             # no fee
        "payment_window_start": None,
        "payment_window_end": None,
        "ballot_finalized_at": _at(day1 + timedelta(days=2), 0, 0),
        "voting_open_at": _at(election_day, 6, 0),
        "voting_close_at": _at(election_day, 18, 0),
        "result_declared_at": _at(election_day + timedelta(days=1), 12, 0),
        "appeal_window_end": None,
        "dashboard_access_at": _at(election_day + timedelta(days=2), 0, 0),
        "voting_duration_minutes": 720,
    }


def _compute_higher_timeline(
    level: str, election_day: date, voting_duration_minutes: int | None,
) -> dict:
    duration = voting_duration_minutes or VOTING_DURATION_TABLE.get(level, 1440)

    def _at(offset: int, hh: int, mm: int = 0) -> datetime:
        return datetime.combine(
            election_day + timedelta(days=offset),
            time(hh, mm), tzinfo=timezone.utc,
        )

    # Voting opens at 06:00 if duration ≤ 12h, else 00:00.
    voting_open_hour = 6 if duration <= 720 else 0

    # Result declared one day after E, at noon.
    result_at = _at(HIGHER_RESULT_OFFSET, 12, 0)

    # Appeal window only for Institution and County.
    if level in LEVELS_WITH_APPEALS:
        appeal_end = _at(HIGHER_APPEAL_WINDOW_END_OFFSET, 23, 59)
        dashboard_at = _at(HIGHER_DASHBOARD_OFFSET, 0, 0)
    else:
        appeal_end = None
        dashboard_at = _at(HIGHER_RESULT_OFFSET + 1, 0, 0)

    return {
        "nomination_open_at": _at(HIGHER_NOMINATION_OPEN_OFFSET, 0, 0),
        "nomination_close_at": _at(HIGHER_NOMINATION_CLOSE_OFFSET, 23, 59),
        "approval_vote_at": _at(HIGHER_NOMINATION_CLOSE_OFFSET, 0, 0),
        "payment_window_start": _at(HIGHER_NOMINATION_CLOSE_OFFSET, 0, 0),
        "payment_window_end": _at(HIGHER_PAYMENT_WINDOW_END_OFFSET, 23, 59),
        "ballot_finalized_at": _at(HIGHER_BALLOT_FINALIZED_OFFSET, 0, 0),
        "voting_open_at": _at(0, voting_open_hour, 0),
        "voting_close_at": (
            _at(0, voting_open_hour, 0) + timedelta(minutes=duration)
        ),
        "result_declared_at": result_at,
        "appeal_window_end": appeal_end,
        "dashboard_access_at": dashboard_at,
        "voting_duration_minutes": duration,
    }


# ============================================================================
# DEFAULT POSITIONS PER LEVEL
# ============================================================================

def _default_positions_for_level(level: str) -> list[dict]:
    """
    Return the list of positions to create for a new election at the
    given level. Each entry is (position_code, title, is_paired,
    paired_with_code).
    """
    if level == GROUP:
        return [
            {
                "position_code": "group_leader",
                "title": "Group Leader",
                "is_paired": True,
                "paired_with_code": "group_secretary",
            },
            {
                "position_code": "group_secretary",
                "title": "Group Secretary",
                "is_paired": True,
                "paired_with_code": "group_leader",
            },
            {
                "position_code": "group_treasurer",
                "title": "Group Treasurer",
                "is_paired": False,
                "paired_with_code": None,
            },
        ]

    if level == SCHOOL:
        return [
            {
                "position_code": "school_representative",
                "title": "School Representative",
                "is_paired": True,
                "paired_with_code": "assistant_school_rep",
            },
            {
                "position_code": "assistant_school_rep",
                "title": "Assistant School Representative",
                "is_paired": True,
                "paired_with_code": "school_representative",
            },
        ]

    if level == INSTITUTION:
        return [
            {
                "position_code": "institution_representative",
                "title": "Institution Representative",
                "is_paired": True,
                "paired_with_code": "assistant_institution_rep",
            },
            {
                "position_code": "assistant_institution_rep",
                "title": "Assistant Institution Representative",
                "is_paired": True,
                "paired_with_code": "institution_representative",
            },
        ]

    if level == COUNTY:
        return [
            {
                "position_code": "county_representative",
                "title": "County Representative",
                "is_paired": True,
                "paired_with_code": "assistant_county_rep",
            },
            {
                "position_code": "assistant_county_rep",
                "title": "Assistant County Representative",
                "is_paired": True,
                "paired_with_code": "county_representative",
            },
        ]

    raise ElectionError(f"Unknown level '{level}'.", 400)


# ============================================================================
# CREATE
# ============================================================================

def create_election(db: Session, data, actor_id: str) -> Election:
    if data.level not in {GROUP, SCHOOL, INSTITUTION, COUNTY}:
        raise ElectionError(f"Invalid level '{data.level}'.", 400)

    timeline = compute_timeline(
        data.level, data.election_day,
        getattr(data, "voting_duration_minutes", None),
    )

    election = Election(
        title=data.title.strip(),
        description=data.description,
        level=data.level,
        constituency_id=data.constituency_id,
        state=DRAFT,
        election_day=data.election_day,
        nomination_open_at=timeline["nomination_open_at"],
        nomination_close_at=timeline["nomination_close_at"],
        approval_vote_at=timeline["approval_vote_at"],
        payment_window_start=timeline["payment_window_start"],
        payment_window_end=timeline["payment_window_end"],
        ballot_finalized_at=timeline["ballot_finalized_at"],
        voting_open_at=timeline["voting_open_at"],
        voting_close_at=timeline["voting_close_at"],
        result_declared_at=timeline["result_declared_at"],
        appeal_window_end=timeline["appeal_window_end"],
        dashboard_access_at=timeline["dashboard_access_at"],
        voting_duration_minutes=timeline["voting_duration_minutes"],
        created_by=actor_id,
        notes=data.notes,
    )
    db.add(election)
    db.flush()

    fee = FEE_TABLE[data.level]
    for pos in _default_positions_for_level(data.level):
        db.add(ElectionPosition(
            election_id=election.id,
            position_code=pos["position_code"],
            title=pos["title"],
            is_paired=pos["is_paired"],
            paired_with_code=pos["paired_with_code"],
            max_candidates=2,
            seats_available=1,
            required_approval_percentage=15.0,
            nomination_fee=fee,
            currency="KES",
            status="pending",
        ))

    _log_audit(
        db, election.id, "election.created", actor_id,
        to_state=DRAFT,
        details={"level": data.level, "election_day": str(data.election_day)},
    )
    db.commit()
    db.refresh(election)
    return election


def schedule_election(db: Session, election_id: str, actor_id: str) -> Election:
    """Move from draft to scheduled. Nominations will open at the computed time."""
    return transition_state(db, election_id, SCHEDULED, actor_id)


# ============================================================================
# STATE TRANSITIONS
# ============================================================================

def transition_state(
    db: Session, election_id: str, to_state: str, actor_id: str | None,
    reason: str | None = None,
) -> Election:
    election = _get(db, election_id)
    from_state = election.state

    if to_state not in ALL_STATES:
        raise ElectionError(f"Unknown state '{to_state}'.", 400)

    try:
        can_transition(from_state, to_state)
    except InvalidStateTransition:
        raise ElectionError(
            f"Illegal transition {from_state} → {to_state}.", 409,
        )

    election.state = to_state

    # Stamp commonly-used timestamps
    now = _now()
    if to_state == BALLOT_FINALIZED and not election.ballot_finalized_at:
        election.ballot_finalized_at = now
    if to_state == RESULT_DECLARED and not election.result_declared_at:
        election.result_declared_at = now

    _log_audit(
        db, election.id, f"state.{to_state}", actor_id,
        from_state=from_state, to_state=to_state,
        details={"reason": reason} if reason else None,
    )
    db.commit()
    db.refresh(election)
    return election


def close_voting_window(db: Session, election_id: str, actor_id: str | None = None) -> Election:
    """
    Called at the scheduled voting close time (or manually by the service
    that runs the timer). Moves the election to COUNTING.
    """
    election = _get(db, election_id)
    if election.state != VOTING:
        raise ElectionError(
            f"Cannot close voting in state '{election.state}'.", 409,
        )
    return transition_state(db, election_id, COUNTING, actor_id,
                            reason="Voting window closed.")


# ============================================================================
# LIVE STREAM
# ============================================================================

def start_live_stream(db: Session, election_id: str, stream_url: str) -> Election:
    election = _get(db, election_id)
    if election.state not in (COUNTING, VOTING):
        raise ElectionError(
            "Live stream can only start during voting or counting.", 409,
        )
    election.live_stream_url = stream_url
    election.stream_started_at = _now()
    _log_audit(db, election.id, "stream.started", None,
               details={"url": stream_url})
    db.commit()
    db.refresh(election)
    return election


def end_live_stream_and_start_suspense(
    db: Session, election_id: str,
) -> Election:
    """
    Ends the stream and sets a suspense window of 2 hours before the
    result can be published.
    """
    election = _get(db, election_id)
    now = _now()
    election.stream_ended_at = now
    election.suspense_until = now + timedelta(hours=SUSPENSE_WINDOW_HOURS)
    _log_audit(db, election.id, "stream.suspense_started", None,
               details={"suspense_until": election.suspense_until.isoformat()})
    db.commit()
    db.refresh(election)
    return election


def declare_result_after_suspense(
    db: Session, election_id: str, actor_id: str | None = None,
) -> Election:
    """
    Moves from suspense_blackout → result_declared once the 2-hour
    window has elapsed.
    """
    election = _get(db, election_id)
    if election.suspense_until and _now() < election.suspense_until:
        raise ElectionError(
            f"Suspense window still active until {election.suspense_until}.",
            409,
        )
    return transition_state(db, election_id, RESULT_DECLARED, actor_id,
                            reason="Suspense window elapsed.")


# ============================================================================
# READ
# ============================================================================

def get_election(db: Session, election_id: str) -> Election:
    return _get(db, election_id)


def list_elections(
    db: Session,
    level: str | None = None,
    constituency_id: str | None = None,
    state: str | None = None,
) -> list[Election]:
    q = db.query(Election)
    if level:
        q = q.filter(Election.level == level)
    if constituency_id:
        q = q.filter(Election.constituency_id == constituency_id)
    if state:
        q = q.filter(Election.state == state)
    return q.order_by(Election.election_day.desc()).all()


# ============================================================================
# INTERNAL
# ============================================================================

def _get(db: Session, election_id: str) -> Election:
    e = db.query(Election).filter(Election.id == election_id).first()
    if not e:
        raise ElectionError("Election not found.", 404)
    return e


def _log_audit(
    db: Session, election_id: str, event_type: str, actor_id: str | None,
    from_state: str | None = None, to_state: str | None = None,
    details: dict | None = None, ip: str | None = None,
) -> None:
    db.add(ElectionAuditEvent(
        election_id=election_id,
        event_type=event_type,
        actor_id=actor_id,
        from_state=from_state,
        to_state=to_state,
        details_json=details,
        ip_address=ip,
    ))