"""
Notification facade.

Thin wrapper around the provider registry. Keeps the existing
`send_email` / `send_sms` public API so callers don't change, but
routes everything through the pluggable providers.

Template functions delegate to `app.core.templates.email_templates`.
"""
import logging

from app.core.config import settings
from app.core.providers import get_email_provider, get_sms_provider
from app.core.templates import email_templates

logger = logging.getLogger(__name__)


# ── Low-level send ─────────────────────────────────────────────

def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    from_address: str | None = None,
) -> bool:
    """
    Send an email via the configured provider.
    Returns True on success, False on failure.
    """
    try:
        get_email_provider().send(
            to=to,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_address=from_address,
        )
        logger.info("Email sent to %s (subject=%r)", to, subject)
        return True
    except Exception as e:
        logger.exception("Failed to send email to %s: %s", to, e)
        return False


def send_sms(to: str, body: str) -> bool:
    """
    Send an SMS via the configured provider.
    Returns True on success, False on failure.
    """
    try:
        get_sms_provider().send(to=to, message=body)
        logger.info("SMS sent to %s", to)
        return True
    except Exception as e:
        logger.exception("Failed to send SMS to %s: %s", to, e)
        return False


# ── Template wrappers ──────────────────────────────────────────
# These keep the existing function signatures used by auth_service
# and other modules. They build the email body via the templates
# module and hand off to send_email().

def send_otp_email(to: str, otp: str, purpose: str = "registration") -> bool:
    subject_map = {
        "registration": "Verify your Smart Comrade email",
        "email_change": "Confirm your new Smart Comrade email",
        "password_reset_confirm": "Smart Comrade — verification code",
    }
    subject = subject_map.get(purpose, "Smart Comrade verification code")

    text = (
        f"Your Smart Comrade verification code is: {otp}\n\n"
        "This code expires in 15 minutes. Do not share it with anyone."
    )
    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #0d0f17;">
      <div style="max-width: 480px; margin: 0 auto; padding: 24px;">
        <h2 style="color: #00d4c8;">Smart Comrade</h2>
        <p>Your verification code is:</p>
        <div style="font-size: 32px; font-weight: 700; letter-spacing: 4px;
                    background: #f3f4f6; padding: 16px; text-align: center;
                    border-radius: 8px; margin: 16px 0;">
          {otp}
        </div>
        <p style="color: #6b7280; font-size: 13px;">
          This code expires in 15 minutes. Do not share it with anyone.
        </p>
      </div>
    </body></html>
    """
    return send_email(to, subject, html, text)


def send_phone_otp_sms(to: str, otp: str, purpose: str = "registration") -> bool:
    """
    Send a phone verification OTP via SMS.
    """
    text = f"Smart Comrade verification code: {otp}. Valid for 10 minutes."
    return send_sms(to, text)


def send_password_reset_email(to: str, reset_url: str) -> bool:
    subject, html, text = email_templates.password_reset(
        name="there", reset_url=reset_url
    )
    return send_email(to, subject, html, text)


def send_account_approved_email(to: str, first_name: str) -> bool:
    subject, html, text = email_templates.account_approved(name=first_name)
    return send_email(to, subject, html, text)


def send_account_rejected_email(
    to: str, first_name: str, reason: str | None = None
) -> bool:
    subject, html, text = email_templates.account_rejected(
        name=first_name, reason=reason
    )
    return send_email(to, subject, html, text)


def send_account_suspended_email(
    to: str, first_name: str, reason: str | None = None
) -> bool:
    subject, html, text = email_templates.account_suspended(
        name=first_name, reason=reason
    )
    return send_email(to, subject, html, text)


def send_new_device_email(
    to: str,
    first_name: str,
    device: str,
    ip: str | None = None,
    when: str | None = None,
) -> bool:
    subject, html, text = email_templates.new_device_login(
        name=first_name, device=device, ip=ip, when=when
    )
    return send_email(to, subject, html, text)


def send_admin_invitation_email(
    to: str, role_code: str, activation_url: str
) -> bool:
    subject, html, text = email_templates.admin_invitation(
        role_code=role_code, activation_url=activation_url
    )
    return send_email(to, subject, html, text)


def send_password_changed_email(
    to: str, first_name: str, ip: str | None = None
) -> bool:
    subject, html, text = email_templates.password_changed(
        name=first_name, ip=ip
    )
    return send_email(to, subject, html, text)


def send_welcome_email(to: str, first_name: str) -> bool:
    subject, html, text = email_templates.welcome(name=first_name)
    return send_email(to, subject, html, text)