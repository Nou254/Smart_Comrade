"""
Upload service — file storage, page rendering, upload lifecycle.
"""
import logging
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile as FastAPIFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.group import Group
from app.models.upload import TimetableUpload, UploadFile
from app.models.user import User

logger = logging.getLogger(__name__)


class UploadError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "doc", "pptx", "ppt"}

# Optional integrations — degrade gracefully if not installed
try:
    import fitz  # pymupdf
    _HAS_PYMUPDF = True
except Exception:
    _HAS_PYMUPDF = False
    logger.warning("pymupdf not installed — PDF page rendering disabled")

try:
    import boto3
    _HAS_BOTO3 = True
except Exception:
    _HAS_BOTO3 = False


# ── Storage ────────────────────────────────────────────────────

def _upload_root() -> Path:
    root = Path(settings.UPLOAD_DIR or "./uploads").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _upload_dir(upload_id: str) -> Path:
    d = _upload_root() / upload_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extension_of(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return ext


def _validate_extension(ext: str) -> None:
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(
            f"File type '.{ext}' is not allowed. "
            f"Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )


def _save_local(upload_id: str, file_id: str, ext: str, content: bytes) -> str:
    dest = _upload_dir(upload_id) / f"{file_id}.{ext}"
    dest.write_bytes(content)
    return str(dest)


def _save_s3(upload_id: str, file_id: str, ext: str, content: bytes) -> str | None:
    if settings.STORAGE_BACKEND not in ("s3", "both"):
        return None
    if not _HAS_BOTO3 or not settings.S3_BUCKET_NAME:
        return None
    try:
        client = boto3.client(
            "s3",
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        key = f"uploads/{upload_id}/{file_id}.{ext}"
        client.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=content,
        )
        return f"s3://{settings.S3_BUCKET_NAME}/{key}"
    except Exception as e:
        logger.exception(f"S3 upload failed: {e}")
        return None


# ── Page count detection ───────────────────────────────────────

def _detect_page_count(local_path: str, ext: str) -> int:
    if ext == "pdf" and _HAS_PYMUPDF:
        try:
            with fitz.open(local_path) as doc:
                return doc.page_count
        except Exception as e:
            logger.warning(f"Could not read PDF page count: {e}")
            return 1
    if ext in ("png", "jpg", "jpeg"):
        return 1
    if ext in ("docx", "doc", "pptx", "ppt"):
        # without additional libs, we don't know — treat as 1
        return 1
    return 1


# ── Public API ─────────────────────────────────────────────────

def create_upload(db: Session, *, group_id: str, user_id: str) -> TimetableUpload:
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise UploadError("Group not found.", 404)

    upload = TimetableUpload(
        group_id=group_id,
        uploaded_by=user_id,
        status="created",
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def get_upload(db: Session, upload_id: str) -> TimetableUpload:
    upload = db.query(TimetableUpload).filter(TimetableUpload.id == upload_id).first()
    if not upload:
        raise UploadError("Upload not found.", 404)
    return upload


def list_upload_files(db: Session, upload_id: str) -> list[UploadFile]:
    return (
        db.query(UploadFile)
        .filter(UploadFile.upload_id == upload_id)
        .order_by(UploadFile.created_at)
        .all()
    )


def add_file(
    db: Session,
    *,
    upload_id: str,
    filename: str,
    content: bytes,
    mime_type: str | None = None,
) -> UploadFile:
    upload = get_upload(db, upload_id)
    if upload.status not in ("created", "uploading"):
        raise UploadError(
            f"Cannot add files to upload in status '{upload.status}'.", 409
        )

    ext = _extension_of(filename)
    _validate_extension(ext)

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise UploadError(
            f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.", 413
        )

    file_id = str(uuid.uuid4())
    local_path = _save_local(upload_id, file_id, ext, content)
    s3_url = _save_s3(upload_id, file_id, ext, content)
    page_count = _detect_page_count(local_path, ext)

    if page_count > settings.MAX_PAGES_PER_FILE:
        # clean up
        try:
            os.remove(local_path)
        except OSError:
            pass
        raise UploadError(
            f"File exceeds {settings.MAX_PAGES_PER_FILE} page limit.", 413
        )

    record = UploadFile(
        id=file_id,
        upload_id=upload_id,
        original_name=filename,
        extension=ext,
        mime_type=mime_type or mimetypes.guess_type(filename)[0],
        size_bytes=len(content),
        page_count=page_count,
        file_url=local_path,
        s3_url=s3_url,
    )
    db.add(record)

    if upload.status == "created":
        upload.status = "uploading"

    db.commit()
    db.refresh(record)
    return record


def get_file(db: Session, file_id: str) -> UploadFile:
    f = db.query(UploadFile).filter(UploadFile.id == file_id).first()
    if not f:
        raise UploadError("File not found.", 404)
    return f


def render_page_preview(file: UploadFile, page_number: int) -> bytes:
    """Return PNG bytes for the requested page (1-indexed)."""
    if page_number < 1 or page_number > file.page_count:
        raise UploadError(f"Page {page_number} out of range.", 400)

    ext = file.extension
    if ext == "pdf":
        if not _HAS_PYMUPDF:
            raise UploadError("PDF preview requires pymupdf.", 500)
        with fitz.open(file.file_url) as doc:
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom
            return pix.tobytes("png")

    if ext in ("png", "jpg", "jpeg"):
        # already an image, return as-is
        with open(file.file_url, "rb") as fh:
            return fh.read()

    raise UploadError(f"Preview not supported for .{ext} files.", 400)


def delete_upload(db: Session, upload_id: str, user_id: str) -> None:
    upload = get_upload(db, upload_id)
    if upload.uploaded_by and upload.uploaded_by != user_id:
        raise UploadError("Only the uploader can cancel this upload.", 403)

    # Delete local files
    dir_path = _upload_dir(upload_id)
    if dir_path.exists():
        shutil.rmtree(dir_path, ignore_errors=True)

    db.delete(upload)
    db.commit()


def update_upload_status(
    db: Session,
    upload_id: str,
    *,
    status: str,
    error_message: str | None = None,
    scan_started: bool = False,
    scan_completed: bool = False,
) -> TimetableUpload:
    upload = get_upload(db, upload_id)
    upload.status = status
    if error_message is not None:
        upload.error_message = error_message
    now_iso = datetime.now(timezone.utc).isoformat()
    if scan_started:
        upload.scan_started_at = now_iso
    if scan_completed:
        upload.scan_completed_at = now_iso
    db.commit()
    db.refresh(upload)
    return upload