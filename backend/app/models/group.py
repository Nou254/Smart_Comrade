"""
Student Group models — Module 003.

Full shape including Phase 3+4+5, the invite-security layer, and
Phase 6 election-adjacent fields.

Group now carries:
  - a permanent, non-guessable `slug`
  - a 7-day-expiring `invite_token` (hashed at rest)
  - election / no-payer fallback flags used by Phase 6
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


# ============================================================================
# GROUP
# ============================================================================

class Group(Base, UUIDMixin, TimestampMixin):
    """
    A student study/academic group.

    Lifecycle:
      forming → pending_election → active → archived

    Two link types:
      slug         — permanent, non-guessable. Shows a preview.
      invite_token — 7-day expiring. Shows a preview + pre-fills the
                     join-request form. Neither auto-joins.
    """
    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('forming','pending_election','active','suspended','archived')",
            name="ck_group_status",
        ),
        CheckConstraint(
            "group_type IN ('academic','activity_club')",
            name="ck_group_type",
        ),
        CheckConstraint(
            "visibility IN ('private','public','invitation_only')",
            name="ck_group_visibility",
        ),
        CheckConstraint(
            "subscription_status IN ('trial','active','expiring','expired','suspended','cancelled')",
            name="ck_group_subscription_status",
        ),
        UniqueConstraint(
            "institution_id", "course_id", "semester_id", "name",
            name="uq_group_context_name",
        ),
        UniqueConstraint("slug", name="uq_group_slug"),
        UniqueConstraint("invite_token", name="uq_group_invite_token"),
    )

    # --- Identity ---
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="academic", index=True,
    )

    # --- Permanent, non-guessable identifier for the profile link ---
    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True,
    )

    # --- Academic binding ---
    institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    school_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    combination_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("combinations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    academic_year_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    semester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("semesters.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    year_level: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Legacy single-unit field ---
    unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # --- Founding leader ---
    creator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    is_provisional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # --- Status ---
    status: Mapped[str] = mapped_column(
        String(24), default="forming", nullable=False, index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(20), default="invitation_only", nullable=False,
    )
    subscription_status: Mapped[str] = mapped_column(
        String(20), default="trial", nullable=False,
    )

    # --- Invite token (7-day expiry) ---
    # `invite_token` stores the SHA-256 hash of the token, never the token
    # itself. The plain token is returned to the founder once, at creation
    # or rotation time.
    invite_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
    )
    invite_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Election trigger ---
    election_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Membership counting ---
    max_members: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    member_count: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, index=True,
    )

    # --- Legacy subscription timestamps (denormalized cache) ---
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Module 003 Phase 6 — election / no-payer state ---
    election_pending_runoff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    under_regional_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # --- Relationships ---
    memberships: Mapped[list["GroupMembership"]] = relationship(
        "GroupMembership", back_populates="group", cascade="all, delete-orphan",
    )
    officials: Mapped[list["GroupOfficial"]] = relationship(
        "GroupOfficial", back_populates="group", cascade="all, delete-orphan",
    )
    meetings: Mapped[list["GroupMeeting"]] = relationship(
        "GroupMeeting", back_populates="group", cascade="all, delete-orphan",
    )
    activities: Mapped[list["GroupActivity"]] = relationship(
        "GroupActivity", back_populates="group", cascade="all, delete-orphan",
    )
    announcements: Mapped[list["GroupAnnouncement"]] = relationship(
        "GroupAnnouncement", back_populates="group", cascade="all, delete-orphan",
    )
    timetables: Mapped[list["GroupTimetable"]] = relationship(
        "GroupTimetable", back_populates="group", cascade="all, delete-orphan",
    )
    join_requests: Mapped[list["GroupJoinRequest"]] = relationship(
        "GroupJoinRequest", back_populates="group",
        cascade="all, delete-orphan",
        foreign_keys="GroupJoinRequest.group_id",
    )

    def __repr__(self) -> str:
        return f"<Group {self.name} ({self.status})>"


# ============================================================================
# MEMBERSHIP
# ============================================================================

class GroupMembership(Base, UUIDMixin, TimestampMixin):
    """
    Membership record: user ↔ group.

    Statuses:
      pending              — joined but awaiting leader approval
      active               — full member
      suspended            — temporarily restricted
      left                 — voluntarily departed
      removed              — removed by an official
      provisional_pending  — clicked link but has not yet confirmed
    """
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_membership"),
        CheckConstraint(
            "status IN ('provisional_pending','pending','active','suspended','left','removed')",
            name="ck_membership_status",
        ),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False, index=True,
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- Invite-based joins ---
    joined_via_invite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    course_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    units_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    invited_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    group: Mapped[Group] = relationship("Group", back_populates="memberships")

    def __repr__(self) -> str:
        return f"<Membership group={self.group_id} user={self.user_id} status={self.status}>"


# ============================================================================
# OFFICIALS
# ============================================================================

class GroupOfficial(Base, UUIDMixin, TimestampMixin):
    """Leadership position within a group."""
    __tablename__ = "group_officials"
    __table_args__ = (
        CheckConstraint(
            "position IN ('leader','secretary','treasurer','unit_representative')",
            name="ck_official_position",
        ),
        CheckConstraint(
            "status IN ('active','expired','removed')",
            name="ck_official_status",
        ),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    position: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="SET NULL"),
        nullable=True,
    )

    term_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    term_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    appointed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    election_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    group: Mapped[Group] = relationship("Group", back_populates="officials")

    def __repr__(self) -> str:
        return f"<Official {self.position} group={self.group_id} user={self.user_id}>"


# ============================================================================
# MEETINGS
# ============================================================================

class GroupMeeting(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_meetings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','in_progress','completed','cancelled')",
            name="ck_meeting_status",
        ),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    agenda: Mapped[str | None] = mapped_column(Text, nullable=True)

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    virtual_link: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )

    group: Mapped[Group] = relationship("Group", back_populates="meetings")
    attendees: Mapped[list["GroupMeetingAttendee"]] = relationship(
        "GroupMeetingAttendee", back_populates="meeting", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Meeting {self.title}>"


class GroupMeetingAttendee(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_meeting_attendees"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_attendee"),
        CheckConstraint(
            "status IN ('invited','accepted','declined','attended','absent')",
            name="ck_attendee_status",
        ),
    )

    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_meetings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="invited", nullable=False)

    meeting: Mapped[GroupMeeting] = relationship(
        "GroupMeeting", back_populates="attendees",
    )

    def __repr__(self) -> str:
        return f"<Attendee meeting={self.meeting_id} user={self.user_id}>"


# ============================================================================
# ACTIVITIES
# ============================================================================

class GroupActivity(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_activities"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('study_session','revision','project','social','event','other')",
            name="ck_activity_type",
        ),
        CheckConstraint(
            "status IN ('scheduled','in_progress','completed','cancelled')",
            name="ck_activity_status",
        ),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    virtual_link: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )

    group: Mapped[Group] = relationship("Group", back_populates="activities")

    def __repr__(self) -> str:
        return f"<Activity {self.title}>"


# ============================================================================
# ANNOUNCEMENTS
# ============================================================================

class GroupAnnouncement(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_announcements"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('normal','important','critical')",
            name="ck_announcement_priority",
        ),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    published_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    group: Mapped[Group] = relationship("Group", back_populates="announcements")

    def __repr__(self) -> str:
        return f"<Announcement {self.title}>"


# ============================================================================
# TIMETABLES
# ============================================================================

class GroupTimetable(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_timetables"
    __table_args__ = (
        CheckConstraint(
            "type IN ('official','revision')",
            name="ck_timetable_type",
        ),
        CheckConstraint(
            "approval_status IN ('pending','approved','rejected')",
            name="ck_timetable_approval_status",
        ),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )

    approval_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    group: Mapped[Group] = relationship("Group", back_populates="timetables")
    entries: Mapped[list["GroupTimetableEntry"]] = relationship(
        "GroupTimetableEntry", back_populates="timetable", cascade="all, delete-orphan",
    )
    approvals: Mapped[list["GroupTimetableApproval"]] = relationship(
        "GroupTimetableApproval", back_populates="timetable", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Timetable {self.name} ({self.type})>"


class GroupTimetableEntry(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_timetable_entries"

    timetable_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_timetables.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("units.id", ondelete="SET NULL"), nullable=True,
    )

    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[str] = mapped_column(String(8), nullable=False)
    end_time: Mapped[str] = mapped_column(String(8), nullable=False)

    activity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    timetable: Mapped[GroupTimetable] = relationship(
        "GroupTimetable", back_populates="entries",
    )

    def __repr__(self) -> str:
        return f"<TimetableEntry {self.day_of_week} {self.start_time}-{self.end_time}>"


class GroupTimetableApproval(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "group_timetable_approvals"
    __table_args__ = (
        UniqueConstraint("timetable_id", "user_id", name="uq_timetable_approval"),
    )

    timetable_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_timetables.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    timetable: Mapped[GroupTimetable] = relationship(
        "GroupTimetable", back_populates="approvals",
    )

    def __repr__(self) -> str:
        return f"<Approval timetable={self.timetable_id} user={self.user_id} approved={self.approved}>"