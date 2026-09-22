"""
Unit Representative appointment lifecycle — Module 004.

Design decisions:
  - Appointment is by Group Leader, not election
  - One active rep per (group, unit offering, semester)
  - Replacement silently removes the outgoing rep from the network
  - When the semester ends, all active appointments are auto-ended
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.academic import UnitMembership, Semester
from app.models.group import Group, GroupMembership
from app.models.group_unit import GroupUnit
from app.models.unit_offering import UnitOffering
from app.models.unit_representation import (
    UnitRepresentative, UnitNetworkMember,
    REP_PENDING, REP_ACTIVE, REP_SUSPENDED, REP_ENDED,
    REP_REPLACED, REP_RESIGNED,
    NETWORK_ROLE_REP,
)
from app.services.admin_audit_service import log_admin_action
from app.services.unit_network_service import (
    get_or_create_network, add_member, remove_member,
)


logger = logging.getLogger(__name__)


class UnitRepError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# APPOINTMENT
# ─────────────────────────────────────────────────────────────────────────

def appoint_representative(
    db: Session,
    *,
    group_id: str,
    unit_offering_id: str,
    user_id: str,
    appointed_by: str,
    notes: str | None = None,
) -> UnitRepresentative:
    """
    Appoint a student as Unit Representative.

    Verifies:
      - the appointing user is the Group Leader (or current Group Leader)
      - the candidate is an active member of the group
      - the candidate is taking the unit (UnitMembership)
      - the group has this unit in its curated list (GroupUnit)
      - no other active rep exists for (group, offering)
    """
    # --- Verify group + offering exist
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise UnitRepError("Group not found.", 404)

    offering = db.query(UnitOffering).filter(
        UnitOffering.id == unit_offering_id,
    ).first()
    if not offering:
        raise UnitRepError("Unit offering not found.", 404)

    # --- Verify appointing user is the Group Leader
    if group.creator_id != appointed_by:
        from app.models.group import GroupOfficial
        leader = db.query(GroupOfficial).filter(
            GroupOfficial.group_id == group_id,
            GroupOfficial.user_id == appointed_by,
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
        ).first()
        if not leader:
            raise UnitRepError(
                "Only the Group Leader may appoint Unit Representatives.", 403,
            )

    # --- Verify candidate is an active group member
    membership = db.query(GroupMembership).filter(
        GroupMembership.group_id == group_id,
        GroupMembership.user_id == user_id,
        GroupMembership.status == "active",
    ).first()
    if not membership:
        raise UnitRepError(
            "The candidate is not an active member of this group.", 400,
        )

    # --- Verify candidate is taking the unit
    unit_membership = db.query(UnitMembership).filter(
        UnitMembership.user_id == user_id,
        UnitMembership.unit_id == offering.unit_id,
        UnitMembership.semester_id == offering.semester_id,
        UnitMembership.status == "active",
    ).first()
    if not unit_membership:
        raise UnitRepError(
            "The candidate is not taking this unit for this semester.", 400,
        )
    # If the unit membership is unconfirmed, require confirmation first
    if unit_membership.confirmation_status != "confirmed":
        raise UnitRepError(
            "The candidate must confirm their unit membership before being "
            "appointed as Unit Representative.", 400,
        )

    # --- Verify the group has the unit in its curated list
    group_unit = db.query(GroupUnit).filter(
        GroupUnit.group_id == group_id,
        GroupUnit.unit_id == offering.unit_id,
    ).first()
    if not group_unit:
        raise UnitRepError(
            "This unit is not part of the group's curated unit list.", 400,
        )

    # --- Verify no other active rep for this (group, offering)
    existing = db.query(UnitRepresentative).filter(
        UnitRepresentative.group_id == group_id,
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if existing:
        raise UnitRepError(
            "This group already has an active Unit Representative for this "
            "offering. End the existing appointment first.", 409,
        )

    # --- Create appointment
    now = _now()
    rep = UnitRepresentative(
        group_id=group_id,
        unit_offering_id=unit_offering_id,
        semester_id=offering.semester_id,
        user_id=user_id,
        appointed_by=appointed_by,
        appointed_at=now,
        status=REP_ACTIVE,
        term_start=now,
        notes=notes,
    )
    db.add(rep)
    db.flush()

    # --- Add to network (creates network lazily)
    network = get_or_create_network(db, offering)
    add_member(
        db,
        network_id=network.id,
        user_id=user_id,
        representative_id=rep.id,
        role_in_network=NETWORK_ROLE_REP,
        joined_at=now,
    )

    log_admin_action(
        db, actor_id=appointed_by, action="unit_rep.appoint",
        target_type="unit_representative", target_id=rep.id,
        new_value=f"group={group_id} offering={unit_offering_id} user={user_id}",
    )
    db.commit()
    db.refresh(rep)
    return rep


# ─────────────────────────────────────────────────────────────────────────
# END / REPLACE / RESIGN
# ─────────────────────────────────────────────────────────────────────────

def end_representative(
    db: Session,
    *,
    representative_id: str,
    actor_id: str,
    reason: str,
    new_status: str = REP_ENDED,
) -> UnitRepresentative:
    """
    End an appointment. Used by:
      - Group Leader replacing them (new_status=REP_REPLACED)
      - Semester archival (new_status=REP_ENDED)
      - Student resignation (new_status=REP_RESIGNED)
      - Suspension as a pre-step (new_status=REP_SUSPENDED)

    The outgoing rep is removed from the network silently — no
    notification is sent. Their historical messages remain queryable.
    """
    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.id == representative_id,
    ).first()
    if not rep:
        raise UnitRepError("Unit Representative not found.", 404)
    if rep.status in (REP_ENDED, REP_REPLACED, REP_RESIGNED):
        return rep  # already ended

    now = _now()
    old_status = rep.status
    rep.status = new_status
    rep.term_end = now
    rep.ended_reason = reason

    # Remove from network (silent — no notification)
    network_member = db.query(UnitNetworkMember).filter(
        UnitNetworkMember.representative_id == rep.id,
        UnitNetworkMember.is_active.is_(True),
    ).first()
    if network_member:
        remove_member(
            db,
            member_id=network_member.id,
            left_reason=new_status,
            left_at=now,
        )

    log_admin_action(
        db, actor_id=actor_id, action=f"unit_rep.{new_status}",
        target_type="unit_representative", target_id=rep.id,
        old_value=old_status, new_value=new_status, reason=reason,
    )
    db.commit()
    db.refresh(rep)
    return rep


def replace_representative(
    db: Session,
    *,
    old_representative_id: str,
    new_user_id: str,
    actor_id: str,
    reason: str,
    notes: str | None = None,
) -> UnitRepresentative:
    """
    Replace a rep. The old rep is silently removed from the network,
    the new rep is appointed in the same appointment slot.
    """
    old_rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.id == old_representative_id,
    ).first()
    if not old_rep:
        raise UnitRepError("Original Representative not found.", 404)

    # End the old appointment as 'replaced'
    end_representative(
        db,
        representative_id=old_rep.id,
        actor_id=actor_id,
        reason=reason,
        new_status=REP_REPLACED,
    )

    # Appoint the new rep
    new_rep = appoint_representative(
        db,
        group_id=old_rep.group_id,
        unit_offering_id=old_rep.unit_offering_id,
        user_id=new_user_id,
        appointed_by=actor_id,
        notes=notes,
    )

    # Link them
    old_rep.replaced_by_id = new_rep.id
    db.commit()
    db.refresh(new_rep)
    return new_rep


def suspend_representative(
    db: Session,
    *,
    representative_id: str,
    actor_id: str,
    reason: str,
) -> UnitRepresentative:
    """Suspend a rep's operational privileges under review."""
    return end_representative(
        db,
        representative_id=representative_id,
        actor_id=actor_id,
        reason=reason,
        new_status=REP_SUSPENDED,
    )


def reactivate_representative(
    db: Session,
    *,
    representative_id: str,
    actor_id: str,
) -> UnitRepresentative:
    """Bring a suspended rep back to active status."""
    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.id == representative_id,
    ).first()
    if not rep:
        raise UnitRepError("Unit Representative not found.", 404)
    if rep.status != REP_SUSPENDED:
        raise UnitRepError(
            f"Only suspended reps can be reactivated. Current status: "
            f"{rep.status}.", 409,
        )

    now = _now()
    rep.status = REP_ACTIVE
    rep.term_end = None
    rep.ended_reason = None

    # Re-add to network if the network still exists
    from app.models.unit_representation import UnitNetwork
    network = db.query(UnitNetwork).filter(
        UnitNetwork.unit_offering_id == rep.unit_offering_id,
        UnitNetwork.is_active.is_(True),
    ).first()
    if network:
        add_member(
            db,
            network_id=network.id,
            user_id=rep.user_id,
            representative_id=rep.id,
            role_in_network=NETWORK_ROLE_REP,
            joined_at=now,
        )

    log_admin_action(
        db, actor_id=actor_id, action="unit_rep.reactivate",
        target_type="unit_representative", target_id=rep.id,
    )
    db.commit()
    db.refresh(rep)
    return rep


# ─────────────────────────────────────────────────────────────────────────
# SEMESTER ARCHIVAL
# ─────────────────────────────────────────────────────────────────────────

def end_all_for_semester(
    db: Session,
    *,
    semester_id: str,
    actor_id: str | None = None,
) -> int:
    """
    Called when a semester ends. Ends every active rep appointment for
    that semester. The network is archived separately by
    unit_network_service.archive_network().
    """
    reps = db.query(UnitRepresentative).filter(
        UnitRepresentative.semester_id == semester_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).all()

    now = _now()
    count = 0
    for rep in reps:
        rep.status = REP_ENDED
        rep.term_end = now
        rep.ended_reason = "semester_ended"

        # Remove from network silently
        network_member = db.query(UnitNetworkMember).filter(
            UnitNetworkMember.representative_id == rep.id,
            UnitNetworkMember.is_active.is_(True),
        ).first()
        if network_member:
            network_member.is_active = False
            network_member.left_at = now
            network_member.left_reason = "semester_ended"
        count += 1

    if count:
        log_admin_action(
            db, actor_id=actor_id, action="unit_rep.semester_archival",
            target_type="semester", target_id=semester_id,
            new_value=f"ended={count}",
        )
        db.commit()
    return count


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_representative(
    db: Session, representative_id: str,
) -> UnitRepresentative:
    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.id == representative_id,
    ).first()
    if not rep:
        raise UnitRepError("Unit Representative not found.", 404)
    return rep


def get_active_rep_for_group_and_offering(
    db: Session, group_id: str, unit_offering_id: str,
) -> UnitRepresentative | None:
    return db.query(UnitRepresentative).filter(
        UnitRepresentative.group_id == group_id,
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()


def list_representatives(
    db: Session,
    *,
    group_id: str | None = None,
    unit_offering_id: str | None = None,
    user_id: str | None = None,
    semester_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[UnitRepresentative]:
    q = db.query(UnitRepresentative)
    if group_id:
        q = q.filter(UnitRepresentative.group_id == group_id)
    if unit_offering_id:
        q = q.filter(UnitRepresentative.unit_offering_id == unit_offering_id)
    if user_id:
        q = q.filter(UnitRepresentative.user_id == user_id)
    if semester_id:
        q = q.filter(UnitRepresentative.semester_id == semester_id)
    if status:
        q = q.filter(UnitRepresentative.status == status)
    return q.order_by(
        UnitRepresentative.appointed_at.desc(),
    ).limit(limit).all()


def list_active_reps_for_offering(
    db: Session, unit_offering_id: str,
) -> list[UnitRepresentative]:
    return db.query(UnitRepresentative).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).all()