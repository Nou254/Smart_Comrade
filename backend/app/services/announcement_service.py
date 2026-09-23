"""
Official announcements — Communication module.

Publishing authority is validated against the publisher's active roles
per level. Audience is snapshotted at publish time.

Levels:
  group       → scope_ref_id = groups.id
  unit        → scope_ref_id = unit_offerings.id
  school      → scope_ref_id = schools.id
  institution → scope_ref_id = institutions.id
  county      → scope_ref_id = counties.id
  platform    → scope_ref_id = NULL (all active users)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.announcement import (
    OfficialAnnouncement,
    OfficialAnnouncementAudience,
    VALID_LEVELS,
    VALID_CLASSIFICATIONS,
    VALID_PRIORITIES,
)
from app.services.role_service import resolve_user_permissions


logger = logging.getLogger(__name__)


class AnnouncementError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# Publish authority matrix
# ============================================================================

_PUBLISH_AUTHORITY: dict[str, set[str]] = {
    "group":       {"group_leader", "group_secretary"},
    "unit":        {"unit_representative", "unit_supervisor", "lecturer"},
    "school":      {"school_representative", "assistant_school_rep"},
    "institution": {
        "institution_administrator",
        "assistant_institution_administrator",
    },
    "county": {
        "county_administrator",
        "assistant_county_administrator",
    },
    "platform":    {"super_admin", "regional_admin"},
}

_PRIORITY_ORDER = [
    "super_admin", "regional_admin",
    "county_administrator", "assistant_county_administrator",
    "institution_administrator", "assistant_institution_administrator",
    "school_representative", "assistant_school_rep",
    "unit_supervisor", "lecturer", "unit_representative",
    "group_leader", "group_secretary",
]

_EMERGENCY_PUBLISHERS = {
    "super_admin", "regional_admin",
    "county_administrator", "assistant_county_administrator",
    "institution_administrator", "assistant_institution_administrator",
}


def _assert_publish_authority(
    db: Session, *, publisher_id: str, level: str,
) -> str:
    """
    Resolve the role the publisher acts under. Raises if not allowed.
    """
    roles, _perms = resolve_user_permissions(db, publisher_id)
    if "super_admin" in roles:
        return "super_admin"

    allowed = _PUBLISH_AUTHORITY.get(level, set())
    matched = allowed.intersection(roles)
    if not matched:
        raise AnnouncementError(
            f"You do not have authority to publish at level '{level}'.", 403,
        )
    for code in _PRIORITY_ORDER:
        if code in matched:
            return code
    return next(iter(matched))


# ============================================================================
# Audience resolution
# ============================================================================

def resolve_audience(
    db: Session, *, level: str, scope_ref_id: str | None,
) -> list[str]:
    if level == "platform":
        from app.models.user import User
        rows = db.query(User.id).filter(
            User.account_status == "active",
        ).all()
        return [r[0] for r in rows]

    if not scope_ref_id:
        raise AnnouncementError(
            f"scope_ref_id is required for level '{level}'.", 400,
        )

    if level == "group":
        from app.models.group import GroupMembership
        rows = db.query(GroupMembership.user_id).filter(
            GroupMembership.group_id == scope_ref_id,
            GroupMembership.status == "active",
        ).all()
        return [r[0] for r in rows]

    if level == "unit":
        from app.models.unit_offering import UnitOffering
        from app.models.academic import UnitMembership
        offering = db.query(UnitOffering).filter(
            UnitOffering.id == scope_ref_id,
        ).first()
        if not offering:
            raise AnnouncementError("Unit offering not found.", 404)
        rows = db.query(UnitMembership.user_id).filter(
            UnitMembership.unit_id == offering.unit_id,
            UnitMembership.semester_id == offering.semester_id,
            UnitMembership.status == "active",
        ).all()
        return [r[0] for r in rows]

    if level == "school":
        from app.models.academic import Course, StudentEnrollment
        rows = db.query(StudentEnrollment.student_id).join(
            Course, Course.id == StudentEnrollment.course_id,
        ).filter(
            Course.school_id == scope_ref_id,
            StudentEnrollment.status == "active",
        ).all()
        return [r[0] for r in rows]

    if level == "institution":
        from app.models.academic import StudentEnrollment
        rows = db.query(StudentEnrollment.student_id).filter(
            StudentEnrollment.institution_id == scope_ref_id,
            StudentEnrollment.status == "active",
        ).all()
        return [r[0] for r in rows]

    if level == "county":
        from app.models.academic import Institution, StudentEnrollment
        rows = db.query(StudentEnrollment.student_id).join(
            Institution, Institution.id == StudentEnrollment.institution_id,
        ).filter(
            Institution.county_id == scope_ref_id,
            StudentEnrollment.status == "active",
        ).all()
        return [r[0] for r in rows]

    raise AnnouncementError(f"Unknown level '{level}'.", 400)


# ============================================================================
# Create
# ============================================================================

def create_announcement(
    db: Session, *, publisher_id: str, data,
) -> OfficialAnnouncement:
    if data.level not in VALID_LEVELS:
        raise AnnouncementError(f"Invalid level '{data.level}'.", 400)
    if data.classification not in VALID_CLASSIFICATIONS:
        raise AnnouncementError(
            f"Invalid classification '{data.classification}'.", 400,
        )
    if data.priority not in VALID_PRIORITIES:
        raise AnnouncementError(
            f"Invalid priority '{data.priority}'.", 400,
        )

    publisher_role = _assert_publish_authority(
        db, publisher_id=publisher_id, level=data.level,
    )

    if data.classification == "emergency":
        if publisher_role not in _EMERGENCY_PUBLISHERS:
            raise AnnouncementError(
                "Only authorized administrators may issue emergency "
                "announcements.", 403,
            )

    now = _now()
    is_scheduled = (
        data.scheduled_for is not None and data.scheduled_for > now
    )

    ann = OfficialAnnouncement(
        publisher_id=publisher_id,
        publisher_role=publisher_role,
        level=data.level,
        scope_ref_id=data.scope_ref_id,
        classification=data.classification,
        priority=data.priority,
        title=data.title,
        content=data.content,
        is_pinned=data.is_pinned,
        scheduled_for=data.scheduled_for,
        expires_at=data.expires_at,
        status="scheduled" if is_scheduled else "published",
        published_at=None if is_scheduled else now,
    )
    db.add(ann)
    db.flush()

    if not is_scheduled:
        _snapshot_audience(db, ann)

    db.commit()
    db.refresh(ann)
    return ann


def _snapshot_audience(db: Session, ann: OfficialAnnouncement) -> int:
    user_ids = resolve_audience(
        db, level=ann.level, scope_ref_id=ann.scope_ref_id,
    )
    user_ids = list(dict.fromkeys(user_ids))
    now = _now()
    for uid in user_ids:
        db.add(OfficialAnnouncementAudience(
            announcement_id=ann.id,
            user_id=uid,
            delivered_at=now,
        ))
    ann.audience_count = len(user_ids)
    db.flush()
    return len(user_ids)


def publish_scheduled(db: Session, *, batch_size: int = 200) -> int:
    """Called by a scheduled job to flush due scheduled announcements."""
    now = _now()
    rows = db.query(OfficialAnnouncement).filter(
        OfficialAnnouncement.status == "scheduled",
        OfficialAnnouncement.scheduled_for <= now,
    ).limit(batch_size).all()
    for ann in rows:
        ann.status = "published"
        ann.published_at = now
        _snapshot_audience(db, ann)
    if rows:
        db.commit()
    return len(rows)


# ============================================================================
# Read
# ============================================================================

def get_announcement(
    db: Session, announcement_id: str,
) -> OfficialAnnouncement:
    a = db.query(OfficialAnnouncement).filter(
        OfficialAnnouncement.id == announcement_id,
    ).first()
    if not a:
        raise AnnouncementError("Announcement not found.", 404)
    return a


def list_announcements(
    db: Session, *,
    level: str | None = None,
    scope_ref_id: str | None = None,
    classification: str | None = None,
    include_archived: bool = False,
    limit: int = 100,
) -> list[OfficialAnnouncement]:
    q = db.query(OfficialAnnouncement).filter(
        OfficialAnnouncement.status == "published",
    )
    if level:
        q = q.filter(OfficialAnnouncement.level == level)
    if scope_ref_id:
        q = q.filter(OfficialAnnouncement.scope_ref_id == scope_ref_id)
    if classification:
        q = q.filter(
            OfficialAnnouncement.classification == classification,
        )
    if not include_archived:
        q = q.filter(OfficialAnnouncement.is_archived.is_(False))
    return q.order_by(
        OfficialAnnouncement.is_pinned.desc(),
        OfficialAnnouncement.published_at.desc(),
    ).limit(limit).all()


def list_my_announcements(
    db: Session, *, viewer_id: str, limit: int = 100,
) -> list[dict]:
    """Inbox-style — announcements the viewer received, with read state."""
    rows = db.query(
        OfficialAnnouncement,
        OfficialAnnouncementAudience.is_read,
        OfficialAnnouncementAudience.read_at,
    ).join(
        OfficialAnnouncementAudience,
        OfficialAnnouncementAudience.announcement_id
            == OfficialAnnouncement.id,
    ).filter(
        OfficialAnnouncementAudience.user_id == viewer_id,
        OfficialAnnouncement.status == "published",
        OfficialAnnouncement.is_archived.is_(False),
    ).order_by(
        OfficialAnnouncement.is_pinned.desc(),
        OfficialAnnouncement.published_at.desc(),
    ).limit(limit).all()

    return [
        {"announcement": ann, "is_read": is_read, "read_at": read_at}
        for ann, is_read, read_at in rows
    ]


def list_audience(
    db: Session, *, announcement_id: str,
    limit: int = 200, cursor: str | None = None,
) -> dict:
    get_announcement(db, announcement_id)
    q = db.query(OfficialAnnouncementAudience).filter(
        OfficialAnnouncementAudience.announcement_id == announcement_id,
    )
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(
                OfficialAnnouncementAudience.created_at < cursor_dt,
            )
        except ValueError:
            raise AnnouncementError("Invalid cursor.", 400)

    rows = q.order_by(
        OfficialAnnouncementAudience.created_at.desc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        rows[-1].created_at.isoformat() if rows and has_more else None
    )
    return {
        "audience": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def mark_read(
    db: Session, *, announcement_id: str, user_id: str,
) -> None:
    row = db.query(OfficialAnnouncementAudience).filter(
        OfficialAnnouncementAudience.announcement_id == announcement_id,
        OfficialAnnouncementAudience.user_id == user_id,
    ).first()
    if not row or row.is_read:
        return
    row.is_read = True
    row.read_at = _now()
    db.commit()


# ============================================================================
# Update / archive / correct
# ============================================================================

def update_announcement(
    db: Session, *, announcement_id: str, actor_id: str, data,
) -> OfficialAnnouncement:
    ann = get_announcement(db, announcement_id)
    if ann.publisher_id != actor_id:
        raise AnnouncementError(
            "Only the publisher may edit this announcement.", 403,
        )
    if ann.status == "archived":
        raise AnnouncementError(
            "Cannot edit an archived announcement.", 409,
        )

    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(ann, field, value)
    db.commit()
    db.refresh(ann)
    return ann


def archive_announcement(
    db: Session, *, announcement_id: str, actor_id: str,
) -> OfficialAnnouncement:
    ann = get_announcement(db, announcement_id)
    if ann.publisher_id != actor_id:
        roles, _ = resolve_user_permissions(db, actor_id)
        if "super_admin" not in roles:
            raise AnnouncementError(
                "Only the publisher or a Super Admin may archive this.", 403,
            )
    ann.is_archived = True
    ann.status = "archived"
    ann.archived_at = _now()
    db.commit()
    db.refresh(ann)
    return ann


def publish_correction(
    db: Session, *, original_id: str, actor_id: str, data,
) -> OfficialAnnouncement:
    original = get_announcement(db, original_id)
    if original.publisher_id != actor_id:
        raise AnnouncementError(
            "Only the original publisher may issue a correction.", 403,
        )

    now = _now()
    correction = OfficialAnnouncement(
        publisher_id=actor_id,
        publisher_role=original.publisher_role,
        level=original.level,
        scope_ref_id=original.scope_ref_id,
        classification=original.classification,
        priority="important",
        title=data.correction_title,
        content=data.correction_body,
        correction_of_id=original.id,
        status="published",
        published_at=now,
    )
    db.add(correction)
    db.flush()
    _snapshot_audience(db, correction)
    db.commit()
    db.refresh(correction)
    return correction