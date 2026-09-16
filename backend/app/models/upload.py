"""
Upload pipeline models — Phase 1.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy import func as _func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class TimetableUpload(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "timetable_uploads"
    __table_args__ = (
        Index("ix_timetable_uploads_group_id", "group_id"),
        Index("ix_timetable_uploads_uploaded_by", "uploaded_by"),
        Index("ix_timetable_uploads_status", "status"),
    )

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # status: created | uploading | scanning | ready | confirmed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    scan_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    scan_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    files: Mapped[list["UploadFile"]] = relationship(
        "UploadFile", back_populates="upload", cascade="all, delete-orphan",
    )
    extracted_units: Mapped[list["ExtractedUnit"]] = relationship(
        "ExtractedUnit", back_populates="upload", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<TimetableUpload {self.id} group={self.group_id} status={self.status}>"


class UploadFile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "upload_files"
    __table_args__ = (
        Index("ix_upload_files_upload_id", "upload_id"),
    )

    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("timetable_uploads.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    upload: Mapped["TimetableUpload"] = relationship(
        "TimetableUpload", back_populates="files",
    )
    scanned_pages: Mapped[list["UploadScannedPage"]] = relationship(
        "UploadScannedPage", back_populates="file", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<UploadFile {self.id} name={self.original_name} pages={self.page_count}>"


class UploadScannedPage(Base, UUIDMixin):
    __tablename__ = "upload_scanned_pages"
    __table_args__ = (
        Index("ix_usp_upload_id", "upload_id"),
        Index("ix_usp_file_id", "file_id"),
        UniqueConstraint("file_id", "page_number", name="uq_usp_file_page"),
    )

    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("timetable_uploads.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence_avg: Mapped[float | None] = mapped_column(Float, nullable=True)

    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_func.now(),
    )

    file: Mapped["UploadFile"] = relationship(
        "UploadFile", back_populates="scanned_pages",
    )

    def __repr__(self) -> str:
        return f"<UploadScannedPage file={self.file_id} page={self.page_number}>"


class ExtractedUnit(Base, UUIDMixin):
    __tablename__ = "extracted_units"
    __table_args__ = (
        Index("ix_extracted_units_upload_id", "upload_id"),
        Index("ix_extracted_units_code", "code"),
        Index("ix_extracted_units_status", "status"),
    )

    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("timetable_uploads.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("upload_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    day_of_week: Mapped[str | None] = mapped_column(String(16), nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(8), nullable=True)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # status: pending | confirmed | discarded | edited
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    upload: Mapped["TimetableUpload"] = relationship(
        "TimetableUpload", back_populates="extracted_units",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_func.now(),
    )

    def __repr__(self) -> str:
        return f"<ExtractedUnit code={self.code} title={self.title}>"