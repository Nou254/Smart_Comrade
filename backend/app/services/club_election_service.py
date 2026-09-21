"""
Club election service — Module 003 Phase 10.

Cycle: positions published → candidates open → voting (day 7) →
results (day 9) → completed.
Fee: KSh 200 recurring at every cycle initiation.
Failed election → halted, 14-day recovery, then dissolved.
"""
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.activity_club import (
    ActivityClub, ActivityClubPosition, ActivityClubMembership,
    ActivityClubElectionCycle, ActivityClubElectionCandidate,
    ActivityClubElectionVote,
    ELECTION_FEE, CYCLE_VOTING_DAY, CYCLE_RESULT_DAY,
    HALT_RECOVERY_WINDOW_DAYS,
)
from app.services.club_audit_service import log_club_event


logger = logging.getLogger(__name__)


MIN_CANDIDATES_PER_POSITION = 2


class ClubElectionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# CYCLE INITIATION
# ─────────────────────────────────────────────────────────────────────────

def initiate_cycle(
    db: Session, club_id: str, actor_id: str, term_months: int,
) -> ActivityClubElectionCycle:
    club = _get_club(db, club_id)
    _assert_leader(db, club, actor_id)

    if term_months < 6 or term_months > 24:
        raise ClubElectionError(
            "Term length must be between 6 and 24 months.", 400,
        )

    # Guard: first cycle can only start after the 4-month mark
    open_cycle = db.query(ActivityClubElectionCycle).filter(
        ActivityClubElectionCycle.club_id == club.id,
        ActivityClubElectionCycle.status.notin_((
            "completed", "failed", "halted",
        )),
    ).first()
    if open_cycle:
        raise ClubElectionError(
            "An open election cycle already exists for this club.", 409,
        )

    last_cycle = db.query(ActivityClubElectionCycle).filter(
        ActivityClubElectionCycle.club_id == club.id,
    ).order_by(ActivityClubElectionCycle.cycle_number.desc()).first()
    cycle_number = (last_cycle.cycle_number + 1) if last_cycle else 1

    now = _now()
    cycle = ActivityClubElectionCycle(
        club_id=club.id,
        cycle_number=cycle_number,
        status="draft",
        initiated_at=now,
        positions_published_at=now,
        voting_at=now + timedelta(days=CYCLE_VOTING_DAY),
        results_declared_at=now + timedelta(days=CYCLE_RESULT_DAY),
        term_months=term_months,
        election_fee_amount=ELECTION_FEE,
        election_fee_paid=False,
    )
    db.add(cycle)
    club.declared_term_months = term_months

    log_club_event(
        db, club.id, "club.first_cycle_initiated", actor_id=actor_id,
        from_state=club.status, to_state="cycle_open",
        details={"cycle_number": cycle_number, "term_months": term_months},
    )
    db.commit()
    db.refresh(cycle)
    return cycle


def record_election_fee(
    db: Session, cycle_id: str, payment_reference: str, method: str,
) -> ActivityClubElectionCycle:
    cycle = _get_cycle(db, cycle_id)
    if cycle.election_fee_paid:
        return cycle
    if method not in ("mpesa", "card"):
        raise ClubElectionError("method must be 'mpesa' or 'card'.", 400)

    cycle.election_fee_paid = True
    cycle.election_fee_reference = payment_reference
    cycle.election_fee_paid_at = _now()
    cycle.election_fee_method = method
    cycle.status = "positions_published"

    log_club_event(
        db, cycle.club_id, "club.election_fee_paid", actor_id=None,
        details={
            "cycle_id": cycle.id,
            "amount": cycle.election_fee_amount,
            "reference": payment_reference,
            "method": method,
        },
    )
    db.commit()
    db.refresh(cycle)
    return cycle


# ─────────────────────────────────────────────────────────────────────────
# CANDIDATES
# ─────────────────────────────────────────────────────────────────────────

def register_candidate(
    db: Session, cycle_id: str, user_id: str, data,
) -> ActivityClubElectionCandidate:
    cycle = _get_cycle(db, cycle_id)
    if cycle.status not in ("positions_published", "candidates_open"):
        raise ClubElectionError(
            f"Candidacy registration is closed (status={cycle.status}).", 409,
        )
    if not cycle.election_fee_paid:
        raise ClubElectionError(
            "The election fee has not been paid yet.", 409,
        )

    # Voter must be an active member
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == cycle.club_id,
        ActivityClubMembership.user_id == user_id,
        ActivityClubMembership.status == "active",
    ).first()
    if not m:
        raise ClubElectionError(
            "Only active club members may stand for office.", 403,
        )

    # Position must be active and belong to this club
    pos = db.query(ActivityClubPosition).filter(
        ActivityClubPosition.id == data.position_id,
        ActivityClubPosition.club_id == cycle.club_id,
        ActivityClubPosition.status == "active",
    ).first()
    if not pos:
        raise ClubElectionError("Position not found or retired.", 404)

    existing = db.query(ActivityClubElectionCandidate).filter(
        ActivityClubElectionCandidate.cycle_id == cycle.id,
        ActivityClubElectionCandidate.position_id == pos.id,
        ActivityClubElectionCandidate.user_id == user_id,
    ).first()
    if existing:
        raise ClubElectionError("You are already a candidate for this position.", 409)

    candidate = ActivityClubElectionCandidate(
        cycle_id=cycle.id,
        club_id=cycle.club_id,
        position_id=pos.id,
        user_id=user_id,
        manifesto=data.manifesto,
        photo_url=data.photo_url,
        status="nominated",
        nominated_at=_now(),
    )
    db.add(candidate)
    cycle.status = "candidates_open"

    db.commit()
    db.refresh(candidate)
    return candidate


# ─────────────────────────────────────────────────────────────────────────
# VOTING
# ─────────────────────────────────────────────────────────────────────────

def cast_vote(
    db: Session, cycle_id: str, voter_id: str, data,
) -> ActivityClubElectionVote:
    cycle = _get_cycle(db, cycle_id)
    if cycle.status != "voting":
        raise ClubElectionError(
            f"Voting is not open (status={cycle.status}).", 409,
        )
    if cycle.voting_at and _now() < cycle.voting_at:
        raise ClubElectionError("Voting has not started yet.", 409)

    # Voter is active member
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == cycle.club_id,
        ActivityClubMembership.user_id == voter_id,
        ActivityClubMembership.status == "active",
    ).first()
    if not m:
        raise ClubElectionError("Only active members may vote.", 403)

    candidate = db.query(ActivityClubElectionCandidate).filter(
        ActivityClubElectionCandidate.id == data.candidate_id,
        ActivityClubElectionCandidate.cycle_id == cycle.id,
        ActivityClubElectionCandidate.position_id == data.position_id,
    ).first()
    if not candidate:
        raise ClubElectionError("Candidate not found for this position.", 404)

    existing = db.query(ActivityClubElectionVote).filter(
        ActivityClubElectionVote.cycle_id == cycle.id,
        ActivityClubElectionVote.position_id == data.position_id,
        ActivityClubElectionVote.voter_id == voter_id,
    ).first()
    if existing:
        raise ClubElectionError("You have already voted for this position.", 409)

    v = ActivityClubElectionVote(
        cycle_id=cycle.id,
        club_id=cycle.club_id,
        position_id=data.position_id,
        candidate_id=data.candidate_id,
        voter_id=voter_id,
        cast_at=_now(),
        vote_hash=hashlib.sha256(
            f"{cycle.id}|{data.position_id}|{voter_id}|{data.candidate_id}"
            .encode()
        ).hexdigest(),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def open_voting(db: Session, cycle_id: str, actor_id: str) -> ActivityClubElectionCycle:
    """Move cycle to voting state once day-7 is reached."""
    cycle = _get_cycle(db, cycle_id)
    if cycle.status != "candidates_open":
        raise ClubElectionError(
            f"Cannot open voting from status '{cycle.status}'.", 409,
        )
    if cycle.voting_at and _now() < cycle.voting_at:
        raise ClubElectionError(
            f"Voting opens at {cycle.voting_at.isoformat()}.", 409,
        )
    cycle.status = "voting"
    db.commit()
    db.refresh(cycle)
    return cycle


# ─────────────────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────────────────

def tally_cycle(
    db: Session, cycle_id: str, actor_id: str,
) -> dict:
    """
    Count votes per position, finalize winners, move cycle to 'verified'.
    Returns a summary + list of positions with < 2 candidates.
    """
    cycle = _get_cycle(db, cycle_id)
    if cycle.status not in ("voting", "candidates_open"):
        raise ClubElectionError(
            f"Cannot tally in status '{cycle.status}'.", 409,
        )

    club = _get_club(db, cycle.club_id)
    positions = db.query(ActivityClubPosition).filter(
        ActivityClubPosition.club_id == club.id,
        ActivityClubPosition.status == "active",
    ).all()

    results: dict[str, dict] = {}
    failed_positions: list[str] = []

    for pos in positions:
        candidates = db.query(ActivityClubElectionCandidate).filter(
            ActivityClubElectionCandidate.cycle_id == cycle.id,
            ActivityClubElectionCandidate.position_id == pos.id,
            ActivityClubElectionCandidate.status.in_(("nominated", "qualified")),
        ).all()

        if len(candidates) < MIN_CANDIDATES_PER_POSITION:
            failed_positions.append(pos.id)
            for c in candidates:
                c.status = "withdrawn"
            continue

        # Count votes per candidate
        counts: dict[str, int] = {}
        for c in candidates:
            counts[c.id] = 0
        rows = db.query(ActivityClubElectionVote.candidate_id).filter(
            ActivityClubElectionVote.cycle_id == cycle.id,
            ActivityClubElectionVote.position_id == pos.id,
        ).all()
        for (cid,) in rows:
            counts[cid] = counts.get(cid, 0) + 1

        sorted_counts = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        top_id, top_votes = sorted_counts[0]

        # Simple majority (no ties in V1 — ties resolved by re-election)
        ties = [cid for cid, c in counts.items() if c == top_votes]
        if len(ties) > 1:
            failed_positions.append(pos.id)
            for c in candidates:
                c.votes_count = counts.get(c.id, 0)
            continue

        winner = next((c for c in candidates if c.id == top_id), None)
        for c in candidates:
            c.votes_count = counts.get(c.id, 0)
            c.status = "winner" if c.id == top_id else "lost"

        if winner:
            pos.current_holder_id = winner.user_id
            pos.current_term_start = _now()
            pos.current_term_end = _now() + timedelta(
                days=30 * (cycle.term_months or 12)
            )
            # Promote the winner's membership to leader
            m = db.query(ActivityClubMembership).filter(
                ActivityClubMembership.club_id == club.id,
                ActivityClubMembership.user_id == winner.user_id,
            ).first()
            if m:
                m.role = "leader"

            results[pos.id] = {
                "position_id": pos.id,
                "position_code": pos.position_code,
                "winner_user_id": winner.user_id,
                "winner_candidate_id": winner.id,
                "votes": top_votes,
            }

    # Determine overall cycle status
    if failed_positions and not results:
        # Every position failed → failed cycle → halt
        cycle.status = "failed"
        cycle.failed_reason = "No position had at least 2 candidates."
        cycle.halt_warning_at = _now()
        cycle.halt_recovery_deadline = _now() + timedelta(
            days=HALT_RECOVERY_WINDOW_DAYS,
        )
        club.status = "halted"
        club.halt_warning_at = cycle.halt_warning_at
        club.halt_recovery_deadline = cycle.halt_recovery_deadline

        log_club_event(
            db, club.id, "club.cycle_failed", actor_id=actor_id,
            details={"cycle_id": cycle.id, "failed_positions": failed_positions},
        )
    else:
        cycle.status = "verified"
        cycle.results_declared_at = _now()
        # If the club is still in 'forming', mark it 'active'
        if club.status == "forming":
            club.status = "active"
            log_club_event(
                db, club.id, "club.cycle_completed", actor_id=actor_id,
                from_state="forming", to_state="active",
                details={"cycle_id": cycle.id},
            )
        else:
            log_club_event(
                db, club.id, "club.cycle_completed", actor_id=actor_id,
                details={"cycle_id": cycle.id},
            )

    cycle.completed_at = _now()
    db.commit()
    db.refresh(cycle)

    return {
        "cycle_id": cycle.id,
        "status": cycle.status,
        "results": results,
        "failed_positions": failed_positions,
    }


# ─────────────────────────────────────────────────────────────────────────
# FAILED ELECTIONS / DISSOLUTION
# ─────────────────────────────────────────────────────────────────────────

def handle_dissolution_if_recovery_expired(
    db: Session, club_id: str,
) -> dict:
    """
    Called by a scheduled job (or admin) after a halted cycle. If the
    recovery window has expired, dissolve the club.
    """
    from app.services.club_lifecycle_service import dissolve_club

    club = _get_club(db, club_id)
    if club.status != "halted":
        return {"dissolved": False, "reason": "not_halted"}

    if not club.halt_recovery_deadline:
        return {"dissolved": False, "reason": "no_deadline"}

    if _now() < club.halt_recovery_deadline:
        return {
            "dissolved": False,
            "reason": "window_still_open",
            "deadline": club.halt_recovery_deadline.isoformat(),
        }

    dissolve_club(
        db, club.id,
        trigger="halted_recovery_expired",
        reason="14-day recovery window expired without a successful election.",
        actor_id=None,
    )
    return {"dissolved": True}


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def list_cycles(db: Session, club_id: str) -> list[ActivityClubElectionCycle]:
    return (
        db.query(ActivityClubElectionCycle)
        .filter(ActivityClubElectionCycle.club_id == club_id)
        .order_by(ActivityClubElectionCycle.cycle_number.desc())
        .all()
    )


def list_candidates(
    db: Session, cycle_id: str, position_id: str | None = None,
) -> list[ActivityClubElectionCandidate]:
    q = db.query(ActivityClubElectionCandidate).filter(
        ActivityClubElectionCandidate.cycle_id == cycle_id,
    )
    if position_id:
        q = q.filter(ActivityClubElectionCandidate.position_id == position_id)
    return q.order_by(ActivityClubElectionCandidate.nominated_at).all()


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _get_club(db: Session, club_id: str) -> ActivityClub:
    c = db.query(ActivityClub).filter(ActivityClub.id == club_id).first()
    if not c:
        raise ClubElectionError("Club not found.", 404)
    return c


def _get_cycle(db: Session, cycle_id: str) -> ActivityClubElectionCycle:
    c = db.query(ActivityClubElectionCycle).filter(
        ActivityClubElectionCycle.id == cycle_id,
    ).first()
    if not c:
        raise ClubElectionError("Election cycle not found.", 404)
    return c


def _assert_leader(db: Session, club: ActivityClub, actor_id: str) -> None:
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club.id,
        ActivityClubMembership.user_id == actor_id,
        ActivityClubMembership.status == "active",
    ).first()
    if not m or m.role != "leader":
        raise ClubElectionError(
            "Only the elected leader may perform this action.", 403,
        )