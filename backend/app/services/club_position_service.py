"""
Club position service — Module 003 Phase 10.

Handles:
  - Standard positions seed (done in lifecycle, exposed for re-seed)
  - Custom positions (founder: pre-first-election; leader: 3+ days after
    positions published + fee paid)
  - Position retirement
  - Member voting on add/retire proposals (2/3 threshold)
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.activity_club import (
    ActivityClub, ActivityClubPosition,
    ActivityClubElectionCycle,
    ActivityClubPositionApprovalVote, ActivityClubPositionApprovalBallot,
    STANDARD_POSITIONS, MAX_CUSTOM_POSITIONS,
    POSITION_APPROVAL_DELAY_DAYS,
    ELECTION_FEE,
)
from app.services.club_audit_service import log_club_event


logger = logging.getLogger(__name__)


RETIREMENT_THRESHOLD = 2 / 3
ADDITION_THRESHOLD = 2 / 3


class ClubPositionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# FOUNDER — CUSTOM POSITIONS (pre-first-election)
# ─────────────────────────────────────────────────────────────────────────

def add_custom_position_by_founder(
    db: Session, club_id: str, actor_id: str, data,
) -> ActivityClubPosition:
    """
    Founder may add a custom position at any time before the first
    election cycle is initiated. No vote required.
    """
    club = _get_club(db, club_id)
    if actor_id != club.founder_id:
        raise ClubPositionError("Only the founder may use this path.", 403)
    if club.status not in ("forming",):
        raise ClubPositionError(
            "Custom positions can only be added by the founder during forming.",
            409,
        )

    first_cycle = db.query(ActivityClubElectionCycle).filter(
        ActivityClubElectionCycle.club_id == club.id,
    ).count()
    if first_cycle > 0:
        raise ClubPositionError(
            "Founder override is only available before the first election cycle.",
            409,
        )

    return _create_custom_position(db, club, data, actor_id, cycle_number=0)


# ─────────────────────────────────────────────────────────────────────────
# LEADER — CUSTOM POSITIONS (post 3-day window)
# ─────────────────────────────────────────────────────────────────────────

def propose_custom_position(
    db: Session, club_id: str, actor_id: str, data,
) -> ActivityClubPositionApprovalVote:
    club = _get_club(db, club_id)
    _assert_leader(db, club, actor_id)

    # Must be at least 3 days after positions were published AND fee paid
    cycle = _get_latest_open_cycle(db, club.id)
    if not cycle:
        raise ClubPositionError(
            "No open election cycle. Custom position proposals are only "
            "available during an active cycle.", 409,
        )
    if not cycle.positions_published_at:
        raise ClubPositionError(
            "Positions have not been published yet for this cycle.", 409,
        )
    if not cycle.election_fee_paid:
        raise ClubPositionError(
            "Election fee has not been paid for this cycle.", 409,
        )
    cutoff = cycle.positions_published_at + timedelta(days=POSITION_APPROVAL_DELAY_DAYS)
    if _now() < cutoff:
        raise ClubPositionError(
            f"Custom positions may be proposed from {cutoff.isoformat()}.", 409,
        )

    # Check custom count cap
    custom_count = db.query(ActivityClubPosition).filter(
        ActivityClubPosition.club_id == club.id,
        ActivityClubPosition.position_type == "custom",
        ActivityClubPosition.status == "active",
    ).count()
    if custom_count >= MAX_CUSTOM_POSITIONS:
        raise ClubPositionError(
            f"Cannot add more than {MAX_CUSTOM_POSITIONS} custom positions.",
            409,
        )

    existing = db.query(ActivityClubPosition).filter(
        ActivityClubPosition.club_id == club.id,
        ActivityClubPosition.position_code == data.position_code,
    ).first()
    if existing:
        raise ClubPositionError(
            "A position with this code already exists.", 409,
        )

    proposal = ActivityClubPositionApprovalVote(
        club_id=club.id,
        cycle_id=cycle.id,
        proposal_type="add_custom",
        proposed_code=data.position_code,
        proposed_title=data.title,
        proposed_description=data.description,
        proposed_by=actor_id,
        proposed_at=_now(),
        status="proposed",
        required_threshold=ADDITION_THRESHOLD,
    )
    db.add(proposal)

    log_club_event(
        db, club.id, "club.position_approval_proposed", actor_id=actor_id,
        details={"type": "add_custom", "code": data.position_code},
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def propose_position_retirement(
    db: Session, club_id: str, actor_id: str, data,
) -> ActivityClubPositionApprovalVote:
    club = _get_club(db, club_id)
    _assert_leader(db, club, actor_id)

    position = db.query(ActivityClubPosition).filter(
        ActivityClubPosition.id == data.position_id,
        ActivityClubPosition.club_id == club.id,
        ActivityClubPosition.status == "active",
    ).first()
    if not position:
        raise ClubPositionError("Position not found or already retired.", 404)

    cycle = _get_latest_open_cycle(db, club.id)

    proposal = ActivityClubPositionApprovalVote(
        club_id=club.id,
        cycle_id=cycle.id if cycle else None,
        target_position_id=position.id,
        proposal_type="retire_position",
        retirement_reason=data.reason,
        proposed_by=actor_id,
        proposed_at=_now(),
        status="proposed",
        required_threshold=RETIREMENT_THRESHOLD,
    )
    db.add(proposal)

    log_club_event(
        db, club.id, "club.position_approval_proposed", actor_id=actor_id,
        details={"type": "retire_position", "position_id": position.id},
    )
    db.commit()
    db.refresh(proposal)
    return proposal


# ─────────────────────────────────────────────────────────────────────────
# MEMBER VOTING
# ─────────────────────────────────────────────────────────────────────────

def vote_on_position_proposal(
    db: Session, proposal_id: str, voter_id: str, vote: str,
) -> ActivityClubPositionApprovalVote:
    if vote not in ("yes", "no"):
        raise ClubPositionError("vote must be 'yes' or 'no'.", 400)

    proposal = db.query(ActivityClubPositionApprovalVote).filter(
        ActivityClubPositionApprovalVote.id == proposal_id,
    ).first()
    if not proposal:
        raise ClubPositionError("Proposal not found.", 404)
    if proposal.status != "proposed":
        raise ClubPositionError(
            f"Proposal is not open (status={proposal.status}).", 409,
        )

    # Voter must be an active member of the club
    from app.models.activity_club import ActivityClubMembership
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == proposal.club_id,
        ActivityClubMembership.user_id == voter_id,
        ActivityClubMembership.status == "active",
    ).first()
    if not m:
        raise ClubPositionError("Only active members may vote.", 403)

    existing = db.query(ActivityClubPositionApprovalBallot).filter(
        ActivityClubPositionApprovalBallot.proposal_id == proposal_id,
        ActivityClubPositionApprovalBallot.voter_id == voter_id,
    ).first()
    if existing:
        raise ClubPositionError("You have already voted.", 409)

    db.add(ActivityClubPositionApprovalBallot(
        proposal_id=proposal_id,
        voter_id=voter_id,
        vote=vote,
        cast_at=_now(),
    ))
    db.flush()

    yes = db.query(ActivityClubPositionApprovalBallot).filter(
        ActivityClubPositionApprovalBallot.proposal_id == proposal_id,
        ActivityClubPositionApprovalBallot.vote == "yes",
    ).count()
    no = db.query(ActivityClubPositionApprovalBallot).filter(
        ActivityClubPositionApprovalBallot.proposal_id == proposal_id,
        ActivityClubPositionApprovalBallot.vote == "no",
    ).count()
    proposal.votes_for = yes
    proposal.votes_against = no

    db.commit()
    db.refresh(proposal)

    _maybe_finalize(db, proposal)
    return proposal


def _maybe_finalize(
    db: Session, proposal: ActivityClubPositionApprovalVote,
) -> None:
    from app.models.activity_club import ActivityClubMembership

    club = db.query(ActivityClub).filter(
        ActivityClub.id == proposal.club_id,
    ).first()
    total_members = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == proposal.club_id,
        ActivityClubMembership.status == "active",
    ).count()
    if total_members == 0:
        return

    required_yes = math.ceil(proposal.required_threshold * total_members)
    total_votes = proposal.votes_for + proposal.votes_against
    remaining = total_members - total_votes

    if proposal.votes_for >= required_yes:
        _apply_proposal(db, proposal, approved=True)
        return
    if proposal.votes_for + remaining < required_yes:
        _apply_proposal(db, proposal, approved=False)
        return


def _apply_proposal(
    db: Session, proposal: ActivityClubPositionApprovalVote, approved: bool,
) -> None:
    proposal.status = "approved" if approved else "rejected"
    proposal.decided_at = _now()

    if not approved:
        log_club_event(
            db, proposal.club_id, "club.position_approval_decided",
            actor_id=None,
            details={"proposal_id": proposal.id, "outcome": "rejected"},
        )
        db.commit()
        return

    club = db.query(ActivityClub).filter(
        ActivityClub.id == proposal.club_id,
    ).first()
    if not club:
        db.commit()
        return

    if proposal.proposal_type == "add_custom":
        cycle_number = 0
        if proposal.cycle_id:
            cycle = db.query(ActivityClubElectionCycle).filter(
                ActivityClubElectionCycle.id == proposal.cycle_id,
            ).first()
            if cycle:
                cycle_number = cycle.cycle_number
        _create_custom_position(
            db,
            club,
            data=_ProposalData(
                position_code=proposal.proposed_code,
                title=proposal.proposed_title,
                description=proposal.proposed_description,
            ),
            actor_id=proposal.proposed_by,
            cycle_number=cycle_number,
        )

    elif proposal.proposal_type == "retire_position":
        if proposal.target_position_id:
            pos = db.query(ActivityClubPosition).filter(
                ActivityClubPosition.id == proposal.target_position_id,
            ).first()
            if pos:
                pos.status = "retired"
                pos.retired_at = _now()
                pos.retired_by = proposal.proposed_by
                pos.retired_in_cycle = 0

    log_club_event(
        db, proposal.club_id, "club.position_approval_decided",
        actor_id=None,
        details={"proposal_id": proposal.id, "outcome": "approved"},
    )
    db.commit()


# ─────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────

class _ProposalData:
    def __init__(self, position_code, title, description):
        self.position_code = position_code
        self.title = title
        self.description = description


def _create_custom_position(
    db: Session, club: ActivityClub, data, actor_id: str, cycle_number: int,
) -> ActivityClubPosition:
    max_order = db.query(ActivityClubPosition).filter(
        ActivityClubPosition.club_id == club.id,
    ).count()

    pos = ActivityClubPosition(
        club_id=club.id,
        position_code=data.position_code,
        title=data.title,
        description=data.description,
        position_type="custom",
        display_order=max_order,
        introduced_in_cycle=cycle_number,
        introduced_by=actor_id,
        status="active",
    )
    db.add(pos)
    club.position_count = (club.position_count or 0) + 1
    db.flush()
    return pos


def _assert_leader(db: Session, club: ActivityClub, actor_id: str) -> None:
    from app.models.activity_club import ActivityClubMembership
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club.id,
        ActivityClubMembership.user_id == actor_id,
        ActivityClubMembership.status == "active",
    ).first()
    if not m or m.role != "leader":
        raise ClubPositionError("Only the elected leader may propose this.", 403)


def _get_latest_open_cycle(
    db: Session, club_id: str,
) -> ActivityClubElectionCycle | None:
    return (
        db.query(ActivityClubElectionCycle)
        .filter(
            ActivityClubElectionCycle.club_id == club_id,
            ActivityClubElectionCycle.status.in_(
                ("positions_published", "candidates_open", "voting")
            ),
        )
        .order_by(ActivityClubElectionCycle.cycle_number.desc())
        .first()
    )


def _get_club(db: Session, club_id: str) -> ActivityClub:
    c = db.query(ActivityClub).filter(ActivityClub.id == club_id).first()
    if not c:
        raise ClubPositionError("Club not found.", 404)
    return c


def list_positions(
    db: Session, club_id: str, status: str | None = "active",
) -> list[ActivityClubPosition]:
    q = db.query(ActivityClubPosition).filter(
        ActivityClubPosition.club_id == club_id,
    )
    if status:
        q = q.filter(ActivityClubPosition.status == status)
    return q.order_by(ActivityClubPosition.display_order).all()