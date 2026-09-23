"""
Shared file storage — Communication module.

Files can attach to three scopes only (per the corrected rule):
  scope_type='direct'    → scope_ref_id = direct_conversations.id
  scope_type='unit'      → scope_ref_id = unit_offerings.id
  scope_type='community' → scope_ref_id = communities.id

Access is inherited from the scope — no per-file ACL table.
Versioning is modelled by chaining rows via parent_file_id.

Ownership belongs to the uploader. The platform never claims IP.

Tables:
  1. shared_files
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
    Index, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


VALID_SCOPE_TYPES = ("direct", "unit", "community")
VALID_SCAN_STATUSES = (
    "pending", "scanning", "clean", "infected", "failed", "skipped",
)


class SharedFile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "shared_files"
    __table_args__ = (
        CheckConstraint(
            f"scope_type IN "
            f"({','.join(repr(s) for s in VALID_SCOPE_TYPES)})",
            name="ck_shared_file_scope_type",
        ),
        CheckConstraint(
            f"malware_scan_status IN "
            f"({','.join(repr(s) for s in VALID_SCAN_STATUSES)})",
            name="ck_shared_file_scan_status",
        ),
        Index("ix_shared_files_scope", "scope_type", "scope_ref_id"),
        Index("ix_shared_files_owner", "owner_id"),
        Index("ix_shared_files_parent", "parent_file_id"),
        Index("ix_shared_files_scan", "malware_scan_status"),
    )

    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False, index=True,
    )

    scope_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True,
    )
    scope_ref_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
    )

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shared_files.id", ondelete="SET NULL"),
        nullable=True,
    )

    malware_scan_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True,
    )
    malware_scan_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    malware_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<SharedFile {self.id} scope={self.scope_type}:{self.scope_ref_id} "
            f"v{self.version}>"
        )