"""
Election candidate service — Module 003 Phase 6.

Owns candidacy registration, approval votes (15% threshold),
nomination fee recording, ballot finalization, no-payer fallback,
and candidacy withdrawal.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.election import (
    Election, ElectionPosition, ElectionTicket,
    ElectionCandidate, ElectionApprovalVote,
    ElectionVoterRoll, ElectionNoPayerEvent, ElectionAuditEvent,
)
from app.models.group import Group
from app.models.academic import Institution, County
from app.services.election_state import (
    NOMINATING, NOMINATIONAL_VOTING, PAYMENT_WINDOW, AWAITING_PAYMENT,
    REGIONAL_ADMIN_INTERIM, BALLOT_FINALIZED, VOTING, COMPLETED,
)
from app.services.election_lifecycle_service import (
    ElectionError, LEVELS_WITH_FEE, GROUP, SCHOOL, INSTITUTION, COUNTY,
)

logger = logging.getLogger(__name__)


EXTENDED_PAYMENT_WINDOW_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# CANDIDACY REGISTRATION
# ============================================================================

def register_candidacy(db: Session, election_id: str, user_id: str, data) -> ElectionCandidate:
    election = _get_election(db, election_id)
    if election.state != NOMINATING:
        raise ElectionError(
            f"Candidacy registration is closed (state={election.state}).", 409,
        )

    position = db.query(ElectionPosition).filter(
        ElectionPosition.id == data.position_id,
        ElectionPosition.election_id == election.id,
    ).first()
    if not position:
        raise ElectionError("Position not found in this election.", 404)

    _validate_candidate_eligibility(db, election, user_id, position)

    # Reject duplicate candidacy for the same position by the same user
    existing = db.query(ElectionCandidate).filter(
        ElectionCandidate.election_id == election.id,
        ElectionCandidate.user_id == user_id,
        ElectionCandidate.position_id == position.id,
    ).first()
    if existing:
        raise ElectionError("You are already a candidate for this position.", 409)

    # --- Ticket resolution ---
    ticket = _resolve_or_create_ticket(db, election, position, data, user_id)

    candidate = ElectionCandidate(
        election_id=election.id,
        ticket_id=ticket.id,
        position_id=position.id,
        user_id=user_id,
        manifesto=data.manifesto.strip(),
        photo_url=data.photo_url,
        nominated_at=_now(),
        status="pending",
    )
    db.add(candidate)
    db.flush()

    _log_audit(db, election.id, "candidate.registered", user_id,
               details={"candidate_id": candidate.id, "position": position.position_code})
    db.commit()
    db.refresh(candidate)
    return candidate


def _resolve_or_create_ticket(
    db: Session, election: Election, position: ElectionPosition,
    data, user_id: str,
) -> ElectionTicket:
    """For paired positions, allow joining an existing partial ticket."""
    if not position.is_paired:
        ticket = ElectionTicket(
            election_id=election.id,
            primary_position_id=position.id,
            name=data.ticket_name,
            slogan=data.ticket_slogan,
            ballot_order=_next_ballot_order(db, election.id),
            status="pending_approval",
        )
        db.add(ticket)
        db.flush()
        return ticket

    # Paired — try to find a partial ticket
    ticket_id = getattr(data, "ticket_id", None)
    if ticket_id:
        ticket = db.query(ElectionTicket).filter(
            ElectionTicket.id == ticket_id,
            ElectionTicket.election_id == election.id,
        ).first()
        if not ticket:
            raise ElectionError("Ticket not found.", 404)
        # Ensure the ticket isn't already full
        existing_members = db.query(ElectionCandidate).filter(
            ElectionCandidate.ticket_id == ticket.id,
        ).count()
        if existing_members >= 2:
            raise ElectionError("Ticket is already full.", 409)
        return ticket

    # Create fresh ticket
    ticket = ElectionTicket(
        election_id=election.id,
        primary_position_id=position.id,
        name=data.ticket_name,
        slogan=data.ticket_slogan,
        ballot_order=_next_ballot_order(db, election.id),
        status="pending_approval",
    )
    db.add(ticket)
    db.flush()
    return ticket


def _next_ballot_order(db: Session, election_id: str) -> int:
    count = db.query(ElectionTicket).filter(
        ElectionTicket.election_id == election_id,
    ).count()
    return count + 1


# ============================================================================
# ELIGIBILITY
# ============================================================================

def _validate_candidate_eligibility(
    db: Session, election: Election, user_id: str, position: ElectionPosition,
) -> None:
    # The full eligibility engine lives in the group-formation / election-
    # trigger layer. Here we do a minimal sanity check.
    from app.models.user import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ElectionError("User not found.", 404)
    if user.account_status != "active":
        raise ElectionError(
            f"Account must be active to run for office (currently {user.account_status}).",
            403,
        )

    # Constituency membership check
    if election.level == GROUP:
        from app.models.group import GroupMembership
        member = db.query(GroupMembership).filter(
            GroupMembership.group_id == election.constituency_id,
            GroupMembership.user_id == user_id,
            GroupMembership.status == "active",
        ).first()
        if not member:
            raise ElectionError("You are not an active member of this group.", 403)


# ============================================================================
# APPROVAL VOTES (15% THRESHOLD)
# ============================================================================

def record_approval_vote(
    db: Session, election_id: str, candidate_id: str, voter_id: str,
) -> dict:
    election = _get_election(db, election_id)
    if election.state != NOMINATIONAL_VOTING:
        raise ElectionError(
            f"Approval votes are not being accepted (state={election.state}).", 409,
        )

    candidate = _get_candidate(db, candidate_id, election_id)

    # Voter must be in the frozen roll
    roll_entry = db.query(ElectionVoterRoll).filter(
        ElectionVoterRoll.election_id == election.id,
        ElectionVoterRoll.user_id == voter_id,
        ElectionVoterRoll.eligible.is_(True),
    ).first()
    if not roll_entry:
        raise ElectionError("You are not eligible to vote in this election.", 403)

    # One approval per voter per candidate
    existing = db.query(ElectionApprovalVote).filter(
        ElectionApprovalVote.election_id == election.id,
        ElectionApprovalVote.candidate_id == candidate.id,
        ElectionApprovalVote.voter_id == voter_id,
    ).first()
    if existing:
        return _candidate_status(db, candidate)

    db.add(ElectionApprovalVote(
        election_id=election.id,
        candidate_id=candidate.id,
        voter_id=voter_id,
        cast_at=_now(),
    ))
    db.flush()

    _recalc_candidate_approval(db, candidate)
    _maybe_qualify_candidate(db, candidate, election)
    db.commit()
    return _candidate_status(db, candidate)


def _recalc_candidate_approval(db: Session, candidate: ElectionCandidate) -> None:
    count = db.query(ElectionApprovalVote).filter(
        ElectionApprovalVote.candidate_id == candidate.id,
    ).count()
    candidate.approval_count = count
    if candidate.election:
        electorate_size = candidate.election.electorate_size or 1
    else:
        election = db.query(Election).filter(Election.id == candidate.election_id).first()
        electorate_size = (election.electorate_size or 1) if election else 1
    candidate.approval_percentage = round((count / electorate_size) * 100, 2)


def _maybe_qualify_candidate(
    db: Session, candidate: ElectionCandidate, election: Election,
) -> None:
    position = db.query(ElectionPosition).filter(
        ElectionPosition.id == candidate.position_id,
    ).first()
    if not position:
        return
    if candidate.approval_percentage >= position.required_approval_percentage:
        if candidate.status == "pending":
            candidate.status = "qualified"
            candidate.qualified_at = _now()
            # Ticket inherits qualified status once its primary candidate qualifies
            ticket = db.query(ElectionTicket).filter(
                ElectionTicket.id == candidate.ticket_id,
            ).first()
            if ticket and ticket.status == "pending_approval":
                ticket.status = "qualified"
                ticket.qualified_at = _now()


# ============================================================================
# FEE
# ============================================================================

def record_nomination_fee(
    db: Session, candidate_id: str, payment_reference: str,
) -> ElectionCandidate:
    candidate = _get_candidate(db, candidate_id)
    if candidate.fee_paid:
        return candidate

    if candidate.status != "qualified":
        raise ElectionError(
            "Candidate has not reached the approval threshold yet.", 409,
        )

    candidate.fee_paid = True
    candidate.fee_payment_reference = payment_reference
    candidate.fee_paid_at = _now()

    ticket = db.query(ElectionTicket).filter(
        ElectionTicket.id == candidate.ticket_id,
    ).first()
    if ticket and ticket.status == "qualified":
        ticket.fee_paid_at = _now()

    _log_audit(db, candidate.election_id, "candidate.fee_paid", None,
               details={"candidate_id": candidate.id, "ref": payment_reference})
    db.commit()
    db.refresh(candidate)
    return candidate


# ============================================================================
# BALLOT FINALIZATION
# ============================================================================

def finalize_ballot(db: Session, election_id: str, actor_id: str | None) -> dict:
    """
    Remove non-payers from the ballot. Sets the election to
    ballot_finalized state.
    If nobody paid, move to awaiting_payment instead.
    """
    election = _get_election(db, election_id)
    if election.state not in (PAYMENT_WINDOW, NOMINATIONAL_VOTING):
        raise ElectionError(
            f"Cannot finalize ballot in state '{election.state}'.", 409,
        )

    total_candidates = db.query(ElectionCandidate).filter(
        ElectionCandidate.election_id == election.id,
        ElectionCandidate.status.in_(("qualified", "pending")),
    ).count()
    paid_candidates = db.query(ElectionCandidate).filter(
        ElectionCandidate.election_id == election.id,
        ElectionCandidate.fee_paid.is_(True),
    ).all()

    removed = 0
    for c in db.query(ElectionCandidate).filter(
        ElectionCandidate.election_id == election.id,
        ElectionCandidate.fee_paid.is_(False),
    ).all():
        c.status = "disqualified"
        removed += 1

    if not paid_candidates:
        # Nobody paid — go to extended payment window
        election.state = AWAITING_PAYMENT
        db.add(ElectionNoPayerEvent(
            election_id=election.id,
            triggered_at=_now(),
            phase="extended_window_started",
            notes=(
                f"Zero paid candidates of {total_candidates}. "
                f"{EXTENDED_PAYMENT_WINDOW_DAYS}-day extension granted."
            ),
        ))
        election.payment_window_end = _now() + timedelta(
            days=EXTENDED_PAYMENT_WINDOW_DAYS,
        )
        db.commit()
        return {
            "state": AWAITING_PAYMENT,
            "removed": removed,
            "message": "No candidates paid. Extended window opened.",
        }

    # Some paid — finalize ballot
    election.state = BALLOT_FINALIZED
    election.ballot_finalized_at = _now()
    db.commit()
    return {
        "state": BALLOT_FINALIZED,
        "removed": removed,
        "message": f"{len(paid_candidates)} candidate(s) on final ballot.",
    }


# ============================================================================
# NO-PAYER FALLBACK
# ============================================================================

def apply_no_payer_fallback(
    db: Session, election_id: str, actor_id: str | None,
) -> dict:
    """
    Called after the extended payment window expires with zero payers.
    Puts the position under Regional Admin interim. The corresponding
    constituency entity gets flagged.
    """
    election = _get_election(db, election_id)
    if election.state != AWAITING_PAYMENT:
        raise ElectionError(
            f"Cannot apply no-payer fallback in state '{election.state}'.", 409,
        )

    election.state = REGIONAL_ADMIN_INTERIM
    election.under_regional_admin = True

    # Flag the constituency
    _flag_constituency_for_regional_admin(db, election)

    db.add(ElectionNoPayerEvent(
        election_id=election.id,
        triggered_at=_now(),
        phase="interim_started",
        notes="Position placed under Regional Admin until Super Admin assigns.",
    ))
    _log_audit(db, election.id, "election.regional_admin_interim", actor_id)
    db.commit()
    return {
        "state": REGIONAL_ADMIN_INTERIM,
        "message": "Position under Regional Admin interim.",
    }


def _flag_constituency_for_regional_admin(db: Session, election: Election) -> None:
    if election.level == INSTITUTION:
        inst = db.query(Institution).filter(
            Institution.id == election.constituency_id,
        ).first()
        if inst:
            inst.under_regional_admin = True
    elif election.level == COUNTY:
        c = db.query(County).filter(County.id == election.constituency_id).first()
        if c:
            c.under_regional_admin = True
    elif election.level == GROUP:
        g = db.query(Group).filter(Group.id == election.constituency_id).first()
        if g:
            g.under_regional_admin = True


# ============================================================================
# WITHDRAWAL
# ============================================================================

def withdraw_candidacy(db: Session, candidate_id: str, actor_id: str) -> ElectionCandidate:
    candidate = _get_candidate(db, candidate_id)
    election = _get_election(db, candidate.election_id)
    if candidate.user_id != actor_id:
        raise ElectionError("You can only withdraw your own candidacy.", 403)
    if election.state in (VOTING, COUNTING, BALLOT_FINALIZED):
        raise ElectionError(
            "Withdrawal is not allowed once the ballot is finalized.", 409,
        )
    candidate.status = "withdrawn"
    _log_audit(db, election.id, "candidate.withdrawn", actor_id,
               details={"candidate_id": candidate_id})
    db.commit()
    db.refresh(candidate)
    return candidate


# ============================================================================
# READ
# ============================================================================

def list_candidates(
    db: Session, election_id: str, position_id: str | None = None,
) -> list[ElectionCandidate]:
    q = db.query(ElectionCandidate).filter(
        ElectionCandidate.election_id == election_id,
    )
    if position_id:
        q = q.filter(ElectionCandidate.position_id == position_id)
    return q.order_by(ElectionCandidate.nominated_at).all()


def list_tickets(db: Session, election_id: str) -> list[ElectionTicket]:
    return (
        db.query(ElectionTicket)
        .filter(ElectionTicket.election_id == election_id)
        .order_by(ElectionTicket.ballot_order)
        .all()
    )


def candidate_approval_status(db: Session, candidate_id: str) -> dict:
    c = _get_candidate(db, candidate_id)
    e = _get_election(db, c.election_id)
    p = db.query(ElectionPosition).filter(ElectionPosition.id == c.position_id).first()
    required = p.required_approval_percentage if p else 15.0
    return {
        "candidate_id": c.id,
        "user_id": c.user_id,
        "position_id": c.position_id,
        "ticket_id": c.ticket_id,
        "approval_count": c.approval_count,
        "electorate_size": e.electorate_size,
        "approval_percentage": c.approval_percentage,
        "required_percentage": required,
        "qualified": c.status == "qualified",
        "fee_paid": c.fee_paid,
        "on_final_ballot": c.status == "qualified" and c.fee_paid,
    }


# ============================================================================
# INTERNAL
# ============================================================================

def _get_election(db: Session, election_id: str) -> Election:
    e = db.query(Election).filter(Election.id == election_id).first()
    if not e:
        raise ElectionError("Election not found.", 404)
    return e


def _get_candidate(db: Session, candidate_id: str, election_id: str | None = None) -> ElectionCandidate:
    q = db.query(ElectionCandidate).filter(ElectionCandidate.id == candidate_id)
    if election_id:
        q = q.filter(ElectionCandidate.election_id == election_id)
    c = q.first()
    if not c:
        raise ElectionError("Candidate not found.", 404)
    return c


def _candidate_status(db: Session, c: ElectionCandidate) -> dict:
    return candidate_approval_status(db, c.id)


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