"""
Authentication endpoints.
Supports 13 user types, CAPTCHA, environment detection, account deactivation,
pending-registration caching, and rate limiting.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user, require_permission, bearer_scheme,
)
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import (
    StudentRegister, LecturerRegister, ExternalRegister,
    InvestorRegister, OrganizationRegister, AlumniRegister,
    MentorRegister, SpecialistRegister, UserLogin,
    UserResponse, ApprovalRequest, PendingApprovalResponse,
)
from app.schemas.auth_extra import (
    VerifyEmailRequest, ResendOtpRequest, OtpSentResponse,
    SendPhoneOtpRequest, VerifyPhoneRequest,
    ForgotPasswordRequest, ResetPasswordRequest, ChangePasswordRequest,
    SessionResponse, MessageResponse,
    TwoFactorSetupResponse, TwoFactorVerifySetupRequest,
    TwoFactorVerifyLoginRequest, TwoFactorDisableRequest,
    TwoFactorStatusResponse, LoginResponse,
    TwoFactorEnableEmailRequest, TwoFactorEnableSmsRequest,
    TwoFactorResendChallengeRequest,
    StepUpRequest, StepUpResponse,
    DeactivateAccountRequest, ReactivateAccountRequest, DeactivationResponse,
)
from app.schemas.admin import (
    AcceptInvitationRequest,
    NotificationPreferencesUpdate, NotificationPreferencesResponse,
)
from app.services.auth_service import (
    AuthError, TwoFactorRequired, Admin2FASetupRequired, CaptchaRequired,
    register_student, register_lecturer, register_external,
    register_investor, register_organization, register_alumni,
    register_mentor, register_specialist,
    login_user, list_pending_approvals, approve_user,
)
from app.services.verification_service import (
    VerificationError,
    verify_pending_registration, resend_registration_otp,
    create_email_verification, verify_email_otp,
    create_phone_verification, verify_phone_otp,
    create_password_reset, consume_password_reset,
)
from app.services import registration_cache
from app.services.session_service import (
    create_session, revoke_session, revoke_all_other_sessions,
    list_sessions, revoke_session_by_id,
    DEFAULT_SESSION_MINUTES, ADMIN_SESSION_MINUTES,
)
from app.services.two_factor_service import (
    TwoFactorError,
    start_setup_totp, verify_setup_totp,
    enable_email_2fa, enable_sms_2fa,
    resend_login_challenge,
    verify_login_challenge, disable, backup_codes_remaining,
)
from app.services.admin_service import (
    accept_invitation, AdminError as InvitationError,
    self_deactivate, self_reactivate,
)
from app.services.jurisdiction_service import is_admin_user
from app.core.security import (
    verify_password, hash_password,
    decode_2fa_pending_token, decode_admin_setup_token, decode_access_token,
    create_step_up_token,
)
from app.services.session_service import is_session_valid
from app.services.audit_service import log_auth_event

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_or_admin_setup(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing token.")
    token = credentials.credentials

    uid = decode_admin_setup_token(token)
    if uid:
        user = db.query(User).filter(User.id == uid).first()
        if user:
            return user

    payload = decode_access_token(token)
    if not payload or not is_session_valid(db, token):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.account_status in ("suspended", "deactivated", "rejected"):
        raise HTTPException(status_code=403, detail=f"Account is {user.account_status}.")
    return user


# ============================================================================
# REGISTRATION — all return pending dict + requires_verification=true
# ============================================================================

def _pending_response(staged: dict) -> LoginResponse:
    return LoginResponse(user=staged, requires_verification=True)


@router.post(
    "/register/student",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_student_endpoint(payload: StudentRegister, db: Session = Depends(get_db)):
    try:
        staged = register_student(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


@router.post(
    "/register/lecturer",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_lecturer_endpoint(payload: LecturerRegister, db: Session = Depends(get_db)):
    try:
        staged = register_lecturer(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


@router.post(
    "/register/external",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_external_endpoint(payload: ExternalRegister, db: Session = Depends(get_db)):
    try:
        staged = register_external(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


@router.post(
    "/register/investor",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_investor_endpoint(payload: InvestorRegister, db: Session = Depends(get_db)):
    try:
        staged = register_investor(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


@router.post(
    "/register/organization",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_organization_endpoint(payload: OrganizationRegister, db: Session = Depends(get_db)):
    try:
        staged = register_organization(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


@router.post(
    "/register/alumni",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_alumni_endpoint(payload: AlumniRegister, db: Session = Depends(get_db)):
    try:
        staged = register_alumni(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


@router.post(
    "/register/mentor",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_mentor_endpoint(payload: MentorRegister, db: Session = Depends(get_db)):
    try:
        staged = register_mentor(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


@router.post(
    "/register/specialist",
    response_model=LoginResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("auth.register.ip"))],
)
def register_specialist_endpoint(payload: SpecialistRegister, db: Session = Depends(get_db)):
    try:
        staged = register_specialist(db, payload)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _pending_response(staged)


# ============================================================================
# LOGIN
# ============================================================================

@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit("auth.login.ip"))],
)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    try:
        user, token, extras = login_user(
            db, payload,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            request=request,
        )
    except CaptchaRequired:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"requires_captcha": True, "detail": "CAPTCHA verification required."},
        )
    except Admin2FASetupRequired as e:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"requires_admin_2fa_setup": True, "setup_token": e.setup_token},
        )
    except TwoFactorRequired as e:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"requires_2fa": True, "temp_token": e.temp_token},
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user).model_dump(),
        redirect_to=extras.get("redirect_to"),
        hub=extras.get("hub"),
        environment=extras.get("environment"),
        environment_warning=extras.get("environment_warning"),
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# ============================================================================
# EMAIL VERIFICATION (routes by purpose)
# ============================================================================

@router.post(
    "/verify-email",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit("auth.otp.verify.email"))],
)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    if payload.purpose == "registration":
        # Cache-based promotion to users table
        try:
            user = verify_pending_registration(db, str(payload.email), payload.otp)
        except VerificationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message)
        return LoginResponse(user=UserResponse.model_validate(user).model_dump())

    # DB-based for email_change / password_reset_confirm
    try:
        user = verify_email_otp(db, str(payload.email), payload.otp, payload.purpose)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return LoginResponse(user=UserResponse.model_validate(user).model_dump())


@router.post(
    "/resend-otp",
    response_model=OtpSentResponse,
    dependencies=[Depends(rate_limit("auth.otp.resend.email"))],
)
def resend_otp(payload: ResendOtpRequest, db: Session = Depends(get_db)):
    # Registration path — check cache first
    if payload.purpose == "registration" and registration_cache.get_pending(str(payload.email)):
        try:
            resend_registration_otp(str(payload.email))
        except VerificationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message)
        return OtpSentResponse(
            message="OTP sent", email=str(payload.email), expires_in_minutes=15,
        )

    # DB path (email_change / password_reset_confirm on existing users)
    user = db.query(User).filter(User.email == str(payload.email).lower().strip()).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email.")
    try:
        create_email_verification(db, user, purpose=payload.purpose)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return OtpSentResponse(message="OTP sent", email=user.email, expires_in_minutes=15)


# ============================================================================
# PHONE VERIFICATION
# ============================================================================

@router.post("/send-phone-otp", response_model=OtpSentResponse)
def send_phone_otp(
    payload: SendPhoneOtpRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(rate_limit("auth.phone_otp.send.user")),
    db: Session = Depends(get_db),
):
    try:
        create_phone_verification(db, current_user, phone=payload.phone)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return OtpSentResponse(
        message="SMS OTP sent",
        phone=payload.phone or current_user.phone,
        expires_in_minutes=10,
    )


@router.post("/verify-phone", response_model=UserResponse)
def verify_phone(
    payload: VerifyPhoneRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        user = verify_phone_otp(db, current_user, payload.otp)
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return user


# ============================================================================
# PASSWORD RESET
# ============================================================================

@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit("auth.forgot_password.email"))],
)
def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db),
):
    create_password_reset(db, str(payload.email), request_ip=_client_ip(request))
    return MessageResponse(message="If an account exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db),
):
    try:
        consume_password_reset(
            db, payload.token, payload.new_password,
            request_ip=_client_ip(request),
        )
    except VerificationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return MessageResponse(message="Password has been reset. Please log in again.")


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    revoke_all_other_sessions(db, current_user.id)
    log_auth_event(db, "password_changed", user_id=current_user.id, email=current_user.email)
    return MessageResponse(message="Password changed. All other sessions have been logged out.")


# ============================================================================
# SESSIONS + LOGOUT
# ============================================================================

@router.get("/sessions", response_model=list[SessionResponse])
def get_my_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_sessions(db, current_user.id)


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = revoke_session_by_id(db, current_user.id, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found.")
    log_auth_event(
        db, "session_revoked", user_id=current_user.id,
        email=current_user.email, event_data={"session_id": session_id},
    )
    return MessageResponse(message="Session revoked.")


@router.delete("/sessions", response_model=MessageResponse)
def logout_all_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = revoke_all_other_sessions(db, current_user.id)
    return MessageResponse(message=f"{count} session(s) revoked.")


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
        revoke_session(db, token)
    return MessageResponse(message="Logged out.")


# ============================================================================
# 2FA
# ============================================================================

@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
def two_factor_setup_totp(
    current_user: User = Depends(_user_or_admin_setup),
    db: Session = Depends(get_db),
):
    if current_user.two_factor_enabled:
        raise HTTPException(status_code=409, detail="2FA is already enabled. Disable it first.")
    result = start_setup_totp(db, current_user)
    return TwoFactorSetupResponse(**result)


@router.post("/2fa/verify-setup", response_model=MessageResponse)
def two_factor_verify_setup(
    payload: TwoFactorVerifySetupRequest,
    current_user: User = Depends(_user_or_admin_setup),
    db: Session = Depends(get_db),
):
    try:
        verify_setup_totp(db, current_user, payload.code)
    except TwoFactorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return MessageResponse(message="TOTP 2FA enabled successfully.")


@router.post("/2fa/enable-email", response_model=MessageResponse)
def two_factor_enable_email(
    payload: TwoFactorEnableEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = enable_email_2fa(db, current_user)
    except TwoFactorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return MessageResponse(message=result["message"])


@router.post("/2fa/enable-sms", response_model=MessageResponse)
def two_factor_enable_sms(
    payload: TwoFactorEnableSmsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = enable_sms_2fa(db, current_user)
    except TwoFactorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return MessageResponse(message=result["message"])


@router.post("/2fa/resend-challenge", response_model=MessageResponse)
def two_factor_resend(
    payload: TwoFactorResendChallengeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = decode_2fa_pending_token(payload.temp_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA token.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        result = resend_login_challenge(
            db, user,
            ip=_client_ip(request), ua=request.headers.get("user-agent"),
        )
    except TwoFactorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return MessageResponse(message=result["message"])


@router.post("/2fa/verify-login", response_model=LoginResponse)
def two_factor_verify_login(
    payload: TwoFactorVerifyLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = decode_2fa_pending_token(payload.temp_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA token.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    try:
        ok = verify_login_challenge(db, user, payload.code)
    except TwoFactorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    if not ok:
        raise HTTPException(status_code=401, detail="Invalid 2FA code.")

    is_admin = is_admin_user(db, user.id)
    expiry = ADMIN_SESSION_MINUTES if is_admin else DEFAULT_SESSION_MINUTES

    token, _ = create_session(
        db, user,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        expires_minutes=expiry,
    )

    from app.services.hub_router import resolve_hub
    from app.services.environment_service import analyze as analyze_env
    hub_target = resolve_hub(db, user.id, user.user_type)
    extras = {"redirect_to": hub_target.redirect_to, "hub": hub_target.hub}
    try:
        env_info = analyze_env(user.user_type, request)
        extras["environment"] = env_info.environment.value
        if env_info.warning:
            extras["environment_warning"] = env_info.warning
    except Exception:
        pass

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user).model_dump(),
        redirect_to=extras.get("redirect_to"),
        hub=extras.get("hub"),
        environment=extras.get("environment"),
        environment_warning=extras.get("environment_warning"),
    )


@router.post("/2fa/disable", response_model=MessageResponse)
def two_factor_disable(
    payload: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        disable(db, current_user, payload.password, payload.code)
    except TwoFactorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return MessageResponse(message="2FA disabled.")


@router.get("/2fa/status", response_model=TwoFactorStatusResponse)
def two_factor_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return TwoFactorStatusResponse(
        enabled=current_user.two_factor_enabled,
        method=current_user.two_factor_method,
        backup_codes_remaining=backup_codes_remaining(db, current_user),
    )


# ============================================================================
# STEP-UP
# ============================================================================

@router.post("/step-up", response_model=StepUpResponse)
def step_up(
    payload: StepUpRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    _: None = Depends(rate_limit("auth.step_up.user")),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    if not current_user.two_factor_enabled:
        raise HTTPException(status_code=409, detail="Enable 2FA before using step-up.")

    try:
        ok = verify_login_challenge(db, current_user, payload.code)
    except TwoFactorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    if not ok:
        raise HTTPException(status_code=401, detail="Invalid 2FA code.")

    token = create_step_up_token(
        current_user.id, scope=payload.scope, expires_minutes=10,
    )
    log_auth_event(
        db, "step_up_issued",
        user_id=current_user.id, email=current_user.email,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        event_data={"scope": payload.scope},
    )
    return StepUpResponse(
        step_up_token=token, scope=payload.scope, expires_in_minutes=10,
    )


# ============================================================================
# INVITATION ACCEPT
# ============================================================================

@router.post("/invitations/accept", response_model=UserResponse, status_code=201)
def accept_admin_invitation(
    payload: AcceptInvitationRequest,
    db: Session = Depends(get_db),
):
    try:
        user = accept_invitation(
            db, token=payload.token,
            first_name=payload.first_name, last_name=payload.last_name,
            password=payload.password, phone=payload.phone,
        )
    except InvitationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return user


# ============================================================================
# APPROVAL WORKFLOW
# ============================================================================

@router.get("/pending-approvals", response_model=list[PendingApprovalResponse])
def get_pending_approvals(
    institution_id: str,
    current_user: User = Depends(require_permission("user.edit")),
    db: Session = Depends(get_db),
):
    rows = list_pending_approvals(db, institution_id)
    return [PendingApprovalResponse.model_validate(r) for r in rows]


@router.post("/pending-approvals/{user_id}", response_model=UserResponse)
def approve_or_reject(
    user_id: str,
    payload: ApprovalRequest,
    current_user: User = Depends(require_permission("user.edit")),
    db: Session = Depends(get_db),
):
    try:
        user = approve_user(
            db, user_id,
            approver_id=current_user.id,
            approve=payload.approve,
            reason=payload.reason,
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return user


# ============================================================================
# ACCOUNT DEACTIVATION
# ============================================================================

@router.post("/deactivate", response_model=DeactivationResponse)
def deactivate_account(
    payload: DeactivateAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="You must confirm deactivation.")
    try:
        user = self_deactivate(db, current_user, payload.password, payload.reason)
    except InvitationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return DeactivationResponse(
        message="Account deactivated. You may reactivate within 30 days.",
        deactivated_at=user.deactivated_at,
        reactivation_deadline=user.reactivation_deadline,
        grace_period_days=30,
    )


@router.post("/reactivate", response_model=LoginResponse)
def reactivate_account(
    payload: ReactivateAccountRequest,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=400,
        detail="Provide your email when reactivating. Use POST /auth/reactivate/{email}",
    )


@router.post("/reactivate/{email}", response_model=LoginResponse)
def reactivate_account_by_email(
    email: str,
    payload: ReactivateAccountRequest,
    db: Session = Depends(get_db),
):
    try:
        user = self_reactivate(db, email, payload.password)
    except InvitationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return LoginResponse(user=UserResponse.model_validate(user).model_dump())


# ============================================================================
# NOTIFICATION PREFERENCES
# ============================================================================

@router.get("/notification-preferences", response_model=NotificationPreferencesResponse)
def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.notification_preference import NotificationPreference
    prefs = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == current_user.id)
        .first()
    )
    if not prefs:
        prefs = NotificationPreference(user_id=current_user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


@router.patch("/notification-preferences", response_model=NotificationPreferencesResponse)
def update_notification_preferences(
    payload: NotificationPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.notification_preference import NotificationPreference
    prefs = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == current_user.id)
        .first()
    )
    if not prefs:
        prefs = NotificationPreference(user_id=current_user.id)
        db.add(prefs)
        db.flush()

    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(prefs, field, value)

    db.commit()
    db.refresh(prefs)
    return prefs