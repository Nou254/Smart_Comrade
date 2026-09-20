"""
Business logic for Student Groups — Module 003.

Module 003 Phase 3+4+5 extension:
  - create_group now delegates to group_formation_service and returns
    the group + invite token + URLs.
  - join_group no longer auto-activates public memberships; it creates
    a pending GroupJoinRequest instead.
  - Everything else (officials, meetings, activities, announcements,
    timetables) is unchanged.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.academic import (
    Institution, School, Course, AcademicYear, Semester, Unit,
)
from app.models.group import (
    Group, GroupMembership, GroupOfficial,
    GroupMeeting, GroupMeetingAttendee,
    GroupActivity, GroupAnnouncement,
    GroupTimetable, GroupTimetableEntry, GroupTimetableApproval,
)
from app.models.group_join_request import GroupJoinRequest
from app.models.user import User
from app.services import group_formation_service


class GroupError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


TRIAL_DAYS = 14


# ============================================================================
# GROUP CRUD
# ============================================================================

def create_group(db: Session, data, creator_id: str):
    """
    Legacy entry point. Delegates to group_formation_service so creation
    always produces a slug, invite token, trial subscription, and
    founding-leader records.

    Returns the dict from the formation service, which the API layer
    unwraps into the group + token response.
    """
    # Translate the legacy shape into the new shape.
    if not hasattr(data, "year_level") or data.year_level is None:
        # Fall back to a sensible default if the caller used the legacy
        # schema without year_level.
        raise GroupError(
            "year_level is required. Use the new create endpoint.", 400,
        )

    try:
        return group_formation_service.create_group_with_context(
            db, data, creator_id=creator_id,
        )
    except group_formation_service.GroupFormationError as e:
        raise GroupError(e.message, e.status_code)


def list_groups(
    db: Session,
    institution_id: str | None = None,
    course_id: str | None = None,
    semester_id: str | None = None,
    unit_id: str | None = None,
    status_filter: str | None = None,
    visibility: str | None = None,
) -> list[Group]:
    q = db.query(Group)
    if institution_id:
        q = q.filter(Group.institution_id == institution_id)
    if course_id:
        q = q.filter(Group.course_id == course_id)
    if semester_id:
        q = q.filter(Group.semester_id == semester_id)
    if unit_id:
        q = q.filter(Group.unit_id == unit_id)
    if status_filter:
        q = q.filter(Group.status == status_filter)
    if visibility:
        q = q.filter(Group.visibility == visibility)
    return q.order_by(Group.created_at.desc()).all()


def get_group(db: Session, group_id: str) -> Group:
    g = db.query(Group).filter(Group.id == group_id).first()
    if not g:
        raise GroupError("Group not found.", 404)
    return g


def update_group(db: Session, group_id: str, data) -> Group:
    g = get_group(db, group_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "visibility" and value not in {"private", "public", "invitation_only"}:
            raise GroupError("Invalid visibility.", 400)
        if field == "slug":
            # Slug is immutable; ignore attempts to change it.
            continue
        setattr(g, field, value)
    db.commit(); db.refresh(g)
    return g


# ============================================================================
# MEMBERSHIP  (legacy endpoints)
# ============================================================================

def _is_official(
    db: Session, group_id: str, user_id: str, positions: set[str],
) -> bool:
    q = db.query(GroupOfficial).filter(
        GroupOfficial.group_id == group_id,
        GroupOfficial.user_id == user_id,
        GroupOfficial.status == "active",
        GroupOfficial.position.in_(positions),
    )
    return q.first() is not None


def join_group(
    db: Session, group_id: str, user_id: str, notes: str | None = None,
) -> GroupMembership:
    """
    Legacy direct-join endpoint. Now ALWAYS creates a pending membership
    that the leader must approve. Never auto-activates.
    """
    g = get_group(db, group_id)
    if g.status in ("suspended", "archived", "pending_election"):
        raise GroupError(
            f"Group is {g.status}. Cannot join.", 403,
        )

    existing = db.query(GroupMembership).filter(
        GroupMembership.group_id == group_id,
        GroupMembership.user_id == user_id,
    ).first()
    if existing and existing.status == "active":
        raise GroupError("You are already an active member.", 409)
    if existing and existing.status == "pending":
        return existing

    if g.member_count >= g.max_members:
        raise GroupError("Group is full.", 409)

    now = datetime.now(timezone.utc)

    if existing:
        existing.status = "pending"
        existing.left_at = None
        existing.notes = notes
        db.commit(); db.refresh(existing)
        return existing

    m = GroupMembership(
        group_id=group_id,
        user_id=user_id,
        status="pending",
        notes=notes,
    )
    db.add(m)
    db.commit(); db.refresh(m)
    return m


def list_members(
    db: Session, group_id: str, status_filter: str | None = None,
) -> list[GroupMembership]:
    q = db.query(GroupMembership).filter(GroupMembership.group_id == group_id)
    if status_filter:
        q = q.filter(GroupMembership.status == status_filter)
    return q.order_by(GroupMembership.created_at).all()


def update_membership(
    db: Session, group_id: str, target_user_id: str,
    new_status: str, acting_user_id: str,
) -> GroupMembership:
    if new_status not in {"active", "suspended", "removed"}:
        raise GroupError("Invalid status.", 400)

    g = get_group(db, group_id)
    if not _is_official(db, group_id, acting_user_id, {"leader", "secretary"}):
        raise GroupError(
            "Only the group leader or secretary can manage memberships.", 403,
        )

    m = db.query(GroupMembership).filter(
        GroupMembership.group_id == group_id,
        GroupMembership.user_id == target_user_id,
    ).first()
    if not m:
        raise GroupError("Membership not found.", 404)

    previous = m.status
    m.status = new_status
    now = datetime.now(timezone.utc)

    if new_status == "active" and previous != "active":
        m.joined_at = now
        m.approved_by = acting_user_id
    elif new_status in ("suspended", "removed") and previous == "active":
        m.left_at = now

    db.flush()

    # Recompute cached member count
    count = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.status == "active",
        )
        .count()
    )
    g.member_count = count

    db.commit(); db.refresh(m)
    return m


def leave_group(db: Session, group_id: str, user_id: str) -> GroupMembership:
    g = get_group(db, group_id)
    m = db.query(GroupMembership).filter(
        GroupMembership.group_id == group_id,
        GroupMembership.user_id == user_id,
    ).first()
    if not m or m.status != "active":
        raise GroupError("You are not an active member.", 404)

    if _is_official(db, group_id, user_id, {"leader"}):
        other_leaders = db.query(GroupOfficial).filter(
            GroupOfficial.group_id == group_id,
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
            GroupOfficial.user_id != user_id,
        ).count()
        if other_leaders == 0:
            raise GroupError(
                "You are the sole leader. Transfer leadership before leaving.",
                409,
            )

    m.status = "left"
    m.left_at = datetime.now(timezone.utc)
    g.member_count = max(0, g.member_count - 1)
    db.commit(); db.refresh(m)
    return m


# ============================================================================
# OFFICIALS
# ============================================================================

def appoint_official(
    db: Session, group_id: str, data, acting_user_id: str,
) -> GroupOfficial:
    get_group(db, group_id)
    if data.position not in {
        "leader", "secretary", "treasurer", "unit_representative",
    }:
        raise GroupError("Invalid position.", 400)

    if not _is_official(db, group_id, acting_user_id, {"leader", "secretary"}):
        raise GroupError("Only the leader or secretary can appoint officials.", 403)

    target_mem = db.query(GroupMembership).filter(
        GroupMembership.group_id == group_id,
        GroupMembership.user_id == data.user_id,
        GroupMembership.status == "active",
    ).first()
    if not target_mem:
        raise GroupError("Target user is not an active group member.", 409)

    if data.position == "unit_representative" and not data.unit_id:
        raise GroupError("Unit representatives must specify unit_id.", 400)

    if data.position == "leader":
        current = db.query(GroupOfficial).filter(
            GroupOfficial.group_id == group_id,
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
        ).all()
        for c in current:
            c.status = "removed"

    official = GroupOfficial(
        group_id=group_id,
        user_id=data.user_id,
        position=data.position,
        unit_id=data.unit_id,
        term_start=data.term_start,
        term_end=data.term_end,
        status="active",
        appointed_by=acting_user_id,
        notes=data.notes,
    )
    db.add(official); db.commit(); db.refresh(official)
    return official


def list_officials(
    db: Session, group_id: str, status_filter: str | None = "active",
) -> list[GroupOfficial]:
    q = db.query(GroupOfficial).filter(GroupOfficial.group_id == group_id)
    if status_filter:
        q = q.filter(GroupOfficial.status == status_filter)
    return q.order_by(GroupOfficial.created_at).all()


def remove_official(
    db: Session, official_id: str, acting_user_id: str,
) -> GroupOfficial:
    o = db.query(GroupOfficial).filter(GroupOfficial.id == official_id).first()
    if not o:
        raise GroupError("Official record not found.", 404)

    if not _is_official(db, o.group_id, acting_user_id, {"leader", "secretary"}):
        raise GroupError("Only the leader or secretary can remove officials.", 403)

    if o.position == "leader" and o.status == "active":
        other_leaders = db.query(GroupOfficial).filter(
            GroupOfficial.group_id == o.group_id,
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
            GroupOfficial.id != o.id,
        ).count()
        if other_leaders == 0:
            raise GroupError(
                "Cannot remove the only leader. Appoint a new leader first.", 409,
            )

    o.status = "removed"
    db.commit(); db.refresh(o)
    return o


# ============================================================================
# MEETINGS
# ============================================================================

def create_meeting(
    db: Session, group_id: str, data, acting_user_id: str,
) -> GroupMeeting:
    get_group(db, group_id)
    if not _is_official(
        db, group_id, acting_user_id, {"leader", "secretary", "treasurer"},
    ):
        raise GroupError("Only group officials can create meetings.", 403)

    m = GroupMeeting(
        group_id=group_id,
        title=data.title.strip(),
        agenda=data.agenda,
        scheduled_at=data.scheduled_at,
        duration_minutes=data.duration_minutes,
        location=data.location,
        virtual_link=data.virtual_link,
        status="scheduled",
        created_by=acting_user_id,
    )
    db.add(m); db.commit(); db.refresh(m)
    return m


def list_meetings(db: Session, group_id: str) -> list[GroupMeeting]:
    return (
        db.query(GroupMeeting)
        .filter(GroupMeeting.group_id == group_id)
        .order_by(GroupMeeting.scheduled_at.desc())
        .all()
    )


# ============================================================================
# ACTIVITIES
# ============================================================================

def create_activity(
    db: Session, group_id: str, data, acting_user_id: str,
) -> GroupActivity:
    get_group(db, group_id)
    mem = db.query(GroupMembership).filter(
        GroupMembership.group_id == group_id,
        GroupMembership.user_id == acting_user_id,
        GroupMembership.status == "active",
    ).first()
    if not mem:
        raise GroupError("Only active group members can create activities.", 403)

    if data.activity_type not in {
        "study_session", "revision", "project", "social", "event", "other",
    }:
        raise GroupError("Invalid activity_type.", 400)

    a = GroupActivity(
        group_id=group_id,
        title=data.title.strip(),
        description=data.description,
        activity_type=data.activity_type,
        start_time=data.start_time,
        end_time=data.end_time,
        location=data.location,
        virtual_link=data.virtual_link,
        status="scheduled",
        created_by=acting_user_id,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def list_activities(db: Session, group_id: str) -> list[GroupActivity]:
    return (
        db.query(GroupActivity)
        .filter(GroupActivity.group_id == group_id)
        .order_by(GroupActivity.start_time.desc())
        .all()
    )


# ============================================================================
# ANNOUNCEMENTS
# ============================================================================

def create_announcement(
    db: Session, group_id: str, data, acting_user_id: str,
) -> GroupAnnouncement:
    get_group(db, group_id)
    if not _is_official(db, group_id, acting_user_id, {"leader", "secretary"}):
        raise GroupError(
            "Only the leader or secretary can post announcements.", 403,
        )

    if data.priority not in {"normal", "important", "critical"}:
        raise GroupError("Invalid priority.", 400)

    a = GroupAnnouncement(
        group_id=group_id,
        title=data.title.strip(),
        content=data.content.strip(),
        priority=data.priority,
        is_pinned=data.is_pinned,
        is_archived=False,
        published_by=acting_user_id,
        published_at=datetime.now(timezone.utc),
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def list_announcements(
    db: Session, group_id: str, include_archived: bool = False,
) -> list[GroupAnnouncement]:
    q = db.query(GroupAnnouncement).filter(GroupAnnouncement.group_id == group_id)
    if not include_archived:
        q = q.filter(GroupAnnouncement.is_archived.is_(False))
    return q.order_by(
        GroupAnnouncement.is_pinned.desc(),
        GroupAnnouncement.published_at.desc(),
    ).all()


# ============================================================================
# TIMETABLES
# ============================================================================

def create_timetable(
    db: Session, group_id: str, data, acting_user_id: str,
) -> GroupTimetable:
    get_group(db, group_id)
    if not _is_official(db, group_id, acting_user_id, {"leader", "secretary"}):
        raise GroupError(
            "Only the leader or secretary can create timetables.", 403,
        )

    if data.type not in {"official", "revision"}:
        raise GroupError("Invalid timetable type.", 400)

    t = GroupTimetable(
        group_id=group_id,
        type=data.type,
        name=data.name.strip(),
        description=data.description,
        created_by=acting_user_id,
        approval_status="pending",
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def add_timetable_entries(
    db: Session, timetable_id: str, entries: list, acting_user_id: str,
) -> list[GroupTimetableEntry]:
    t = db.query(GroupTimetable).filter(GroupTimetable.id == timetable_id).first()
    if not t:
        raise GroupError("Timetable not found.", 404)
    if not _is_official(db, t.group_id, acting_user_id, {"leader", "secretary"}):
        raise GroupError(
            "Only the leader or secretary can edit this timetable.", 403,
        )

    created = []
    for e in entries:
        entry = GroupTimetableEntry(
            timetable_id=timetable_id,
            unit_id=e.unit_id,
            day_of_week=e.day_of_week,
            start_time=e.start_time,
            end_time=e.end_time,
            activity_type=e.activity_type,
            location=e.location,
            notes=e.notes,
        )
        db.add(entry)
        created.append(entry)
    db.commit()
    for entry in created:
        db.refresh(entry)
    return created


def list_timetables(db: Session, group_id: str) -> list[GroupTimetable]:
    return (
        db.query(GroupTimetable)
        .filter(GroupTimetable.group_id == group_id)
        .order_by(GroupTimetable.created_at.desc())
        .all()
    )