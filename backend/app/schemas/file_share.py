"""
Pydantic schemas for shared files.

Scope is limited to direct | unit | community. Access is inherited
from the scope — no per-file ACL.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Create / update
# ============================================================================

class FileInitUploadRequest(BaseModel):
    """
    Called after the client has uploaded to storage. The service
    verifies scope access, resolves versioning, and creates the row.
    """
    scope_type: str = Field(
        ..., description="direct | unit | community",
    )
    scope_ref_id: str = Field(..., min_length=36, max_length=36)
    file_name: str = Field(..., min_length=1, max_length=255)
    file_url: str = Field(..., min_length=1, max_length=500)
    file_size_bytes: int = Field(..., ge=0)
    mime_type: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(None, max_length=2000)
    parent_file_id: str | None = Field(None, min_length=36, max_length=36)
    tags: list[str] | None = None


class FileUpdateRequest(BaseModel):
    description: str | None = Field(None, max_length=2000)
    tags: list[str] | None = None


# ============================================================================
# Response
# ============================================================================

class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    scope_type: str
    scope_ref_id: str
    file_name: str
    file_url: str
    file_size_bytes: int
    mime_type: str
    version: int
    parent_file_id: str | None
    description: str | None
    tags: list | None
    malware_scan_status: str
    malware_scan_notes: str | None
    malware_scanned_at: datetime | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class FileListResponse(BaseModel):
    files: list[FileResponse]
    next_cursor: str | None
    has_more: bool


class FileVersionListResponse(BaseModel):
    """Full version chain for a file, oldest → newest."""
    versions: list[FileResponse]