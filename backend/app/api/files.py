"""
Shared file endpoints — Communication module.

Access is inherited from the scope (direct | unit | community).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.file_share import (
    FileInitUploadRequest,
    FileUpdateRequest,
    FileResponse,
    FileListResponse,
    FileVersionListResponse,
)
from app.services import file_share_service as svc


router = APIRouter(tags=["Files"])


def _err(e):
    raise HTTPException(
        status_code=getattr(e, "status_code", 400),
        detail=getattr(e, "message", str(e)),
    )


@router.post(
    "/files",
    response_model=FileResponse,
    status_code=201,
)
def create_shared_file(
    payload: FileInitUploadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_shared_file(
            db,
            owner_id=current_user.id,
            scope_type=payload.scope_type,
            scope_ref_id=payload.scope_ref_id,
            file_name=payload.file_name,
            file_url=payload.file_url,
            file_size_bytes=payload.file_size_bytes,
            mime_type=payload.mime_type,
            description=payload.description,
            parent_file_id=payload.parent_file_id,
            tags=payload.tags,
        )
    except svc.FileShareError as e:
        _err(e)


@router.get("/files", response_model=FileListResponse)
def list_files(
    scope_type: str = Query(...),
    scope_ref_id: str = Query(...),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=200),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = svc.list_files_for_scope(
            db,
            scope_type=scope_type, scope_ref_id=scope_ref_id,
            viewer_id=current_user.id,
            include_deleted=include_deleted,
            limit=limit, cursor=cursor,
        )
    except svc.FileShareError as e:
        _err(e)
    return FileListResponse(**result)


@router.get("/files/{file_id}", response_model=FileResponse)
def get_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_file(
            db, file_id=file_id, viewer_id=current_user.id,
        )
    except svc.FileShareError as e:
        _err(e)


@router.get(
    "/files/{file_id}/versions",
    response_model=FileVersionListResponse,
)
def list_versions(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        chain = svc.list_versions(
            db, file_id=file_id, viewer_id=current_user.id,
        )
        return FileVersionListResponse(
            versions=[FileResponse.model_validate(f) for f in chain],
        )
    except svc.FileShareError as e:
        _err(e)


@router.patch("/files/{file_id}", response_model=FileResponse)
def update_file(
    file_id: str,
    payload: FileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_file_metadata(
            db, file_id=file_id, owner_id=current_user.id,
            description=payload.description, tags=payload.tags,
        )
    except svc.FileShareError as e:
        _err(e)


@router.delete("/files/{file_id}", response_model=FileResponse)
def delete_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.delete_file(
            db, file_id=file_id, actor_id=current_user.id,
        )
    except svc.FileShareError as e:
        _err(e)


@router.post("/files/{file_id}/scan-result", response_model=FileResponse)
def record_scan_result(
    file_id: str,
    status: str = Query(..., description="clean | infected | failed | skipped"),
    notes: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Called by the malware scanner service after analysis completes."""
    from app.services.role_service import resolve_user_permissions
    roles, _ = resolve_user_permissions(db, current_user.id)
    if "super_admin" not in roles and "institution_administrator" not in roles:
        raise HTTPException(status_code=403, detail="Not authorised.")
    try:
        return svc.record_scan_result(
            db, file_id=file_id, status=status, notes=notes,
        )
    except svc.FileShareError as e:
        _err(e)