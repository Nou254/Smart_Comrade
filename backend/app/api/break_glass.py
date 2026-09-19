"""
Break-glass endpoints. No CLI. All actions via HTTP.

  POST   /break-glass/setup       Super Admin + step-up -> returns shares (once)
  GET    /break-glass/status      Super Admin
  POST   /break-glass/unlock      Public (rate-limited) -> issues emergency session
  DELETE /break-glass/session     Super Admin -> revokes active break-glass session
  POST   /break-glass/regenerate  Super Admin + step-up -> rotates shares
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    require_super_admin, require_step_up,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.break_glass import (
    BreakGlassSetupResponse,
    BreakGlassStatusResponse,
    BreakGlassUnlockRequest,
    BreakGlassUnlockResponse,
    BreakGlassRevokeResponse,
)
from app.services import break_glass_service as bg
from app.services.break_glass_service import BreakGlassError


router = APIRouter(prefix="/break-glass", tags=["Break-Glass"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post("/setup", response_model=BreakGlassSetupResponse)
def setup_break_glass(
    current_user: User = Depends(require_super_admin),
    _step_up: User = Depends(require_step_up("system.config")),
    db: Session = Depends(get_db),
):
    try:
        return bg.setup(db, current_user)
    except BreakGlassError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/status", response_model=BreakGlassStatusResponse)
def break_glass_status(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return bg.status(db)


@router.post("/unlock", response_model=BreakGlassUnlockResponse)
def break_glass_unlock(
    payload: BreakGlassUnlockRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        return bg.unlock(
            db,
            share_a_b64=payload.share_a,
            share_b_b64=payload.share_b,
            reason=payload.reason,
            ip=_ip(request),
            ua=_ua(request),
        )
    except BreakGlassError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/session", response_model=BreakGlassRevokeResponse)
def break_glass_revoke(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return bg.revoke_active_session(db, current_user)


@router.post("/regenerate", response_model=BreakGlassSetupResponse)
def break_glass_regenerate(
    current_user: User = Depends(require_super_admin),
    _step_up: User = Depends(require_step_up("system.config")),
    db: Session = Depends(get_db),
):
    try:
        return bg.regenerate(db, current_user)
    except BreakGlassError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)