"""
Schemas for the upload pipeline.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


# ── Upload ─────────────────────────────────────────────────────

class UploadCreateRequest(BaseModel):
    notes: str | None = None


class UploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    group_id: str
    uploaded_by: str | None
    status: str
    error_message: str | None = None
    scan_started_at: datetime | None = None
    scan_completed_at: datetime | None = None
    created_at: datetime


# ── Files ──────────────────────────────────────────────────────

class UploadFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    original_name: str
    extension: str
    mime_type: str | None
    size_bytes: int
    page_count: int
    file_url: str
    s3_url: str | None
    created_at: datetime


# ── Pages ──────────────────────────────────────────────────────

class PageInfo(BaseModel):
    page_number: int
    thumbnail_url: str
    preview_url: str


class PageListResponse(BaseModel):
    file_id: str
    original_name: str
    total_pages: int
    pages: list[PageInfo]


# ── Scan ───────────────────────────────────────────────────────

class PageSelection(BaseModel):
    file_id: str
    pages: list[int] = Field(..., min_length=1)


class ScanRequest(BaseModel):
    selections: list[PageSelection] = Field(..., min_length=1)


class ScanResponse(BaseModel):
    upload_id: str
    status: str
    pages_queued: int


# ── Extracted units ────────────────────────────────────────────

class ExtractedUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str | None
    title: str | None
    day_of_week: str | None
    start_time: str | None
    end_time: str | None
    confidence: float | None
    status: str
    source_file_id: str | None
    source_page_number: int | None