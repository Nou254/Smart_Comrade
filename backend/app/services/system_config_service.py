"""
Feature flags + emergency mode.
"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.system_config import SystemConfig


class ConfigError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


DEFAULTS = {
    "emergency_mode": {"enabled": False, "reason": None, "since": None},
    "registration_enabled": {"enabled": True},
    "elections_enabled": {"enabled": True},
    "events_enabled": {"enabled": True},
    "admin_2fa_required": {"enabled": True},
}


def get_config(db: Session, key: str) -> dict:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if not row:
        return dict(DEFAULTS.get(key, {}))
    try:
        return json.loads(row.value) if row.value else {}
    except Exception:
        return {}


def set_config(db: Session, key: str, value: dict, updated_by: str | None = None) -> dict:
    if key not in DEFAULTS and not key.startswith("flag_"):
        raise ConfigError(f"Unknown config key: {key}", 400)
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    encoded = json.dumps(value)
    if not row:
        db.add(SystemConfig(key=key, value=encoded, updated_by=updated_by))
    else:
        row.value = encoded
        row.updated_by = updated_by
    db.commit()
    return value


def list_configs(db: Session) -> dict[str, dict]:
    result = {k: dict(v) for k, v in DEFAULTS.items()}
    for row in db.query(SystemConfig).all():
        try:
            result[row.key] = json.loads(row.value)
        except Exception:
            pass
    return result


def is_emergency_mode(db: Session) -> bool:
    return bool(get_config(db, "emergency_mode").get("enabled", False))


def is_registration_enabled(db: Session) -> bool:
    return bool(get_config(db, "registration_enabled").get("enabled", True))


def is_admin_2fa_required(db: Session) -> bool:
    return bool(get_config(db, "admin_2fa_required").get("enabled", True))