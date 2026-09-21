"""
Community endpoints — Module 003 Phase 11.

Route order: literal paths (/messages/, /reports/, /admin/) come before
dynamic /{community_id}/... to avoid path collisions.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.community import (
    Community, CommunityMembership, CommunityMessage,
    CommunityMessageReport, CommunityModerationAction,
)
from app.models.user import User
from app.schemas.community import (
    CommunityResponse, CommunityMembershipResponse, CommunityDetailResponse,
    CommunityMessageCreate, CommunityMessageResponse, CommunityMessageListResponse,
    CommunityReportRequest, CommunityReportResponse, CommunityReportReviewRequest,
    CommunityMuteRequest, CommunityBanRequest, CommunityModerationActionResponse,
    CommunityStatsResponse, CommunityListResponse,
)
from app.services.community_service import (
    CommunityError,
    get_community, list_communities_for_user, list_all_communities,
    leave_community, rejoin_community, archive_community,
)
from app.services.community_message_service import (
    send_message, list_messages, delete_own_message,
)
from app.services.community_moderation_service import (
    report_message, review_report,
    mute_member, unmute_member, ban_member, unban_member,
    hide_message, delete_message_by_moderator,
    get_stats, is_community_moderator,
)

router = APIRouter(prefix="/communities", tags=["Communities"])


def _err(e: CommunityError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


# ============================================================================
# LIST USER'S COMMUNITIES
# ============================================================================

@router.get("", response_model=list[CommunityListResponse])
def get_my_communities(
    community_type: str | None = Query(None, description="course_year | school | institution"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_communities_for_user(
        db, current_user.id,
        community_type=community_type,
        active_only=True,
    )


# ============================================================================
# MESSAGE-LEVEL LITERAL PATHS  (before /{community_id})
# ============================================================================

@router.post(
    "/messages/{message_id}/report",
    response_model=CommunityReportResponse,
    status_code=201,
)
def post_report_message(
    message_id: str,
    payload: CommunityReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return report_message(
            db, message_id, current_user.id,
            reason=payload.reason, notes=payload.notes,
        )
    except CommunityError as e:
        _err(e)


@router.post(
    "/messages/{message_id}/hide",
    response_model=CommunityMessageResponse,
)
def post_hide_message(
    message_id: str,
    reason: str = Query(..., min_length=3, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return hide_message(db, message_id, current_user.id, reason=reason)
    except CommunityError as e:
        _err(e)


@router.post(
    "/messages/{message_id}/mod-delete",
    response_model=CommunityMessageResponse,
)
def post_mod_delete_message(
    message_id: str,
    reason: str = Query(..., min_length=3, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return delete_message_by_moderator(
            db, message_id, current_user.id, reason=reason,
        )
    except CommunityError as e:
        _err(e)


@router.delete(
    "/messages/{message_id}",
    response_model=CommunityMessageResponse,
)
def delete_my_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return delete_own_message(db, message_id, current_user.id)
    except CommunityError as e:
        _err(e)


@router.post(
    "/reports/{report_id}/review",
    response_model=CommunityReportResponse,
)
def post_review_report(
    report_id: str,
    payload: CommunityReportReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return review_report(
            db, report_id, current_user.id,
            decision=payload.status,
            review_notes=payload.review_notes,
            delete_message=payload.delete_message,
            hide_message=payload.hide_message,
        )
    except CommunityError as e:
        _err(e)


# ============================================================================
# ADMIN LITERAL PATHS
# ============================================================================

@router.get(
    "/admin/all",
    response_model=list[CommunityListResponse],
)
def admin_list_all_communities(
    community_type: str | None = Query(None),
    institution_id: str | None = Query(None),
    is_active: bool | None = Query(None),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return list_all_communities(
        db,
        community_type=community_type,
        institution_id=institution_id,
        is_active=is_active,
    )


@router.post(
    "/admin/{community_id}/archive",
    response_model=CommunityResponse,
)
def admin_archive_community(
    community_id: str,
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        return archive_community(db, community_id)
    except CommunityError as e:
        _err(e)


# ============================================================================
# DYNAMIC PATHS — /{community_id}/...
# ============================================================================

@router.get("/{community_id}", response_model=CommunityDetailResponse)
def get_one_community(
    community_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        comm = get_community(db, community_id)
    except CommunityError as e:
        _err(e)

    mem = db.query(CommunityMembership).filter(
        CommunityMembership.community_id == comm.id,
        CommunityMembership.user_id == current_user.id,
    ).first()

    return CommunityDetailResponse(
        community=CommunityResponse.model_validate(comm),
        viewer_membership=(
            CommunityMembershipResponse.model_validate(mem) if mem else None
        ),
        is_moderator=is_community_moderator(db, comm, current_user.id),
    )


@router.get("/{community_id}/messages", response_model=CommunityMessageListResponse)
def get_community_messages(
    community_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = list_messages(
            db, community_id, viewer_id=current_user.id,
            limit=limit, cursor=cursor,
        )
    except CommunityError as e:
        _err(e)

    return CommunityMessageListResponse(
        messages=[
            CommunityMessageResponse.model_validate(m)
            for m in result["messages"]
        ],
        next_cursor=result["next_cursor"],
        has_more=result["has_more"],
    )


@router.post(
    "/{community_id}/messages",
    response_model=CommunityMessageResponse,
    status_code=201,
)
def post_community_message(
    community_id: str,
    payload: CommunityMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return send_message(
            db, community_id, current_user.id,
            content=payload.content, reply_to_id=payload.reply_to_id,
        )
    except CommunityError as e:
        _err(e)


@router.get("/{community_id}/stats", response_model=CommunityStatsResponse)
def get_community_stats(
    community_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        comm = get_community(db, community_id)
        if not is_community_moderator(db, comm, current_user.id):
            raise HTTPException(403, "Only moderators may view community stats.")
        return get_stats(db, community_id)
    except CommunityError as e:
        _err(e)


@router.post("/{community_id}/leave", response_model=CommunityMembershipResponse)
def post_leave_community(
    community_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return leave_community(db, community_id, current_user.id)
    except CommunityError as e:
        _err(e)


@router.post("/{community_id}/rejoin", response_model=CommunityMembershipResponse)
def post_rejoin_community(
    community_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return rejoin_community(db, community_id, current_user.id)
    except CommunityError as e:
        _err(e)


# ============================================================================
# MEMBER MODERATION
# ============================================================================

@router.post(
    "/{community_id}/members/{target_user_id}/mute",
    response_model=CommunityModerationActionResponse,
)
def post_mute_member(
    community_id: str,
    target_user_id: str,
    payload: CommunityMuteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        m = mute_member(
            db, community_id, target_user_id, current_user.id,
            until_at=payload.until_at, reason=payload.reason,
        )
        # Fetch the last moderation action for the response
        action = (
            db.query(CommunityModerationAction)
            .filter(
                CommunityModerationAction.community_id == community_id,
                CommunityModerationAction.target_user_id == target_user_id,
                CommunityModerationAction.action_type == "mute_member",
            )
            .order_by(CommunityModerationAction.created_at.desc())
            .first()
        )
        return action
    except CommunityError as e:
        _err(e)


@router.post(
    "/{community_id}/members/{target_user_id}/unmute",
    response_model=CommunityMembershipResponse,
)
def post_unmute_member(
    community_id: str,
    target_user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return unmute_member(db, community_id, target_user_id, current_user.id)
    except CommunityError as e:
        _err(e)


@router.post(
    "/{community_id}/members/{target_user_id}/ban",
    response_model=CommunityMembershipResponse,
)
def post_ban_member(
    community_id: str,
    target_user_id: str,
    payload: CommunityBanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return ban_member(
            db, community_id, target_user_id, current_user.id,
            reason=payload.reason,
        )
    except CommunityError as e:
        _err(e)


@router.post(
    "/{community_id}/members/{target_user_id}/unban",
    response_model=CommunityMembershipResponse,
)
def post_unban_member(
    community_id: str,
    target_user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return unban_member(db, community_id, target_user_id, current_user.id)
    except CommunityError as e:
        _err(e)