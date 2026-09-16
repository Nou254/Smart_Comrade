"""
IP geolocation.

Best-effort lookup of a city/country from an IP address. Uses
ip-api.com's free tier by default (no key required, 45 req/min).

Failures are swallowed — the calling code receives "unknown" and
continues. This is display-only metadata, never used for access control.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


# Free tier endpoint. No API key needed.
DEFAULT_ENDPOINT = "http://ip-api.com/json/{ip}?fields=status,country,regionName,city"

# Local/private IP prefixes we should skip
_PRIVATE_PREFIXES = (
    "127.", "10.", "192.168.", "169.254.",
    "::1", "fe80:", "fc", "fd",
)


def lookup(ip: str | None) -> str | None:
    """
    Return a human-readable location like "Nairobi, Kenya".
    Returns None on failure or for private IPs.
    """
    if not ip or _is_private(ip):
        return None

    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(DEFAULT_ENDPOINT.format(ip=ip))
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "success":
            return None

        city = data.get("city") or ""
        country = data.get("country") or ""

        if city and country:
            return f"{city}, {country}"
        return country or city or None
    except Exception as e:
        logger.debug("Geo lookup failed for %s: %s", ip, e)
        return None


def _is_private(ip: str) -> bool:
    return any(ip.startswith(p) for p in _PRIVATE_PREFIXES)