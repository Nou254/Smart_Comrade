"""
Club membership service — Module 003 Phase 10.

Handles:
  - Public join (direct)
  - Private join (request + approval)
  - Leave / remove
  - Alumni transition on graduation
  - 20-club per-student cap
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.activity_club import (
    ActivityClub, ActivityClubMembership,
    VISIBILITY_PUBLIC, VISIBILITY_PRIVATE,
    MAX_CLUBS_PER_STUDENT,
    INSTITUTION_CLUB_MEMBER_CAP, COUNTY_CLUB_MEMBER_CAP,
)
from app.models.user import User
from app.services.club_audit_service import log_club_event


logger = logging.getLogger(__name__)


class ClubMembershipError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# JOIN
# ─────────────────────────────────────────────────────────────────────────

def join_public_club(
    db: Session, club_id: str, user_id: str,
) -> ActivityClubMembership:
    club = _get_club(db, club_id)
    if club.membership_visibility != VISIBILITY_PUBLIC:
        raise ClubMembershipError(
            "This club is private. Please submit a join request instead.", 409,
        )
    return _finalize_join(db, club, user_id, request_message=None)


def request_private_join(
    db: Session, club_id: str, user_id: str, message: str | None = None,
) -> ActivityClubMembership:
    club = _get_club(db, club_id)
    if club.membership_visibility != VISIBILITY_PRIVATE:
        raise ClubMembershipError(
            "This club is public. You can join directly.", 409,
        )
    return _finalize_join(
        db, club, user_id, request_message=message, force_pending=True,
    )


def _finalize_join(
    db: Session, club: ActivityClub, user_id: str,
    *, request_message: str | None = None, force_pending: bool = False,
) -> ActivityClubMembership:
    _assert_club_joinable(club)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ClubMembershipError("User not found.", 404)

    # 20-club cap
    active_count = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.user_id == user_id,
        ActivityClubMembership.status.in_(("active", "pending")),
    ).count()
    if active_count >= MAX_CLUBS_PER_STUDENT:
        raise ClubMembershipError(
            f"You can belong to at most {MAX_CLUBS_PER_STUDENT} clubs.", 409,
        )

    existing = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club.id,
        ActivityClubMembership.user_id == user_id,
    ).first()
    if existing and existing.status in ("active", "pending"):
        raise ClubMembershipError("You are already a member of this club.", 409)

    # Cap check
    cap = (
        COUNTY_CLUB_MEMBER_CAP if club.current_level == "county"
        else INSTITUTION_CLUB_MEMBER_CAP
    )
    if club.member_count >= cap:
        raise ClubMembershipError("Club has reached its membership cap.", 409)

    status = "pending" if force_pending else "active"

    if existing:
        existing.status = status
        existing.request_message = request_message
        existing.joined_at = _now() if status == "active" else existing.joined_at
        existing.left_at = None
        membership = existing
    else:
        membership = ActivityClubMembership(
            club_id=club.id,
            user_id=user_id,
            status=status,
            role="member",
            request_message=request_message,
            joined_at=_now() if status == "active" else None or _now(),
        )
        db.add(membership)

    if status == "active":
        club.member_count = (club.member_count or 0) + 1

    log_club_event(
        db, club.id,
        "club.created" if status == "pending" else "club.created",
        actor_id=user_id,
        details={"membership_status": status, "user_id": user_id},
    )
    db.commit()
    db.refresh(membership)
    return membership


def approve_join_request(
    db: Session, membership_id: str, actor_id: str,
) -> ActivityClubMembership:
    membership = _get_membership(db, membership_id)
    if membership.status != "pending":
        raise ClubMembershipError(
            f"Membership is not pending (status={membership.status}).", 409,
        )

    club = _get_club(db, membership.club_id)
    cap = (
        COUNTY_CLUB_MEMBER_CAP if club.current_level == "county"
        else INSTITUTION_CLUB_MEMBER_CAP
    )
    if club.member_count >= cap:
        raise ClubMembershipError("Club has reached its membership cap.", 409)

    membership.status = "active"
    membership.approved_by = actor_id
    membership.approved_at = _now()
    membership.joined_at = _now()

    club.member_count = (club.member_count or 0) + 1

    log_club_event(
        db, club.id, "club.created", actor_id=actor_id,
        details={"membership_id": membership.id, "action": "join_approved"},
    )
    db.commit()
    db.refresh(membership)
    return membership


def reject_join_request(
    db: Session, membership_id: str, actor_id: str, reason: str,
) -> ActivityClubMembership:
    membership = _get_membership(db, membership_id)
    if membership.status != "pending":
        raise ClubMembershipError("Membership is not pending.", 409)

    membership.status = "removed"
    membership.left_at = _now()
    membership.left_reason = reason
    membership.approved_by = actor_id
    membership.approved_at = _now()

    log_club_event(
        db, membership.club_id, "club.created", actor_id=actor_id,
        details={"membership_id": membership.id, "action": "join_rejected",
                 "reason": reason},
    )
    db.commit()
    db.refresh(membership)
    return membership


# ─────────────────────────────────────────────────────────────────────────
# LEAVE / REMOVE
# ─────────────────────────────────────────────────────────────────────────

def leave_club(
    db: Session, club_id: str, user_id: str, reason: str | None = None,
) -> ActivityClubMembership:
    club = _get_club(db, club_id)
    membership = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club_id,
        ActivityClubMembership.user_id == user_id,
        ActivityClubMembership.status == "active",
    ).first()
    if not membership:
        raise ClubMembershipError("You are not an active member.", 404)

    # Founder cannot leave before first election completes
    if club.founder_id == user_id:
        from app.models.activity_club import ActivityClubElectionCycle
        cycles = db.query(ActivityClubElectionCycle).filter(
            ActivityClubElectionCycle.club_id == club.id,
            ActivityClubElectionCycle.status == "completed",
        ).count()
        if cycles == 0:
            raise ClubMembershipError(
                "The founder cannot leave before the first election completes.",
                409,
            )

    membership.status = "left"
    membership.left_at = _now()
    membership.left_reason = reason
    club.member_count = max(0, (club.member_count or 1) - 1)

    db.commit()
    db.refresh(membership)
    return membership


def remove_member(
    db: Session, club_id: str, target_user_id: str, actor_id: str,
    reason: str,
) -> ActivityClubMembership:
    club = _get_club(db, club_id)
    if target_user_id == club.founder_id:
        raise ClubMembershipError(
            "Use the founder-removal flow to remove the founder.", 409,
        )

    membership = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club_id,
        ActivityClubMembership.user_id == target_user_id,
    ).first()
    if not membership:
        raise ClubMembershipError("Membership not found.", 404)

    membership.status = "removed"
    membership.left_at = _now()
    membership.left_reason = reason
    club.member_count = max(0, (club.member_count or 1) - 1)

    db.commit()
    db.refresh(membership)
    return membership


# ─────────────────────────────────────────────────────────────────────────
# GRADUATION
# ─────────────────────────────────────────────────────────────────────────

def mark_member_graduated(
    db: Session, user_id: str,
) -> int:
    """
    Called by the graduation pipeline. Flips every active club membership
    to 'alumni_readonly' for that user. Returns the number of memberships
    affected.
    """
    rows = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.user_id == user_id,
        ActivityClubMembership.status == "active",
    ).all()
    now = _now()
    for m in rows:
        m.status = "alumni_readonly"
        m.graduated_at = now

    db.commit()
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────

def count_user_active_clubs(db: Session, user_id: str) -> int:
    return db.query(ActivityClubMembership).filter(
        ActivityClubMembership.user_id == user_id,
        ActivityClubMembership.status.in_(("active", "pending")),
    ).count()


def list_club_members(
    db: Session, club_id: str, status: str | None = None,
) -> list[ActivityClubMembership]:
    q = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.club_id == club_id,
    )
    if status:
        q = q.filter(ActivityClubMembership.status == status)
    return q.order_by(ActivityClubMembership.joined_at).all()


def _get_club(db: Session, club_id: str) -> ActivityClub:
    c = db.query(ActivityClub).filter(ActivityClub.id == club_id).first()
    if not c:
        raise ClubMembershipError("Club not found.", 404)
    return c


def _get_membership(db: Session, membership_id: str) -> ActivityClubMembership:
    m = db.query(ActivityClubMembership).filter(
        ActivityClubMembership.id == membership_id,
    ).first()
    if not m:
        raise ClubMembershipError("Membership not found.", 404)
    return m


def _assert_club_joinable(club: ActivityClub) -> None:
    if club.status not in ("forming", "active", "county"):
        raise ClubMembershipError(
            f"Club is not accepting members (status={club.status}).", 409,
        )
    if not club.regional_rep_approved_at:
        raise ClubMembershipError(
            "Club has not completed the approval process.", 409,
        )