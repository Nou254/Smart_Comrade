"""
Unit discussions + announcements — Module 004.

Student-facing threaded discussion plus unit-wide announcements
published by reps, supervisors, and lecturers.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.unit_offering import UnitOffering
from app.models.unit_representation import (
    UnitDiscussion, UnitAnnouncement,
    UnitNetworkMember, UnitRepresentative,
    REP_ACTIVE,
)


logger = logging.getLogger(__name__)


class UnitDiscussionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# DISCUSSIONS
# ─────────────────────────────────────────────────────────────────────────

def create_discussion(
    db: Session,
    *,
    unit_offering_id: str,
    author_id: str,
    title: str | None,
    content: str,
    parent_id: str | None = None,
) -> UnitDiscussion:
    offering = db.query(UnitOffering).filter(
        UnitOffering.id == unit_offering_id,
    ).first()
    if not offering:
        raise UnitDiscussionError("Unit offering not found.", 404)

    if parent_id:
        parent = db.query(UnitDiscussion).filter(
            UnitDiscussion.id == parent_id,
        ).first()
        if not parent:
            raise UnitDiscussionError("Parent thread not found.", 404)
        if parent.unit_offering_id != unit_offering_id:
            raise UnitDiscussionError(
                "Parent thread belongs to a different unit offering.", 400,
            )
        if parent.is_locked:
            raise UnitDiscussionError(
                "This thread is locked and cannot receive replies.", 409,
            )
        if parent.parent_id is not None:
            raise UnitDiscussionError(
                "Replies may only be made to root threads.", 400,
            )
    else:
        # Root threads must have a title
        if not title:
            raise UnitDiscussionError("Root threads require a title.", 400)

    thread = UnitDiscussion(
        unit_offering_id=unit_offering_id,
        author_id=author_id,
        parent_id=parent_id,
        title=title,
        content=content,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def update_discussion(
    db: Session,
    *,
    discussion_id: str,
    actor_id: str,
    is_pinned: bool | None = None,
    is_locked: bool | None = None,
) -> UnitDiscussion:
    thread = db.query(UnitDiscussion).filter(
        UnitDiscussion.id == discussion_id,
    ).first()
    if not thread:
        raise UnitDiscussionError("Thread not found.", 404)

    _assert_moderator(db, thread.unit_offering_id, actor_id)

    if is_pinned is not None:
        thread.is_pinned = is_pinned
    if is_locked is not None:
        thread.is_locked = is_locked

    db.commit()
    db.refresh(thread)
    return thread


def soft_delete_discussion(
    db: Session,
    *,
    discussion_id: str,
    actor_id: str,
) -> UnitDiscussion:
    thread = db.query(UnitDiscussion).filter(
        UnitDiscussion.id == discussion_id,
    ).first()
    if not thread:
        raise UnitDiscussionError("Thread not found.", 404)

    # Author can delete own; moderator can delete any
    if thread.author_id != actor_id:
        _assert_moderator(db, thread.unit_offering_id, actor_id)

    thread.is_deleted = True
    thread.deleted_at = _now()
    thread.deleted_by = actor_id
    db.commit()
    db.refresh(thread)
    return thread


def list_discussions(
    db: Session,
    *,
    unit_offering_id: str,
    include_deleted: bool = False,
    limit: int = 100,
) -> list[UnitDiscussion]:
    q = db.query(UnitDiscussion).filter(
        UnitDiscussion.unit_offering_id == unit_offering_id,
        UnitDiscussion.parent_id.is_(None),
    )
    if not include_deleted:
        q = q.filter(UnitDiscussion.is_deleted.is_(False))
    return q.order_by(
        UnitDiscussion.is_pinned.desc(),
        UnitDiscussion.created_at.desc(),
    ).limit(limit).all()


def list_replies(
    db: Session,
    *,
    parent_id: str,
    include_deleted: bool = False,
    limit: int = 500,
) -> list[UnitDiscussion]:
    q = db.query(UnitDiscussion).filter(
        UnitDiscussion.parent_id == parent_id,
    )
    if not include_deleted:
        q = q.filter(UnitDiscussion.is_deleted.is_(False))
    return q.order_by(UnitDiscussion.created_at).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────
# ANNOUNCEMENTS
# ─────────────────────────────────────────────────────────────────────────

def create_announcement(
    db: Session,
    *,
    unit_offering_id: str,
    publisher_id: str,
    title: str,
    content: str,
    is_pinned: bool = False,
    publisher_role: str | None = None,
) -> UnitAnnouncement:
    offering = db.query(UnitOffering).filter(
        UnitOffering.id == unit_offering_id,
    ).first()
    if not offering:
        raise UnitDiscussionError("Unit offering not found.", 404)

    # Determine publisher role if not given
    if publisher_role is None:
        publisher_role = _resolve_publisher_role(
            db, unit_offering_id, publisher_id,
        )

    if publisher_role not in ("rep", "supervisor", "lecturer"):
        raise UnitDiscussionError(
            "You are not authorized to publish unit announcements.", 403,
        )

    ann = UnitAnnouncement(
        unit_offering_id=unit_offering_id,
        publisher_id=publisher_id,
        publisher_role=publisher_role,
        title=title,
        content=content,
        is_pinned=is_pinned,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def update_announcement(
    db: Session,
    *,
    announcement_id: str,
    actor_id: str,
    title: str | None = None,
    content: str | None = None,
    is_pinned: bool | None = None,
    is_archived: bool | None = None,
) -> UnitAnnouncement:
    ann = db.query(UnitAnnouncement).filter(
        UnitAnnouncement.id == announcement_id,
    ).first()
    if not ann:
        raise UnitDiscussionError("Announcement not found.", 404)

    if ann.publisher_id != actor_id:
        _assert_moderator(db, ann.unit_offering_id, actor_id)

    if title is not None:
        ann.title = title
    if content is not None:
        ann.content = content
    if is_pinned is not None:
        ann.is_pinned = is_pinned
    if is_archived is not None:
        ann.is_archived = is_archived

    db.commit()
    db.refresh(ann)
    return ann


def list_announcements(
    db: Session,
    *,
    unit_offering_id: str,
    include_archived: bool = False,
    limit: int = 100,
) -> list[UnitAnnouncement]:
    q = db.query(UnitAnnouncement).filter(
        UnitAnnouncement.unit_offering_id == unit_offering_id,
    )
    if not include_archived:
        q = q.filter(UnitAnnouncement.is_archived.is_(False))
    return q.order_by(
        UnitAnnouncement.is_pinned.desc(),
        UnitAnnouncement.created_at.desc(),
    ).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _assert_moderator(
    db: Session, unit_offering_id: str, user_id: str,
) -> None:
    """
    A user is a moderator if they are an active rep for the offering
    OR the assigned supervisor.
    """
    from app.models.unit_representation import UnitNetwork

    # Active rep?
    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.user_id == user_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if rep:
        return

    # Supervisor?
    network = db.query(UnitNetwork).filter(
        UnitNetwork.unit_offering_id == unit_offering_id,
    ).first()
    if network and network.supervisor_user_id == user_id:
        return

    raise UnitDiscussionError(
        "You are not a moderator for this unit offering.", 403,
    )


def _resolve_publisher_role(
    db: Session, unit_offering_id: str, user_id: str,
) -> str:
    from app.models.unit_representation import UnitNetwork

    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.user_id == user_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if rep:
        return "rep"

    network = db.query(UnitNetwork).filter(
        UnitNetwork.unit_offering_id == unit_offering_id,
    ).first()
    if network and network.supervisor_user_id == user_id:
        return "supervisor"

    # Fall back to lecturer role if the user's role catalogue lists them
    # as academic staff. In V1, we conservatively return "lecturer" for
    # any user who is neither rep nor supervisor but whose role carries
    # `unit_offering.supervise`. This keeps the door open.
    from app.services.role_service import resolve_user_permissions
    _, perms = resolve_user_permissions(db, user_id)
    if "unit_offering.supervise" in perms:
        return "lecturer"

    return "unknown"