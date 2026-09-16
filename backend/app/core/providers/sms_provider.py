"""
SMS provider abstraction.

Supported backends:
  - console         (development — prints to stdout)
  - africastalking  (Africa's Talking — recommended for Kenya)
  - twilio          (global)
  - vonage          (global)

Selection is by settings.SMS_PROVIDER.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)


class SMSError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ── Base ───────────────────────────────────────────────────────

class SMSProvider(ABC):
    @abstractmethod
    def send(self, *, to: str | Sequence[str], message: str) -> None:
        """Send an SMS. Raises SMSError on failure."""


# ── Console (dev) ──────────────────────────────────────────────

class ConsoleSMSProvider(SMSProvider):
    def send(self, *, to: str | Sequence[str], message: str) -> None:
        recipients = [to] if isinstance(to, str) else list(to)
        logger.info("─" * 60)
        logger.info("SMS (console provider)")
        logger.info("To:      %s", ", ".join(recipients))
        logger.info("Message: %s", message)
        logger.info("─" * 60)


# ── Africa's Talking ───────────────────────────────────────────

class AfricasTalkingSMSProvider(SMSProvider):
    def __init__(self) -> None:
        try:
            import africastalking  # noqa: F401
        except ImportError as e:
            raise SMSError("africastalking package is not installed.") from e
        if not settings.AT_API_KEY or not settings.AT_USERNAME:
            raise SMSError("AT_API_KEY or AT_USERNAME is not configured.")

    def send(self, *, to: str | Sequence[str], message: str) -> None:
        import africastalking

        recipients = [to] if isinstance(to, str) else list(to)

        try:
            africastalking.initialize(
                username=settings.AT_USERNAME,
                api_key=settings.AT_API_KEY,
            )
            sms = africastalking.SMS
            response = sms.send(message, recipients)
            # Africa's Talking returns a dict with Recipients and their status
            # Note: "Success" responses come back even for partial failures
            recipients_resp = (response or {}).get("SMSMessageData", {}).get(
                "Recipients", []
            )
            failed = [
                r for r in recipients_resp if r.get("status") not in ("Success", "Sent")
            ]
            if failed:
                raise SMSError(f"Africa's Talking partial failure: {failed}")
        except SMSError:
            raise
        except Exception as e:
            logger.exception("Africa's Talking send failed")
            raise SMSError(f"Africa's Talking send failed: {e}")


# ── Twilio ─────────────────────────────────────────────────────

class TwilioSMSProvider(SMSProvider):
    def __init__(self) -> None:
        try:
            import twilio  # noqa: F401
        except ImportError as e:
            raise SMSError("twilio package is not installed.") from e
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
            raise SMSError("Twilio credentials missing.")
        if not settings.TWILIO_FROM_NUMBER:
            raise SMSError("TWILIO_FROM_NUMBER missing.")

    def send(self, *, to: str | Sequence[str], message: str) -> None:
        from twilio.rest import Client

        recipients = [to] if isinstance(to, str) else list(to)

        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            for r in recipients:
                client.messages.create(
                    body=message,
                    from_=settings.TWILIO_FROM_NUMBER,
                    to=r,
                )
        except Exception as e:
            logger.exception("Twilio send failed")
            raise SMSError(f"Twilio send failed: {e}")


# ── Vonage ─────────────────────────────────────────────────────

class VonageSMSProvider(SMSProvider):
    def __init__(self) -> None:
        if not settings.VONAGE_API_KEY or not settings.VONAGE_API_SECRET:
            raise SMSError("Vonage credentials missing.")

    def send(self, *, to: str | Sequence[str], message: str) -> None:
        import httpx

        recipients = [to] if isinstance(to, str) else list(to)

        try:
            with httpx.Client(timeout=15) as client:
                for r in recipients:
                    resp = client.post(
                        "https://rest.nexmo.com/sms/json",
                        data={
                            "api_key": settings.VONAGE_API_KEY,
                            "api_secret": settings.VONAGE_API_SECRET,
                            "to": r,
                            "from": settings.VONAGE_SENDER_ID or "SmartComrade",
                            "text": message,
                        },
                    )
                    if resp.status_code >= 400:
                        raise SMSError(
                            f"Vonage returned {resp.status_code}: {resp.text[:200]}"
                        )
        except SMSError:
            raise
        except Exception as e:
            logger.exception("Vonage send failed")
            raise SMSError(f"Vonage send failed: {e}")


# ── Factory ────────────────────────────────────────────────────

def build_sms_provider(name: str | None) -> SMSProvider:
    name = (name or "console").lower()

    if name == "console":
        return ConsoleSMSProvider()
    if name in ("africastalking", "africastalking_sms", "at"):
        return AfricasTalkingSMSProvider()
    if name == "twilio":
        return TwilioSMSProvider()
    if name == "vonage":
        return VonageSMSProvider()

    logger.warning("Unknown SMS_PROVIDER=%r, falling back to console", name)
    return ConsoleSMSProvider()