"""
Impeachment service — Module 003 Phase 9.

Full lifecycle. See module docstring in app/models/impeachment.py for
the state machine.

Key gating rules (added in the follow-up fix):
  - Sessions run strictly in order 1 → 2 → 3 → 4. You cannot start
    session N until session N-1 is completed, and you cannot complete
    session N until it is in_progress.
  - Verdict voting only opens when:
      * sessions 1, 2, and 3 are all completed
      * session 4 is in_progress
      * the moderator (initializer) explicitly calls open_verdict_voting()
  - Votes are only accepted after verdict_voting_opened_at is set.
  - When 2/3 threshold is reached, or when the remaining un-voted
    members can no longer change the outcome, the verdict auto-finalizes.
"""
import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.academic import Institution, School
from app.models.election import ElectionAuditEvent
from app.models.group import Group, GroupOfficial, GroupMembership
from app.models.impeachment import (
    ImpeachmentCase, ImpeachmentPetition, ImpeachmentSession, ImpeachmentVote,
    TARGET_LEVELS, SESSION_TYPES,
)
from app.models.role import Role, UserRole
from app.models.user import User


logger = logging.getLogger(__name__)


# ── constants ────────────────────────────────────────────────────────────

PETITION_THRESHOLD = 0.25          # 25% of the electorate
COMMITTEE_RATIO = 2 / 3            # 2/3 of the level below
VERDICT_THRESHOLD = 2 / 3          # 2/3 of committee must vote remove
DISCLOSURE_PERIOD_DAYS = 14
REPLACEMENT_VOTING_HOURS = 12
PRELIMINARY_SESSIONS = (1, 2, 3)   # sessions that must complete before voting
VERDICT_SESSION = 4                # the session where voting happens


# ── exception ────────────────────────────────────────────────────────────

class ImpeachmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# FILING
# ─────────────────────────────────────────────────────────────────────────

def file_complaint(
    db: Session,
    *,
    target_user_id: str,
    target_role_code: str,
    target_level: str,
    constituency_id: str,
    filed_by: str,
    grounds: str,
    evidence: dict | None = None,
) -> ImpeachmentCase:
    """Open an impeachment case. Starts in 'filed' — no petition yet."""
    if target_level not in TARGET_LEVELS:
        raise ImpeachmentError(
            f"Impeachment only applies at school, institution, or county "
            f"(got '{target_level}').", 400,
        )

    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise ImpeachmentError("Target user not found.", 404)

    if not grounds or len(grounds.strip()) < 20:
        raise ImpeachmentError("Grounds must be at least 20 characters.", 400)

    # Target must be a legitimate elected official — not an acting one.
    if _is_acting_official(db, target_user_id, target_role_code, constituency_id):
        raise ImpeachmentError(
            "Acting officials cannot be impeached.", 409,
        )

    # No open case for the same target + role.
    existing = db.query(ImpeachmentCase).filter(
        ImpeachmentCase.target_user_id == target_user_id,
        ImpeachmentCase.target_role_code == target_role_code,
        ImpeachmentCase.status.notin_((
            "resolved_removed", "resolved_reinstated",
            "petition_failed", "dismissed_via_reconciliation", "withdrawn",
        )),
    ).first()
    if existing:
        raise ImpeachmentError(
            "An open impeachment case already exists for this official.", 409,
        )

    # Compute the petition threshold now, so the UI can show progress.
    electorate = _compute_electorate(db, target_level, constituency_id)
    required = math.ceil(PETITION_THRESHOLD * len(electorate))

    case = ImpeachmentCase(
        target_user_id=target_user_id,
        target_role_code=target_role_code,
        target_level=target_level,
        constituency_id=constituency_id,
        filed_by=filed_by,
        filed_at=_now(),
        grounds=grounds.strip(),
        evidence_json=evidence,
        status="filed",
        petition_required_count=required,
        petition_signature_count=0,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


# ─────────────────────────────────────────────────────────────────────────
# RECONCILIATION
# ─────────────────────────────────────────────────────────────────────────

def attempt_reconciliation(
    db: Session,
    case_id: str,
    mediator_id: str,
    outcome: str,
    notes: str,
) -> ImpeachmentCase:
    """
    Higher-authority mediator attempts to resolve.
    - outcome='resolved' → case is dismissed
    - outcome='unresolved' → case moves to petition phase
    """
    case = _get_case(db, case_id)
    if case.status != "filed":
        raise ImpeachmentError(
            f"Reconciliation is only available in 'filed' (got '{case.status}').",
            409,
        )
    if outcome not in ("resolved", "unresolved"):
        raise ImpeachmentError("outcome must be 'resolved' or 'unresolved'.", 400)

    case.reconciliation_attempted_at = _now()
    case.reconciliation_mediator_id = mediator_id
    case.reconciliation_outcome = outcome
    case.reconciliation_notes = notes

    if outcome == "resolved":
        case.status = "dismissed_via_reconciliation"
    else:
        case.status = "petition"

    db.commit()
    db.refresh(case)
    return case


# ─────────────────────────────────────────────────────────────────────────
# PETITION
# ─────────────────────────────────────────────────────────────────────────

def sign_petition(
    db: Session,
    case_id: str,
    signer_id: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> ImpeachmentPetition:
    """Record one signature. Idempotent per signer."""
    case = _get_case(db, case_id)
    if case.status != "petition":
        raise ImpeachmentError(
            f"Cannot sign petition in status '{case.status}'.", 409,
        )

    electorate = _compute_electorate(db, case.target_level, case.constituency_id)
    if signer_id not in electorate:
        raise ImpeachmentError(
            "Only members of the target's original electorate may sign.", 403,
        )

    existing = db.query(ImpeachmentPetition).filter(
        ImpeachmentPetition.case_id == case_id,
        ImpeachmentPetition.signer_id == signer_id,
    ).first()
    if existing:
        return existing

    signature = ImpeachmentPetition(
        case_id=case_id,
        signer_id=signer_id,
        signed_at=_now(),
        signature_hash=_hash_signature(case_id, signer_id),
        ip_address=ip,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(signature)
    db.flush()

    count = db.query(ImpeachmentPetition).filter(
        ImpeachmentPetition.case_id == case_id,
    ).count()
    case.petition_signature_count = count

    if count >= case.petition_required_count and not case.petition_reached_at:
        case.petition_reached_at = _now()
        case.status = "committee_forming"

    db.commit()
    db.refresh(signature)
    return signature


def petition_status(db: Session, case_id: str) -> dict:
    case = _get_case(db, case_id)
    return {
        "case_id": case.id,
        "required": case.petition_required_count,
        "collected": case.petition_signature_count,
        "reached": case.petition_reached_at is not None,
        "reached_at": case.petition_reached_at,
    }


# ─────────────────────────────────────────────────────────────────────────
# COMMITTEE
# ─────────────────────────────────────────────────────────────────────────

def form_committee(
    db: Session,
    case_id: str,
    *,
    member_user_ids: list[str],
    moderator_user_id: str,
    formed_by: str,
) -> ImpeachmentCase:
    """Initializer locks the committee. Committee size must be 2/3 of the level below."""
    case = _get_case(db, case_id)
    if case.status != "committee_forming":
        raise ImpeachmentError(
            f"Committee can only form after petition reaches threshold "
            f"(current status '{case.status}').", 409,
        )
    if case.committee_locked:
        raise ImpeachmentError("Committee is already locked.", 409)

    eligible = _eligible_committee_pool(db, case)
    required_size = math.ceil(COMMITTEE_RATIO * len(eligible))
    if required_size == 0:
        raise ImpeachmentError(
            "No eligible officials exist at the level below.", 409,
        )

    if len(member_user_ids) != required_size:
        raise ImpeachmentError(
            f"Committee must have exactly {required_size} members "
            f"(2/3 of {len(eligible)} eligible officials).",
            400,
        )

    for m in member_user_ids:
        if m not in eligible:
            raise ImpeachmentError(
                f"User {m} is not eligible for this committee.", 400,
            )

    if moderator_user_id in member_user_ids:
        raise ImpeachmentError(
            "The moderator cannot be a voting member of the committee.", 400,
        )

    case.committee_json = {
        "members": member_user_ids,
        "moderator_user_id": moderator_user_id,
    }
    case.committee_size = len(member_user_ids)
    case.committee_formed_at = _now()
    case.committee_locked = True
    case.initializer_id = moderator_user_id
    case.status = "hearing"

    db.commit()
    db.refresh(case)
    return case


def committee_detail(db: Session, case_id: str) -> dict:
    case = _get_case(db, case_id)
    if not case.committee_json:
        raise ImpeachmentError("Committee not yet formed.", 404)
    return {
        "case_id": case.id,
        "members": case.committee_json.get("members", []),
        "moderator_user_id": case.committee_json.get("moderator_user_id"),
        "committee_size": case.committee_size,
        "locked": case.committee_locked,
        "formed_at": case.committee_formed_at,
    }


# ─────────────────────────────────────────────────────────────────────────
# HEARING SESSIONS
# ─────────────────────────────────────────────────────────────────────────

def schedule_all_sessions(
    db: Session,
    case_id: str,
    *,
    accusation_at: datetime,
    evidence_at: datetime,
    defense_at: datetime,
    verdict_at: datetime,
    is_live_streamed: bool = True,
    is_closed: bool = False,
) -> list[ImpeachmentSession]:
    """Schedule the 4 sessions. Idempotent — refuses duplicates."""
    case = _get_case(db, case_id)
    if case.status != "hearing":
        raise ImpeachmentError(
            "Can only schedule sessions while case is 'hearing'.", 409,
        )

    existing = db.query(ImpeachmentSession).filter(
        ImpeachmentSession.case_id == case_id,
    ).count()
    if existing > 0:
        raise ImpeachmentError("Sessions already scheduled for this case.", 409)

    # Sessions must be in chronological order
    if not (accusation_at <= evidence_at <= defense_at <= verdict_at):
        raise ImpeachmentError(
            "Sessions must be scheduled in chronological order "
            "(accusation → evidence → defense → verdict).", 400,
        )

    schedule = [
        (1, "accusation", accusation_at),
        (2, "evidence", evidence_at),
        (3, "defense", defense_at),
        (4, "verdict", verdict_at),
    ]

    created: list[ImpeachmentSession] = []
    for num, stype, at in schedule:
        s = ImpeachmentSession(
            case_id=case_id,
            session_number=num,
            session_type=stype,
            scheduled_at=at,
            is_live_streamed=is_live_streamed,
            is_closed=is_closed,
            status="scheduled",
        )
        db.add(s)
        created.append(s)

    case.hearing_is_live_streamed = is_live_streamed
    case.hearing_is_closed = is_closed
    case.hearing_started_at = accusation_at

    db.commit()
    for s in created:
        db.refresh(s)
    return created


def start_session(
    db: Session,
    case_id: str,
    session_number: int,
    actor_id: str,
    *,
    is_live_streamed: bool | None = None,
    is_closed: bool | None = None,
) -> ImpeachmentSession:
    """
    Start a session. Enforces strict ordering: session N cannot start
    until session N-1 is completed.
    """
    s = _get_session(db, case_id, session_number)
    if s.status != "scheduled":
        raise ImpeachmentError(
            f"Session is not scheduled (status={s.status}).", 409,
        )

    # Strict ordering
    if session_number > 1:
        prev = _get_session(db, case_id, session_number - 1)
        if prev.status != "completed":
            raise ImpeachmentError(
                f"Cannot start session {session_number} before session "
                f"{session_number - 1} is completed.", 409,
            )

    s.status = "in_progress"
    s.started_at = _now()
    if is_live_streamed is not None:
        s.is_live_streamed = is_live_streamed
    if is_closed is not None:
        s.is_closed = is_closed
    db.commit()
    db.refresh(s)
    return s


def record_session_minutes(
    db: Session,
    case_id: str,
    session_number: int,
    actor_id: str,
    *,
    transcript_text: str | None,
    minutes_text: str,
    audio_url: str | None = None,
    audio_hash: str | None = None,
) -> ImpeachmentSession:
    s = _get_session(db, case_id, session_number)
    if s.status not in ("in_progress", "completed"):
        raise ImpeachmentError(
            "Minutes can only be recorded on an in-progress or completed session.",
            409,
        )
    s.transcript_text = transcript_text
    if transcript_text:
        s.transcript_generated_at = _now()
    s.minutes_text = minutes_text
    s.minutes_finalized_at = _now()
    s.minutes_finalized_by = actor_id
    if audio_url:
        s.audio_url = audio_url
    if audio_hash:
        s.audio_hash = audio_hash
    db.commit()
    db.refresh(s)
    return s


def complete_session(
    db: Session,
    case_id: str,
    session_number: int,
    actor_id: str,
) -> ImpeachmentSession:
    """
    Complete a session. Enforces strict ordering: session N cannot be
    completed until session N-1 is already completed.
    """
    s = _get_session(db, case_id, session_number)
    if s.status != "in_progress":
        raise ImpeachmentError(
            f"Session cannot be completed (status={s.status}).", 409,
        )

    # Strict ordering
    if session_number > 1:
        prev = _get_session(db, case_id, session_number - 1)
        if prev.status != "completed":
            raise ImpeachmentError(
                f"Cannot complete session {session_number} before session "
                f"{session_number - 1} is completed.", 409,
            )

    # Session 4 cannot be completed while voting is still open
    if session_number == VERDICT_SESSION:
        case = _get_case(db, case_id)
        if case.verdict_voting_opened_at and not case.verdict_voting_closed_at:
            raise ImpeachmentError(
                "Close verdict voting before completing Session 4.", 409,
            )

    s.status = "completed"
    s.completed_at = _now()

    if s.session_number == VERDICT_SESSION:
        case = _get_case(db, case_id)
        case.hearing_completed_at = _now()

    db.commit()
    db.refresh(s)
    return s


def list_sessions(db: Session, case_id: str) -> list[ImpeachmentSession]:
    return (
        db.query(ImpeachmentSession)
        .filter(ImpeachmentSession.case_id == case_id)
        .order_by(ImpeachmentSession.session_number)
        .all()
    )


# ─────────────────────────────────────────────────────────────────────────
# VERDICT VOTING CONTROL (moderator-gated)
# ─────────────────────────────────────────────────────────────────────────

def open_verdict_voting(
    db: Session, case_id: str, actor_id: str,
) -> ImpeachmentCase:
    """
    Moderator's green light. Called during Session 4 (verdict session)
    to formally open voting to the committee.

    Preconditions:
      - case.status == 'hearing'
      - Sessions 1, 2, 3 are all completed
      - Session 4 is in_progress
      - actor_id == case.initializer_id (moderator)
      - Voting is not already open
    """
    case = _get_case(db, case_id)

    if case.status != "hearing":
        raise ImpeachmentError(
            f"Voting can only be opened while case is in 'hearing' "
            f"(status='{case.status}').", 409,
        )

    if actor_id != case.initializer_id:
        raise ImpeachmentError(
            "Only the moderator may open verdict voting.", 403,
        )

    if case.verdict_voting_opened_at:
        raise ImpeachmentError("Verdict voting is already open.", 409)

    # Sessions 1-3 must be completed
    prelim = db.query(ImpeachmentSession).filter(
        ImpeachmentSession.case_id == case_id,
        ImpeachmentSession.session_number.in_(PRELIMINARY_SESSIONS),
    ).all()
    if len(prelim) < len(PRELIMINARY_SESSIONS):
        raise ImpeachmentError(
            "Cannot open voting: not all preliminary sessions are "
            "scheduled yet.", 409,
        )
    incomplete = [
        s.session_number for s in prelim if s.status != "completed"
    ]
    if incomplete:
        raise ImpeachmentError(
            f"Cannot open voting: sessions {incomplete} are not "
            f"completed.", 409,
        )

    # Session 4 must be in progress
    session4 = _get_session(db, case_id, VERDICT_SESSION)
    if session4.status != "in_progress":
        raise ImpeachmentError(
            "Cannot open voting: Session 4 (verdict) is not in progress. "
            f"Current status: '{session4.status}'.", 409,
        )

    case.verdict_voting_opened_at = _now()
    case.verdict_voting_opened_by = actor_id
    db.commit()
    db.refresh(case)
    return case


def close_verdict_voting(
    db: Session, case_id: str, actor_id: str,
) -> ImpeachmentCase:
    """
    Moderator closes voting. If no verdict has been finalized yet, one
    is forced: removal only if the threshold has already been met;
    otherwise the incumbent is reinstated.
    """
    case = _get_case(db, case_id)

    if case.status != "hearing":
        raise ImpeachmentError(
            f"Voting can only be closed while case is in 'hearing'.", 409,
        )
    if actor_id != case.initializer_id:
        raise ImpeachmentError(
            "Only the moderator may close verdict voting.", 403,
        )
    if not case.verdict_voting_opened_at:
        raise ImpeachmentError("Verdict voting has not been opened yet.", 409)
    if case.verdict_voting_closed_at:
        raise ImpeachmentError("Verdict voting is already closed.", 409)

    case.verdict_voting_closed_at = _now()
    case.verdict_voting_closed_by = actor_id

    # Force a verdict if not already finalized by the auto-check.
    if not case.verdict_at:
        required_for = math.ceil(VERDICT_THRESHOLD * case.committee_size)
        if case.verdict_votes_for >= required_for:
            _finalize_verdict(db, case, "removed")
        else:
            _finalize_verdict(db, case, "reinstated")

    db.commit()
    db.refresh(case)
    return case


def verdict_voting_status(db: Session, case_id: str) -> dict:
    case = _get_case(db, case_id)
    is_open = bool(
        case.verdict_voting_opened_at and not case.verdict_voting_closed_at
    )
    return {
        "case_id": case.id,
        "status": case.status,
        "voting_is_open": is_open,
        "voting_opened_at": case.verdict_voting_opened_at,
        "voting_opened_by": case.verdict_voting_opened_by,
        "voting_closed_at": case.verdict_voting_closed_at,
        "voting_closed_by": case.verdict_voting_closed_by,
    }


# ─────────────────────────────────────────────────────────────────────────
# VERDICT VOTING
# ─────────────────────────────────────────────────────────────────────────

def cast_verdict_vote(
    db: Session,
    case_id: str,
    voter_id: str,
    vote: str,
) -> ImpeachmentVote:
    """
    Cast a verdict vote.

    Preconditions (all enforced):
      - case.status == 'hearing'
      - moderator has opened voting (verdict_voting_opened_at set)
      - voting has not been closed yet
      - voter is a committee member
      - voter is not the moderator
      - voter has not already voted
    """
    if vote not in ("remove", "keep"):
        raise ImpeachmentError("vote must be 'remove' or 'keep'.", 400)

    case = _get_case(db, case_id)
    if case.status != "hearing":
        raise ImpeachmentError(
            f"Voting is not open (status='{case.status}').", 409,
        )

    # ── Voting must have been opened by the moderator ──
    if not case.verdict_voting_opened_at:
        raise ImpeachmentError(
            "Verdict voting has not been opened by the moderator yet. "
            "The moderator must open voting during Session 4.", 409,
        )
    if case.verdict_voting_closed_at:
        raise ImpeachmentError(
            "Verdict voting has been closed.", 409,
        )

    members: list[str] = (case.committee_json or {}).get("members", [])
    if voter_id not in members:
        raise ImpeachmentError("Only committee members may vote.", 403)

    if voter_id == case.initializer_id:
        raise ImpeachmentError("The moderator does not vote.", 403)

    existing = db.query(ImpeachmentVote).filter(
        ImpeachmentVote.case_id == case_id,
        ImpeachmentVote.voter_id == voter_id,
    ).first()
    if existing:
        raise ImpeachmentError("You have already voted.", 409)

    v = ImpeachmentVote(
        case_id=case_id,
        voter_id=voter_id,
        vote=vote,
        cast_at=_now(),
        vote_hash=_hash_vote(case_id, voter_id, vote),
    )
    db.add(v)
    db.flush()

    # Update tally
    votes_for = db.query(ImpeachmentVote).filter(
        ImpeachmentVote.case_id == case_id,
        ImpeachmentVote.vote == "remove",
    ).count()
    votes_against = db.query(ImpeachmentVote).filter(
        ImpeachmentVote.case_id == case_id,
        ImpeachmentVote.vote == "keep",
    ).count()
    case.verdict_votes_for = votes_for
    case.verdict_votes_against = votes_against

    db.commit()
    db.refresh(v)

    # Auto-finalize when the outcome is mathematically decided
    _maybe_finalize_verdict(db, case)
    return v


def _maybe_finalize_verdict(db: Session, case: ImpeachmentCase) -> None:
    """
    If 2/3 threshold is met → remove.
    If remaining unvoted members cannot push to threshold → reinstate.
    """
    total_votes = case.verdict_votes_for + case.verdict_votes_against
    required_for = math.ceil(VERDICT_THRESHOLD * case.committee_size)

    if case.verdict_votes_for >= required_for:
        _finalize_verdict(db, case, "removed")
        return

    max_possible_for = case.verdict_votes_for + (
        case.committee_size - total_votes
    )
    if max_possible_for < required_for:
        _finalize_verdict(db, case, "reinstated")
        return


def _finalize_verdict(
    db: Session, case: ImpeachmentCase, outcome: str,
) -> None:
    case.verdict = outcome
    case.verdict_at = _now()

    if outcome == "removed":
        case.status = "verdict_removed"
        case.removal_effective_at = _now()
    else:
        case.status = "verdict_reinstated"

    # Emit an audit event
    try:
        db.add(ElectionAuditEvent(
            election_id=case.constituency_id,
            event_type=f"impeachment.{outcome}",
            actor_id=None,
            details_json={
                "case_id": case.id,
                "target_user_id": case.target_user_id,
                "target_role_code": case.target_role_code,
            },
        ))
    except Exception:
        pass

    db.commit()


def verdict_summary(db: Session, case_id: str) -> dict:
    case = _get_case(db, case_id)
    required = math.ceil(VERDICT_THRESHOLD * case.committee_size) \
        if case.committee_size else 0
    is_open = bool(
        case.verdict_voting_opened_at and not case.verdict_voting_closed_at
    )
    return {
        "case_id": case.id,
        "votes_for": case.verdict_votes_for,
        "votes_against": case.verdict_votes_against,
        "committee_size": case.committee_size,
        "threshold_required": required,
        "outcome": (
            "removed" if case.verdict_votes_for >= required
            else "reinstated" if case.verdict_at
            else "pending"
        ),
        "verdict": case.verdict,
        "verdict_at": case.verdict_at,
        "voting_opened_at": case.verdict_voting_opened_at,
        "voting_opened_by": case.verdict_voting_opened_by,
        "voting_closed_at": case.verdict_voting_closed_at,
        "voting_closed_by": case.verdict_voting_closed_by,
        "voting_is_open": is_open,
    }


# ─────────────────────────────────────────────────────────────────────────
# POST-REMOVAL: DISCLOSURE + REPLACEMENT
# ─────────────────────────────────────────────────────────────────────────

def start_disclosure_period(
    db: Session, case_id: str, actor_id: str,
) -> ImpeachmentCase:
    case = _get_case(db, case_id)
    if case.status != "verdict_removed":
        raise ImpeachmentError(
            "Disclosure period can only start after a removal verdict.", 409,
        )
    case.disclosure_period_ends_at = _now() + timedelta(days=DISCLOSURE_PERIOD_DAYS)
    case.status = "disclosure_period"
    db.commit()
    db.refresh(case)
    return case


def trigger_replacement_election(
    db: Session, case_id: str, actor_id: str,
) -> ImpeachmentCase:
    """
    Called at the end of the 14-day disclosure window. Creates a
    child election for the vacant seat and records the reference.
    """
    case = _get_case(db, case_id)
    if case.status != "disclosure_period":
        raise ImpeachmentError(
            f"Replacement election cannot be triggered (status='{case.status}').",
            409,
        )
    if case.disclosure_period_ends_at and _now() < case.disclosure_period_ends_at:
        raise ImpeachmentError(
            "Disclosure period has not ended yet.", 409,
        )

    from app.services.election_lifecycle_service import create_election
    from app.schemas.election import ElectionCreate
    from datetime import date

    data = ElectionCreate(
        title=f"Replacement — {case.target_role_code} — {case.constituency_id[:8]}",
        description=(
            f"Replacement election following successful impeachment "
            f"(case {case.id})."
        ),
        level=case.target_level,
        constituency_id=case.constituency_id,
        election_day=date.today() + timedelta(days=2),
    )
    election = create_election(db, data, actor_id=actor_id)

    case.replacement_election_id = election.id
    case.status = "replacement_election"
    db.commit()
    db.refresh(case)
    return case


def finalize_removal(
    db: Session, case_id: str, winner_user_id: str, actor_id: str,
) -> ImpeachmentCase:
    """Called once the replacement election is verified."""
    case = _get_case(db, case_id)
    if case.status != "replacement_election":
        raise ImpeachmentError(
            "Case is not awaiting a replacement election.", 409,
        )
    case.replacement_winner_user_id = winner_user_id
    case.status = "resolved_removed"
    db.commit()
    db.refresh(case)
    return case


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_case(db: Session, case_id: str) -> ImpeachmentCase:
    return _get_case(db, case_id)


def list_cases(
    db: Session,
    *,
    target_level: str | None = None,
    constituency_id: str | None = None,
    status: str | None = None,
    target_user_id: str | None = None,
) -> list[ImpeachmentCase]:
    q = db.query(ImpeachmentCase)
    if target_level:
        q = q.filter(ImpeachmentCase.target_level == target_level)
    if constituency_id:
        q = q.filter(ImpeachmentCase.constituency_id == constituency_id)
    if status:
        q = q.filter(ImpeachmentCase.status == status)
    if target_user_id:
        q = q.filter(ImpeachmentCase.target_user_id == target_user_id)
    return q.order_by(ImpeachmentCase.filed_at.desc()).all()


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────

def _get_case(db: Session, case_id: str) -> ImpeachmentCase:
    c = db.query(ImpeachmentCase).filter(ImpeachmentCase.id == case_id).first()
    if not c:
        raise ImpeachmentError("Impeachment case not found.", 404)
    return c


def _get_session(db: Session, case_id: str, number: int) -> ImpeachmentSession:
    s = db.query(ImpeachmentSession).filter(
        ImpeachmentSession.case_id == case_id,
        ImpeachmentSession.session_number == number,
    ).first()
    if not s:
        raise ImpeachmentError(
            f"Session {number} not found for case {case_id}.", 404,
        )
    return s


def _hash_signature(case_id: str, signer_id: str) -> str:
    return hashlib.sha256(f"pet|{case_id}|{signer_id}".encode()).hexdigest()


def _hash_vote(case_id: str, voter_id: str, vote: str) -> str:
    return hashlib.sha256(
        f"vote|{case_id}|{voter_id}|{vote}".encode()
    ).hexdigest()


def _is_acting_official(
    db: Session, user_id: str, role_code: str, jurisdiction_id: str,
) -> bool:
    """
    An acting official is anyone whose UserRole notes contain 'Acting'.
    The role-provisioning path sets those notes explicitly when an
    Assistant takes over a vacant seat. Anyone not currently holding the
    role is also considered ineligible.
    """
    role = db.query(Role).filter(Role.code == role_code).first()
    if not role:
        return False

    row = db.query(UserRole).filter(
        UserRole.user_id == user_id,
        UserRole.role_id == role.id,
        UserRole.jurisdiction_id == jurisdiction_id,
        UserRole.status == "active",
    ).first()

    if not row:
        # Target does not hold the role — treat as ineligible.
        return True

    return "acting" in (row.notes or "").lower()


def _compute_electorate(
    db: Session, level: str, constituency_id: str,
) -> list[str]:
    """
    Electorate = the body that originally elected the target.
      - School Rep      → all members of the school's groups
      - Institution Rep → all Group Leaders of the institution
      - County Rep      → all School Representatives of the county
    """
    if level == "school":
        group_ids = [
            g.id for g in db.query(Group.id).filter(
                Group.school_id == constituency_id,
                Group.status.in_(("forming", "pending_election", "active")),
            ).all()
        ]
        if not group_ids:
            return []
        rows = db.query(GroupMembership.user_id).filter(
            GroupMembership.group_id.in_(group_ids),
            GroupMembership.status == "active",
        ).distinct().all()
        return [r[0] for r in rows]

    if level == "institution":
        group_ids = [
            g.id for g in db.query(Group.id).filter(
                Group.institution_id == constituency_id,
                Group.status.in_(("forming", "pending_election", "active")),
            ).all()
        ]
        if not group_ids:
            return []
        rows = db.query(GroupOfficial.user_id).filter(
            GroupOfficial.group_id.in_(group_ids),
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
        ).distinct().all()
        return [r[0] for r in rows]

    if level == "county":
        school_ids = [
            s.id for s in db.query(School.id).join(
                Institution, School.institution_id == Institution.id,
            ).filter(Institution.county_id == constituency_id).all()
        ]
        if not school_ids:
            return []
        rows = db.query(UserRole.user_id).filter(
            UserRole.role_id.in_(
                db.query(Role.id).filter(Role.code == "school_representative")
            ),
            UserRole.jurisdiction_type == "school",
            UserRole.jurisdiction_id.in_(school_ids),
            UserRole.status == "active",
        ).distinct().all()
        return [r[0] for r in rows]

    return []


def _eligible_committee_pool(
    db: Session, case: ImpeachmentCase,
) -> list[str]:
    """
    Committee pool = officials at the level immediately below the target.
      - School Rep      → Group Leaders of that school
      - Institution Rep → School Representatives of that institution
      - County Rep      → Institution Representatives of that county
    """
    if case.target_level == "school":
        group_ids = [
            g.id for g in db.query(Group.id).filter(
                Group.school_id == case.constituency_id,
            ).all()
        ]
        if not group_ids:
            return []
        rows = db.query(GroupOfficial.user_id).filter(
            GroupOfficial.group_id.in_(group_ids),
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
        ).distinct().all()
        return [r[0] for r in rows]

    if case.target_level == "institution":
        school_ids = [
            s.id for s in db.query(School.id).filter(
                School.institution_id == case.constituency_id,
            ).all()
        ]
        if not school_ids:
            return []
        rows = db.query(UserRole.user_id).filter(
            UserRole.role_id.in_(
                db.query(Role.id).filter(Role.code == "school_representative")
            ),
            UserRole.jurisdiction_type == "school",
            UserRole.jurisdiction_id.in_(school_ids),
            UserRole.status == "active",
        ).distinct().all()
        return [r[0] for r in rows]

    if case.target_level == "county":
        institution_ids = [
            i.id for i in db.query(Institution.id).filter(
                Institution.county_id == case.constituency_id,
            ).all()
        ]
        if not institution_ids:
            return []
        rows = db.query(UserRole.user_id).filter(
            UserRole.role_id.in_(
                db.query(Role.id).filter(
                    Role.code == "institution_representative"
                )
            ),
            UserRole.jurisdiction_type == "institution",
            UserRole.jurisdiction_id.in_(institution_ids),
            UserRole.status == "active",
        ).distinct().all()
        return [r[0] for r in rows]

    return []