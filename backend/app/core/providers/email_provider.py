"""
Email provider abstraction.

Supported backends:
  - console  (development — prints to stdout)
  - smtp     (any SMTP server: Gmail, Outlook, Mailgun SMTP, etc.)
  - sendgrid (SendGrid API)
  - mailgun  (Mailgun HTTP API)
  - ses      (AWS SES via boto3)

Selection is by settings.EMAIL_PROVIDER.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ── Base ───────────────────────────────────────────────────────

class EmailProvider(ABC):
    @abstractmethod
    def send(
        self,
        *,
        to: str | Sequence[str],
        subject: str,
        html_body: str,
        text_body: str | None = None,
        from_address: str | None = None,
    ) -> None:
        """Send an email. Raises EmailError on failure."""


# ── Console (dev) ──────────────────────────────────────────────

class ConsoleEmailProvider(EmailProvider):
    def send(
        self,
        *,
        to: str | Sequence[str],
        subject: str,
        html_body: str,
        text_body: str | None = None,
        from_address: str | None = None,
    ) -> None:
        recipients = [to] if isinstance(to, str) else list(to)
        logger.info("─" * 60)
        logger.info("EMAIL (console provider)")
        logger.info("From:    %s", from_address or settings.SMTP_FROM)
        logger.info("To:      %s", ", ".join(recipients))
        logger.info("Subject: %s", subject)
        logger.info("─" * 60)
        logger.info("Text body:\n%s", text_body or "(none)")
        logger.info("─" * 60)
        logger.info("HTML body:\n%s", html_body)
        logger.info("─" * 60)


# ── SMTP ───────────────────────────────────────────────────────

class SMTPEmailProvider(EmailProvider):
    def __init__(self) -> None:
        if not settings.SMTP_HOST:
            raise EmailError("SMTP_HOST is not configured.")
        if not settings.SMTP_FROM:
            raise EmailError("SMTP_FROM is not configured.")

    def send(
        self,
        *,
        to: str | Sequence[str],
        subject: str,
        html_body: str,
        text_body: str | None = None,
        from_address: str | None = None,
    ) -> None:
        recipients = [to] if isinstance(to, str) else list(to)
        sender = from_address or settings.SMTP_FROM

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)

        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            context = ssl.create_default_context()
            if settings.SMTP_USE_SSL:
                with smtplib.SMTP_SSL(
                    settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=15
                ) as server:
                    if settings.SMTP_USER:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                    server.sendmail(sender, recipients, msg.as_string())
            else:
                with smtplib.SMTP(
                    settings.SMTP_HOST, settings.SMTP_PORT, timeout=15
                ) as server:
                    server.ehlo()
                    if settings.SMTP_USE_TLS:
                        server.starttls(context=context)
                        server.ehlo()
                    if settings.SMTP_USER:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                    server.sendmail(sender, recipients, msg.as_string())
        except Exception as e:
            logger.exception("SMTP send failed")
            raise EmailError(f"SMTP send failed: {e}")


# ── SendGrid ───────────────────────────────────────────────────

class SendGridEmailProvider(EmailProvider):
    def __init__(self) -> None:
        try:
            import sendgrid  # noqa: F401
        except ImportError as e:
            raise EmailError("sendgrid package is not installed.") from e
        if not settings.SENDGRID_API_KEY:
            raise EmailError("SENDGRID_API_KEY is not configured.")

    def send(
        self,
        *,
        to: str | Sequence[str],
        subject: str,
        html_body: str,
        text_body: str | None = None,
        from_address: str | None = None,
    ) -> None:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Content

        recipients = [to] if isinstance(to, str) else list(to)
        sender = from_address or settings.SMTP_FROM

        message = Mail(
            from_email=sender,
            to_emails=recipients,
            subject=subject,
            html_content=html_body,
        )
        if text_body:
            message.add_content(Content("text/plain", text_body))

        try:
            client = SendGridAPIClient(settings.SENDGRID_API_KEY)
            response = client.send(message)
            if response.status_code >= 400:
                raise EmailError(f"SendGrid returned {response.status_code}")
        except EmailError:
            raise
        except Exception as e:
            logger.exception("SendGrid send failed")
            raise EmailError(f"SendGrid send failed: {e}")


# ── Mailgun ────────────────────────────────────────────────────

class MailgunEmailProvider(EmailProvider):
    def __init__(self) -> None:
        if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
            raise EmailError("MAILGUN_API_KEY or MAILGUN_DOMAIN is not configured.")

    def send(
        self,
        *,
        to: str | Sequence[str],
        subject: str,
        html_body: str,
        text_body: str | None = None,
        from_address: str | None = None,
    ) -> None:
        import httpx

        recipients = [to] if isinstance(to, str) else list(to)
        sender = from_address or settings.SMTP_FROM or f"noreply@{settings.MAILGUN_DOMAIN}"

        data = {
            "from": sender,
            "to": recipients,
            "subject": subject,
            "html": html_body,
        }
        if text_body:
            data["text"] = text_body

        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(
                    f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages",
                    auth=("api", settings.MAILGUN_API_KEY),
                    data=data,
                )
                if resp.status_code >= 400:
                    raise EmailError(
                        f"Mailgun returned {resp.status_code}: {resp.text[:200]}"
                    )
        except EmailError:
            raise
        except Exception as e:
            logger.exception("Mailgun send failed")
            raise EmailError(f"Mailgun send failed: {e}")


# ── AWS SES ────────────────────────────────────────────────────

class SESEmailProvider(EmailProvider):
    def __init__(self) -> None:
        try:
            import boto3  # noqa: F401
        except ImportError as e:
            raise EmailError("boto3 package is not installed.") from e
        if not settings.AWS_REGION:
            raise EmailError("AWS_REGION is not configured.")

    def send(
        self,
        *,
        to: str | Sequence[str],
        subject: str,
        html_body: str,
        text_body: str | None = None,
        from_address: str | None = None,
    ) -> None:
        import boto3

        recipients = [to] if isinstance(to, str) else list(to)
        sender = from_address or settings.SMTP_FROM

        body = {"Html": {"Charset": "UTF-8", "Data": html_body}}
        if text_body:
            body["Text"] = {"Charset": "UTF-8", "Data": text_body}

        try:
            client = boto3.client(
                "ses",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            client.send_email(
                Source=sender,
                Destination={"ToAddresses": recipients},
                Message={
                    "Subject": {"Charset": "UTF-8", "Data": subject},
                    "Body": body,
                },
            )
        except Exception as e:
            logger.exception("SES send failed")
            raise EmailError(f"SES send failed: {e}")


# ── Factory ────────────────────────────────────────────────────

def build_email_provider(name: str | None) -> EmailProvider:
    name = (name or "console").lower()

    if name == "console":
        return ConsoleEmailProvider()
    if name == "smtp":
        return SMTPEmailProvider()
    if name == "sendgrid":
        return SendGridEmailProvider()
    if name == "mailgun":
        return MailgunEmailProvider()
    if name == "ses":
        return SESEmailProvider()

    logger.warning("Unknown EMAIL_PROVIDER=%r, falling back to console", name)
    return ConsoleEmailProvider()