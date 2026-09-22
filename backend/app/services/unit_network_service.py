"""
Unit Network lifecycle — Module 004.

A network is created lazily when the first rep is appointed to a unit
offering. It persists until the semester ends, at which point it is
archived (read-only).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.academic import Semester
from app.models.unit_offering import UnitOffering
from app.models.unit_representation import (
    UnitNetwork, UnitNetworkMember,
    NETWORK_ROLE_REP, NETWORK_ROLE_SUPERVISOR, NETWORK_ROLE_OBSERVER,
)


logger = logging.getLogger(__name__)


class UnitNetworkError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# CREATE / GET
# ─────────────────────────────────────────────────────────────────────────

def get_or_create_network(
    db: Session, offering: UnitOffering,
) -> UnitNetwork:
    """
    Lazy-create the network for a unit offering. Idempotent.
    """
    existing = db.query(UnitNetwork).filter(
        UnitNetwork.unit_offering_id == offering.id,
    ).first()
    if existing:
        return existing

    network = UnitNetwork(
        unit_offering_id=offering.id,
        semester_id=offering.semester_id,
        is_active=True,
    )
    db.add(network)
    db.flush()
    logger.info(
        "[unit_network] created network for offering=%s", offering.id,
    )
    return network


def get_network(db: Session, network_id: str) -> UnitNetwork:
    network = db.query(UnitNetwork).filter(
        UnitNetwork.id == network_id,
    ).first()
    if not network:
        raise UnitNetworkError("Unit Network not found.", 404)
    return network


def get_network_by_offering(
    db: Session, unit_offering_id: str,
) -> UnitNetwork | None:
    return db.query(UnitNetwork).filter(
        UnitNetwork.unit_offering_id == unit_offering_id,
    ).first()


# ─────────────────────────────────────────────────────────────────────────
# MEMBERSHIP
# ─────────────────────────────────────────────────────────────────────────

def add_member(
    db: Session,
    *,
    network_id: str,
    user_id: str,
    role_in_network: str = NETWORK_ROLE_REP,
    representative_id: str | None = None,
    joined_at: datetime | None = None,
) -> UnitNetworkMember:
    """Add a member to the network. Idempotent for active members."""
    network = get_network(db, network_id)
    if not network.is_active:
        raise UnitNetworkError(
            "Cannot add members to an archived network.", 409,
        )

    # If already an active member, return that row
    existing = db.query(UnitNetworkMember).filter(
        UnitNetworkMember.network_id == network_id,
        UnitNetworkMember.user_id == user_id,
        UnitNetworkMember.is_active.is_(True),
    ).first()
    if existing:
        return existing

    member = UnitNetworkMember(
        network_id=network_id,
        user_id=user_id,
        representative_id=representative_id,
        role_in_network=role_in_network,
        is_active=True,
        joined_at=joined_at or _now(),
    )
    db.add(member)
    db.flush()
    return member


def remove_member(
    db: Session,
    *,
    member_id: str,
    left_reason: str,
    left_at: datetime | None = None,
) -> UnitNetworkMember:
    """
    Remove a member. Silent — no notification is sent. The historical
    messages they sent remain queryable to the remaining network members.
    """
    member = db.query(UnitNetworkMember).filter(
        UnitNetworkMember.id == member_id,
    ).first()
    if not member:
        raise UnitNetworkError("Network member not found.", 404)

    member.is_active = False
    member.left_at = left_at or _now()
    member.left_reason = left_reason
    db.flush()
    return member


def remove_member_by_rep(
    db: Session,
    *,
    representative_id: str,
    left_reason: str,
) -> UnitNetworkMember | None:
    """Convenience: remove by representative id (used on rep replacement)."""
    member = db.query(UnitNetworkMember).filter(
        UnitNetworkMember.representative_id == representative_id,
        UnitNetworkMember.is_active.is_(True),
    ).first()
    if not member:
        return None
    return remove_member(
        db, member_id=member.id, left_reason=left_reason,
    )


def assign_supervisor(
    db: Session,
    *,
    network_id: str,
    supervisor_user_id: str,
    assigned_by: str | None = None,
) -> UnitNetwork:
    """
    Assign a Unit Supervisor to the network. Their user is added as a
    network member with role 'supervisor'.
    """
    network = get_network(db, network_id)
    network.supervisor_user_id = supervisor_user_id

    add_member(
        db,
        network_id=network_id,
        user_id=supervisor_user_id,
        role_in_network=NETWORK_ROLE_SUPERVISOR,
    )
    db.commit()
    db.refresh(network)
    return network


# ─────────────────────────────────────────────────────────────────────────
# ARCHIVAL
# ─────────────────────────────────────────────────────────────────────────

def archive_network(
    db: Session,
    *,
    network_id: str,
    actor_id: str | None = None,
) -> UnitNetwork:
    """
    Archive the network. After this, it becomes read-only:
    no new messages, no new members, no new resources.
    """
    network = get_network(db, network_id)
    if not network.is_active:
        return network

    now = _now()
    network.is_active = False
    network.archived_at = now

    # Deactivate all members silently
    db.query(UnitNetworkMember).filter(
        UnitNetworkMember.network_id == network_id,
        UnitNetworkMember.is_active.is_(True),
    ).update({
        UnitNetworkMember.is_active: False,
        UnitNetworkMember.left_at: now,
        UnitNetworkMember.left_reason: "network_archived",
    }, synchronize_session=False)

    logger.info("[unit_network] archived network=%s", network_id)
    db.commit()
    db.refresh(network)
    return network


def archive_all_for_semester(
    db: Session, *, semester_id: str,
) -> int:
    """Archive every active network belonging to a semester."""
    networks = db.query(UnitNetwork).filter(
        UnitNetwork.semester_id == semester_id,
        UnitNetwork.is_active.is_(True),
    ).all()
    count = 0
    for n in networks:
        archive_network(db, network_id=n.id)
        count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def list_members(
    db: Session,
    *,
    network_id: str,
    active_only: bool = True,
) -> list[UnitNetworkMember]:
    q = db.query(UnitNetworkMember).filter(
        UnitNetworkMember.network_id == network_id,
    )
    if active_only:
        q = q.filter(UnitNetworkMember.is_active.is_(True))
    return q.order_by(UnitNetworkMember.joined_at).all()


def is_network_member(
    db: Session,
    *,
    network_id: str,
    user_id: str,
    active_only: bool = True,
) -> bool:
    q = db.query(UnitNetworkMember).filter(
        UnitNetworkMember.network_id == network_id,
        UnitNetworkMember.user_id == user_id,
    )
    if active_only:
        q = q.filter(UnitNetworkMember.is_active.is_(True))
    return q.first() is not None


def is_network_member_any(
    db: Session, *, user_id: str,
) -> UnitNetwork | None:
    """Return any active network the user is a member of."""
    member = db.query(UnitNetworkMember).filter(
        UnitNetworkMember.user_id == user_id,
        UnitNetworkMember.is_active.is_(True),
    ).first()
    if not member:
        return None
    return db.query(UnitNetwork).filter(
        UnitNetwork.id == member.network_id,
    ).first()