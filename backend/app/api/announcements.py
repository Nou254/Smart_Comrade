"""
Official announcement endpoints — Communication module.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.announcement import (
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementCorrectionRequest,
    AnnouncementResponse,
    AnnouncementListItem,
    AnnouncementListResponse,
    AnnouncementAudienceItem,
    AnnouncementAudienceListResponse,
)
from app.services import announcement_service as svc


router = APIRouter(tags=["Announcements"])


def _err(e):
    raise HTTPException(
        status_code=getattr(e, "status_code", 400),
        detail=getattr(e, "message", str(e)),
    )


# ============================================================================
# Create / update
# ============================================================================

@router.post(
    "/announcements",
    response_model=AnnouncementResponse,
    status_code=201,
)
def create_announcement(
    payload: AnnouncementCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_announcement(
            db, publisher_id=current_user.id, data=payload,
        )
    except svc.AnnouncementError as e:
        _err(e)


@router.patch(
    "/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
)
def update_announcement(
    announcement_id: str,
    payload: AnnouncementUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_announcement(
            db, announcement_id=announcement_id,
            actor_id=current_user.id, data=payload,
        )
    except svc.AnnouncementError as e:
        _err(e)


@router.post(
    "/announcements/{announcement_id}/archive",
    response_model=AnnouncementResponse,
)
def archive_announcement(
    announcement_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.archive_announcement(
            db, announcement_id=announcement_id,
            actor_id=current_user.id,
        )
    except svc.AnnouncementError as e:
        _err(e)


@router.post(
    "/announcements/{announcement_id}/correct",
    response_model=AnnouncementResponse,
    status_code=201,
)
def publish_correction(
    announcement_id: str,
    payload: AnnouncementCorrectionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.publish_correction(
            db, original_id=announcement_id,
            actor_id=current_user.id, data=payload,
        )
    except svc.AnnouncementError as e:
        _err(e)


# ============================================================================
# Read
# ============================================================================

@router.get(
    "/announcements",
    response_model=list[AnnouncementResponse],
)
def list_announcements(
    level: str | None = Query(None),
    scope_ref_id: str | None = Query(None),
    classification: str | None = Query(None),
    include_archived: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.list_announcements(
            db, level=level, scope_ref_id=scope_ref_id,
            classification=classification,
            include_archived=include_archived, limit=limit,
        )
    except svc.AnnouncementError as e:
        _err(e)


@router.get(
    "/announcements/mine",
    response_model=AnnouncementListResponse,
)
def list_my_announcements(
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = svc.list_my_announcements(
        db, viewer_id=current_user.id, limit=limit,
    )
    items = []
    for row in rows:
        ann = row["announcement"]
        items.append(AnnouncementListItem(
            id=ann.id,
            level=ann.level,
            classification=ann.classification,
            priority=ann.priority,
            title=ann.title,
            is_pinned=ann.is_pinned,
            is_archived=ann.is_archived,
            published_at=ann.published_at,
            is_read=row["is_read"],
        ))
    return AnnouncementListResponse(
        announcements=items, next_cursor=None, has_more=False,
    )


@router.get(
    "/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
)
def get_announcement(
    announcement_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_announcement(db, announcement_id)
    except svc.AnnouncementError as e:
        _err(e)


@router.post("/announcements/{announcement_id}/read")
def mark_announcement_read(
    announcement_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        svc.mark_read(
            db, announcement_id=announcement_id, user_id=current_user.id,
        )
        return {"ok": True}
    except svc.AnnouncementError as e:
        _err(e)


# ============================================================================
# Audience
# ============================================================================

@router.get(
    "/announcements/{announcement_id}/audience",
    response_model=AnnouncementAudienceListResponse,
)
def list_audience(
    announcement_id: str,
    limit: int = Query(200, ge=1, le=500),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = svc.list_audience(
            db, announcement_id=announcement_id,
            limit=limit, cursor=cursor,
        )
    except svc.AnnouncementError as e:
        _err(e)
    return AnnouncementAudienceListResponse(**result)


# ============================================================================
# Scheduled publish — callable by a scheduler endpoint
# ============================================================================

@router.post("/announcements/publish-scheduled")
def publish_scheduled(
    batch_size: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.role_service import resolve_user_permissions
    roles, _ = resolve_user_permissions(db, current_user.id)
    if "super_admin" not in roles:
        raise HTTPException(status_code=403, detail="Super Admin only.")
    n = svc.publish_scheduled(db, batch_size=batch_size)
    return {"published": n}