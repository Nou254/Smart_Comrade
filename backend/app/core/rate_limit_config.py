"""
Endpoint rate-limit configuration.

Each entry defines:
    limit  — max requests
    window — window in seconds

Keying strategies (used by the dependency):
    ip      — client IP
    user    — authenticated user id (from request.state.user)
    email   — email in the request body
    custom  — callable(request) -> str
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window: int           # seconds
    key_strategy: str     # "ip" | "user" | "email" | "custom"
    key_fn: Callable | None = None
    scope: str = ""       # used to build the storage key


# Named rules for auth endpoints (per spec §11.5)

RULES: dict[str, RateLimitRule] = {
    # Login: 10/min per IP
    "auth.login.ip": RateLimitRule(
        limit=10, window=60, key_strategy="ip", scope="auth.login.ip"
    ),
    # Password reset request: 5/hour per email
    "auth.forgot_password.email": RateLimitRule(
        limit=5, window=3600, key_strategy="email",
        scope="auth.forgot_password.email",
    ),
    # OTP verification: 5/hour per email (anonymous flow)
    "auth.otp.verify.email": RateLimitRule(
        limit=5, window=3600, key_strategy="email",
        scope="auth.otp.verify.email",
    ),
    # OTP resend: 3/hour per email
    "auth.otp.resend.email": RateLimitRule(
        limit=3, window=3600, key_strategy="email",
        scope="auth.otp.resend.email",
    ),
    # Phone OTP send: 5/hour per user
    "auth.phone_otp.send.user": RateLimitRule(
        limit=5, window=3600, key_strategy="user",
        scope="auth.phone_otp.send.user",
    ),
    # Account creation: 5/day per IP
    "auth.register.ip": RateLimitRule(
        limit=5, window=86400, key_strategy="ip",
        scope="auth.register.ip",
    ),
    # Generic — used as a default for endpoints that need light limiting
    "auth.generic.ip": RateLimitRule(
        limit=60, window=60, key_strategy="ip", scope="auth.generic.ip"
    ),
    # Step-up auth — same as login threshold
    "auth.step_up.user": RateLimitRule(
        limit=10, window=300, key_strategy="user", scope="auth.step_up.user"
    ),
}


def get_rule(name: str) -> RateLimitRule | None:
    return RULES.get(name)