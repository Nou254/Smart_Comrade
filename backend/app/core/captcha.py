"""
CAPTCHA verification.

Supported providers:
  - none         (disabled)
  - hcaptcha     (hCaptcha — recommended for privacy-friendly)
  - recaptcha    (Google reCAPTCHA v2/v3)
  - turnstile    (Cloudflare Turnstile)

The login flow calls `captcha_required(failed_attempts)` to decide
whether to challenge the client. If challenged, the client must
include `captcha_token` in the login request.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class CaptchaError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# Threshold at which CAPTCHA becomes required (spec §11.3)
CAPTCHA_TRIGGER_AFTER_FAILED_ATTEMPTS = 3


def is_enabled() -> bool:
    return (settings.CAPTCHA_PROVIDER or "none").lower() != "none"


def captcha_required(failed_attempts: int) -> bool:
    """Return True if CAPTCHA should be required for this login attempt."""
    if not is_enabled():
        return False
    return failed_attempts >= CAPTCHA_TRIGGER_AFTER_FAILED_ATTEMPTS


async def verify_captcha(token: str | None, remote_ip: str | None = None) -> bool:
    """
    Verify a CAPTCHA token against the configured provider.

    Returns True if valid. Raises CaptchaError if the provider is
    misconfigured or if the request is invalid.
    """
    if not is_enabled():
        return True

    provider = settings.CAPTCHA_PROVIDER.lower()

    if not token:
        raise CaptchaError("CAPTCHA token missing.", 400)

    if provider == "hcaptcha":
        return await _verify_hcaptcha(token, remote_ip)
    if provider == "recaptcha":
        return await _verify_recaptcha(token, remote_ip)
    if provider == "turnstile":
        return await _verify_turnstile(token, remote_ip)

    raise CaptchaError(f"Unknown CAPTCHA provider: {provider}", 500)


async def _verify_hcaptcha(token: str, remote_ip: str | None) -> bool:
    if not settings.HCAPTCHA_SECRET_KEY:
        raise CaptchaError("HCAPTCHA_SECRET_KEY is not configured.", 500)
    url = "https://hcaptcha.com/siteverify"
    return await _generic_verify(url, settings.HCAPTCHA_SECRET_KEY, token, remote_ip)


async def _verify_recaptcha(token: str, remote_ip: str | None) -> bool:
    if not settings.RECAPTCHA_SECRET_KEY:
        raise CaptchaError("RECAPTCHA_SECRET_KEY is not configured.", 500)
    url = "https://www.google.com/recaptcha/api/siteverify"
    return await _generic_verify(url, settings.RECAPTCHA_SECRET_KEY, token, remote_ip)


async def _verify_turnstile(token: str, remote_ip: str | None) -> bool:
    if not settings.TURNSTILE_SECRET_KEY:
        raise CaptchaError("TURNSTILE_SECRET_KEY is not configured.", 500)
    url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    return await _generic_verify(url, settings.TURNSTILE_SECRET_KEY, token, remote_ip)


async def _generic_verify(
    url: str, secret: str, token: str, remote_ip: str | None
) -> bool:
    payload = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, data=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.exception("CAPTCHA verification failed")
        raise CaptchaError(f"CAPTCHA verification service error: {e}", 502)

    if not data.get("success"):
        error_codes = data.get("error-codes") or data.get("error-codes", [])
        raise CaptchaError(
            f"CAPTCHA verification failed: {error_codes}", 400
        )

    # reCAPTCHA v3 returns a score — enforce it if configured
    if "score" in data:
        min_score = settings.RECAPTCHA_MIN_SCORE
        if float(data["score"]) < min_score:
            raise CaptchaError("CAPTCHA score too low.", 400)

    return True