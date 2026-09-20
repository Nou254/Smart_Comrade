"""
Student Groups endpoints — Module 003.

Route order matters: literal prefixes (/invite/, /g/, /join-requests/)
come before dynamic segments (/{group_id}/...) so FastAPI's path matcher
picks the right handler.

Every join path (invite token, slug, direct request) creates a
GroupJoinRequest. Leader approval is required before any membership
becomes active.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.group import (
    # Group
    GroupCreate, GroupCreateWithContext, GroupUpdate, GroupResponse,
    GroupCreatedResponse,
    # Membership (legacy)
    LegacyJoinNotes,
    MembershipUpdate, MembershipResponse,
    # Officials
    OfficialAppoint, OfficialResponse,
    # Meetings
    MeetingCreate, MeetingUpdate, MeetingResponse,
    # Activities
    ActivityCreate, ActivityResponse,
    # Announcements
    AnnouncementCreate, AnnouncementResponse,
    # Timetables
    TimetableCreate, TimetableEntryCreate, TimetableEntryResponse,
    TimetableApprovalAction, TimetableResponse,
    # Invite flow
    GroupInvitePreview, GroupJoinRequestSubmit, GroupJoinRequestResponse,
    GroupJoinRequestDecision, GroupJoinRequestResult,
    InviteRotationResponse,
    GroupUnitResponse, GroupUnitsCurateRequest,
    # Subscription
    GroupSubscriptionResponse, SubscriptionCalculationResponse,
    SubscriptionRenewRequest,
    # Eligibility
    GroupEligibilityResponse,
)
from app.services.group_service import (
    GroupError,
    create_group, list_groups, get_group, update_group,
    join_group, list_members, update_membership, leave_group,
    appoint_official, list_officials, remove_official,
    create_meeting, list_meetings,
    create_activity, list_activities,
    create_announcement, list_announcements,
    create_timetable, add_timetable_entries, list_timetables,
)
from app.services.group_formation_service import (
    GroupFormationError,
    create_group_with_context,
    rotate_invite_token, rotate_slug,
    preview_by_token, preview_by_slug,
    curate_group_units, list_group_units,
    submit_join_request_via_token, submit_join_request_via_slug,
    list_join_requests, approve_join_request,
    reject_join_request, withdraw_join_request,
)
from app.services.group_subscription_service import (
    SubscriptionError,
    calculate_amount, calculate_breakdown,
    get_active_subscription, activate_subscription,
    check_election_eligibility,
)

router = APIRouter(prefix="/groups", tags=["Student Groups"])


def _err(e):
    """Uniform error translation for any of the group-service exceptions."""
    raise HTTPException(status_code=getattr(e, "status_code", 400),
                        detail=getattr(e, "message", str(e)))


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


# ============================================================================
# CREATE + LIST  (literal path, matched before /{group_id})
# ============================================================================

@router.post("", response_model=GroupCreatedResponse, status_code=201)
def post_group(
    payload: GroupCreateWithContext,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a course-bound group. Requires the creator to be enrolled in
    the given course + semester. Returns the group plus its slug URL and
    a freshly-minted 7-day invite token.
    """
    try:
        result = create_group_with_context(db, payload, creator_id=current_user.id)
    except (GroupFormationError, GroupError) as e:
        _err(e)

    return GroupCreatedResponse(
        group=result["group"],
        invite_token=result["invite_token"],
        invite_expires_at=result["invite_expires_at"],
        invite_url=result["invite_url"],
        slug_url=result["slug_url"],
    )


@router.get("", response_model=list[GroupResponse])
def get_groups(
    institution_id: str | None = Query(None),
    course_id: str | None = Query(None),
    semester_id: str | None = Query(None),
    unit_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    visibility: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_groups(
        db,
        institution_id=institution_id,
        course_id=course_id,
        semester_id=semester_id,
        unit_id=unit_id,
        status_filter=status_filter,
        visibility=visibility,
    )


# ============================================================================
# PREVIEW VIA INVITE TOKEN  (literal "invite" prefix)
# ============================================================================

@router.get("/invite/{token}", response_model=GroupInvitePreview)
def preview_invite(
    token: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Preview the group behind an invite token. Auth required; the visitor
    must match the group's course + semester. Does not consume the token.
    """
    try:
        preview = preview_by_token(
            db, token, viewer_id=current_user.id,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except GroupFormationError as e:
        _err(e)
    return preview


@router.post("/invite/{token}/request", response_model=GroupJoinRequestResponse, status_code=201)
def submit_request_via_token(
    token: str,
    payload: GroupJoinRequestSubmit,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit a join request via invite token. Creates a GroupJoinRequest
    (pending) plus a pending GroupMembership. The leader must approve.
    """
    try:
        req = submit_join_request_via_token(
            db, token, user_id=current_user.id, data=payload,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except GroupFormationError as e:
        _err(e)
    return req


# ============================================================================
# PREVIEW VIA SLUG  (literal "g" prefix)
# ============================================================================

@router.get("/g/{slug}", response_model=GroupInvitePreview)
def preview_slug(
    slug: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview the group via its permanent slug link."""
    try:
        preview = preview_by_slug(
            db, slug, viewer_id=current_user.id,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except GroupFormationError as e:
        _err(e)
    return preview


@router.post("/g/{slug}/request", response_model=GroupJoinRequestResponse, status_code=201)
def submit_request_via_slug(
    slug: str,
    payload: GroupJoinRequestSubmit,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit a join request via the permanent slug link."""
    try:
        req = submit_join_request_via_slug(
            db, slug, user_id=current_user.id, data=payload,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except GroupFormationError as e:
        _err(e)
    return req


# ============================================================================
# JOIN REQUEST DECISIONS  (literal "join-requests" prefix)
# ============================================================================

@router.post("/join-requests/{request_id}/approve", response_model=GroupJoinRequestResult)
def approve_request(
    request_id: str,
    payload: GroupJoinRequestDecision,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a pending join request. Founder or leader only."""
    if not payload.approve:
        raise HTTPException(
            status_code=400,
            detail="Use the /reject endpoint to reject a request.",
        )
    try:
        result = approve_join_request(
            db, request_id, actor_id=current_user.id, notes=payload.notes,
        )
    except GroupFormationError as e:
        _err(e)
    return result


@router.post("/join-requests/{request_id}/reject", response_model=GroupJoinRequestResult)
def reject_request(
    request_id: str,
    payload: GroupJoinRequestDecision,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reject a pending join request. Reason is delivered to the visitor."""
    if payload.approve:
        raise HTTPException(
            status_code=400,
            detail="Use the /approve endpoint to approve a request.",
        )
    if not payload.notes:
        raise HTTPException(
            status_code=400,
            detail="A reason is required when rejecting.",
        )
    try:
        result = reject_join_request(
            db, request_id, actor_id=current_user.id, reason=payload.notes,
        )
    except GroupFormationError as e:
        _err(e)
    return result


@router.post("/join-requests/{request_id}/withdraw",
             response_model=GroupJoinRequestResponse)
def withdraw_request(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Visitor withdraws their own pending request."""
    try:
        return withdraw_join_request(
            db, request_id, user_id=current_user.id,
        )
    except GroupFormationError as e:
        _err(e)


# ============================================================================
# GROUP — READ / UPDATE  (dynamic, must come after literal prefixes)
# ============================================================================

@router.get("/{group_id}", response_model=GroupResponse)
def get_one_group(
    group_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_group(db, group_id)
    except GroupError as e:
        _err(e)


@router.patch("/{group_id}", response_model=GroupResponse)
def patch_group(
    group_id: str,
    payload: GroupUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_group(db, group_id, payload)
    except GroupError as e:
        _err(e)


# ============================================================================
# GROUP UNITS — CURATION
# ============================================================================

@router.post("/{group_id}/curate-units", response_model=list[GroupUnitResponse])
def post_curate_units(
    group_id: str,
    payload: GroupUnitsCurateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Founder (or acting leader) submits the group's curated unit list —
    normally right after reviewing the OCR extraction. Replaces any prior
    list. Allowed only while the group is in `forming` state.
    """
    try:
        return curate_group_units(
            db, group_id, payload, actor_id=current_user.id,
        )
    except GroupFormationError as e:
        _err(e)


@router.get("/{group_id}/units", response_model=list[GroupUnitResponse])
def get_group_units(
    group_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_group_units(db, group_id)


# ============================================================================
# INVITE / SLUG ROTATION
# ============================================================================

@router.post("/{group_id}/rotate-invite", response_model=InviteRotationResponse)
def post_rotate_invite(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Founder or leader issues a new 7-day invite token; the old token dies."""
    try:
        result = rotate_invite_token(db, group_id, actor_id=current_user.id)
    except GroupFormationError as e:
        _err(e)
    return {
        "group_id": result["group_id"],
        "invite_token": result["invite_token"],
        "invite_expires_at": result["invite_expires_at"],
        "invite_url": result["invite_url"],
        "message": "New invite token issued. The previous token is now invalid.",
    }


@router.post("/{group_id}/rotate-slug")
def post_rotate_slug(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Founder or leader issues a new permanent slug; the old slug 404s."""
    try:
        return rotate_slug(db, group_id, actor_id=current_user.id)
    except GroupFormationError as e:
        _err(e)


# ============================================================================
# JOIN REQUESTS — LEADER QUEUE
# ============================================================================

@router.get("/{group_id}/join-requests", response_model=list[GroupJoinRequestResponse])
def get_join_requests(
    group_id: str,
    status: str = Query("pending"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List join requests for a group. Leader/secretary only. Defaults to
    pending only.
    """
    # Light authorization: service layer enforces the deeper check on
    # approve/reject. For listing, we require the caller to be at least
    # a group official.
    from app.services.group_service import _is_official
    if not _is_official(db, group_id, current_user.id,
                        {"leader", "secretary"}):
        raise HTTPException(403, "Only leaders or secretaries may view requests.")
    try:
        return list_join_requests(db, group_id, status=status)
    except GroupFormationError as e:
        _err(e)


# ============================================================================
# ELIGIBILITY
# ============================================================================

@router.get("/{group_id}/eligibility", response_model=GroupEligibilityResponse)
def get_eligibility(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explains whether the group can trigger its next election, and why not."""
    try:
        return check_election_eligibility(db, group_id)
    except SubscriptionError as e:
        _err(e)


# ============================================================================
# SUBSCRIPTION
# ============================================================================

@router.get("/{group_id}/subscription", response_model=GroupSubscriptionResponse)
def get_subscription(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        sub = get_active_subscription(db, group_id)
    except SubscriptionError as e:
        _err(e)
    if not sub:
        raise HTTPException(404, "No active subscription.")
    return sub


@router.get("/{group_id}/subscription/calculate",
            response_model=SubscriptionCalculationResponse)
def calculate_subscription(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview the next renewal amount based on current member count."""
    try:
        group = get_group(db, group_id)
    except GroupError as e:
        _err(e)

    return SubscriptionCalculationResponse(
        member_count=group.member_count,
        amount=calculate_amount(group.member_count),
        currency="KES",
        breakdown=calculate_breakdown(group.member_count),
    )


@router.post("/{group_id}/subscription/renew", response_model=GroupSubscriptionResponse)
def renew_subscription(
    group_id: str,
    payload: SubscriptionRenewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Record a manual renewal. Stub until M-Pesa integration lands — in
    production this endpoint will only succeed when a verified payment
    webhook has landed.
    """
    try:
        group = get_group(db, group_id)
        if group.creator_id != current_user.id:
            from app.services.group_service import _is_official
            if not _is_official(db, group_id, current_user.id, {"leader"}):
                raise HTTPException(
                    403, "Only the founder or leader may renew the subscription."
                )

        # Expire any prior subscription that is still open
        from app.services.group_subscription_service import (
            get_active_subscription as _get_active,
        )
        prior = _get_active(db, group_id)
        if prior:
            prior.status = "cancelled"

        sub = activate_subscription(
            db,
            group_id=group_id,
            member_count=group.member_count,
            payment_reference=payload.payment_reference,
        )
    except (GroupError, SubscriptionError) as e:
        _err(e)
    return sub


# ============================================================================
# MEMBERSHIP  (legacy direct-join)
# ============================================================================

@router.post("/{group_id}/members/join",
             response_model=MembershipResponse, status_code=201)
def post_join_group(
    group_id: str,
    payload: LegacyJoinNotes,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Legacy direct-join endpoint. Now creates a PENDING membership only —
    leader approval is required. New integrations should use the
    invite/slug join-request endpoints.
    """
    try:
        return join_group(db, group_id, current_user.id, notes=payload.notes)
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/members", response_model=list[MembershipResponse])
def get_members(
    group_id: str,
    status_filter: str | None = Query(None, alias="status"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_members(db, group_id, status_filter=status_filter)


@router.patch("/{group_id}/members/{target_user_id}",
              response_model=MembershipResponse)
def patch_member(
    group_id: str,
    target_user_id: str,
    payload: MembershipUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_membership(
            db, group_id, target_user_id,
            payload.status, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)


@router.delete("/{group_id}/members/me", response_model=MembershipResponse)
def delete_my_membership(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return leave_group(db, group_id, current_user.id)
    except GroupError as e:
        _err(e)


# ============================================================================
# OFFICIALS
# ============================================================================

@router.post("/{group_id}/officials", response_model=OfficialResponse, status_code=201)
def post_official(
    group_id: str,
    payload: OfficialAppoint,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return appoint_official(
            db, group_id, payload, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/officials", response_model=list[OfficialResponse])
def get_officials(
    group_id: str,
    status_filter: str | None = Query("active", alias="status"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_officials(db, group_id, status_filter=status_filter)


@router.delete("/officials/{official_id}", response_model=OfficialResponse)
def delete_official(
    official_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return remove_official(
            db, official_id, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)


# ============================================================================
# MEETINGS
# ============================================================================

@router.post("/{group_id}/meetings", response_model=MeetingResponse, status_code=201)
def post_meeting(
    group_id: str,
    payload: MeetingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_meeting(
            db, group_id, payload, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/meetings", response_model=list[MeetingResponse])
def get_meetings(
    group_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_meetings(db, group_id)


# ============================================================================
# ACTIVITIES
# ============================================================================

@router.post("/{group_id}/activities", response_model=ActivityResponse, status_code=201)
def post_activity(
    group_id: str,
    payload: ActivityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_activity(
            db, group_id, payload, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/activities", response_model=list[ActivityResponse])
def get_activities(
    group_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_activities(db, group_id)


# ============================================================================
# ANNOUNCEMENTS
# ============================================================================

@router.post("/{group_id}/announcements",
             response_model=AnnouncementResponse, status_code=201)
def post_announcement(
    group_id: str,
    payload: AnnouncementCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_announcement(
            db, group_id, payload, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/announcements", response_model=list[AnnouncementResponse])
def get_announcements(
    group_id: str,
    include_archived: bool = Query(False),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_announcements(db, group_id, include_archived=include_archived)


# ============================================================================
# TIMETABLES
# ============================================================================

@router.post("/{group_id}/timetables", response_model=TimetableResponse, status_code=201)
def post_timetable(
    group_id: str,
    payload: TimetableCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_timetable(
            db, group_id, payload, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/timetables", response_model=list[TimetableResponse])
def get_timetables(
    group_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_timetables(db, group_id)


@router.post("/timetables/{timetable_id}/entries",
             response_model=list[TimetableEntryResponse], status_code=201)
def post_timetable_entries(
    timetable_id: str,
    payload: list[TimetableEntryCreate],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return add_timetable_entries(
            db, timetable_id, payload, acting_user_id=current_user.id,
        )
    except GroupError as e:
        _err(e)