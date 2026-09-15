"""
Pydantic schemas for Student Groups.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ---------- GROUP ----------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = None
    institution_id: str
    school_id: str
    course_id: str
    academic_year_id: str
    semester_id: str
    unit_id: str | None = None
    visibility: str = Field("invitation_only",
                            description="private | public | invitation_only")
    max_members: int = Field(60, ge=2, le=200)


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=150)
    description: str | None = None
    visibility: str | None = None
    max_members: int | None = Field(None, ge=2, le=200)
    status: str | None = None


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    institution_id: str
    school_id: str
    course_id: str
    academic_year_id: str
    semester_id: str
    unit_id: str | None
    creator_id: str
    status: str
    visibility: str
    subscription_status: str
    max_members: int
    member_count: int
    trial_ends_at: datetime | None
    subscription_expires_at: datetime | None
    created_at: datetime


# ---------- MEMBERSHIP ----------

class GroupJoinRequest(BaseModel):
    notes: str | None = None


class MembershipUpdate(BaseModel):
    status: str = Field(..., description="active | suspended | removed")


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    user_id: str
    status: str
    joined_at: datetime | None
    left_at: datetime | None
    invited_by: str | None
    approved_by: str | None
    notes: str | None
    created_at: datetime


# ---------- OFFICIALS ----------

class OfficialAppoint(BaseModel):
    user_id: str
    position: str = Field(..., description="leader | secretary | treasurer | unit_representative")
    unit_id: str | None = None
    term_start: datetime | None = None
    term_end: datetime | None = None
    notes: str | None = None


class OfficialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    user_id: str
    position: str
    unit_id: str | None
    term_start: datetime | None
    term_end: datetime | None
    status: str
    appointed_by: str | None
    notes: str | None
    created_at: datetime


# ---------- MEETINGS ----------

class MeetingCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    agenda: str | None = None
    scheduled_at: datetime
    duration_minutes: int | None = Field(None, ge=5, le=480)
    location: str | None = None
    virtual_link: str | None = None


class MeetingUpdate(BaseModel):
    title: str | None = None
    agenda: str | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = None
    location: str | None = None
    virtual_link: str | None = None
    status: str | None = None


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    title: str
    agenda: str | None
    scheduled_at: datetime
    duration_minutes: int | None
    location: str | None
    virtual_link: str | None
    status: str
    created_by: str
    created_at: datetime


# ---------- ACTIVITIES ----------

class ActivityCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: str | None = None
    activity_type: str = Field(..., description="study_session|revision|project|social|event|other")
    start_time: datetime
    end_time: datetime | None = None
    location: str | None = None
    virtual_link: str | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    title: str
    description: str | None
    activity_type: str
    start_time: datetime
    end_time: datetime | None
    location: str | None
    virtual_link: str | None
    status: str
    created_by: str
    created_at: datetime


# ---------- ANNOUNCEMENTS ----------

class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=1)
    priority: str = Field("normal", description="normal | important | critical")
    is_pinned: bool = False


class AnnouncementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    title: str
    content: str
    priority: str
    is_pinned: bool
    is_archived: bool
    published_by: str
    published_at: datetime
    created_at: datetime


# ---------- TIMETABLES ----------

class TimetableCreate(BaseModel):
    type: str = Field(..., description="official | revision")
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = None


class TimetableEntryCreate(BaseModel):
    unit_id: str | None = None
    day_of_week: int | None = Field(None, ge=0, le=6)
    start_time: str = Field(..., description="HH:MM (24-hour)")
    end_time: str = Field(..., description="HH:MM (24-hour)")
    activity_type: str | None = None
    location: str | None = None
    notes: str | None = None


class TimetableEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    timetable_id: str
    unit_id: str | None
    day_of_week: int | None
    start_time: str
    end_time: str
    activity_type: str | None
    location: str | None
    notes: str | None


class TimetableApprovalAction(BaseModel):
    approved: bool
    comments: str | None = None


class TimetableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    type: str
    name: str
    description: str | None
    created_by: str
    approval_status: str
    approved_at: datetime | None
    created_at: datetime