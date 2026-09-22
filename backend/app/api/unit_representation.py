"""
Unit Representation endpoints — Module 004.

Route groups:
  /unit-representatives/...              appointment lifecycle
  /unit-networks/...                     network read + coordination chat
  /unit-offerings/{id}/discussions/...   student-facing discussions
  /unit-offerings/{id}/announcements/... unit-wide announcements
  /unit-offerings/{id}/issues/...        issues + escalation
  /unit-offerings/{id}/questions/...     AI-assisted educational questions
  /unit-offerings/{id}/resources/...     shared resources
  /unit-offerings/{id}/analytics/...     per-offering analytics
  /admin/unit-rep/...                    platform-wide admin views

Route ordering note: literal segments (public, replace, by-offering,
analytics, rescan, flag, supervisor-response) are declared before
dynamic /{id} segments at the same depth.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.user import User
from app.models.unit_representation import (
    UnitRepresentative, UnitNetwork, UnitNetworkMember,
    UnitCoordinationMessage, UnitDiscussion, UnitAnnouncement,
    UnitIssue, UnitIssueEscalation,
    UnitQuestion, UnitQuestionResponse,
    UnitSharedResource,
    REP_ACTIVE,
)
from app.schemas.unit_representation import (
    UnitRepresentativeAppoint, UnitRepresentativeEnd,
    UnitRepresentativeResponse, UnitRepresentativeListResponse,
    UnitNetworkResponse, UnitNetworkDetailResponse,
    UnitNetworkMemberResponse,
    UnitCoordinationMessageCreate, UnitCoordinationMessageResponse,
    UnitCoordinationMessageListResponse,
    UnitDiscussionCreate, UnitDiscussionUpdate, UnitDiscussionResponse,
    UnitAnnouncementCreate, UnitAnnouncementUpdate, UnitAnnouncementResponse,
    UnitIssueCreate, UnitIssueEscalate, UnitIssueResolve,
    UnitIssueResponse, UnitIssuePublicResponse, UnitIssueListResponse,
    UnitIssueEscalationResponse,
    UnitQuestionCreate, UnitQuestionResponse, UnitQuestionListItem,
    UnitQuestionSupervisorResponseCreate, UnitQuestionResponseItem,
    UnitQuestionDetailResponse,
    UnitSharedResourceCreate, UnitSharedResourceUpdate,
    UnitSharedResourceResponse, UnitSharedResourcePublicResponse,
)
from app.services.unit_representation_service import (
    UnitRepError,
    appoint_representative, end_representative, replace_representative,
    suspend_representative, reactivate_representative,
    list_representatives, list_active_reps_for_offering,
    get_representative, get_active_rep_for_group_and_offering,
)
from app.services.unit_network_service import (
    UnitNetworkError,
    get_or_create_network, get_network, get_network_by_offering,
    add_member, remove_member, list_members, is_network_member,
    archive_network,
)
from app.services.unit_discussion_service import (
    UnitDiscussionError,
    create_discussion, update_discussion, soft_delete_discussion,
    list_discussions, list_replies,
    create_announcement, update_announcement, list_announcements,
)
from app.services.unit_issue_service import (
    UnitIssueError,
    create_issue, escalate_issue, resolve_issue, dismiss_issue,
    withdraw_issue, get_issue, list_issues, list_public_issues,
    list_escalations,
)
from app.services.unit_question_service import (
    UnitQuestionError,
    pose_question, supervisor_respond, resolve_question, dismiss_question,
    get_question, list_questions, list_responses,
)
from app.services.unit_resource_service import (
    UnitResourceError,
    share_resource, force_rescan, supervisor_flag_resource,
    get_resource, list_published_resources, list_network_resources,
)
from app.services.unit_analytics_service import (
    offering_coverage, global_rep_coverage, network_activity,
    rep_activity_summary, ai_response_sla, pending_resource_scans,
)
from app.services.admin_audit_service import log_admin_action


router = APIRouter(tags=["Unit Representation"])


# ── helpers ─────────────────────────────────────────────────────────────

def _err(e):
    """Translate any unit-* service exception into an HTTPException."""
    raise HTTPException(
        status_code=getattr(e, "status_code", 400),
        detail=getattr(e, "message", str(e)),
    )


def _require_offering_access(
    db: Session, user_id: str, unit_offering_id: str,
) -> None:
    """
    Any authenticated user taking the unit or representing a group
    taking it may read. Writes are gated separately per endpoint.
    """
    # Only real check: user exists. Fine-grained checks happen in
    # the service or via specific `_require_rep` / `_require_moderator`.
    return


def _require_rep(
    db: Session, user_id: str, unit_offering_id: str,
) -> UnitRepresentative:
    """Raise 403 unless the user is an active rep for this offering."""
    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.user_id == user_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if not rep:
        raise HTTPException(
            status_code=403,
            detail="Only active Unit Representatives may perform this action.",
        )
    return rep


# ═════════════════════════════════════════════════════════════════════════
# 1. UNIT REPRESENTATIVES
# ═════════════════════════════════════════════════════════════════════════

@router.post(
    "/unit-representatives",
    response_model=UnitRepresentativeResponse,
    status_code=201,
)
def post_appoint_representative(
    payload: UnitRepresentativeAppoint,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Group Leader appoints a member as Unit Rep for a specific offering."""
    try:
        return appoint_representative(
            db,
            group_id=payload.group_id,
            unit_offering_id=payload.unit_offering_id,
            user_id=payload.user_id,
            appointed_by=current_user.id,
            notes=payload.notes,
        )
    except UnitRepError as e:
        _err(e)


@router.get(
    "/unit-representatives",
    response_model=list[UnitRepresentativeListResponse],
)
def get_representatives(
    group_id: str | None = Query(None),
    unit_offering_id: str | None = Query(None),
    user_id: str | None = Query(None),
    semester_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_representatives(
        db,
        group_id=group_id,
        unit_offering_id=unit_offering_id,
        user_id=user_id,
        semester_id=semester_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/unit-representatives/by-offering/{unit_offering_id}",
    response_model=list[UnitRepresentativeListResponse],
)
def get_active_reps_for_offering(
    unit_offering_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_active_reps_for_offering(db, unit_offering_id)


@router.get(
    "/unit-representatives/by-group-offering",
    response_model=UnitRepresentativeResponse | None,
)
def get_rep_for_group_and_offering(
    group_id: str = Query(...),
    unit_offering_id: str = Query(...),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_active_rep_for_group_and_offering(
        db, group_id, unit_offering_id,
    )


@router.get(
    "/unit-representatives/{representative_id}",
    response_model=UnitRepresentativeResponse,
)
def get_one_representative(
    representative_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_representative(db, representative_id)
    except UnitRepError as e:
        _err(e)


@router.post(
    "/unit-representatives/{representative_id}/end",
    response_model=UnitRepresentativeResponse,
)
def post_end_representative(
    representative_id: str,
    payload: UnitRepresentativeEnd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return end_representative(
            db,
            representative_id=representative_id,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except UnitRepError as e:
        _err(e)


@router.post(
    "/unit-representatives/{representative_id}/resign",
    response_model=UnitRepresentativeResponse,
)
def post_resign_representative(
    representative_id: str,
    payload: UnitRepresentativeEnd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A rep resigns from their own position."""
    try:
        rep = get_representative(db, representative_id)
        if rep.user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You may only resign your own appointment.",
            )
        return end_representative(
            db,
            representative_id=representative_id,
            actor_id=current_user.id,
            reason=payload.reason,
            new_status="resigned",
        )
    except UnitRepError as e:
        _err(e)


@router.post(
    "/unit-representatives/{representative_id}/suspend",
    response_model=UnitRepresentativeResponse,
)
def post_suspend_representative(
    representative_id: str,
    payload: UnitRepresentativeEnd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return suspend_representative(
            db,
            representative_id=representative_id,
            actor_id=current_user.id,
            reason=payload.reason,
        )
    except UnitRepError as e:
        _err(e)


@router.post(
    "/unit-representatives/{representative_id}/reactivate",
    response_model=UnitRepresentativeResponse,
)
def post_reactivate_representative(
    representative_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return reactivate_representative(
            db,
            representative_id=representative_id,
            actor_id=current_user.id,
        )
    except UnitRepError as e:
        _err(e)


@router.post(
    "/unit-representatives/replace",
    response_model=UnitRepresentativeResponse,
)
def post_replace_representative(
    old_representative_id: str = Query(...),
    new_user_id: str = Query(...),
    reason: str = Query(..., min_length=3, max_length=500),
    notes: str | None = Query(None, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Replace a Unit Rep. The outgoing rep is silently removed from the
    network; no notification is sent. Their historical messages remain
    visible to the remaining network members.
    """
    try:
        return replace_representative(
            db,
            old_representative_id=old_representative_id,
            new_user_id=new_user_id,
            actor_id=current_user.id,
            reason=reason,
            notes=notes,
        )
    except UnitRepError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# 2. UNIT NETWORKS
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-networks/by-offering/{unit_offering_id}",
    response_model=UnitNetworkResponse | None,
)
def get_network_for_offering(
    unit_offering_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_network_by_offering(db, unit_offering_id)


@router.get(
    "/unit-networks/{network_id}",
    response_model=UnitNetworkDetailResponse,
)
def get_one_network(
    network_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Network detail. Members-only access: reps and supervisor.
    """
    try:
        network = get_network(db, network_id)
        if not is_network_member(db, network_id=network_id, user_id=current_user.id):
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this network.",
            )
        members = list_members(db, network_id=network_id, active_only=True)
        return UnitNetworkDetailResponse(
            network=UnitNetworkResponse.model_validate(network),
            members=[
                UnitNetworkMemberResponse.model_validate(m) for m in members
            ],
        )
    except UnitNetworkError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# 3. NETWORK COORDINATION MESSAGES
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-networks/{network_id}/messages",
    response_model=UnitCoordinationMessageListResponse,
)
def get_network_messages(
    network_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Paginated network chat. Only active network members may read.
    """
    if not is_network_member(db, network_id=network_id, user_id=current_user.id):
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this network.",
        )

    q = db.query(UnitCoordinationMessage).filter(
        UnitCoordinationMessage.network_id == network_id,
        UnitCoordinationMessage.is_deleted.is_(False),
    )
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(UnitCoordinationMessage.created_at < cursor_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor.")

    rows = q.order_by(
        UnitCoordinationMessage.created_at.desc(),
    ).limit(limit + 1).all()

    has_more = len(rows) > limit
    messages = rows[:limit]
    next_cursor = (
        messages[-1].created_at.isoformat() if messages and has_more else None
    )

    return UnitCoordinationMessageListResponse(
        messages=[
            UnitCoordinationMessageResponse.model_validate(m) for m in messages
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post(
    "/unit-networks/{network_id}/messages",
    response_model=UnitCoordinationMessageResponse,
    status_code=201,
)
def post_network_message(
    network_id: str,
    payload: UnitCoordinationMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a coordination message. Network members only."""
    if not is_network_member(db, network_id=network_id, user_id=current_user.id):
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this network.",
        )

    network = get_network(db, network_id)
    if not network.is_active:
        raise HTTPException(
            status_code=409,
            detail="This network is archived and read-only.",
        )

    msg = UnitCoordinationMessage(
        network_id=network_id,
        sender_id=current_user.id,
        content=payload.content,
        reply_to_id=payload.reply_to_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.delete(
    "/unit-networks/{network_id}/messages/{message_id}",
    response_model=UnitCoordinationMessageResponse,
)
def delete_network_message(
    network_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a message. Sender only."""
    msg = db.query(UnitCoordinationMessage).filter(
        UnitCoordinationMessage.id == message_id,
        UnitCoordinationMessage.network_id == network_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")
    if msg.sender_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You may only delete your own messages.",
        )

    msg.is_deleted = True
    msg.deleted_at = datetime.now()
    msg.deleted_by = current_user.id
    db.commit()
    db.refresh(msg)
    return msg


@router.post(
    "/unit-networks/{network_id}/messages/{message_id}/hide",
    response_model=UnitCoordinationMessageResponse,
)
def hide_network_message(
    network_id: str,
    message_id: str,
    reason: str = Query(..., min_length=3, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Supervisor-only moderation hide. The message disappears from
    network view but the row remains for audit.
    """
    network = get_network(db, network_id)
    if network.supervisor_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the assigned Unit Supervisor may hide messages.",
        )

    msg = db.query(UnitCoordinationMessage).filter(
        UnitCoordinationMessage.id == message_id,
        UnitCoordinationMessage.network_id == network_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")

    msg.is_deleted = True
    msg.deleted_at = datetime.now()
    msg.deleted_by = current_user.id
    db.commit()
    db.refresh(msg)

    log_admin_action(
        db, actor_id=current_user.id, action="unit_network.message.hide",
        target_type="unit_coordination_message", target_id=message_id,
        reason=reason,
    )
    return msg


# ═════════════════════════════════════════════════════════════════════════
# 4. UNIT DISCUSSIONS
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-offerings/{unit_offering_id}/discussions",
    response_model=list[UnitDiscussionResponse],
)
def get_unit_discussions(
    unit_offering_id: str,
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Root threads for a unit offering."""
    return list_discussions(
        db,
        unit_offering_id=unit_offering_id,
        include_deleted=include_deleted,
        limit=limit,
    )


@router.post(
    "/unit-offerings/{unit_offering_id}/discussions",
    response_model=UnitDiscussionResponse,
    status_code=201,
)
def post_unit_discussion(
    unit_offering_id: str,
    payload: UnitDiscussionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_discussion(
            db,
            unit_offering_id=unit_offering_id,
            author_id=current_user.id,
            title=payload.title,
            content=payload.content,
            parent_id=payload.parent_id,
        )
    except UnitDiscussionError as e:
        _err(e)


@router.get(
    "/unit-offerings/{unit_offering_id}/discussions/{discussion_id}/replies",
    response_model=list[UnitDiscussionResponse],
)
def get_discussion_replies(
    unit_offering_id: str,
    discussion_id: str,
    include_deleted: bool = Query(False),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_replies(
        db, parent_id=discussion_id, include_deleted=include_deleted,
    )


@router.post(
    "/unit-offerings/{unit_offering_id}/discussions/{discussion_id}/replies",
    response_model=UnitDiscussionResponse,
    status_code=201,
)
def post_discussion_reply(
    unit_offering_id: str,
    discussion_id: str,
    payload: UnitDiscussionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_discussion(
            db,
            unit_offering_id=unit_offering_id,
            author_id=current_user.id,
            title=None,
            content=payload.content,
            parent_id=discussion_id,
        )
    except UnitDiscussionError as e:
        _err(e)


@router.patch(
    "/unit-offerings/{unit_offering_id}/discussions/{discussion_id}",
    response_model=UnitDiscussionResponse,
)
def patch_unit_discussion(
    unit_offering_id: str,
    discussion_id: str,
    payload: UnitDiscussionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pin or lock a thread. Reps and supervisor only."""
    try:
        return update_discussion(
            db,
            discussion_id=discussion_id,
            actor_id=current_user.id,
            is_pinned=payload.is_pinned,
            is_locked=payload.is_locked,
        )
    except UnitDiscussionError as e:
        _err(e)


@router.delete(
    "/unit-offerings/{unit_offering_id}/discussions/{discussion_id}",
    response_model=UnitDiscussionResponse,
)
def delete_unit_discussion(
    unit_offering_id: str,
    discussion_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return soft_delete_discussion(
            db,
            discussion_id=discussion_id,
            actor_id=current_user.id,
        )
    except UnitDiscussionError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# 5. UNIT ANNOUNCEMENTS
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-offerings/{unit_offering_id}/announcements",
    response_model=list[UnitAnnouncementResponse],
)
def get_unit_announcements(
    unit_offering_id: str,
    include_archived: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_announcements(
        db,
        unit_offering_id=unit_offering_id,
        include_archived=include_archived,
        limit=limit,
    )


@router.post(
    "/unit-offerings/{unit_offering_id}/announcements",
    response_model=UnitAnnouncementResponse,
    status_code=201,
)
def post_unit_announcement(
    unit_offering_id: str,
    payload: UnitAnnouncementCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_announcement(
            db,
            unit_offering_id=unit_offering_id,
            publisher_id=current_user.id,
            title=payload.title,
            content=payload.content,
            is_pinned=payload.is_pinned,
        )
    except UnitDiscussionError as e:
        _err(e)


@router.patch(
    "/unit-offerings/{unit_offering_id}/announcements/{announcement_id}",
    response_model=UnitAnnouncementResponse,
)
def patch_unit_announcement(
    unit_offering_id: str,
    announcement_id: str,
    payload: UnitAnnouncementUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_announcement(
            db,
            announcement_id=announcement_id,
            actor_id=current_user.id,
            title=payload.title,
            content=payload.content,
            is_pinned=payload.is_pinned,
            is_archived=payload.is_archived,
        )
    except UnitDiscussionError as e:
        _err(e)


@router.delete(
    "/unit-offerings/{unit_offering_id}/announcements/{announcement_id}",
    response_model=UnitAnnouncementResponse,
)
def delete_unit_announcement(
    unit_offering_id: str,
    announcement_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive an announcement (soft delete)."""
    try:
        return update_announcement(
            db,
            announcement_id=announcement_id,
            actor_id=current_user.id,
            is_archived=True,
        )
    except UnitDiscussionError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# 6. UNIT ISSUES
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-offerings/{unit_offering_id}/issues/public",
    response_model=UnitIssueListResponse,
)
def get_public_issues(
    unit_offering_id: str,
    limit: int = Query(200, ge=1, le=500),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Non-rep view — public issues and their outcomes only.
    """
    rows = list_public_issues(
        db, unit_offering_id=unit_offering_id, limit=limit,
    )
    return UnitIssueListResponse(
        issues=[UnitIssuePublicResponse.model_validate(r) for r in rows],
    )


@router.get(
    "/unit-offerings/{unit_offering_id}/issues",
    response_model=list[UnitIssueResponse],
)
def get_unit_issues(
    unit_offering_id: str,
    status: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Full issue list. Reps and supervisor only. Public list is a
    separate endpoint.
    """
    _require_rep(db, current_user.id, unit_offering_id)
    return list_issues(
        db,
        unit_offering_id=unit_offering_id,
        status=status,
        category=category,
        limit=limit,
    )


@router.post(
    "/unit-offerings/{unit_offering_id}/issues",
    response_model=UnitIssueResponse,
    status_code=201,
)
def post_unit_issue(
    unit_offering_id: str,
    payload: UnitIssueCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Raise an issue. Rep-only. May be raised on behalf of an anonymous
    student by setting is_anonymous + anonymous_student_reference.
    """
    try:
        return create_issue(
            db,
            unit_offering_id=unit_offering_id,
            raised_by_user_id=current_user.id,
            category=payload.category,
            title=payload.title,
            description=payload.description,
            is_anonymous=payload.is_anonymous,
            anonymous_student_reference=payload.anonymous_student_reference,
            is_public=payload.is_public,
            public_summary=payload.public_summary,
        )
    except UnitIssueError as e:
        _err(e)


@router.get(
    "/unit-offerings/{unit_offering_id}/issues/{issue_id}",
    response_model=UnitIssueResponse,
)
def get_one_issue(
    unit_offering_id: str,
    issue_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rep or supervisor view of a full issue."""
    _require_rep(db, current_user.id, unit_offering_id)
    try:
        return get_issue(db, issue_id)
    except UnitIssueError as e:
        _err(e)


@router.get(
    "/unit-offerings/{unit_offering_id}/issues/{issue_id}/escalations",
    response_model=list[UnitIssueEscalationResponse],
)
def get_issue_escalations(
    unit_offering_id: str,
    issue_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_rep(db, current_user.id, unit_offering_id)
    return list_escalations(db, issue_id)


@router.post(
    "/unit-offerings/{unit_offering_id}/issues/{issue_id}/escalate",
    response_model=UnitIssueResponse,
)
def post_escalate_issue(
    unit_offering_id: str,
    issue_id: str,
    payload: UnitIssueEscalate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return escalate_issue(
            db,
            issue_id=issue_id,
            to_level=payload.to_level,
            actor_id=current_user.id,
            notes=payload.notes,
        )
    except UnitIssueError as e:
        _err(e)


@router.post(
    "/unit-offerings/{unit_offering_id}/issues/{issue_id}/resolve",
    response_model=UnitIssueResponse,
)
def post_resolve_issue(
    unit_offering_id: str,
    issue_id: str,
    payload: UnitIssueResolve,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return resolve_issue(
            db,
            issue_id=issue_id,
            actor_id=current_user.id,
            resolution_notes=payload.resolution_notes,
        )
    except UnitIssueError as e:
        _err(e)


@router.post(
    "/unit-offerings/{unit_offering_id}/issues/{issue_id}/dismiss",
    response_model=UnitIssueResponse,
)
def post_dismiss_issue(
    unit_offering_id: str,
    issue_id: str,
    payload: UnitIssueResolve,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return dismiss_issue(
            db,
            issue_id=issue_id,
            actor_id=current_user.id,
            resolution_notes=payload.resolution_notes,
        )
    except UnitIssueError as e:
        _err(e)


@router.post(
    "/unit-offerings/{unit_offering_id}/issues/{issue_id}/withdraw",
    response_model=UnitIssueResponse,
)
def post_withdraw_issue(
    unit_offering_id: str,
    issue_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return withdraw_issue(
            db, issue_id=issue_id, actor_id=current_user.id,
        )
    except UnitIssueError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# 7. UNIT QUESTIONS (AI-assisted educational research)
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-offerings/{unit_offering_id}/questions",
    response_model=list[UnitQuestionListItem],
)
def get_unit_questions(
    unit_offering_id: str,
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_rep(db, current_user.id, unit_offering_id)
    return list_questions(
        db, unit_offering_id=unit_offering_id, status=status, limit=limit,
    )


@router.post(
    "/unit-offerings/{unit_offering_id}/questions",
    response_model=UnitQuestionResponse,
    status_code=201,
)
def post_unit_question(
    unit_offering_id: str,
    payload: UnitQuestionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Pose an educational question. Rep-only. AI responds within 5 minutes.
    Can be raised on behalf of an anonymous student.
    """
    try:
        return pose_question(
            db,
            unit_offering_id=unit_offering_id,
            raised_by_user_id=current_user.id,
            subject=payload.subject,
            question_text=payload.question_text,
            category=payload.category,
            is_anonymous=payload.is_anonymous,
            anonymous_student_reference=payload.anonymous_student_reference,
        )
    except UnitQuestionError as e:
        _err(e)


@router.get(
    "/unit-offerings/{unit_offering_id}/questions/{question_id}",
    response_model=UnitQuestionDetailResponse,
)
def get_one_question(
    unit_offering_id: str,
    question_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_rep(db, current_user.id, unit_offering_id)
    try:
        question = get_question(db, question_id)
    except UnitQuestionError as e:
        _err(e)
    responses = list_responses(db, question_id)
    return UnitQuestionDetailResponse(
        question=UnitQuestionResponse.model_validate(question),
        responses=[
            UnitQuestionResponseItem.model_validate(r) for r in responses
        ],
    )


@router.post(
    "/unit-offerings/{unit_offering_id}/questions/{question_id}/supervisor-response",
    response_model=UnitQuestionResponseItem,
)
def post_supervisor_response(
    unit_offering_id: str,
    question_id: str,
    payload: UnitQuestionSupervisorResponseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Supervisor posts a response. May supersede an earlier AI response.
    """
    try:
        return supervisor_respond(
            db,
            question_id=question_id,
            supervisor_user_id=current_user.id,
            content=payload.content,
            supersedes_response_id=payload.supersedes_response_id,
        )
    except UnitQuestionError as e:
        _err(e)


@router.post(
    "/unit-offerings/{unit_offering_id}/questions/{question_id}/resolve",
    response_model=UnitQuestionResponse,
)
def post_resolve_question(
    unit_offering_id: str,
    question_id: str,
    resolution_notes: str = Query(..., min_length=5, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return resolve_question(
            db,
            question_id=question_id,
            actor_id=current_user.id,
            resolution_notes=resolution_notes,
        )
    except UnitQuestionError as e:
        _err(e)


@router.post(
    "/unit-offerings/{unit_offering_id}/questions/{question_id}/dismiss",
    response_model=UnitQuestionResponse,
)
def post_dismiss_question(
    unit_offering_id: str,
    question_id: str,
    resolution_notes: str = Query(..., min_length=5, max_length=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return dismiss_question(
            db,
            question_id=question_id,
            actor_id=current_user.id,
            resolution_notes=resolution_notes,
        )
    except UnitQuestionError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# 8. UNIT SHARED RESOURCES
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-offerings/{unit_offering_id}/resources/public",
    response_model=list[UnitSharedResourcePublicResponse],
)
def get_public_resources(
    unit_offering_id: str,
    limit: int = Query(200, ge=1, le=500),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Student-facing list — only all-unit-visible published resources.
    """
    rows = list_published_resources(
        db,
        unit_offering_id=unit_offering_id,
        visibility="all_unit_students",
        limit=limit,
    )
    return [
        UnitSharedResourcePublicResponse.model_validate(r) for r in rows
    ]


@router.get(
    "/unit-offerings/{unit_offering_id}/resources",
    response_model=list[UnitSharedResourceResponse],
)
def get_unit_resources(
    unit_offering_id: str,
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rep-facing list — includes network-only resources."""
    _require_rep(db, current_user.id, unit_offering_id)
    return list_network_resources(
        db, unit_offering_id=unit_offering_id, limit=limit,
    )


@router.post(
    "/unit-offerings/{unit_offering_id}/resources",
    response_model=UnitSharedResourceResponse,
    status_code=201,
)
def post_unit_resource(
    unit_offering_id: str,
    payload: UnitSharedResourceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Share a resource. AI scans for unit relevance before publishing.
    """
    try:
        return share_resource(
            db,
            unit_offering_id=unit_offering_id,
            shared_by_user_id=current_user.id,
            title=payload.title,
            resource_type=payload.resource_type,
            description=payload.description,
            file_url=payload.file_url,
            external_url=payload.external_url,
            content_text=payload.content_text,
            visibility=payload.visibility,
            source_group_id=payload.source_group_id,
        )
    except UnitResourceError as e:
        _err(e)


@router.get(
    "/unit-offerings/{unit_offering_id}/resources/{resource_id}",
    response_model=UnitSharedResourceResponse,
)
def get_one_resource(
    unit_offering_id: str,
    resource_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_rep(db, current_user.id, unit_offering_id)
    try:
        return get_resource(db, resource_id)
    except UnitResourceError as e:
        _err(e)


@router.post(
    "/unit-offerings/{unit_offering_id}/resources/{resource_id}/rescan",
    response_model=UnitSharedResourceResponse,
)
def post_rescan_resource(
    unit_offering_id: str,
    resource_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Force a re-run of the AI scan."""
    _require_rep(db, current_user.id, unit_offering_id)
    try:
        return force_rescan(db, resource_id)
    except UnitResourceError as e:
        _err(e)


@router.post(
    "/unit-offerings/{unit_offering_id}/resources/{resource_id}/flag",
    response_model=UnitSharedResourceResponse,
)
def post_flag_resource(
    unit_offering_id: str,
    resource_id: str,
    reason: str = Query(..., min_length=3, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Supervisor flags a resource as off-topic."""
    try:
        return supervisor_flag_resource(
            db,
            resource_id=resource_id,
            supervisor_user_id=current_user.id,
            reason=reason,
        )
    except UnitResourceError as e:
        _err(e)


# ═════════════════════════════════════════════════════════════════════════
# 9. PER-OFFERING ANALYTICS
# ═════════════════════════════════════════════════════════════════════════

@router.get(
    "/unit-offerings/{unit_offering_id}/analytics/coverage",
)
def get_offering_coverage(
    unit_offering_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rep or supervisor only."""
    _require_rep(db, current_user.id, unit_offering_id)
    return offering_coverage(db, unit_offering_id=unit_offering_id)


@router.get(
    "/unit-networks/{network_id}/analytics/activity",
)
def get_network_analytics(
    network_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_network_member(db, network_id=network_id, user_id=current_user.id):
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this network.",
        )
    return network_activity(db, network_id=network_id)


@router.get(
    "/unit-representatives/{representative_id}/analytics/activity",
)
def get_rep_analytics(
    representative_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rep = get_representative(db, representative_id)
    except UnitRepError as e:
        _err(e)
    # Self or admin only
    if rep.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You may only view your own representative analytics.",
        )
    return rep_activity_summary(db, representative_id=representative_id)


# ═════════════════════════════════════════════════════════════════════════
# 10. ADMIN VIEWS
# ═════════════════════════════════════════════════════════════════════════

@router.get("/admin/unit-rep/analytics/global-coverage")
def admin_global_coverage(
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return global_rep_coverage(db)


@router.get("/admin/unit-rep/analytics/ai-sla")
def admin_ai_sla(
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """SLA monitor for the 5-minute AI response target."""
    return ai_response_sla(db)


@router.get("/admin/unit-rep/analytics/pending-scans")
def admin_pending_scans(
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """How many resources are stuck in the AI scan pipeline."""
    return {"pending_scans": pending_resource_scans(db)}


@router.post("/admin/unit-rep/networks/{network_id}/archive")
def admin_archive_network(
    network_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Force-archive a network (emergency)."""
    try:
        network = archive_network(
            db, network_id=network_id, actor_id=current_user.id,
        )
    except UnitNetworkError as e:
        _err(e)
    log_admin_action(
        db, actor_id=current_user.id, action="unit_network.force_archive",
        target_type="unit_network", target_id=network_id,
    )
    return UnitNetworkResponse.model_validate(network)