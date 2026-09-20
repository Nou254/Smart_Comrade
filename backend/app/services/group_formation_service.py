"""
Group formation service — Module 003 Phases 3+4 + security layer.

Owns:
  - Course-bound group creation with founder → provisional leader
  - Curated unit list (from OCR output)
  - Slug + invite-token lifecycle (7-day token, permanent slug)
  - Preview flows (token-based, slug-based)
  - Join request submission → leader approval → membership activation
  - Election trigger when eligibility is met

Every path into a group creates a GroupJoinRequest. No auto-join.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.invite_security import (
    generate_invite_token,
    generate_unique_slug,
    hash_invite_token,
    invite_token_expiry,
    log_invite_event,
    visitor_matches_group,
)
from app.models.academic import (
    AcademicYear,
    Course,
    Institution,
    School,
    Semester,
    StudentEnrollment,
)
from app.models.group import (
    Group,
    GroupMembership,
    GroupOfficial,
)
from app.models.group_join_request import GroupJoinRequest
from app.models.group_subscription import GroupSubscription
from app.models.group_unit import GroupUnit, GroupUnitConfirmation
from app.services.group_subscription_service import (
    check_election_eligibility,
    create_trial_subscription,
    refresh_member_count,
)

logger = logging.getLogger(__name__)


JOIN_REQUEST_TTL_DAYS = 30
JOIN_REQUEST_MESSAGE_MAX = 500


class GroupFormationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# GROUP CREATION
# ============================================================================

def create_group_with_context(
    db: Session, data, creator_id: str,
) -> dict:
    """
    Full context creation. The creator must be enrolled in the given
    course + semester. Returns the group plus the plain invite token and
    the two URLs (invite + slug).
    """
    # --- Validate academic chain ---
    inst = db.query(Institution).filter(Institution.id == data.institution_id).first()
    if not inst:
        raise GroupFormationError("Institution not found.", 404)

    school = db.query(School).filter(
        School.id == data.school_id, School.institution_id == inst.id,
    ).first()
    if not school:
        raise GroupFormationError("School not found in this institution.", 404)

    course = db.query(Course).filter(
        Course.id == data.course_id, Course.school_id == school.id,
    ).first()
    if not course:
        raise GroupFormationError("Course not found in this school.", 404)

    ay = db.query(AcademicYear).filter(
        AcademicYear.id == data.academic_year_id,
        AcademicYear.institution_id == inst.id,
    ).first()
    if not ay:
        raise GroupFormationError("Academic year not found.", 404)

    sem = db.query(Semester).filter(
        Semester.id == data.semester_id,
        Semester.academic_year_id == ay.id,
    ).first()
    if not sem:
        raise GroupFormationError("Semester not found.", 404)

    # --- Validate creator's enrollment ---
    enrollment = (
        db.query(StudentEnrollment)
        .filter(
            StudentEnrollment.user_id == creator_id,
            StudentEnrollment.course_id == course.id,
            StudentEnrollment.semester_id == sem.id,
            StudentEnrollment.status == "active",
        )
        .first()
    )
    if not enrollment:
        raise GroupFormationError(
            "You are not enrolled in this course for this semester.", 403,
        )

    if data.combination_id and enrollment.combination_id != data.combination_id:
        raise GroupFormationError(
            "Your subject combination does not match.", 409,
        )

    # --- Uniqueness ---
    existing = db.query(Group).filter(
        Group.institution_id == inst.id,
        Group.course_id == course.id,
        Group.semester_id == sem.id,
        Group.name == data.name.strip(),
    ).first()
    if existing:
        raise GroupFormationError(
            "A group with this name already exists in this semester.", 409,
        )

    if data.visibility not in ("private", "public", "invitation_only"):
        raise GroupFormationError("Invalid visibility.", 400)

    # --- Generate slug + invite token ---
    slug = generate_unique_slug(db, data.name.strip())
    plain_token = generate_invite_token()
    token_hash = hash_invite_token(plain_token)
    token_expires = invite_token_expiry()

    now = _now()

    group = Group(
        name=data.name.strip(),
        description=data.description,
        group_type="academic",
        slug=slug,
        institution_id=inst.id,
        school_id=school.id,
        course_id=course.id,
        combination_id=data.combination_id,
        academic_year_id=ay.id,
        semester_id=sem.id,
        year_level=data.year_level,
        creator_id=creator_id,
        is_provisional=True,
        status="forming",
        visibility=data.visibility,
        subscription_status="trial",
        invite_token=token_hash,
        invite_expires_at=token_expires,
        max_members=data.max_members,
        member_count=1,
    )
    db.add(group)
    db.flush()

    # --- Founding leader: active member + provisional leader ---
    db.add(GroupMembership(
        group_id=group.id,
        user_id=creator_id,
        status="active",
        joined_at=now,
        joined_via_invite=False,
        course_confirmed_at=now,
        units_confirmed_at=None,
    ))
    db.add(GroupOfficial(
        group_id=group.id,
        user_id=creator_id,
        position="leader",
        status="active",
        term_start=now,
        appointed_by=creator_id,
        notes="Provisional founding leader",
    ))

    # --- Trial subscription ---
    create_trial_subscription(db, group.id, member_count=1)

    db.commit()
    db.refresh(group)

    log_invite_event(
        db,
        event_type="group.created",
        group_id=group.id,
        actor_id=creator_id,
        extra={"slug": slug, "name": group.name},
    )

    return {
        "group": group,
        "invite_token": plain_token,
        "invite_expires_at": token_expires,
        "invite_url": f"https://app.smartcomrade.com/join/{plain_token}",
        "slug_url": f"https://app.smartcomrade.com/g/{slug}",
    }


# ============================================================================
# SLUG / TOKEN ROTATION
# ============================================================================

def rotate_invite_token(
    db: Session, group_id: str, actor_id: str,
) -> dict:
    """Founder only. Issues a new 7-day token and invalidates the old one."""
    group = _get_group_for_mutation(db, group_id)
    _ensure_founder_or_leader(db, group, actor_id)

    plain = generate_invite_token()
    group.invite_token = hash_invite_token(plain)
    group.invite_expires_at = invite_token_expiry()

    db.commit()
    db.refresh(group)

    log_invite_event(
        db,
        event_type="invite.rotated",
        group_id=group.id,
        actor_id=actor_id,
    )

    return {
        "group_id": group.id,
        "invite_token": plain,
        "invite_expires_at": group.invite_expires_at,
        "invite_url": f"https://app.smartcomrade.com/join/{plain}",
    }


def rotate_slug(
    db: Session, group_id: str, actor_id: str,
) -> dict:
    """Founder only. Issues a new slug; the old link 404s immediately."""
    group = _get_group_for_mutation(db, group_id)
    _ensure_founder_or_leader(db, group, actor_id)

    old_slug = group.slug
    group.slug = generate_unique_slug(db, group.name)

    db.commit()
    db.refresh(group)

    log_invite_event(
        db,
        event_type="slug.rotated",
        group_id=group.id,
        actor_id=actor_id,
        extra={"old_slug": old_slug, "new_slug": group.slug},
    )

    return {
        "group_id": group.id,
        "slug": group.slug,
        "slug_url": f"https://app.smartcomrade.com/g/{group.slug}",
    }


# ============================================================================
# PREVIEW
# ============================================================================

def preview_by_token(
    db: Session, plain_token: str, viewer_id: str,
    ip: str | None = None, user_agent: str | None = None,
) -> dict:
    """Preview a group via the invite token. Auth-required at the API layer."""
    token_hash = hash_invite_token(plain_token)
    group = db.query(Group).filter(Group.invite_token == token_hash).first()
    if not group:
        log_invite_event(
            db, event_type="invite.preview.miss",
            ip_address=ip, user_agent=user_agent,
            extra={"reason": "token_not_found"},
        )
        raise GroupFormationError("Invalid invite link.", 404)

    ok, reason = _invite_is_usable(group)
    if not ok:
        log_invite_event(
            db, event_type="invite.preview.blocked",
            group_id=group.id, actor_id=viewer_id,
            ip_address=ip, user_agent=user_agent,
            extra={"reason": reason},
        )
        raise GroupFormationError(reason or "Invite is not usable.", 410)

    matches, mismatch_reason = visitor_matches_group(db, viewer_id, group)
    if not matches:
        log_invite_event(
            db, event_type="invite.preview.mismatch",
            group_id=group.id, actor_id=viewer_id,
            ip_address=ip, user_agent=user_agent,
            extra={"reason": mismatch_reason},
        )
        raise GroupFormationError(mismatch_reason or "Enrollment mismatch.", 403)

    log_invite_event(
        db, event_type="invite.preview.hit",
        group_id=group.id, actor_id=viewer_id,
        ip_address=ip, user_agent=user_agent,
        extra={"source": "token"},
    )
    return _build_preview(db, group, source="invite_token")


def preview_by_slug(
    db: Session, slug: str, viewer_id: str,
    ip: str | None = None, user_agent: str | None = None,
) -> dict:
    """Preview a group via the permanent slug."""
    group = db.query(Group).filter(Group.slug == slug).first()
    if not group:
        log_invite_event(
            db, event_type="slug.preview.miss",
            ip_address=ip, user_agent=user_agent,
            extra={"reason": "slug_not_found"},
        )
        raise GroupFormationError("Group not found.", 404)

    # Slug previews do not require a valid token, but the group must still
    # be accepting join requests.
    ok, reason = _group_accepting_joins(group)
    if not ok:
        raise GroupFormationError(reason or "Group is not accepting joins.", 410)

    matches, mismatch_reason = visitor_matches_group(db, viewer_id, group)
    if not matches:
        raise GroupFormationError(mismatch_reason or "Enrollment mismatch.", 403)

    log_invite_event(
        db, event_type="slug.preview.hit",
        group_id=group.id, actor_id=viewer_id,
        ip_address=ip, user_agent=user_agent,
        extra={"source": "slug"},
    )
    return _build_preview(db, group, source="slug_link")


def _build_preview(db: Session, group: Group, *, source: str) -> dict:
    inst = db.query(Institution).filter(Institution.id == group.institution_id).first()
    school = db.query(School).filter(School.id == group.school_id).first()
    course = db.query(Course).filter(Course.id == group.course_id).first()
    sem = db.query(Semester).filter(Semester.id == group.semester_id).first()

    units = (
        db.query(GroupUnit)
        .filter(GroupUnit.group_id == group.id)
        .order_by(GroupUnit.code)
        .all()
    )

    invite_valid = (
        group.invite_expires_at is not None
        and group.invite_expires_at > _now()
        and group.invite_token is not None
    )

    return {
        "group_id": group.id,
        "group_name": group.name,
        "group_slug": group.slug,
        "description": group.description,
        "institution_name": inst.name if inst else "",
        "school_name": school.name if school else "",
        "course_name": course.name if course else "",
        "course_code": course.code if course else "",
        "semester_name": sem.name if sem else "",
        "year_level": group.year_level,
        "member_count": group.member_count,
        "max_members": group.max_members,
        "status": group.status,
        "invite_valid": invite_valid,
        "invite_expires_at": group.invite_expires_at,
        "source": source,
        "units": units,
    }


# ============================================================================
# GROUP UNITS — CURATION
# ============================================================================

def curate_group_units(
    db: Session, group_id: str, data, actor_id: str,
) -> list[GroupUnit]:
    """
    Replace the group's curated unit list with `data.units`.
    Founder or acting leader only. Existing GroupUnit rows not in the
    new list are deleted (their confirmations cascade).

    This is normally called once, right after the founder uploads the
    timetable and reviews the OCR extraction. It can be called again if
    the group needs to correct the list before the first election.
    """
    group = _get_group_for_mutation(db, group_id)
    _ensure_founder_or_leader(db, group, actor_id)

    if group.status not in ("forming",):
        raise GroupFormationError(
            "The unit list can only be curated before the first election.", 409,
        )

    # Delete existing rows
    db.query(GroupUnit).filter(GroupUnit.group_id == group_id).delete()

    created: list[GroupUnit] = []
    for u in data.units:
        row = GroupUnit(
            group_id=group_id,
            code=u.code.strip().upper(),
            name=u.name.strip(),
            description=u.description,
            year_level=u.year_level,
            semester_number=u.semester_number,
            unit_id=u.unit_id,
            source=u.source,
            source_extracted_unit_id=u.source_extracted_unit_id,
            created_by=actor_id,
        )
        db.add(row)
        created.append(row)

    db.commit()
    for row in created:
        db.refresh(row)
    return created


def list_group_units(db: Session, group_id: str) -> list[GroupUnit]:
    return (
        db.query(GroupUnit)
        .filter(GroupUnit.group_id == group_id)
        .order_by(GroupUnit.code)
        .all()
    )


# ============================================================================
# JOIN REQUEST SUBMISSION
# ============================================================================

def submit_join_request_via_token(
    db: Session,
    plain_token: str,
    user_id: str,
    data,
    ip: str | None = None,
    user_agent: str | None = None,
) -> GroupJoinRequest:
    token_hash = hash_invite_token(plain_token)
    group = db.query(Group).filter(Group.invite_token == token_hash).first()
    if not group:
        raise GroupFormationError("Invalid invite link.", 404)
    return _submit_join_request(
        db, group, user_id, data, source="invite_token",
        ip=ip, user_agent=user_agent,
    )


def submit_join_request_via_slug(
    db: Session,
    slug: str,
    user_id: str,
    data,
    ip: str | None = None,
    user_agent: str | None = None,
) -> GroupJoinRequest:
    group = db.query(Group).filter(Group.slug == slug).first()
    if not group:
        raise GroupFormationError("Group not found.", 404)
    return _submit_join_request(
        db, group, user_id, data, source="slug_link",
        ip=ip, user_agent=user_agent,
    )


def _submit_join_request(
    db: Session,
    group: Group,
    user_id: str,
    data,
    *,
    source: str,
    ip: str | None,
    user_agent: str | None,
) -> GroupJoinRequest:
    ok, reason = _group_accepting_joins(group)
    if not ok:
        raise GroupFormationError(reason or "Group is not accepting joins.", 410)

    matches, mismatch_reason = visitor_matches_group(db, user_id, group)
    if not matches:
        raise GroupFormationError(mismatch_reason or "Enrollment mismatch.", 403)

    # Already a member?
    existing_member = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == user_id,
            GroupMembership.status == "active",
        )
        .first()
    )
    if existing_member:
        raise GroupFormationError("You are already an active member.", 409)

    # Existing pending request? Return it (idempotent).
    existing_request = (
        db.query(GroupJoinRequest)
        .filter(
            GroupJoinRequest.group_id == group.id,
            GroupJoinRequest.user_id == user_id,
            GroupJoinRequest.status == "pending",
        )
        .first()
    )
    if existing_request:
        return existing_request

    if not data.course_confirmed:
        raise GroupFormationError(
            "You must confirm your course/semester enrollment.", 400,
        )

    if not data.unit_confirmations:
        raise GroupFormationError(
            "You must confirm at least one unit.", 400,
        )

    # Validate every submitted group_unit_id belongs to this group.
    group_unit_ids = {
        row.id for row in
        db.query(GroupUnit).filter(GroupUnit.group_id == group.id).all()
    }
    for uc in data.unit_confirmations:
        if uc.group_unit_id not in group_unit_ids:
            raise GroupFormationError(
                f"Unit {uc.group_unit_id} does not belong to this group.", 400,
            )

    now = _now()
    expires_at = now.replace(microsecond=0)  # placeholder, set properly below
    from datetime import timedelta
    expires_at = now + timedelta(days=JOIN_REQUEST_TTL_DAYS)

    snapshot = [
        {
            "group_unit_id": uc.group_unit_id,
            "confirmed": uc.confirmed,
            "flagged_as_incorrect": uc.flagged_as_incorrect,
            "note": uc.note,
        }
        for uc in data.unit_confirmations
    ]

    request = GroupJoinRequest(
        group_id=group.id,
        user_id=user_id,
        status="pending",
        source=source,
        message=(data.message or "")[:JOIN_REQUEST_MESSAGE_MAX] or None,
        course_confirmed=True,
        unit_confirmations_json=json.dumps(snapshot),
        expires_at=expires_at,
        request_ip=ip,
        request_user_agent=(user_agent or "")[:255] or None,
    )
    db.add(request)

    # Record the per-unit confirmations immediately so the leader can
    # review them while deciding. They are tied to this user; if the
    # request is rejected they stay on file (audit trail).
    for uc in data.unit_confirmations:
        db.add(GroupUnitConfirmation(
            group_unit_id=uc.group_unit_id,
            user_id=user_id,
            confirmed=uc.confirmed,
            flagged_as_incorrect=uc.flagged_as_incorrect,
            note=uc.note,
            confirmed_at=now if uc.confirmed else None,
        ))

    # Keep a pending membership row so the leader can see the request
    # in the group's member list too.
    existing_mem = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == user_id,
        )
        .first()
    )
    if existing_mem:
        existing_mem.status = "pending"
        existing_mem.joined_via_invite = source == "invite_token"
        existing_mem.course_confirmed_at = now
        existing_mem.units_confirmed_at = now
    else:
        db.add(GroupMembership(
            group_id=group.id,
            user_id=user_id,
            status="pending",
            joined_via_invite=source == "invite_token",
            course_confirmed_at=now,
            units_confirmed_at=now,
        ))

    db.commit()
    db.refresh(request)

    log_invite_event(
        db,
        event_type="join_request.submitted",
        group_id=group.id,
        actor_id=user_id,
        ip_address=ip,
        user_agent=user_agent,
        extra={"source": source, "request_id": request.id},
    )

    return request


# ============================================================================
# JOIN REQUEST DECISIONS
# ============================================================================

def list_join_requests(
    db: Session, group_id: str, status: str = "pending",
) -> list[GroupJoinRequest]:
    q = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.group_id == group_id,
    )
    if status:
        q = q.filter(GroupJoinRequest.status == status)
    return q.order_by(GroupJoinRequest.created_at.asc()).all()


def approve_join_request(
    db: Session, request_id: str, actor_id: str,
    notes: str | None = None,
) -> dict:
    request = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.id == request_id,
    ).first()
    if not request:
        raise GroupFormationError("Join request not found.", 404)
    if request.status != "pending":
        raise GroupFormationError(
            f"Request is not pending (status={request.status}).", 409,
        )

    group = _get_group_for_mutation(db, request.group_id)
    _ensure_founder_or_leader(db, group, actor_id)

    ok, reason = _group_accepting_joins(group)
    if not ok:
        raise GroupFormationError(reason or "Group is not accepting joins.", 410)

    now = _now()

    request.status = "approved"
    request.reviewed_by = actor_id
    request.reviewed_at = now
    request.review_notes = notes

    membership = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == request.user_id,
        )
        .first()
    )
    if not membership:
        membership = GroupMembership(
            group_id=group.id,
            user_id=request.user_id,
            status="active",
            joined_at=now,
            joined_via_invite=request.source == "invite_token",
            approved_by=actor_id,
        )
        db.add(membership)
    else:
        membership.status = "active"
        membership.joined_at = now
        membership.approved_by = actor_id

    db.flush()
    refresh_member_count(db, group.id)

    # Election trigger check
    triggered = _maybe_trigger_election(db, group.id)

    db.commit()

    log_invite_event(
        db,
        event_type="join_request.approved",
        group_id=group.id,
        actor_id=actor_id,
        extra={
            "request_id": request.id,
            "new_member": request.user_id,
            "election_triggered": triggered,
        },
    )

    return {
        "request_id": request.id,
        "status": "approved",
        "membership_id": membership.id,
        "message": "Member approved and added to the group.",
    }


def reject_join_request(
    db: Session, request_id: str, actor_id: str,
    reason: str,
) -> dict:
    request = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.id == request_id,
    ).first()
    if not request:
        raise GroupFormationError("Join request not found.", 404)
    if request.status != "pending":
        raise GroupFormationError(
            f"Request is not pending (status={request.status}).", 409,
        )

    group = _get_group_for_mutation(db, request.group_id)
    _ensure_founder_or_leader(db, group, actor_id)

    now = _now()
    request.status = "rejected"
    request.reviewed_by = actor_id
    request.reviewed_at = now
    request.review_notes = reason

    membership = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group.id,
            GroupMembership.user_id == request.user_id,
            GroupMembership.status == "pending",
        )
        .first()
    )
    if membership:
        membership.status = "removed"
        membership.left_at = now
        membership.notes = f"Join request rejected: {reason}"

    db.commit()

    log_invite_event(
        db,
        event_type="join_request.rejected",
        group_id=group.id,
        actor_id=actor_id,
        extra={"request_id": request.id, "reason": reason},
    )

    return {
        "request_id": request.id,
        "status": "rejected",
        "membership_id": None,
        "message": "Join request rejected.",
    }


def withdraw_join_request(
    db: Session, request_id: str, user_id: str,
) -> GroupJoinRequest:
    request = db.query(GroupJoinRequest).filter(
        GroupJoinRequest.id == request_id,
    ).first()
    if not request:
        raise GroupFormationError("Join request not found.", 404)
    if request.user_id != user_id:
        raise GroupFormationError("You can only withdraw your own request.", 403)
    if request.status != "pending":
        raise GroupFormationError(
            f"Request is not pending (status={request.status}).", 409,
        )

    now = _now()
    request.status = "withdrawn"
    request.reviewed_at = now

    membership = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == request.group_id,
            GroupMembership.user_id == user_id,
            GroupMembership.status == "pending",
        )
        .first()
    )
    if membership:
        membership.status = "left"
        membership.left_at = now

    db.commit()
    db.refresh(request)
    return request


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _get_group_for_mutation(db: Session, group_id: str) -> Group:
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise GroupFormationError("Group not found.", 404)
    return group


def _ensure_founder_or_leader(db: Session, group: Group, actor_id: str) -> None:
    """
    Founder OR current active leader may act on formation-level mutations.
    """
    if group.creator_id == actor_id:
        return
    leader = (
        db.query(GroupOfficial)
        .filter(
            GroupOfficial.group_id == group.id,
            GroupOfficial.user_id == actor_id,
            GroupOfficial.position == "leader",
            GroupOfficial.status == "active",
        )
        .first()
    )
    if leader:
        return
    raise GroupFormationError(
        "Only the founder or group leader may perform this action.", 403,
    )


def _group_accepting_joins(group: Group) -> tuple[bool, str | None]:
    if group.status in ("pending_election", "suspended", "archived"):
        return False, f"Group is not accepting joins (status={group.status})."
    if group.member_count >= group.max_members:
        return False, "Group is full."
    return True, None


def _invite_is_usable(group: Group) -> tuple[bool, str | None]:
    ok, reason = _group_accepting_joins(group)
    if not ok:
        return False, reason
    if group.invite_token is None:
        return False, "Invite link has been revoked."
    if group.invite_expires_at is None:
        return False, "Invite link has been revoked."
    if group.invite_expires_at <= _now():
        return False, "Invite link has expired."
    return True, None


def _maybe_trigger_election(db: Session, group_id: str) -> bool:
    """
    Called after every membership change. If the group is in 'forming'
    and eligibility is met, flip it to 'pending_election' and stamp
    election_triggered_at. Idempotent.
    """
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        return False
    if group.status != "forming":
        return False
    if group.election_triggered_at is not None:
        return False

    status = check_election_eligibility(db, group_id)
    if not status["eligible"]:
        return False

    group.status = "pending_election"
    group.election_triggered_at = _now()

    logger.info(
        "[election.triggered] group=%s members=%s subscription=%s",
        group.id, group.member_count, group.subscription_status,
    )
    return True