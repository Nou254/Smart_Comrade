"""
Shared FastAPI dependencies: auth + RBAC + jurisdiction + step-up + admin 2FA setup.
Sets request.state.user so rate-limit user-keyed rules work.

Step-up tokens are context-bound: they can only be used from the same IP and
User-Agent that issued them. A mismatch rejects the request and writes a
step_up_context_mismatch audit event.
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    decode_access_token, decode_step_up_token, decode_admin_setup_token,
    hash_context,
)
from app.db.session import get_db
from app.models.user import User
from app.services.role_service import resolve_user_permissions
from app.services.session_service import is_session_valid
from app.services.jurisdiction_service import user_has_jurisdiction, is_admin_user
from app.services.audit_service import log_auth_event

bearer_scheme = HTTPBearer(auto_error=False)


# ============================================================================
# Client IP (respects proxy headers when configured)
# ============================================================================

def _client_ip(request: Request) -> str | None:
    """Best-effort client IP.

    If TRUST_PROXY_HEADERS is enabled, uses the first entry of X-Forwarded-For.
    Otherwise falls back to the socket peer address.
    """
    if settings.TRUST_PROXY_HEADERS:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip() or None
    return request.client.host if request.client else None


# ============================================================================
# Authentication
# ============================================================================

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")
    if not is_session_valid(db, token):
        raise HTTPException(status_code=401, detail="Session has been revoked or expired.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    if user.account_status in ("suspended", "deactivated", "rejected"):
        raise HTTPException(status_code=403, detail=f"Account is {user.account_status}.")

    # Expose authenticated user for downstream rate-limit dependencies
    request.state.user = user
    request.state.access_token = token
    return user


# ============================================================================
# RBAC
# ============================================================================

def require_role(*role_codes: str):
    required = set(role_codes)

    def _checker(current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> User:
        roles, _ = resolve_user_permissions(db, current_user.id)
        if not required.intersection(roles):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {sorted(required)}",
            )
        return current_user
    return _checker


def require_permission(*permission_codes: str):
    required = set(permission_codes)

    def _checker(current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> User:
        _, perms = resolve_user_permissions(db, current_user.id)
        if not required.intersection(perms):
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of permissions: {sorted(required)}",
            )
        return current_user
    return _checker


def require_super_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    roles, _ = resolve_user_permissions(db, current_user.id)
    if "super_admin" not in roles:
        raise HTTPException(status_code=403, detail="Super Admin access required.")
    return current_user


def require_jurisdiction(resource_type: str):
    """
    Requires the current user to have jurisdiction over the resource.
    The endpoint must expose the resource id as a path param called
    `resource_id` or `id`.
    """
    def _checker(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        resource_id = (
            request.path_params.get("resource_id")
            or request.path_params.get("id")
        )
        if not resource_id:
            raise HTTPException(status_code=500, detail="Endpoint missing resource id.")
        if not user_has_jurisdiction(db, current_user.id, resource_type, resource_id):
            raise HTTPException(
                status_code=403,
                detail=f"You do not have jurisdiction over this {resource_type}.",
            )
        return current_user
    return _checker


# ============================================================================
# Step-up
#
# Enforces:
#   1. Presence of X-Step-Up-Token header
#   2. Token sub matches the current user
#   3. Token scope matches the endpoint's required scope (or is "*")
#   4. If the token carries ip_hash, current request's IP hash matches
#   5. If the token carries ua_hash, current request's User-Agent hash matches
#
# Legacy tokens (issued before this change) carry no context claims and are
# accepted for backward compatibility.
# ============================================================================

def require_step_up(scope: str):
    def _checker(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        token = request.headers.get("x-step-up-token")
        if not token:
            raise HTTPException(
                status_code=401,
                detail="Step-up authentication required.",
                headers={"X-Step-Up-Required": "true", "X-Step-Up-Scope": scope},
            )

        payload = decode_step_up_token(token)
        if not payload or payload.get("sub") != current_user.id:
            raise HTTPException(status_code=401, detail="Invalid step-up token.")

        token_scope = payload.get("scope")
        if token_scope != scope and token_scope != "*":
            raise HTTPException(
                status_code=403,
                detail=f"Step-up token not valid for scope '{scope}'.",
            )

        # --- Context binding checks ---
        expected_ip = payload.get("ip_hash")
        expected_ua = payload.get("ua_hash")

        if expected_ip is not None:
            current_ip = _client_ip(request)
            if hash_context(current_ip) != expected_ip:
                log_auth_event(
                    db,
                    "step_up_context_mismatch",
                    user_id=current_user.id,
                    email=current_user.email,
                    ip_address=current_ip,
                    user_agent=request.headers.get("user-agent"),
                    event_data={"scope": scope, "dimension": "ip"},
                    success=False,
                )
                raise HTTPException(
                    status_code=401,
                    detail="Step-up token context mismatch. Re-authenticate.",
                )

        if expected_ua is not None:
            current_ua = request.headers.get("user-agent")
            if hash_context(current_ua) != expected_ua:
                log_auth_event(
                    db,
                    "step_up_context_mismatch",
                    user_id=current_user.id,
                    email=current_user.email,
                    ip_address=_client_ip(request),
                    user_agent=current_ua,
                    event_data={"scope": scope, "dimension": "user_agent"},
                    success=False,
                )
                raise HTTPException(
                    status_code=401,
                    detail="Step-up token context mismatch. Re-authenticate.",
                )

        return current_user
    return _checker


# ============================================================================
# Admin setup token (used by 2FA setup flow)
# ============================================================================

def get_admin_setup_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Allows access only with a valid admin-2FA-setup token."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing admin setup token.")
    user_id = decode_admin_setup_token(credentials.credentials)
    if not user_id:
        raise HTTPException(
            status_code=401, detail="Invalid or expired admin setup token."
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if not is_admin_user(db, user.id):
        raise HTTPException(status_code=403, detail="Not an admin account.")
    return user