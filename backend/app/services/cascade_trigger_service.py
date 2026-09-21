"""
Election cascade trigger service — Module 003 Phase 7.

Detects when a level's threshold is met and auto-schedules the parent
election. Higher-first ordering enforced: if a parent election is active,
child triggers are queued.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.academic import (
    County, Institution, School,
)
from app.models.election import Election
from app.models.election_trigger_event import ElectionTriggerEvent
from app.models.group import Group
from app.services.election_lifecycle_service import (
    ElectionError, create_election, GROUP, SCHOOL, INSTITUTION, COUNTY,
)
from app.services.group_subscription_service import is_subscription_current


logger = logging.getLogger(__name__)


SCHOOL_THRESHOLD = 15
COUNTY_THRESHOLD = 15
INSTITUTION_BUFFER_DAYS = 30
INSTITUTION_MIN_MISSING = 3


# Precedence order: higher position runs first.
PRECEDENCE = [COUNTY, INSTITUTION, SCHOOL, GROUP]


class CascadeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# COMPLIANCE CHECKS
# ============================================================================

def is_group_compliant(db: Session, group_id: str) -> bool:
    g = db.query(Group).filter(Group.id == group_id).first()
    if not g:
        return False
    if g.status == "archived":
        return False
    if g.member_count < 10:
        return False
    ok, _ = is_subscription_current(db, group_id)
    return ok


def check_school_threshold(db: Session, school_id: str) -> dict:
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise CascadeError("School not found.", 404)

    groups = db.query(Group).filter(
        Group.school_id == school_id,
        Group.status.notin_(("archived",)),
    ).all()

    compliant = [g.id for g in groups if is_group_compliant(db, g.id)]

    return {
        "level": SCHOOL,
        "constituency_id": school_id,
        "threshold_met": len(compliant) >= SCHOOL_THRESHOLD,
        "current_count": len(compliant),
        "required_count": SCHOOL_THRESHOLD,
        "compliant_children": compliant,
        "blockers": (
            [] if len(compliant) >= SCHOOL_THRESHOLD
            else [f"{SCHOOL_THRESHOLD - len(compliant)} more compliant group(s) needed."]
        ),
        "election_id": None,
        "message": "",
    }


def check_institution_threshold(db: Session, institution_id: str) -> dict:
    institution = db.query(Institution).filter(Institution.id == institution_id).first()
    if not institution:
        raise CascadeError("Institution not found.", 404)

    schools = db.query(School).filter(
        School.institution_id == institution_id,
        School.status == "active",
    ).all()

    from app.models.role import Role, UserRole
    rep_role = db.query(Role).filter(Role.code == "school_representative").first()
    represented: list[str] = []
    if rep_role:
        for s in schools:
            exists = db.query(UserRole).filter(
                UserRole.role_id == rep_role.id,
                UserRole.jurisdiction_type == "school",
                UserRole.jurisdiction_id == s.id,
                UserRole.status == "active",
            ).first()
            if exists:
                represented.append(s.id)

    missing = [s.id for s in schools if s.id not in represented]
    threshold_met = (
        len(missing) == 0
        or (len(schools) >= 1 and len(missing) <= INSTITUTION_MIN_MISSING and _buffer_passed(institution))
    )

    return {
        "level": INSTITUTION,
        "constituency_id": institution_id,
        "threshold_met": threshold_met,
        "current_count": len(represented),
        "required_count": len(schools),
        "compliant_children": represented,
        "blockers": (
            [] if threshold_met
            else [f"{len(missing)} school(s) still without representatives."]
        ),
        "election_id": None,
        "message": "",
        "missing_schools": missing,
        "buffer_ends_at": institution.buffer_ends_at.isoformat() if institution.buffer_ends_at else None,
    }


def _buffer_passed(institution: Institution) -> bool:
    if not institution.buffer_ends_at:
        return False
    return _now() >= institution.buffer_ends_at


def check_county_threshold(db: Session, county_id: str) -> dict:
    county = db.query(County).filter(County.id == county_id).first()
    if not county:
        raise CascadeError("County not found.", 404)

    institutions = db.query(Institution).filter(
        Institution.county_id == county_id,
        Institution.status == "active",
    ).all()

    return {
        "level": COUNTY,
        "constituency_id": county_id,
        "threshold_met": len(institutions) >= COUNTY_THRESHOLD,
        "current_count": len(institutions),
        "required_count": COUNTY_THRESHOLD,
        "compliant_children": [i.id for i in institutions],
        "blockers": (
            [] if len(institutions) >= COUNTY_THRESHOLD
            else [f"{COUNTY_THRESHOLD - len(institutions)} more institution(s) needed."]
        ),
        "election_id": None,
        "message": "",
    }


# ============================================================================
# TRIGGERS
# ============================================================================

def _active_parent_election(db: Session, level: str, constituency_id: str) -> Election | None:
    """
    Return an active election at a superior level that covers this
    constituency. Used to enforce higher-first ordering.
    """
    parent_map = {
        SCHOOL: INSTITUTION,   # school's parent is institution
        INSTITUTION: COUNTY,   # institution's parent is county
        GROUP: SCHOOL,         # group's parent is school
    }
    parent_level = parent_map.get(level)
    if not parent_level:
        return None

    # Find the parent constituency id
    parent_id = None
    if level == SCHOOL:
        s = db.query(School).filter(School.id == constituency_id).first()
        parent_id = s.institution_id if s else None
    elif level == INSTITUTION:
        i = db.query(Institution).filter(Institution.id == constituency_id).first()
        parent_id = i.county_id if i else None
    elif level == GROUP:
        g = db.query(Group).filter(Group.id == constituency_id).first()
        parent_id = g.school_id if g else None

    if not parent_id:
        return None

    return db.query(Election).filter(
        Election.level == parent_level,
        Election.constituency_id == parent_id,
        Election.state.notin_(("completed",)),
    ).first()


def try_trigger_school_election(
    db: Session, school_id: str, actor_id: str | None = None,
) -> Election | None:
    status = check_school_threshold(db, school_id)
    if not status["threshold_met"]:
        return None

    # Already has an active election?
    existing = db.query(Election).filter(
        Election.level == SCHOOL,
        Election.constituency_id == school_id,
        Election.state.notin_(("completed",)),
    ).first()
    if existing:
        return existing

    parent = _active_parent_election(db, SCHOOL, school_id)
    if parent:
        _queue_trigger(db, SCHOOL, school_id, parent.id,
                       reason="Parent institution election still active.")
        return None

    return _create_cascade_election(db, SCHOOL, school_id, actor_id,
                                    f"School threshold reached: {status['current_count']} compliant groups")


def try_trigger_institution_election(
    db: Session, institution_id: str, actor_id: str | None = None,
) -> Election | None:
    status = check_institution_threshold(db, institution_id)
    if not status["threshold_met"]:
        return None

    existing = db.query(Election).filter(
        Election.level == INSTITUTION,
        Election.constituency_id == institution_id,
        Election.state.notin_(("completed",)),
    ).first()
    if existing:
        return existing

    parent = _active_parent_election(db, INSTITUTION, institution_id)
    if parent:
        _queue_trigger(db, INSTITUTION, institution_id, parent.id,
                       reason="Parent county election still active.")
        return None

    return _create_cascade_election(db, INSTITUTION, institution_id, actor_id,
                                    f"Institution threshold reached: {status['current_count']} schools represented")


def try_trigger_county_election(
    db: Session, county_id: str, actor_id: str | None = None,
) -> Election | None:
    status = check_county_threshold(db, county_id)
    if not status["threshold_met"]:
        return None

    existing = db.query(Election).filter(
        Election.level == COUNTY,
        Election.constituency_id == county_id,
        Election.state.notin_(("completed",)),
    ).first()
    if existing:
        return existing

    return _create_cascade_election(db, COUNTY, county_id, actor_id,
                                    f"County threshold reached: {status['current_count']} institutions")


def _create_cascade_election(
    db: Session, level: str, constituency_id: str,
    actor_id: str | None, reason: str,
) -> Election:
    from app.schemas.election import ElectionCreate

    # Default election day: today + 14 days for higher levels
    election_day = date.today() + timedelta(days=14)

    data = ElectionCreate(
        title=f"{level.capitalize()} Election — {constituency_id[:8]}",
        description=f"Auto-scheduled by cascade trigger. {reason}",
        level=level,
        constituency_id=constituency_id,
        election_day=election_day,
    )

    election = create_election(db, data, actor_id=actor_id or "system")

    evt = ElectionTriggerEvent(
        level=level,
        constituency_id=constituency_id,
        triggered_at=_now(),
        reason=reason,
        status="triggered",
        election_id=election.id,
    )
    db.add(evt)
    db.commit()
    db.refresh(election)
    return election


def _queue_trigger(
    db: Session, level: str, constituency_id: str,
    blocked_by_election_id: str, reason: str,
) -> ElectionTriggerEvent:
    evt = ElectionTriggerEvent(
        level=level,
        constituency_id=constituency_id,
        triggered_at=_now(),
        reason=reason,
        status="blocked_by_parent",
        blocked_by_election_id=blocked_by_election_id,
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    return evt


# ============================================================================
# SWEEP (fallback — periodic)
# ============================================================================

def run_sweep(db: Session) -> dict:
    """
    Check every school, institution, and county for threshold compliance.
    Trigger any newly-compliant parent election.
    """
    triggered: list[str] = []

    # Schools first (their parents will queue if busy)
    for s in db.query(School).filter(School.status == "active").all():
        try:
            if try_trigger_school_election(db, s.id):
                triggered.append(f"school:{s.id}")
        except Exception as e:
            logger.exception("school trigger failed: %s", e)

    for i in db.query(Institution).filter(Institution.status == "active").all():
        try:
            if try_trigger_institution_election(db, i.id):
                triggered.append(f"institution:{i.id}")
        except Exception as e:
            logger.exception("institution trigger failed: %s", e)

    for c in db.query(County).all():
        try:
            if try_trigger_county_election(db, c.id):
                triggered.append(f"county:{c.id}")
        except Exception as e:
            logger.exception("county trigger failed: %s", e)

    return {"triggered": triggered, "count": len(triggered)}


# ============================================================================
# EVENT HOOKS (callable from other services)
# ============================================================================

def on_group_threshold_reached(db: Session, group_id: str) -> None:
    """
    Called after a group crosses 10 members + current subscription.
    Checks whether the parent school should trigger.
    """
    g = db.query(Group).filter(Group.id == group_id).first()
    if not g or not g.school_id:
        return
    try:
        try_trigger_school_election(db, g.school_id)
    except Exception as e:
        logger.exception("on_group_threshold_reached failed: %s", e)


def on_school_election_completed(db: Session, school_id: str) -> None:
    """Called after a school election concludes. Checks the parent institution."""
    s = db.query(School).filter(School.id == school_id).first()
    if not s:
        return
    try:
        try_trigger_institution_election(db, s.institution_id)
    except Exception as e:
        logger.exception("on_school_election_completed failed: %s", e)


def on_institution_election_completed(db: Session, institution_id: str) -> None:
    """Called after an institution election concludes. Checks the parent county."""
    i = db.query(Institution).filter(Institution.id == institution_id).first()
    if not i:
        return
    try:
        try_trigger_county_election(db, i.county_id)
    except Exception as e:
        logger.exception("on_institution_election_completed failed: %s", e)


def on_institution_created(db: Session, county_id: str) -> None:
    """Called after a new institution is created. Checks the county threshold."""
    try:
        try_trigger_county_election(db, county_id)
    except Exception as e:
        logger.exception("on_institution_created failed: %s", e)


def process_queued_triggers(db: Session, parent_election_id: str) -> dict:
    """
    When a parent election completes, retry its queued child triggers.
    """
    queued = db.query(ElectionTriggerEvent).filter(
        ElectionTriggerEvent.blocked_by_election_id == parent_election_id,
        ElectionTriggerEvent.status == "blocked_by_parent",
    ).all()

    retried = []
    for evt in queued:
        try:
            if evt.level == SCHOOL:
                triggered = try_trigger_school_election(db, evt.constituency_id)
            elif evt.level == INSTITUTION:
                triggered = try_trigger_institution_election(db, evt.constituency_id)
            elif evt.level == COUNTY:
                triggered = try_trigger_county_election(db, evt.constituency_id)
            else:
                triggered = None

            if triggered:
                evt.status = "completed"
                evt.election_id = triggered.id
                retried.append(evt.id)
        except Exception as e:
            logger.exception("Queued trigger retry failed for %s: %s", evt.id, e)

    if retried:
        db.commit()
    return {"retried": retried, "count": len(retried)}