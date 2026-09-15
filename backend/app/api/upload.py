"""
Upload pipeline endpoints — Phase 1.
"""
import logging

from fastapi import (
    APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile as FastAPIFile,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.group import Group, GroupMembership
from app.models.upload import ExtractedUnit, UploadScannedPage, TimetableUpload
from app.models.user import User
from app.schemas.upload import (
    ExtractedUnitResponse,
    PageInfo, PageListResponse, PageSelection,
    ScanRequest, ScanResponse,
    UploadFileResponse, UploadResponse,
)
from app.services import upload_service
from app.services.upload_service import UploadError
from app.services.ocr_service import scan_page
from app.services.extraction_service import extract_units_from_text, dedupe_units
from app.services.admin_audit_service import log_admin_action

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Upload — Timetable Pipeline"])


def _err(e: UploadError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


def _require_group_member_or_leader(db: Session, user_id: str, group_id: str) -> None:
    """Only members of a group can upload / view its data."""
    m = (
        db.query(GroupMembership)
        .filter(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user_id,
            GroupMembership.status == "active",
        )
        .first()
    )
    if not m:
        raise HTTPException(403, "You are not an active member of this group.")


# ── 1. Create upload ───────────────────────────────────────────

@router.post(
    "/groups/{group_id}/uploads",
    response_model=UploadResponse,
    status_code=201,
)
def create_upload(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_group_member_or_leader(db, current_user.id, group_id)
    try:
        upload = upload_service.create_upload(db, group_id=group_id, user_id=current_user.id)
    except UploadError as e:
        _err(e)

    log_admin_action(
        db, actor_id=current_user.id, action="upload.create",
        target_type="timetable_upload", target_id=upload.id,
        new_value=f"group={group_id}",
    )
    return upload


# ── 2. Upload a file ───────────────────────────────────────────

@router.post(
    "/uploads/{upload_id}/files",
    response_model=UploadFileResponse,
    status_code=201,
)
async def upload_file(
    upload_id: str,
    file: FastAPIFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        record = upload_service.add_file(
            db,
            upload_id=upload_id,
            filename=file.filename or "unnamed",
            content=content,
            mime_type=file.content_type,
        )
    except UploadError as e:
        _err(e)

    log_admin_action(
        db, actor_id=current_user.id, action="upload.file.added",
        target_type="upload_file", target_id=record.id,
        new_value=f"name={record.original_name} pages={record.page_count}",
    )
    return record


# ── 3. Get upload with files ───────────────────────────────────

@router.get("/uploads/{upload_id}", response_model=UploadResponse)
def get_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = upload_service.get_upload(db, upload_id)
    except UploadError as e:
        _err(e)
    _require_group_member_or_leader(db, current_user.id, upload.group_id)
    return upload


# ── 4. List files ──────────────────────────────────────────────

@router.get("/uploads/{upload_id}/files", response_model=list[UploadFileResponse])
def list_files(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = upload_service.get_upload(db, upload_id)
    except UploadError as e:
        _err(e)
    _require_group_member_or_leader(db, current_user.id, upload.group_id)
    return upload_service.list_upload_files(db, upload_id)


# ── 5. List pages of a file ────────────────────────────────────

@router.get(
    "/uploads/{upload_id}/files/{file_id}/pages",
    response_model=PageListResponse,
)
def list_pages(
    upload_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = upload_service.get_upload(db, upload_id)
        file = upload_service.get_file(db, file_id)
    except UploadError as e:
        _err(e)
    _require_group_member_or_leader(db, current_user.id, upload.group_id)

    if file.upload_id != upload_id:
        raise HTTPException(400, "File does not belong to this upload.")

    pages = [
        PageInfo(
            page_number=i,
            thumbnail_url=f"/uploads/{upload_id}/files/{file_id}/pages/{i}?mode=thumb",
            preview_url=f"/uploads/{upload_id}/files/{file_id}/pages/{i}",
        )
        for i in range(1, file.page_count + 1)
    ]
    return PageListResponse(
        file_id=file.id,
        original_name=file.original_name,
        total_pages=file.page_count,
        pages=pages,
    )


# ── 6. Serve page as image ─────────────────────────────────────

@router.get("/uploads/{upload_id}/files/{file_id}/pages/{page_number}")
def get_page_image(
    upload_id: str,
    file_id: str,
    page_number: int,
    mode: str = "preview",  # "preview" | "thumb"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = upload_service.get_upload(db, upload_id)
        file = upload_service.get_file(db, file_id)
    except UploadError as e:
        _err(e)
    _require_group_member_or_leader(db, current_user.id, upload.group_id)

    if file.upload_id != upload_id:
        raise HTTPException(400, "File does not belong to this upload.")

    try:
        img_bytes = upload_service.render_page_preview(file, page_number)
    except UploadError as e:
        _err(e)

    return Response(content=img_bytes, media_type="image/png")


# ── 7. Trigger scan ────────────────────────────────────────────

@router.post("/uploads/{upload_id}/scan", response_model=ScanResponse)
def scan_selected_pages(
    upload_id: str,
    payload: ScanRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = upload_service.get_upload(db, upload_id)
    except UploadError as e:
        _err(e)
    _require_group_member_or_leader(db, current_user.id, upload.group_id)

    if upload.status not in ("created", "uploading", "ready", "failed"):
        raise HTTPException(409, f"Cannot scan upload in status '{upload.status}'.")

    # Validate selections
    total_pages = 0
    for sel in payload.selections:
        try:
            f = upload_service.get_file(db, sel.file_id)
        except UploadError:
            raise HTTPException(404, f"File {sel.file_id} not found.")
        if f.upload_id != upload_id:
            raise HTTPException(400, f"File {sel.file_id} not in this upload.")
        for p in sel.pages:
            if p < 1 or p > f.page_count:
                raise HTTPException(400, f"Page {p} out of range for {f.original_name}.")
            total_pages += 1

    if total_pages == 0:
        raise HTTPException(400, "No pages selected.")

    if total_pages > 50:
        raise HTTPException(400, "Cannot scan more than 50 pages at once.")

    # Mark as scanning
    upload_service.update_upload_status(
        db, upload_id, status="scanning", scan_started=True,
    )

    # Fire background task
    selections_payload = [
        {"file_id": s.file_id, "pages": list(s.pages)}
        for s in payload.selections
    ]
    background_tasks.add_task(
        _run_scan_job,
        upload_id=upload_id,
        selections=selections_payload,
    )

    log_admin_action(
        db, actor_id=current_user.id, action="upload.scan.queued",
        target_type="timetable_upload", target_id=upload_id,
        new_value=f"pages={total_pages}",
    )

    return ScanResponse(upload_id=upload_id, status="scanning", pages_queued=total_pages)


# ── Background job ─────────────────────────────────────────────

def _run_scan_job(upload_id: str, selections: list[dict]) -> None:
    """
    Runs in a background thread. Uses its own DB session.
    """
    from app.db.session import SessionLocal
    db: Session = SessionLocal()
    try:
        # Clear any prior extractions for these pages (re-scan case)
        for sel in selections:
            db.query(UploadScannedPage).filter(
                UploadScannedPage.upload_id == upload_id,
                UploadScannedPage.file_id == sel["file_id"],
                UploadScannedPage.page_number.in_(sel["pages"]),
            ).delete(synchronize_session=False)
            db.query(ExtractedUnit).filter(
                ExtractedUnit.upload_id == upload_id,
                ExtractedUnit.source_file_id == sel["file_id"],
                ExtractedUnit.source_page_number.in_(sel["pages"]),
            ).delete(synchronize_session=False)
        db.commit()

        for sel in selections:
            file_record = upload_service.get_file(db, sel["file_id"])
            for page_number in sel["pages"]:
                try:
                    result = scan_page(
                        file_path=file_record.file_url,
                        extension=file_record.extension,
                        page_number=page_number,
                    )
                except Exception as e:
                    logger.exception(f"OCR failed for page {page_number}: {e}")
                    continue

                # Persist raw page text
                page_row = UploadScannedPage(
                    upload_id=upload_id,
                    file_id=file_record.id,
                    page_number=page_number,
                    raw_text=result.raw_text,
                    ocr_confidence_avg=result.confidence,
                )
                db.add(page_row)

                if not result.raw_text:
                    continue

                # Structured extraction
                parsed = extract_units_from_text(result.raw_text, page_number)
                parsed = dedupe_units(parsed)

                for u in parsed:
                    db.add(ExtractedUnit(
                        upload_id=upload_id,
                        source_file_id=file_record.id,
                        source_page_number=page_number,
                        code=u.code,
                        title=u.title,
                        day_of_week=u.day_of_week,
                        start_time=u.start_time,
                        end_time=u.end_time,
                        raw_text=u.raw_text,
                        confidence=u.confidence,
                        status="pending",
                    ))

            db.commit()

        upload_service.update_upload_status(
            db, upload_id, status="ready", scan_completed=True,
        )
    except Exception as e:
        logger.exception(f"Scan job failed for upload {upload_id}: {e}")
        try:
            upload_service.update_upload_status(
                db, upload_id, status="failed", error_message=str(e),
                scan_completed=True,
            )
        except Exception:
            pass
    finally:
        db.close()


# ── 8. Get extracted units ─────────────────────────────────────

@router.get(
    "/uploads/{upload_id}/extracted",
    response_model=list[ExtractedUnitResponse],
)
def get_extracted_units(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload = upload_service.get_upload(db, upload_id)
    except UploadError as e:
        _err(e)
    _require_group_member_or_leader(db, current_user.id, upload.group_id)

    rows = (
        db.query(ExtractedUnit)
        .filter(ExtractedUnit.upload_id == upload_id)
        .order_by(ExtractedUnit.source_page_number, ExtractedUnit.code)
        .all()
    )
    return rows


# ── 9. Cancel upload ───────────────────────────────────────────

@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        upload_service.delete_upload(db, upload_id, user_id=current_user.id)
    except UploadError as e:
        _err(e)

    log_admin_action(
        db, actor_id=current_user.id, action="upload.delete",
        target_type="timetable_upload", target_id=upload_id,
    )
    return Response(status_code=204)