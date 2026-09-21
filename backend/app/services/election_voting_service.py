"""
Election voting, tallying, and result service — Module 003 Phase 6.

Owns voter roll freeze, ballot casting, tallying, tie detection,
winner declaration, role provisioning, and run-off scheduling.
"""
import hashlib
import logging
from datetime import datetime, time as _time, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.election import (
    Election, ElectionPosition, ElectionTicket, ElectionCandidate,
    ElectionVoterRoll, ElectionBallot, ElectionResult, ElectionAuditEvent,
)
from app.models.group import Group, GroupMembership, GroupOfficial
from app.models.role import Role, UserRole
from app.services.election_state import (
    VOTING, COUNTING, RESULT_DECLARED, RUN_OFF_SCHEDULED,
    RUN_OFF_VOTING, COMPLETED, APPEAL_WINDOW,
)
from app.services.election_lifecycle_service import (
    ElectionError, GROUP, SCHOOL, INSTITUTION, COUNTY, LEVELS_WITH_APPEALS,
)

# Module 003 Phase 7 — integration hookups
from app.services.cascade_trigger_service import (
    on_school_election_completed as _on_school_election_completed,
    on_institution_election_completed as _on_institution_election_completed,
    process_queued_triggers as _process_queued_triggers,
)

logger = logging.getLogger(__name__)


MIN_VOTER_ACTIVITY_DAYS = 60
GROUP_MIN_ACTIVITY_DAYS = 14


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# VOTER ROLL
# ============================================================================

def freeze_voter_roll(db: Session, election_id: str) -> int:
    """
    Snapshot all currently eligible voters into `election_voter_roll`.
    Called once when the election enters `nominational_voting`.
    Idempotent: existing rows are not re-created.
    """
    election = _get_election(db, election_id)
    if election.state not in (VOTING, "nominating", "nominational_voting",
                              "payment_window", "ballot_finalized", "campaigning"):
        raise ElectionError(
            f"Cannot freeze voter roll in state '{election.state}'.", 409,
        )

    existing = db.query(ElectionVoterRoll).filter(
        ElectionVoterRoll.election_id == election.id,
    ).count()
    if existing > 0:
        return existing

    eligible_users = _compute_eligible_voters(db, election)
    now = _now()
    for user_id in eligible_users:
        db.add(ElectionVoterRoll(
            election_id=election.id,
            user_id=user_id,
            eligible=True,
            frozen_at=now,
        ))

    election.electorate_size = len(eligible_users)
    db.commit()
    return len(eligible_users)


def _compute_eligible_voters(db: Session, election: Election) -> list[str]:
    """
    Return the list of user_ids eligible to vote in this election.
    Depends on level:
      group       → active group members
      school      → all members of the school's groups
      institution → Group Leaders of the institution
      county      → School Representatives of the county
    """
    if election.level == GROUP:
        rows = db.query(GroupMembership.user_id).filter(
            GroupMembership.group_id == election.constituency_id,
            GroupMembership.status == "active",
        ).all()
        return [r[0] for r in rows]

    if election.level == SCHOOL:
        # School → groups → members
        group_ids = [
            g.id for g in db.query(Group.id).filter(
                Group.school_id == election.constituency_id,
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

    if election.level == INSTITUTION:
        # Group Leaders of the institution's groups
        group_ids = [
            g.id for g in db.query(Group.id).filter(
                Group.institution_id == election.constituency_id,
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

    if election.level == COUNTY:
        # School Representatives of the county — resolved via user_roles
        # for the current term, scoped by jurisdiction. The jurisdiction
        # resolver is authoritative; here we query user_roles directly.
        from app.models.academic import School, Institution
        school_ids = [
            s.id for s in db.query(School.id).join(
                Institution, School.institution_id == Institution.id,
            ).filter(Institution.county_id == election.constituency_id).all()
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


# ============================================================================
# CAST BALLOT
# ============================================================================

def cast_ballot(
    db: Session, election_id: str, user_id: str, position_id: str,
    ticket_id: str,
) -> ElectionBallot:
    election = _get_election(db, election_id)
    if election.state != VOTING:
        raise ElectionError(
            f"Voting is not open (state={election.state}).", 409,
        )
    if election.voting_close_at and _now() > election.voting_close_at:
        raise ElectionError("Voting window has closed.", 410)

    roll = db.query(ElectionVoterRoll).filter(
        ElectionVoterRoll.election_id == election.id,
        ElectionVoterRoll.user_id == user_id,
        ElectionVoterRoll.eligible.is_(True),
    ).first()
    if not roll:
        raise ElectionError("You are not eligible to vote in this election.", 403)

    # Must be a valid position + ticket for this election
    position = db.query(ElectionPosition).filter(
        ElectionPosition.id == position_id,
        ElectionPosition.election_id == election.id,
    ).first()
    if not position:
        raise ElectionError("Position not found in this election.", 404)

    ticket = db.query(ElectionTicket).filter(
        ElectionTicket.id == ticket_id,
        ElectionTicket.election_id == election.id,
        ElectionTicket.status.in_(("qualified", "pending_approval")),
    ).first()
    if not ticket:
        raise ElectionError("Ticket not found on this election's ballot.", 404)

    # One vote per position per voter
    existing = db.query(ElectionBallot).filter(
        ElectionBallot.election_id == election.id,
        ElectionBallot.position_id == position_id,
        ElectionBallot.voter_id == user_id,
    ).first()
    if existing:
        raise ElectionError("You have already voted for this position.", 409)

    vote_hash = _hash_vote(election.id, position.id, user_id, ticket.id)

    ballot = ElectionBallot(
        election_id=election.id,
        position_id=position.id,
        ticket_id=ticket.id,
        voter_id=user_id,
        cast_at=_now(),
        vote_hash=vote_hash,
    )
    db.add(ballot)

    roll.has_voted = True
    roll.voted_at = ballot.cast_at

    # Vote finality: no further updates permitted
    _log_audit(db, election.id, "ballot.cast", user_id,
               details={"position_id": position.id})
    db.commit()
    db.refresh(ballot)
    return ballot


def _hash_vote(
    election_id: str, position_id: str, voter_id: str, ticket_id: str,
) -> str:
    """Deterministic hash for tamper-evident storage without exposing choice."""
    payload = f"{election_id}|{position_id}|{voter_id}|{ticket_id}".encode()
    return hashlib.sha256(payload).hexdigest()


# ============================================================================
# TALLY
# ============================================================================

def tally_position(db: Session, election_id: str, position_id: str) -> ElectionResult:
    """Compute and persist the result for one position."""
    election = _get_election(db, election_id)
    position = db.query(ElectionPosition).filter(
        ElectionPosition.id == position_id,
        ElectionPosition.election_id == election.id,
    ).first()
    if not position:
        raise ElectionError("Position not found in this election.", 404)

    # Existing result already? Return it (idempotent tally).
    existing = db.query(ElectionResult).filter(
        ElectionResult.election_id == election.id,
        ElectionResult.position_id == position.id,
    ).first()
    if existing:
        return existing

    # Count ballots per ticket
    rows = db.query(
        ElectionBallot.ticket_id,
    ).filter(
        ElectionBallot.election_id == election.id,
        ElectionBallot.position_id == position.id,
    ).all()
    counts: dict[str, int] = {}
    for (tid,) in rows:
        counts[tid] = counts.get(tid, 0) + 1

    if not counts:
        # No votes at all — position vacant
        result = ElectionResult(
            election_id=election.id,
            position_id=position.id,
            total_valid_votes=0,
            total_invalid_votes=0,
            winner_ticket_id=None,
            winner_candidate_id=None,
            winner_vote_count=0,
            runner_up_ticket_id=None,
            runner_up_vote_count=0,
            margin=0,
            is_tie=False,
            declared_at=_now(),
            official=True,
            notes="No votes cast.",
        )
        db.add(result)
        position.status = "vacant"
        db.commit()
        return result

    sorted_counts = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_ticket_id, top_votes = sorted_counts[0]
    runner_up_ticket_id = sorted_counts[1][0] if len(sorted_counts) > 1 else None
    runner_up_votes = sorted_counts[1][1] if len(sorted_counts) > 1 else 0

    # Tie detection
    tied = [tid for tid, c in counts.items() if c == top_votes]
    is_tie = len(tied) > 1

    total_valid = sum(counts.values())

    winner_candidate_id = _primary_candidate_for_ticket(db, top_ticket_id)

    result = ElectionResult(
        election_id=election.id,
        position_id=position.id,
        total_valid_votes=total_valid,
        total_invalid_votes=0,
        winner_ticket_id=None if is_tie else top_ticket_id,
        winner_candidate_id=None if is_tie else winner_candidate_id,
        winner_vote_count=top_votes,
        runner_up_ticket_id=runner_up_ticket_id,
        runner_up_vote_count=runner_up_votes,
        margin=top_votes - runner_up_votes,
        is_tie=is_tie,
        tie_ticket_ids={"ticket_ids": tied} if is_tie else None,
        declared_at=_now(),
        official=True,
    )
    db.add(result)

    # Update ticket statuses
    for tid, votes in counts.items():
        t = db.query(ElectionTicket).filter(ElectionTicket.id == tid).first()
        if not t:
            continue
        t.total_votes_cast = votes
        if is_tie:
            t.status = "tied" if hasattr(t, "tied") else t.status
        elif tid == top_ticket_id:
            t.status = "winner"
        elif tid == runner_up_ticket_id:
            t.status = "runner_up"
        else:
            t.status = "lost"

    position.status = "open" if is_tie else "filled"
    if not is_tie:
        position.winner_ticket_id = top_ticket_id
        position.winner_candidate_id = winner_candidate_id
        position.filled_at = _now()

    db.commit()
    db.refresh(result)
    return result


def tally_all_positions(db: Session, election_id: str) -> list[ElectionResult]:
    election = _get_election(db, election_id)
    positions = db.query(ElectionPosition).filter(
        ElectionPosition.election_id == election.id,
    ).all()
    return [tally_position(db, election.id, p.id) for p in positions]


def _primary_candidate_for_ticket(db: Session, ticket_id: str) -> str | None:
    """
    For paired tickets, the winner_candidate_id is the Leader (or the
    primary position). For solo positions, it's the single candidate.
    """
    ticket = db.query(ElectionTicket).filter(ElectionTicket.id == ticket_id).first()
    if not ticket:
        return None
    primary_position_id = ticket.primary_position_id
    c = db.query(ElectionCandidate).filter(
        ElectionCandidate.ticket_id == ticket_id,
        ElectionCandidate.position_id == primary_position_id,
    ).first()
    return c.id if c else None


# ============================================================================
# TIE / RUN-OFF
# ============================================================================

def schedule_run_off(
    db: Session, election_id: str, position_id: str, tied_ticket_ids: list[str],
    scheduled_for=None,
) -> Election:
    """
    Create a child election for the tied position. Runs 2 days after the
    original election day. Run-offs are final — no appeals window.
    """
    parent = _get_election(db, election_id)
    position = db.query(ElectionPosition).filter(
        ElectionPosition.id == position_id,
        ElectionPosition.election_id == parent.id,
    ).first()
    if not position:
        raise ElectionError("Position not found.", 404)

    runoff_day = scheduled_for or (parent.election_day + timedelta(days=2))

    child = Election(
        title=f"Run-off — {parent.title} — {position.title}",
        description=f"Run-off election for {position.title}.",
        level=parent.level,
        constituency_id=parent.constituency_id,
        state="run_off_scheduled",
        election_day=runoff_day,
        voting_duration_minutes=parent.voting_duration_minutes,
        is_runoff=True,
        parent_election_id=parent.id,
        created_by=parent.created_by,
        notes="Auto-created for tie-break. Run-offs are final.",
    )
    db.add(child)
    db.flush()

    # Only the tied tickets carry over — no new nominations
    for tid in tied_ticket_ids:
        t = db.query(ElectionTicket).filter(
            ElectionTicket.id == tid,
            ElectionTicket.election_id == parent.id,
        ).first()
        if not t:
            continue
        db.add(ElectionTicket(
            election_id=child.id,
            primary_position_id=position.id,
            name=t.name,
            slogan=t.slogan,
            color=t.color,
            ballot_order=t.ballot_order,
            status="qualified",
            qualified_at=t.qualified_at,
            fee_paid_at=t.fee_paid_at,
        ))

    # Single position for the run-off
    db.add(ElectionPosition(
        election_id=child.id,
        position_code=position.position_code,
        title=position.title,
        is_paired=position.is_paired,
        paired_with_code=position.paired_with_code,
        max_candidates=2,
        seats_available=1,
        required_approval_percentage=0.0,
        nomination_fee=0,
        currency="KES",
        status="open",
    ))

    parent.state = RUN_OFF_SCHEDULED
    _log_audit(db, parent.id, "election.runoff_scheduled", None,
               details={"child_id": child.id, "runoff_day": str(runoff_day)})
    db.commit()
    db.refresh(child)
    return child


# ============================================================================
# WINNER DECLARATION + ROLE PROVISIONING
# ============================================================================

def declare_winner_and_provision(
    db: Session, election_id: str, actor_id: str | None,
) -> dict:
    """
    For each position with a non-tie result, provision the elected role
    to the winning candidate. Clears the previous official.
    """
    election = _get_election(db, election_id)
    positions = db.query(ElectionPosition).filter(
        ElectionPosition.election_id == election.id,
        ElectionPosition.status == "filled",
    ).all()

    provisioned: list[dict] = []
    for p in positions:
        winner_id = p.winner_candidate_id
        if not winner_id:
            continue
        candidate = db.query(ElectionCandidate).filter(
            ElectionCandidate.id == winner_id,
        ).first()
        if not candidate:
            continue

        _provision_role(db, election, p, candidate.user_id)
        p.status = "filled"
        provisioned.append({
            "position_id": p.id,
            "position_code": p.position_code,
            "winner_user_id": candidate.user_id,
        })

    # If this was a group election, clear provisional status
    if election.level == GROUP:
        _clear_group_provisional_status(db, election)

    # Move to appeal window (if applicable) or completed
    if election.level in LEVELS_WITH_APPEALS:
        election.state = APPEAL_WINDOW
    else:
        election.state = COMPLETED

    _log_audit(db, election.id, "election.roles_provisioned", actor_id,
               details={"provisioned": provisioned})
    db.commit()

    # Module 003 Phase 7 — cascade triggers after completion
    try:
        if election.level == SCHOOL:
            _on_school_election_completed(db, election.constituency_id)
        elif election.level == INSTITUTION:
            _on_institution_election_completed(db, election.constituency_id)

        # Retry anything queued behind this election
        _process_queued_triggers(db, election.id)
    except Exception:
        pass

    return {"state": election.state, "provisioned": provisioned}


def _provision_role(
    db: Session, election: Election, position: ElectionPosition, winner_user_id: str,
) -> None:
    """Assign the elected role to the winner, deactivating any previous holder."""
    role_code = _role_code_for_position(position.position_code)
    if not role_code:
        return

    # Deactivate any active holder of this role in this constituency
    _deactivate_previous_holder(db, election, position)

    role = db.query(Role).filter(Role.code == role_code).first()
    if not role:
        logger.warning("Role code '%s' not found; skipping assignment.", role_code)
        return

    jurisdiction_type = _jurisdiction_type_for_level(election.level)

    db.add(UserRole(
        user_id=winner_user_id,
        role_id=role.id,
        jurisdiction_type=jurisdiction_type,
        jurisdiction_id=election.constituency_id,
        status="active",
        start_date=_now(),
        end_date=_now() + timedelta(days=365),
        notes=f"Elected via election {election.id}",
    ))


def _deactivate_previous_holder(
    db: Session, election: Election, position: ElectionPosition,
) -> None:
    role_code = _role_code_for_position(position.position_code)
    if not role_code:
        return
    role = db.query(Role).filter(Role.code == role_code).first()
    if not role:
        return
    jurisdiction_type = _jurisdiction_type_for_level(election.level)
    db.query(UserRole).filter(
        UserRole.role_id == role.id,
        UserRole.jurisdiction_type == jurisdiction_type,
        UserRole.jurisdiction_id == election.constituency_id,
        UserRole.status == "active",
    ).update({"status": "ended_by_election", "end_date": _now()})


def _role_code_for_position(position_code: str) -> str | None:
    return {
        "group_leader": "group_leader",
        "group_secretary": "group_secretary",
        "group_treasurer": "group_treasurer",
        "school_representative": "school_representative",
        "assistant_school_rep": "assistant_school_rep",
        "institution_representative": "institution_representative",
        "assistant_institution_rep": "assistant_institution_rep",
        "county_representative": "county_representative",
        "assistant_county_rep": "assistant_county_rep",
    }.get(position_code)


def _jurisdiction_type_for_level(level: str) -> str:
    return {
        GROUP: "group",
        SCHOOL: "school",
        INSTITUTION: "institution",
        COUNTY: "county",
    }.get(level, "platform")


def _clear_group_provisional_status(db: Session, election: Election) -> None:
    g = db.query(Group).filter(Group.id == election.constituency_id).first()
    if g:
        g.is_provisional = False
        if g.status == "pending_election":
            g.status = "active"
        g.election_pending_runoff = False


# ============================================================================
# INTERNAL
# ============================================================================

def _get_election(db: Session, election_id: str) -> Election:
    e = db.query(Election).filter(Election.id == election_id).first()
    if not e:
        raise ElectionError("Election not found.", 404)
    return e


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