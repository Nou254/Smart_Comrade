"""
Official announcements — Communication module.

Unified model for authoritative communications at any level:
group, unit, school, institution, county, platform.

Distinct from:
  - GroupAnnouncement (group-internal, unchanged)
  - CommunityMessage (chat, unchanged)
  - OfficialAnnouncementAudience tracks per-user delivery + read state

Tables:
  1. official_announcements
  2. official_announcement_audiences
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


VALID_LEVELS = (
    "group", "unit", "school", "institution", "county", "platform",
)
VALID_CLASSIFICATIONS = (
    "academic", "administrative", "election", "assessment",
    "event", "emergency", "opportunity", "project", "general",
)
VALID_PRIORITIES = ("normal", "important", "critical")
VALID_STATUSES = ("scheduled", "published", "archived")


class OfficialAnnouncement(Base, UUIDMixin, TimestampMixin):
    """
    Level determines the scope:
      group       → scope_ref_id = groups.id
      unit        → scope_ref_id = unit_offerings.id
      school      → scope_ref_id = schools.id
      institution → scope_ref_id = institutions.id
      county      → scope_ref_id = counties.id
      platform    → scope_ref_id = NULL
    """
    __tablename__ = "official_announcements"
    __table_args__ = (
        CheckConstraint(
            f"level IN ({','.join(repr(l) for l in VALID_LEVELS)})",
            name="ck_official_announcement_level",
        ),
        CheckConstraint(
            f"classification IN "
            f"({','.join(repr(c) for c in VALID_CLASSIFICATIONS)})",
            name="ck_official_announcement_classification",
        ),
        CheckConstraint(
            f"priority IN ({','.join(repr(p) for p in VALID_PRIORITIES)})",
            name="ck_official_announcement_priority",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(s) for s in VALID_STATUSES)})",
            name="ck_official_announcement_status",
        ),
        CheckConstraint(
            "(level = 'platform' AND scope_ref_id IS NULL) OR "
            "(level != 'platform' AND scope_ref_id IS NOT NULL)",
            name="ck_official_announcement_scope",
        ),
        Index("ix_official_announcement_level_scope",
              "level", "scope_ref_id"),
        Index("ix_official_announcement_published", "published_at"),
        Index("ix_official_announcement_status", "status"),
    )

    publisher_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False, index=True,
    )
    publisher_role: Mapped[str] = mapped_column(String(64), nullable=False)

    level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scope_ref_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )

    classification: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    # Corrections reference the original announcement
    correction_of_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("official_announcements.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="published", index=True,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    audience_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    audience: Mapped[list["OfficialAnnouncementAudience"]] = relationship(
        "OfficialAnnouncementAudience",
        back_populates="announcement",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<OfficialAnnouncement {self.id} "
            f"level={self.level} classification={self.classification}>"
        )


class OfficialAnnouncementAudience(Base, UUIDMixin, TimestampMixin):
    """
    Snapshot of users eligible to receive the announcement at publish
    time, plus per-user read state.
    """
    __tablename__ = "official_announcement_audiences"
    __table_args__ = (
        UniqueConstraint(
            "announcement_id", "user_id",
            name="uq_official_announcement_audience",
        ),
        Index("ix_official_audience_user", "user_id"),
        Index("ix_official_audience_read", "is_read"),
    )

    announcement_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("official_announcements.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # If the user later becomes ineligible, flag rather than delete
    is_still_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    announcement: Mapped[OfficialAnnouncement] = relationship(
        "OfficialAnnouncement", back_populates="audience",
    )

    def __repr__(self) -> str:
        return (
            f"<OfficialAnnouncementAudience ann={self.announcement_id} "
            f"user={self.user_id} read={self.is_read}>"
        )