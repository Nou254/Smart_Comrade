"""
Lightweight User-Agent parser.

Extracts device type, OS, and browser from a raw UA string without
depending on external libraries. Good enough for session display and
new-device detection. If more precision is needed later, swap for
`ua-parser` package.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedUA:
    device_type: str   # "mobile" | "tablet" | "desktop" | "bot" | "unknown"
    os: str            # "Android", "iOS", "Windows", "macOS", "Linux", "unknown"
    browser: str       # "Chrome", "Safari", "Firefox", "Edge", "unknown"
    raw: str           # truncated original UA (max 500 chars)

    @property
    def friendly(self) -> str:
        """Human-readable summary for session lists."""
        return f"{self.browser} on {self.os} ({self.device_type})"


BOT_KEYWORDS = (
    "bot", "crawler", "spider", "crawling", "facebookexternalhit",
    "whatsapp", "telegrambot", "slackbot", "discordbot", "curl", "wget",
)

MOBILE_KEYWORDS = ("iphone", "android", "mobile", "windows phone")
TABLET_KEYWORDS = ("ipad", "tablet")


def parse(user_agent: str | None) -> ParsedUA:
    if not user_agent:
        return ParsedUA("unknown", "unknown", "unknown", "")

    ua = user_agent.strip()
    lower = ua.lower()
    raw = ua[:500]

    if any(b in lower for b in BOT_KEYWORDS):
        return ParsedUA("bot", _os(lower), _browser(lower), raw)

    if any(t in lower for t in TABLET_KEYWORDS):
        dtype = "tablet"
    elif any(m in lower for m in MOBILE_KEYWORDS):
        dtype = "mobile"
    else:
        dtype = "desktop"

    return ParsedUA(dtype, _os(lower), _browser(lower), raw)


def _os(lower: str) -> str:
    if "windows" in lower:
        return "Windows"
    if "android" in lower:
        return "Android"
    if "iphone" in lower or "ipad" in lower or "ios" in lower:
        return "iOS"
    if "mac os" in lower or "macintosh" in lower:
        return "macOS"
    if "linux" in lower:
        return "Linux"
    return "unknown"


def _browser(lower: str) -> str:
    if "edg/" in lower or "edgios" in lower or "edga/" in lower:
        return "Edge"
    if "opr/" in lower or "opera" in lower:
        return "Opera"
    if "chrome/" in lower or "crios/" in lower:
        return "Chrome"
    if "safari/" in lower and "chrome/" not in lower:
        return "Safari"
    if "firefox/" in lower or "fxios/" in lower:
        return "Firefox"
    return "unknown"