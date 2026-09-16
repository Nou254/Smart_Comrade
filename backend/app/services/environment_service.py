"""
Client environment detection.

Determines whether the request came from the mobile App or the PWA,
and whether the user's account type is compatible with that environment.

Detection is based on a custom header the frontend sets:
    X-Client-Environment: app | pwa | web

If the header is absent, we infer from User-Agent:
    - "SmartComradeApp/..." → app
    - else → pwa (default fallback)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fastapi import Request


class Environment(str, Enum):
    APP = "app"
    PWA = "pwa"
    WEB = "web"
    UNKNOWN = "unknown"


# Which environments are "primary" for each user_type
PRIMARY_ENV = {
    "student":     Environment.APP,
    "lecturer":    Environment.PWA,
    "external":    Environment.PWA,
    "investor":    Environment.PWA,
    "organization": Environment.PWA,
    "alumni":      Environment.PWA,
    "mentor":      Environment.PWA,
    "specialist":  Environment.PWA,
}


@dataclass
class EnvironmentInfo:
    environment: Environment
    primary: Environment | None       # primary env for this user_type
    mismatched: bool                  # True if accessing from non-primary
    warning: str | None = None


def detect_environment(request: Request) -> Environment:
    header = request.headers.get("x-client-environment", "").strip().lower()
    if header in ("app", "pwa", "web"):
        return Environment(header)

    ua = (request.headers.get("user-agent") or "").lower()
    if "smartcomradeapp" in ua or "smartcomrade-app" in ua:
        return Environment.APP

    # Browser requests default to PWA
    if "mozilla" in ua or "webkit" in ua or "chrome" in ua or "safari" in ua:
        return Environment.PWA

    return Environment.UNKNOWN


def analyze(user_type: str | None, request: Request) -> EnvironmentInfo:
    env = detect_environment(request)
    primary = PRIMARY_ENV.get((user_type or "").lower()) if user_type else None

    mismatched = False
    warning: str | None = None

    if primary and env != Environment.UNKNOWN and env != primary:
        mismatched = True
        if primary == Environment.PWA:
            warning = (
                "This account is designed for the Smart Comrade PWA. "
                "Please continue in the browser for the full experience."
            )
        elif primary == Environment.APP:
            warning = (
                "This account works best in the Smart Comrade App. "
                "Download the App for the best experience."
            )

    return EnvironmentInfo(
        environment=env,
        primary=primary,
        mismatched=mismatched,
        warning=warning,
    )