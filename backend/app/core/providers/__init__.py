"""
Notification provider registry.

Exposes:
  - get_email_provider() → EmailProvider
  - get_sms_provider()   → SMSProvider

The provider is selected based on settings.EMAIL_PROVIDER / settings.SMS_PROVIDER.
Default is "console" for local development.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings


@lru_cache(maxsize=1)
def get_email_provider():
    from app.core.providers.email_provider import build_email_provider
    return build_email_provider(settings.EMAIL_PROVIDER)


@lru_cache(maxsize=1)
def get_sms_provider():
    from app.core.providers.sms_provider import build_sms_provider
    return build_sms_provider(settings.SMS_PROVIDER)


__all__ = ["get_email_provider", "get_sms_provider"]