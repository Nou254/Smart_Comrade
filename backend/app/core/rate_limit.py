"""
Rate limiting core.

Provides a FastAPI dependency factory:

    @router.post("/login")
    def login(
        _: None = Depends(rate_limit("auth.login.ip")),
        ...
    ):
        ...

The dependency:
  1. Resolves the rate-limit rule from config
  2. Extracts the key (IP, email, or user)
  3. Increments the counter
  4. Raises HTTP 429 with Retry-After header if over limit
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import HTTPException, Request
from fastapi.params import Depends

from app.core.config import settings
from app.core.rate_limit_config import get_rule
from app.core.rate_limit_store import RateLimitStore, build_store

logger = logging.getLogger(__name__)


# ── Store singleton ────────────────────────────────────────────

@lru_cache(maxsize=1)
def _store() -> RateLimitStore:
    return build_store(settings.RATE_LIMIT_BACKEND, settings.REDIS_URL)


# ── Key extraction ─────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    # Respect common proxy headers when explicitly trusted
    if settings.TRUST_PROXY_HEADERS:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else "unknown"


async def _extract_key(request: Request, strategy: str) -> str | None:
    if strategy == "ip":
        return _client_ip(request)

    if strategy == "user":
        # `get_current_user` populates `request.state.user`
        user = getattr(request.state, "user", None)
        if user is not None:
            return getattr(user, "id", None)
        return None  # fall through → skip limit rather than 500

    if strategy == "email":
        # Parse JSON body once; cache on request.state so downstream handlers reuse it
        body = getattr(request.state, "json_body", None)
        if body is None:
            try:
                body = await request.json()
            except Exception:
                body = {}
            request.state.json_body = body

        email = (body or {}).get("email")
        if isinstance(email, str):
            return email.lower().strip()
        return None

    return None


# ── Dependency factory ─────────────────────────────────────────

def rate_limit(rule_name: str):
    """
    Returns a FastAPI dependency that enforces the named rule.

    Usage:
        Depends(rate_limit("auth.login.ip"))
    """
    rule = get_rule(rule_name)
    if rule is None:
        raise RuntimeError(f"Unknown rate-limit rule: {rule_name}")

    async def _dep(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return None

        key_part = await _extract_key(request, rule.key_strategy)
        if not key_part:
            # Cannot build a key — do not block the request.
            return None

        storage_key = f"rl:{rule.scope}:{key_part}"
        count = _store().hit(storage_key, rule.window)

        if count > rule.limit:
            ttl = _store().ttl(storage_key)
            retry_after = max(ttl, 1)
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded for {rule.scope}. "
                    f"Try again in {retry_after}s."
                ),
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(rule.limit),
                    "X-RateLimit-Window": str(rule.window),
                },
            )
        return None

    return _dep


def reset_rate_limit(rule_name: str, key: str) -> None:
    """Helper for tests: clear a rate-limit counter."""
    rule = get_rule(rule_name)
    if rule is None:
        return
    _store().reset(f"rl:{rule.scope}:{key}")