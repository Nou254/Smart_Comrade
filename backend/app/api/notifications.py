"""
Persistent notification endpoints — Communication module.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    NotificationCountResponse,
    NotificationMarkReadRequest,
    NotificationMarkReadResponse,
    NotificationDismissResponse,
)
from app.services import notification_store as store


router = APIRouter(tags=["Notifications"])


def _err(e):
    raise HTTPException(
        status_code=getattr(e, "status_code", 400),
        detail=getattr(e, "message", str(e)),
    )


@router.get("/notifications", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = Query(False),
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = store.list_for_user(
            db, user_id=current_user.id,
            unread_only=unread_only, category=category,
            limit=limit, cursor=cursor,
        )
    except store.NotificationStoreError as e:
        _err(e)

    return NotificationListResponse(
        notifications=[
            NotificationResponse.model_validate(n)
            for n in result["notifications"]
        ],
        next_cursor=result["next_cursor"],
        has_more=result["has_more"],
        unread_count=result["unread_count"],
    )


@router.get("/notifications/count", response_model=NotificationCountResponse)
def count_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return NotificationCountResponse(
        **store.count_for_user(db, user_id=current_user.id)
    )


@router.post(
    "/notifications/read",
    response_model=NotificationMarkReadResponse,
)
def mark_notifications_read(
    payload: NotificationMarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = store.mark_read(
        db, user_id=current_user.id,
        notification_ids=payload.notification_ids,
    )
    return NotificationMarkReadResponse(marked_read=n)


@router.post(
    "/notifications/{notification_id}/dismiss",
    response_model=NotificationDismissResponse,
)
def dismiss_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = store.dismiss(
        db, user_id=current_user.id, notification_id=notification_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return NotificationDismissResponse(dismissed=True)


@router.post("/notifications/{notification_id}/acknowledge")
def acknowledge_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = store.acknowledge(
        db, user_id=current_user.id, notification_id=notification_id,
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Notification not found or does not require acknowledgment.",
        )
    return {"ok": True}


@router.post("/notifications/expire-stale")
def expire_stale(
    batch_size: int = Query(500, ge=1, le=2000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.role_service import resolve_user_permissions
    roles, _ = resolve_user_permissions(db, current_user.id)
    if "super_admin" not in roles:
        raise HTTPException(status_code=403, detail="Super Admin only.")
    n = store.expire_stale(db, batch_size=batch_size)
    return {"expired": n}