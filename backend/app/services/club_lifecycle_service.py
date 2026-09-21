"""
Club lifecycle service — Module 003 Phase 10.

Owns:
  - Creation + dual approval chain (Institution Rep → Regional Rep)
  - Forming period transitions
  - Dissolution (soft delete with snapshot)
  - Revival petitions
  - County promotion
  - Founder removal (post-first-election, 2/3 vote)
"""
import logging
import math
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.invite_security import generate_unique_slug
from app.models.academic import Institution
from app.models.activity_club import (
    ActivityClub, ActivityClubMembership, ActivityClubPosition,
    ActivityClubElectionCycle, ActivityClubMilestone,
    ActivityClubDissolutionEvent, ActivityClubRevivalPetition,
    VISIBILITY_PUBLIC, VISIBILITY_PRIVATE,
    STANDARD_POSITIONS, MAX_CUSTOM_POSITIONS,
    FORMING_PERIOD_DAYS, DEBATE_WINDOW_DAYS, FIRST_CYCLE_OFFSET_DAYS,
    INSTITUTION_CLUB_MEMBER_CAP, COUNTY_CLUB_MEMBER_CAP,
    PROMOTION_FEE, MAX_CLUBS_PER_STUDENT,
)
from app.models.user import User
from app.services.club_audit_service import log_club_event


logger = logging.getLogger(__name__)


# ── constants ────────────────────────────────────────────────────────────

FOUNDER_VOTE_THRESHOLD = 2 / 3


# ── exceptions ───────────────────────────────────────────────────────────

class ClubError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# CREATION + DUAL APPROVAL
# ─────────────────────────────────────────────────────────────────────────

def create_club_request(
    db: Session, data, founder_id: str,
    ip: str | None = None, ua: str | None = None,
) -> ActivityClub:
    """
    Founder files a club request. Club enters approval_stage
    'pending_institution_rep'. No forming clock starts until Regional
    Rep approves.
    """
    inst = db.query(Institution).filter(
        Institution.id == data.institution_id,
    ).first()
    if not inst:
        raise ClubError("Institution not found.", 404)

    founder = db.query(User).filter(User.id == founder_id).first()
    if not founder:
        raise ClubError("Founder not found.", 404)
    if founder.user_type != "student":
        raise ClubError("Only students may found activity clubs.", 403)

    if data.membership_visibility not in (VISIBILITY_PUBLIC, VISIBILITY_PRIVATE):
        raise ClubError(
            "membership_visibility must be 'public' or 'private'.", 400,
        )

    existing = db.query(ActivityClub).filter(
        ActivityClub.institution_id == data.institution_id,
        ActivityClub.name == data.name.strip(),
    ).first()
    if existing:
        raise ClubError(
            "A club with this name already exists at this institution.", 409,
        )

    slug = generate_unique_slug(db, data.name.strip())

    club = ActivityClub(
        name=data.name.strip(),
        slug=slug,
        description=data.description,
        objective=data.objective.strip(),
        motive=data.motive.strip(),
        institution_id=data.institution_id,
        founder_id=founder_id,
        membership_visibility=data.membership_visibility,
        current_level="institution",
        status="forming",                       # provisional; approval_stage gates
        approval_stage="pending_institution_rep",
        member_count=0,
        position_count=0,
    )
    db.add(club)
    db.flush()

    # Founder auto-joins as provisional leader
    db.add(ActivityClubMembership(
        club_id=club.id,
        user_id=founder_id,
        status="active",
        role="leader",
        joined_at=_now(),
    ))
    club.member_count = 1

    log_club_event(
        db, club.id, "club.created", actor_id=founder_id,
        to_state="pending_institution_rep",
        details={"name": club.name}, ip=ip, ua=ua,
    )
    db.commit()
    db.refresh(club)
    return club


def institution_rep_approve(
    db: Session, club_id: str, actor_id: str,
    notes: str | None = None,
    ip: str | None = None, ua: str | None = None,
) -> ActivityClub:
    club = _get(db, club_id)
    if club.approval_stage != "pending_institution_rep":
        raise ClubError(
            f"Club is not awaiting Institution Rep approval "
            f"(stage={club.approval_stage}).", 409,
        )

    club.institution_rep_approved_at = _now()
    club.institution_rep_approved_by = actor_id
    club.institution_rep_notes = notes
    club.approval_stage = "pending_regional_rep"

    log_club_event(
        db, club.id, "club.institution_rep_approved", actor_id=actor_id,
        from_state="pending_institution_rep", to_state="pending_regional_rep",
        details={"notes": notes}, ip=ip, ua=ua,
    )
    db.commit()
    db.refresh(club)
    return club


def institution_rep_reject(
    db: Session, club_id: str, actor_id: str, reason: str,
    ip: str | None = None, ua: str | None = None,
) -> ActivityClub:
    club = _get(db, club_id)
    if club.approval_stage != "pending_institution_rep":
        raise ClubError("Club is not awaiting Institution Rep approval.", 409)
    if not reason or len(reason.strip()) < 5:
        raise ClubError("A rejection reason is required.", 400)

    club.approval_stage = "rejected"
    club.rejection_reason = reason.strip()
    club.status = "dissolved"
    club.dissolved_at = _now()

    log_club_event(
        db, club.id, "club.institution_rep_rejected", actor_id=actor_id,
        from_state="pending_institution_rep", to_state="rejected",
        details={"reason": reason}, ip=ip, ua=ua,
    )
    db.commit()
    db.refresh(club)
    return club


def regional_rep_approve(
    db: Session, club_id: str, actor_id: str,
    notes: str | None = None,
    ip: str | None = None, ua: str | None = None,
) -> ActivityClub:
    club = _get(db, club_id)
    if club.approval_stage != "pending_regional_rep":
        raise ClubError(
            "Club is not awaiting Regional Rep approval.", 409,
        )

    now = _now()
    club.regional_rep_approved_at = now
    club.regional_rep_approved_by = actor_id
    club.regional_rep_notes = notes
    club.approval_stage = "approved"

    # Forming clock starts NOW
    club.formed_at = now
    club.positions_published_at = now + timedelta(days=FORMING_PERIOD_DAYS)
    club.first_cycle_due_at = now + timedelta(days=FIRST_CYCLE_OFFSET_DAYS)

    # Seed the 12 standard positions
    _seed_standard_positions(db, club)

    log_club_event(
        db, club.id, "club.regional_rep_approved", actor_id=actor_id,
        from_state="pending_regional_rep", to_state="approved",
        details={
            "notes": notes,
            "positions_published_at": club.positions_published_at.isoformat(),
            "first_cycle_due_at": club.first_cycle_due_at.isoformat(),
        }, ip=ip, ua=ua,
    )
    db.commit()
    db.refresh(club)
    return club


def regional_rep_reject(
    db: Session, club_id: str, actor_id: str, reason: str,
    required_changes: list[str] | None = None,
    ip: str | None = None, ua: str | None = None,
) -> ActivityClub:
    club = _get(db, club_id)
    if club.approval_stage != "pending_regional_rep":
        raise ClubError("Club is not awaiting Regional Rep approval.", 409)
    if not reason or len(reason.strip()) < 5:
        raise ClubError("A rejection reason is required.", 400)

    club.approval_stage = "rejected"
    club.rejection_reason = reason.strip()
    club.status = "dissolved"
    club.dissolved_at = _now()

    log_club_event(
        db, club.id, "club.regional_rep_rejected", actor_id=actor_id,
        from_state="pending_regional_rep", to_state="rejected",
        details={
            "reason": reason,
            "required_changes": required_changes or [],
        }, ip=ip, ua=ua,
    )
    db.commit()
    db.refresh(club)
    return club


# ─────────────────────────────────────────────────────────────────────────
# FORMING → ACTIVE HANDLING
# ─────────────────────────────────────────────────────────────────────────

def publish_positions(
    db: Session, club_id: str, actor_id: str | None = None,
) -> ActivityClub:
    """
    Transition the club through the 'positions published' event.
    Called manually or by a scheduled job once positions_published_at
    has elapsed. Idempotent.
    """
    club = _get(db, club_id)
    if club.status != "forming":
        raise ClubError(
            f"Club is not in forming state (status={club.status}).", 409,
        )
    if not club.formed_at:
        raise ClubError("Club is not yet approved.", 409)
    if club.positions_published_at and _now() < club.positions_published_at:
        raise ClubError(
            f"Positions cannot be published until "
            f"{club.positions_published_at.isoformat()}.", 409,
        )

    log_club_event(
        db, club.id, "club.positions_published", actor_id=actor_id,
        details={"positions": club.position_count},
    )
    db.commit()
    db.refresh(club)
    return club


def mark_club_active(
    db: Session, club_id: str,
) -> ActivityClub:
    """Called after the first election cycle completes."""
    club = _get(db, club_id)
    if club.status not in ("forming", "halted"):
        raise ClubError(
            f"Cannot activate club from status '{club.status}'.", 409,
        )
    old = club.status
    club.status = "active"
    log_club_event(
        db, club.id, "club.cycle_completed", actor_id=None,
        from_state=old, to_state="active",
    )
    db.commit()
    db.refresh(club)
    return club


# ─────────────────────────────────────────────────────────────────────────
# DISSOLUTION
# ─────────────────────────────────────────────────────────────────────────

def dissolve_club(
    db: Session, club_id: str, *,
    trigger: str, reason: str, actor_id: str | None = None,
) -> ActivityClub:
    """
    Soft delete. Snapshots members, positions, milestones to
    ActivityClubDissolutionEvent. Club status → 'dissolved'.
    """
    club = _get(db, club_id)
    if club.status == "dissolved":
        return club

    snapshot = _build_snapshot(db, club)
    ev = ActivityClubDissolutionEvent(
        club_id=club.id,
        trigger=trigger,
        reason=reason,
        triggered_by=actor_id,
        triggered_at=_now(),
        snapshot_json=snapshot,
    )
    db.add(ev)

    old = club.status
    club.status = "dissolved"
    club.dissolved_at = _now()
    club.halt_warning_at = None
    club.halt_recovery_deadline = None

    log_club_event(
        db, club.id, "club.dissolved", actor_id=actor_id,
        from_state=old, to_state="dissolved",
        details={"trigger": trigger, "reason": reason},
    )
    db.commit()
    db.refresh(club)
    return club


def _build_snapshot(db: Session, club: ActivityClub) -> dict:
    members = [
        {"user_id": m.user_id, "role": m.role, "status": m.status}
        for m in db.query(ActivityClubMembership).filter(
            ActivityClubMembership.club_id == club.id,
        ).all()
    ]
    positions = [
        {"position_code": p.position_code, "title": p.title,
         "position_type": p.position_type, "current_holder_id": p.current_holder_id}
        for p in db.query(ActivityClubPosition).filter(
            ActivityClubPosition.club_id == club.id,
        ).all()
    ]
    milestones = [
        {"title": m.title, "period_start": str(m.period_start),
         "period_end": str(m.period_end), "status": m.status}
        for m in db.query(ActivityClubMilestone).filter(
            ActivityClubMilestone.club_id == club.id,
        ).all()
    ]
    return {
        "members": members,
        "positions": positions,
        "milestones": milestones,
        "dissolved_at": club.dissolved_at.isoformat() if club.dissolved_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────
# REVIVAL
# ─────────────────────────────────────────────────────────────────────────

def file_revival_petition(
    db: Session, club_id: str, filer_id: str, data,
    ip: str | None = None, ua: str | None = None,
) -> ActivityClubRevivalPetition:
    club = _get(db, club_id)
    if club.status != "dissolved":
        raise ClubError("Only dissolved clubs can be revived.", 409)
    if not data.letter_text or len(data.letter_text.strip()) < 50:
        raise ClubError("The revival letter must be at least 50 characters.", 400)

    existing = db.query(ActivityClubRevivalPetition).filter(
        ActivityClubRevivalPetition.club_id == club.id,
        ActivityClubRevivalPetition.status.in_(("filed", "under_review")),
    ).first()
    if existing:
        raise ClubError("An active revival petition already exists.", 409)

    last_dissolution = db.query(ActivityClubDissolutionEvent).filter(
        ActivityClubDissolutionEvent.club_id == club.id,
    ).order_by(ActivityClubDissolutionEvent.triggered_at.desc()).first()

    petition = ActivityClubRevivalPetition(
        club_id=club.id,
        dissolution_event_id=last_dissolution.id if last_dissolution else None,
        filed_by=filer_id,
        filed_at=_now(),
        letter_text=data.letter_text.strip(),
        supporting_urls_json=data.supporting_urls,
        status="filed",
    )
    db.add(petition)

    log_club_event(
        db, club.id, "club.revival_petition_filed", actor_id=filer_id,
        details={"letter_length": len(data.letter_text)},
        ip=ip, ua=ua,
    )
    db.commit()
    db.refresh(petition)
    return petition


def review_revival_petition(
    db: Session, petition_id: str, actor_id: str, data,
    ip: str | None = None, ua: str | None = None,
) -> ActivityClubRevivalPetition:
    pet = db.query(ActivityClubRevivalPetition).filter(
        ActivityClubRevivalPetition.id == petition_id,
    ).first()
    if not pet:
        raise ClubError("Revival petition not found.", 404)
    if pet.status not in ("filed", "under_review"):
        raise ClubError(
            f"Petition is not under review (status={pet.status}).", 409,
        )

    pet.reviewed_by = actor_id
    pet.reviewed_at = _now()
    pet.review_notes = data.notes
    pet.status = "approved" if data.approve else "rejected"

    if data.approve:
        club = _get(db, pet.club_id)
        # Reinstate members from the snapshot
        reinstated = _reinstate_from_snapshot(db, club, pet)
        pet.approved_at = _now()
        pet.members_reinstated_count = reinstated

        club.status = "active"
        club.revived_at = _now()
        club.dissolved_at = None

        log_club_event(
            db, club.id, "club.revived", actor_id=actor_id,
            from_state="dissolved", to_state="active",
            details={"reinstated": reinstated}, ip=ip, ua=ua,
        )
    else:
        log_club_event(
            db, pet.club_id, "club.revival_rejected", actor_id=actor_id,
            details={"notes": data.notes}, ip=ip, ua=ua,
        )

    db.commit()
    db.refresh(pet)
    return pet


def _reinstate_from_snapshot(
    db: Session, club: ActivityClub, petition: ActivityClubRevivalPetition,
) -> int:
    if not petition.dissolution_event_id:
        return 0
    ev = db.query(ActivityClubDissolutionEvent).filter(
        ActivityClubDissolutionEvent.id == petition.dissolution_event_id,
    ).first()
    if not ev or not ev.snapshot_json:
        return 0

    count = 0
    for entry in ev.snapshot_json.get("members", []):
        uid = entry.get("user_id")
        if not uid:
            continue
        existing = db.query(ActivityClubMembership).filter(
            ActivityClubMembership.club_id == club.id,
            ActivityClubMembership.user_id == uid,
        ).first()
        if existing:
            existing.status = "active"
            existing.left_at = None
        else:
            db.add(ActivityClubMembership(
                club_id=club.id,
                user_id=uid,
                status="active",
                role=entry.get("role", "member"),
                joined_at=_now(),
            ))
        count += 1

    club.member_count = count
    return count


# ─────────────────────────────────────────────────────────────────────────
# COUNTY PROMOTION
# ─────────────────────────────────────────────────────────────────────────

def promote_to_county(
    db: Session, club_id: str, actor_id: str, payment_reference: str,
    method: str = "mpesa",
    ip: str | None = None, ua: str | None = None,
) -> ActivityClub:
    club = _get(db, club_id)
    if club.status not in ("active", "forming"):
        raise ClubError(
            f"Cannot promote a club in status '{club.status}'.", 409,
        )
    if club.current_level == "county":
        raise ClubError("Club is already at county level.", 409)

    if not club.formed_at or _now() < club.formed_at + timedelta(days=180):
        raise ClubError("Club must be at least 6 months old.", 409)

    # One evaluated milestone required
    evaluated = db.query(ActivityClubMilestone).filter(
        ActivityClubMilestone.club_id == club.id,
        ActivityClubMilestone.status == "evaluated",
    ).count()
    if evaluated < 1:
        raise ClubError(
            "At least one evaluated milestone is required for promotion.", 409,
        )

    if not payment_reference or len(payment_reference) < 3:
        raise ClubError("A payment reference is required.", 400)

    club.current_level = "county"
    club.promoted_to_county_at = _now()

    log_club_event(
        db, club.id, "club.promoted", actor_id=actor_id,
        from_state="institution", to_state="county",
        details={
            "payment_reference": payment_reference,
            "method": method,
            "fee": PROMOTION_FEE,
        }, ip=ip, ua=ua,
    )
    db.commit()
    db.refresh(club)
    return club


# ─────────────────────────────────────────────────────────────────────────
# FOUNDER REMOVAL
# ─────────────────────────────────────────────────────────────────────────

def remove_founder(
    db: Session, club_id: str, actor_id: str,
    votes_for: int, votes_against: int,
    reason: str,
) -> ActivityClub:
    """
    Founder removal. Requires:
      - First election cycle to have completed
      - 2/3 of votes_cast to be 'for'
    """
    club = _get(db, club_id)

    cycles_completed = db.query(ActivityClubElectionCycle).filter(
        ActivityClubElectionCycle.club_id == club.id,
        ActivityClubElectionCycle.status == "completed",
    ).count()
    if cycles_completed == 0:
        raise ClubError(
            "The founder cannot be removed until the first election "
            "has been held.", 409,
        )

    total = votes_for + votes_against
    if total == 0:
        raise ClubError("A vote tally is required.", 400)
    if votes_for / total < FOUNDER_VOTE_THRESHOLD:
        raise ClubError(
            f"Removal requires 2/3 of the votes cast "
            f"(got {votes_for}/{total}).", 409,
        )

    # Remove founder's leader role; keep them as a normal member.
    membership = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club.id,
        ActivityClubMembership.user_id == club.founder_id,
    ).first()
    if membership:
        membership.role = "member"

    log_club_event(
        db, club.id, "club.founder_removed", actor_id=actor_id,
        details={
            "votes_for": votes_for,
            "votes_against": votes_against,
            "reason": reason,
        },
    )
    db.commit()
    db.refresh(club)
    return club


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_club(db: Session, club_id: str) -> ActivityClub:
    return _get(db, club_id)


def list_clubs(
    db: Session, *,
    institution_id: str | None = None,
    status: str | None = None,
    level: str | None = None,
    membership_visibility: str | None = None,
) -> list[ActivityClub]:
    q = db.query(ActivityClub)
    if institution_id:
        q = q.filter(ActivityClub.institution_id == institution_id)
    if status:
        q = q.filter(ActivityClub.status == status)
    if level:
        q = q.filter(ActivityClub.current_level == level)
    if membership_visibility:
        q = q.filter(ActivityClub.membership_visibility == membership_visibility)
    return q.order_by(ActivityClub.created_at.desc()).all()


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _get(db: Session, club_id: str) -> ActivityClub:
    c = db.query(ActivityClub).filter(ActivityClub.id == club_id).first()
    if not c:
        raise ClubError("Club not found.", 404)
    return c


def _seed_standard_positions(db: Session, club: ActivityClub) -> None:
    """Create the 12 standard positions on first approval."""
    existing_codes = {
        p.position_code
        for p in db.query(ActivityClubPosition).filter(
            ActivityClubPosition.club_id == club.id,
        ).all()
    }
    order = 0
    for code, title in STANDARD_POSITIONS:
        if code in existing_codes:
            order += 1
            continue
        db.add(ActivityClubPosition(
            club_id=club.id,
            position_code=code,
            title=title,
            position_type="standard",
            display_order=order,
            introduced_in_cycle=0,
            introduced_by=club.founder_id,
            status="active",
        ))
        order += 1
    club.position_count = order
    db.flush()