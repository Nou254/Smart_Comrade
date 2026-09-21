"""
Community moderation service — Module 003 Phase 11.

Moderator assignment rules:
  - Course-year: School Rep + Assistant + Group Leaders of that cohort
  - School:      School Rep + Assistant
  - Institution: Institution Rep + Assistant + Super Admin
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.community import (
    Community, CommunityMembership, CommunityMessage,
    CommunityMessageReport, CommunityModerationAction,
)
from app.models.group import Group, GroupOfficial
from app.models.role import Role, UserRole
from app.services.community_service import (
    CommunityError, get_community, refresh_member_count,
    INSTITUTION, SCHOOL, COURSE_YEAR,
)


logger = logging.getLogger(__name__)


AUTO_HIDE_REPORT_THRESHOLD = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# MODERATOR AUTHORIZATION
# ============================================================================

def is_community_moderator(db: Session, community: Community, user_id: str) -> bool:
    if _has_role_in(db, user_id, "super_admin"):
        return True

    if community.community_type == INSTITUTION:
        return _has_role_at(db, user_id, "institution_representative",
                            "institution", community.institution_id) or \
               _has_role_at(db, user_id, "assistant_institution_rep",
                            "institution", community.institution_id)

    if community.community_type == SCHOOL:
        return _has_role_at(db, user_id, "school_representative",
                            "school", community.school_id) or \
               _has_role_at(db, user_id, "assistant_school_rep",
                            "school", community.school_id)

    if community.community_type == COURSE_YEAR:
        # School rep also moderates course-year communities in their school
        if _has_role_at(db, user_id, "school_representative",
                        "school", community.school_id):
            return True
        # Group Leaders of that cohort
        group_ids = [
            g.id for g in db.query(Group.id).filter(
                Group.course_id == community.course_id,
                Group.year_level == community.year_level,
                Group.school_id == community.school_id,
            ).all()
        ]
        if not group_ids:
            return False
        return db.query(GroupOfficial).filter(
            GroupOfficial.group_id.in_(group_ids),
            GroupOfficial.user_id == user_id,
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
        ).first() is not None

    return False


def _has_role_in(db: Session, user_id: str, role_code: str) -> bool:
    return db.query(UserRole).join(Role, UserRole.role_id == Role.id).filter(
        UserRole.user_id == user_id,
        Role.code == role_code,
        UserRole.status == "active",
    ).first() is not None


def _has_role_at(
    db: Session, user_id: str, role_code: str,
    jurisdiction_type: str, jurisdiction_id: str,
) -> bool:
    return db.query(UserRole).join(Role, UserRole.role_id == Role.id).filter(
        UserRole.user_id == user_id,
        Role.code == role_code,
        UserRole.jurisdiction_type == jurisdiction_type,
        UserRole.jurisdiction_id == jurisdiction_id,
        UserRole.status == "active",
    ).first() is not None


def _require_moderator(db: Session, community: Community, user_id: str) -> None:
    if not is_community_moderator(db, community, user_id):
        raise CommunityError("Only community moderators may perform this action.", 403)


# ============================================================================
# REPORT
# ============================================================================

def report_message(
    db: Session,
    message_id: str,
    reporter_id: str,
    reason: str,
    notes: str | None = None,
) -> CommunityMessageReport:
    msg = db.query(CommunityMessage).filter(CommunityMessage.id == message_id).first()
    if not msg:
        raise CommunityError("Message not found.", 404)

    # One report per user per message
    existing = db.query(CommunityMessageReport).filter(
        CommunityMessageReport.message_id == message_id,
        CommunityMessageReport.reporter_id == reporter_id,
    ).first()
    if existing:
        return existing

    r = CommunityMessageReport(
        message_id=message_id,
        reporter_id=reporter_id,
        reason=reason,
        notes=notes,
        status="pending",
    )
    db.add(r)
    db.flush()

    # Auto-hide if threshold reached
    total_reports = db.query(CommunityMessageReport).filter(
        CommunityMessageReport.message_id == message_id,
    ).count()
    if total_reports >= AUTO_HIDE_REPORT_THRESHOLD and not msg.is_hidden:
        msg.is_hidden = True
        msg.hidden_at = _now()
        msg.hidden_reason = f"Auto-hidden after {total_reports} reports."

    db.commit()
    db.refresh(r)
    return r


# ============================================================================
# REVIEW REPORT
# ============================================================================

def review_report(
    db: Session,
    report_id: str,
    moderator_id: str,
    decision: str,
    review_notes: str | None = None,
    delete_message: bool = False,
    hide_message: bool = False,
) -> CommunityMessageReport:
    r = db.query(CommunityMessageReport).filter(
        CommunityMessageReport.id == report_id,
    ).first()
    if not r:
        raise CommunityError("Report not found.", 404)

    msg = db.query(CommunityMessage).filter(
        CommunityMessage.id == r.message_id,
    ).first()
    if not msg:
        raise CommunityError("Message no longer exists.", 404)

    community = get_community(db, msg.community_id)
    _require_moderator(db, community, moderator_id)

    if decision not in ("resolved", "dismissed"):
        raise CommunityError("decision must be 'resolved' or 'dismissed'.", 400)

    r.status = decision
    r.reviewed_by = moderator_id
    r.reviewed_at = _now()
    r.review_notes = review_notes

    if hide_message and not msg.is_hidden:
        msg.is_hidden = True
        msg.hidden_at = _now()
        msg.hidden_reason = review_notes or "Moderator hidden."
        _log_action(db, community.id, moderator_id, None, msg.id, "hide_message", review_notes)

    if delete_message and not msg.is_deleted:
        msg.is_deleted = True
        msg.deleted_at = _now()
        msg.deleted_by = moderator_id
        msg.delete_reason = review_notes or "Moderator deleted."
        _log_action(db, community.id, moderator_id, None, msg.id, "delete_message", review_notes)

    db.commit()
    db.refresh(r)
    return r


# ============================================================================
# MUTE / BAN
# ============================================================================

def mute_member(
    db: Session,
    community_id: str,
    target_user_id: str,
    moderator_id: str,
    until_at: datetime,
    reason: str,
) -> CommunityMembership:
    community = get_community(db, community_id)
    _require_moderator(db, community, moderator_id)

    m = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == target_user_id,
    ).first()
    if not m:
        raise CommunityError("Target user is not a member of this community.", 404)

    m.muted_until = until_at
    _log_action(db, community_id, moderator_id, target_user_id, None,
                "mute_member", reason, until_at=until_at)
    db.commit()
    db.refresh(m)
    return m


def unmute_member(
    db: Session, community_id: str, target_user_id: str, moderator_id: str,
) -> CommunityMembership:
    community = get_community(db, community_id)
    _require_moderator(db, community, moderator_id)
    m = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == target_user_id,
    ).first()
    if not m:
        raise CommunityError("Target user is not a member.", 404)
    m.muted_until = None
    _log_action(db, community_id, moderator_id, target_user_id, None, "unmute_member", None)
    db.commit()
    db.refresh(m)
    return m


def ban_member(
    db: Session, community_id: str, target_user_id: str,
    moderator_id: str, reason: str,
) -> CommunityMembership:
    community = get_community(db, community_id)
    _require_moderator(db, community, moderator_id)
    if community.community_type == INSTITUTION:
        # Institution community: can't ban, only mute
        raise CommunityError(
            "Institution members cannot be banned, only muted.", 409,
        )

    m = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == target_user_id,
    ).first()
    if not m:
        raise CommunityError("Target user is not a member.", 404)

    m.banned_at = _now()
    m.banned_by = moderator_id
    m.ban_reason = reason
    m.is_active = False
    m.left_at = _now()
    refresh_member_count(db, community_id)
    _log_action(db, community_id, moderator_id, target_user_id, None,
                "ban_member", reason)
    db.commit()
    db.refresh(m)
    return m


def unban_member(
    db: Session, community_id: str, target_user_id: str, moderator_id: str,
) -> CommunityMembership:
    community = get_community(db, community_id)
    _require_moderator(db, community, moderator_id)
    m = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.user_id == target_user_id,
    ).first()
    if not m:
        raise CommunityError("Target user is not a member.", 404)
    m.banned_at = None
    m.banned_by = None
    m.ban_reason = None
    _log_action(db, community_id, moderator_id, target_user_id, None,
                "unban_member", None)
    db.commit()
    db.refresh(m)
    return m


# ============================================================================
# MODERATOR MESSAGE ACTIONS
# ============================================================================

def hide_message(
    db: Session, message_id: str, moderator_id: str, reason: str,
) -> CommunityMessage:
    msg = db.query(CommunityMessage).filter(CommunityMessage.id == message_id).first()
    if not msg:
        raise CommunityError("Message not found.", 404)
    community = get_community(db, msg.community_id)
    _require_moderator(db, community, moderator_id)

    msg.is_hidden = True
    msg.hidden_at = _now()
    msg.hidden_reason = reason
    _log_action(db, community.id, moderator_id, None, msg.id, "hide_message", reason)
    db.commit()
    db.refresh(msg)
    return msg


def delete_message_by_moderator(
    db: Session, message_id: str, moderator_id: str, reason: str,
) -> CommunityMessage:
    msg = db.query(CommunityMessage).filter(CommunityMessage.id == message_id).first()
    if not msg:
        raise CommunityError("Message not found.", 404)
    community = get_community(db, msg.community_id)
    _require_moderator(db, community, moderator_id)

    msg.is_deleted = True
    msg.deleted_at = _now()
    msg.deleted_by = moderator_id
    msg.delete_reason = reason
    _log_action(db, community.id, moderator_id, None, msg.id, "delete_message", reason)
    db.commit()
    db.refresh(msg)
    return msg


# ============================================================================
# STATS
# ============================================================================

def get_stats(db: Session, community_id: str) -> dict:
    community = get_community(db, community_id)
    active_members = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.is_active.is_(True),
    ).count()
    total_msgs = db.query(CommunityMessage).filter(
        CommunityMessage.community_id == community_id,
        CommunityMessage.is_deleted.is_(False),
    ).count()

    now = _now()
    last_24h = db.query(CommunityMessage).filter(
        CommunityMessage.community_id == community_id,
        CommunityMessage.created_at >= now - __import__("datetime").timedelta(hours=24),
    ).count()
    last_7d = db.query(CommunityMessage).filter(
        CommunityMessage.community_id == community_id,
        CommunityMessage.created_at >= now - __import__("datetime").timedelta(days=7),
    ).count()

    reports_pending = (
        db.query(CommunityMessageReport)
        .join(CommunityMessage, CommunityMessageReport.message_id == CommunityMessage.id)
        .filter(
            CommunityMessage.community_id == community_id,
            CommunityMessageReport.status.in_(("pending", "reviewing")),
        )
        .count()
    )
    muted = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.muted_until > now,
    ).count()
    banned = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == community_id,
        CommunityMembership.banned_at.isnot(None),
    ).count()

    return {
        "community_id": community_id,
        "member_count": community.member_count,
        "active_member_count": active_members,
        "message_count_total": total_msgs,
        "message_count_last_24h": last_24h,
        "message_count_last_7d": last_7d,
        "reports_pending": reports_pending,
        "muted_members": muted,
        "banned_members": banned,
    }


# ============================================================================
# INTERNAL
# ============================================================================

def _log_action(
    db: Session,
    community_id: str,
    moderator_id: str,
    target_user_id: str | None,
    target_message_id: str | None,
    action_type: str,
    reason: str | None,
    until_at: datetime | None = None,
) -> None:
    db.add(CommunityModerationAction(
        community_id=community_id,
        moderator_id=moderator_id,
        target_user_id=target_user_id,
        target_message_id=target_message_id,
        action_type=action_type,
        reason=reason,
        until_at=until_at,
    ))