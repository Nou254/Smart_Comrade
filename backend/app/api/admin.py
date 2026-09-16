"""
Admin-only endpoints: invitations, suspension, config, emergency mode, audit.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user, require_super_admin, require_permission, require_step_up,
)
from app.db.session import get_db
from app.models.user import User
from app.models.role import UserRole
from app.models.admin_action import AdminActionLog
from app.schemas.user import UserResponse
from app.schemas.admin import (
    InvitationCreate, InvitationResponse,
    AcceptInvitationRequest,
    SuspendRequest, ReactivateRequest,
    ConfigUpdateRequest, ConfigEntry,
    AdminActionResponse,UserDeletionRequest, 
)
from app.services.admin_service import (
    AdminError, create_invitation, accept_invitation,
    suspend_user, reactivate_user,
)
from app.services.system_config_service import (
    ConfigError, get_config, set_config, list_configs,
)
from app.services.admin_audit_service import log_admin_action


router = APIRouter(prefix="/admin", tags=["Admin — Platform Management"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


# ============================================================================
# Invitations (Super Admin only)
# ============================================================================

@router.post("/invitations", response_model=InvitationResponse, status_code=201)
def create_admin_invitation(
    payload: InvitationCreate,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        inv, token = create_invitation(
            db, invited_by=current_user.id,
            email=str(payload.email), role_code=payload.role_code,
            jurisdiction_type=payload.jurisdiction_type,
            jurisdiction_id=payload.jurisdiction_id,
            notes=payload.notes,
        )
    except AdminError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    # In dev this prints to console; in prod it's sent via SMTP.
    from app.core.notifications import send_email
    activation_url = f"https://app.smartcomrade.com/activate?token={token}"
    send_email(
        to=inv.email,
        subject="You're invited to Smart Comrade as an administrator",
        html_body=f"""
        <html><body style="font-family:Arial,sans-serif;">
          <div style="max-width:480px;margin:0 auto;padding:24px;">
            <h2 style="color:#00d4c8;">Smart Comrade Admin Invitation</h2>
            <p>You've been invited as <strong>{inv.role_code}</strong>.</p>
            <p><a href="{activation_url}" style="background:#00d4c8;color:#fff;padding:12px 24px;
              text-decoration:none;border-radius:6px;font-weight:600;">Activate account</a></p>
            <p style="color:#6b7280;font-size:13px;">This link expires in 7 days.</p>
          </div>
        </body></html>
        """,
        text_body=f"Activate your Smart Comrade admin account: {activation_url}",
    )

    return InvitationResponse(
        id=inv.id, email=inv.email, role_code=inv.role_code,
        jurisdiction_type=inv.jurisdiction_type, jurisdiction_id=inv.jurisdiction_id,
        expires_at=inv.expires_at, is_used=inv.is_used,
        invitation_token=token,  # dev convenience only
    )


@router.get("/invitations", response_model=list[InvitationResponse])
def list_invitations(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    from app.models.admin_invitation import AdminInvitation
    rows = db.query(AdminInvitation).order_by(AdminInvitation.created_at.desc()).all()
    return [
        InvitationResponse(
            id=r.id, email=r.email, role_code=r.role_code,
            jurisdiction_type=r.jurisdiction_type, jurisdiction_id=r.jurisdiction_id,
            expires_at=r.expires_at, is_used=r.is_used,
        )
        for r in rows
    ]


# ============================================================================
# Suspend / reactivate (any admin with user.suspend / user.reactivate)
# ============================================================================

@router.post("/users/{resource_id}/suspend", response_model=UserResponse)
def admin_suspend_user(
    resource_id: str,
    payload: SuspendRequest,
    request: Request,
    current_user: User = Depends(require_permission("user.suspend")),
    db: Session = Depends(get_db),
):
    try:
        return suspend_user(
            db, target_user_id=resource_id, actor_id=current_user.id,
            reason=payload.reason, ip=_ip(request), ua=_ua(request),
        )
    except AdminError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/users/{resource_id}/reactivate", response_model=UserResponse)
def admin_reactivate_user(
    resource_id: str,
    payload: ReactivateRequest,
    request: Request,
    current_user: User = Depends(require_permission("user.reactivate")),
    db: Session = Depends(get_db),
):
    try:
        return reactivate_user(
            db, target_user_id=resource_id, actor_id=current_user.id,
            reason=payload.reason, ip=_ip(request), ua=_ua(request),
        )
    except AdminError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ============================================================================
# System config / feature flags / emergency mode
# ============================================================================

@router.get("/config", response_model=list[ConfigEntry])
def admin_list_configs(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return [ConfigEntry(key=k, value=v) for k, v in list_configs(db).items()]


@router.get("/config/{key}", response_model=ConfigEntry)
def admin_get_config(
    key: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return ConfigEntry(key=key, value=get_config(db, key))


@router.patch("/config/{key}", response_model=ConfigEntry)
def admin_set_config(
    key: str,
    payload: ConfigUpdateRequest,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    # Config writes require a fresh step-up auth
    # Applied at the endpoint level because we need both the body and the header
    from app.core.security import decode_step_up_token
    step_token = request.headers.get("x-step-up-token")
    if not step_token:
        raise HTTPException(401, "Step-up authentication required for config changes.",
                            headers={"X-Step-Up-Required": "true", "X-Step-Up-Scope": "system.config"})
    payload_data = decode_step_up_token(step_token)
    if not payload_data or payload_data.get("sub") != current_user.id:
        raise HTTPException(401, "Invalid step-up token.")
    if payload_data.get("scope") not in ("system.config", "*"):
        raise HTTPException(403, "Step-up token not valid for scope 'system.config'.")

    try:
        old = get_config(db, key)
        new = set_config(db, key, payload.value, updated_by=current_user.id)
    except ConfigError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    log_admin_action(
        db, actor_id=current_user.id, action="config.update",
        target_type="system_config", target_id=key,
        old_value=str(old), new_value=str(new), reason=payload.reason,
        ip_address=_ip(request), user_agent=_ua(request),
    )
    return ConfigEntry(key=key, value=new)

# ============================================================================
# User deletion (Super Admin only)
# ============================================================================

@router.delete("/users/{resource_id}", response_model=dict)
def admin_delete_user(
    resource_id: str,
    payload: UserDeletionRequest,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    from app.services.admin_service import AdminError as AdminSvcError, delete_user
    try:
        result = delete_user(
            db,
            target_user_id=resource_id,
            actor_id=current_user.id,
            reason=payload.reason,
            confirm_email=str(payload.confirm_email),
            ip=_ip(request),
            ua=_ua(request),
        )
    except AdminSvcError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {
        "message": "User permanently deleted.",
        "deleted_user_id": result["deleted_user_id"],
        "deleted_at": result["deleted_at"].isoformat(),
    }

# ============================================================================
# Admin action log
# ============================================================================

@router.get("/actions", response_model=list[AdminActionResponse])
def admin_list_actions(
    limit: int = 100,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(AdminActionLog)
        .order_by(AdminActionLog.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return rows