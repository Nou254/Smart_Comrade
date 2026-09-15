"""
Student Groups endpoints — Module 003.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.group import (
    GroupCreate, GroupUpdate, GroupResponse,
    GroupJoinRequest, MembershipUpdate, MembershipResponse,
    OfficialAppoint, OfficialResponse,
    MeetingCreate, MeetingUpdate, MeetingResponse,
    ActivityCreate, ActivityResponse,
    AnnouncementCreate, AnnouncementResponse,
    TimetableCreate, TimetableEntryCreate, TimetableEntryResponse,
    TimetableApprovalAction, TimetableResponse,
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

router = APIRouter(prefix="/groups", tags=["Student Groups"])


def _err(e: GroupError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


# ---------- GROUP CRUD ----------

@router.post("", response_model=GroupResponse, status_code=201)
def post_group(
    payload: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_group(db, payload, creator_id=current_user.id)
    except GroupError as e:
        _err(e)


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
    return list_groups(db, institution_id=institution_id, course_id=course_id,
                       semester_id=semester_id, unit_id=unit_id,
                       status_filter=status_filter, visibility=visibility)


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


# ---------- MEMBERSHIP ----------

@router.post("/{group_id}/members/join", response_model=MembershipResponse, status_code=201)
def post_join_group(
    group_id: str,
    payload: GroupJoinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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


@router.patch("/{group_id}/members/{target_user_id}", response_model=MembershipResponse)
def patch_member(
    group_id: str,
    target_user_id: str,
    payload: MembershipUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return update_membership(db, group_id, target_user_id,
                                 payload.status, acting_user_id=current_user.id)
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


# ---------- OFFICIALS ----------

@router.post("/{group_id}/officials", response_model=OfficialResponse, status_code=201)
def post_official(
    group_id: str,
    payload: OfficialAppoint,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return appoint_official(db, group_id, payload, acting_user_id=current_user.id)
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
        return remove_official(db, official_id, acting_user_id=current_user.id)
    except GroupError as e:
        _err(e)


# ---------- MEETINGS ----------

@router.post("/{group_id}/meetings", response_model=MeetingResponse, status_code=201)
def post_meeting(
    group_id: str,
    payload: MeetingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_meeting(db, group_id, payload, acting_user_id=current_user.id)
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/meetings", response_model=list[MeetingResponse])
def get_meetings(
    group_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_meetings(db, group_id)


# ---------- ACTIVITIES ----------

@router.post("/{group_id}/activities", response_model=ActivityResponse, status_code=201)
def post_activity(
    group_id: str,
    payload: ActivityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_activity(db, group_id, payload, acting_user_id=current_user.id)
    except GroupError as e:
        _err(e)


@router.get("/{group_id}/activities", response_model=list[ActivityResponse])
def get_activities(
    group_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_activities(db, group_id)


# ---------- ANNOUNCEMENTS ----------

@router.post("/{group_id}/announcements", response_model=AnnouncementResponse, status_code=201)
def post_announcement(
    group_id: str,
    payload: AnnouncementCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_announcement(db, group_id, payload, acting_user_id=current_user.id)
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


# ---------- TIMETABLES ----------

@router.post("/{group_id}/timetables", response_model=TimetableResponse, status_code=201)
def post_timetable(
    group_id: str,
    payload: TimetableCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return create_timetable(db, group_id, payload, acting_user_id=current_user.id)
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
        return add_timetable_entries(db, timetable_id, payload, acting_user_id=current_user.id)
    except GroupError as e:
        _err(e)