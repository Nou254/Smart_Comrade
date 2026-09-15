"""
Email and SMS delivery services.
Email works via SMTP when SMTP_ENABLED=True.
Falls back to console logging in development.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """
    Send an email via SMTP. If SMTP is disabled or missing creds,
    log the message to the console instead (dev fallback).
    Returns True on success, False on failure.
    """
    if not settings.SMTP_ENABLED:
        logger.warning(
            "\n========== [DEV EMAIL — SMTP DISABLED] ==========\n"
            f"To:      {to}\n"
            f"Subject: {subject}\n"
            f"Text:    {text_body or '(no text body)'}\n"
            "================================================="
        )
        return True

    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.error("SMTP_ENABLED is True but SMTP_USER/SMTP_PASSWORD are missing.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to

    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, [to], msg.as_string())
        logger.info(f"Email sent to {to}")
        return True
    except Exception as e:
        logger.exception(f"Failed to send email to {to}: {e}")
        return False


def send_sms(to: str, body: str) -> bool:
    """
    Send an SMS. Currently a stub — logs to console.
    Replace with Twilio/Africa's Talking/Semaphore later.
    """
    if not settings.SMS_ENABLED:
        logger.warning(
            "\n========== [DEV SMS — DISABLED] ==========\n"
            f"To:   {to}\n"
            f"Body: {body}\n"
            "=========================================="
        )
        return True
    logger.error("SMS_ENABLED is True but no SMS provider is configured.")
    return False


# ---------- Email templates ----------

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


def send_password_reset_email(to: str, reset_url: str) -> bool:
    subject = "Reset your Smart Comrade password"
    text = (
        f"Click this link to reset your password:\n{reset_url}\n\n"
        "This link expires in 60 minutes. If you did not request this, ignore this email."
    )
    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #0d0f17;">
      <div style="max-width: 480px; margin: 0 auto; padding: 24px;">
        <h2 style="color: #00d4c8;">Smart Comrade</h2>
        <p>You requested to reset your password.</p>
        <p style="margin: 24px 0;">
          <a href="{reset_url}"
             style="background: #00d4c8; color: #fff; padding: 12px 24px;
                    text-decoration: none; border-radius: 6px; font-weight: 600;">
            Reset password
          </a>
        </p>
        <p style="color: #6b7280; font-size: 13px;">
          This link expires in 60 minutes. If you did not request this, ignore this email.
        </p>
      </div>
    </body></html>
    """
    return send_email(to, subject, html, text)


def send_account_approved_email(to: str, first_name: str) -> bool:
    subject = "Your Smart Comrade account has been approved"
    text = f"Hi {first_name}, your account has been approved. You can now log in."
    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #0d0f17;">
      <div style="max-width: 480px; margin: 0 auto; padding: 24px;">
        <h2 style="color: #00d4c8;">Smart Comrade</h2>
        <p>Hi {first_name},</p>
        <p>Your account has been <strong>approved</strong>. You can now log in and start using the platform.</p>
      </div>
    </body></html>
    """
    return send_email(to, subject, html, text)


def send_account_rejected_email(to: str, first_name: str, reason: str | None = None) -> bool:
    subject = "Smart Comrade — registration update"
    reason_text = f"\n\nReason: {reason}" if reason else ""
    text = f"Hi {first_name}, unfortunately your registration was not approved.{reason_text}"
    html = f"""
    <html><body style="font-family: Arial, sans-serif; color: #0d0f17;">
      <div style="max-width: 480px; margin: 0 auto; padding: 24px;">
        <h2 style="color: #00d4c8;">Smart Comrade</h2>
        <p>Hi {first_name},</p>
        <p>Unfortunately your registration was not approved.{f'<br><br><strong>Reason:</strong> {reason}' if reason else ''}</p>
      </div>
    </body></html>
    """
    return send_email(to, subject, html, text)