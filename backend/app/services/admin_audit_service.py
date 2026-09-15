"""
Dedicated admin action logging.
"""
import logging

from sqlalchemy.orm import Session

from app.models.admin_action import AdminActionLog
from app.models.role import UserRole

logger = logging.getLogger(__name__)


def log_admin_action(
    db: Session,
    *,
    actor_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    jurisdiction_type: str | None = None,
    jurisdiction_id: str | None = None,
) -> None:
    try:
        actor_role = None
        if actor_id:
            r = (
                db.query(UserRole)
                .filter(UserRole.user_id == actor_id, UserRole.status == "active")
                .first()
            )
            if r and r.role:
                actor_role = r.role.code

        db.add(AdminActionLog(
            actor_id=actor_id, actor_role=actor_role,
            action=action, target_type=target_type, target_id=target_id,
            old_value=old_value, new_value=new_value, reason=reason,
            ip_address=ip_address, user_agent=user_agent,
            jurisdiction_type=jurisdiction_type, jurisdiction_id=jurisdiction_id,
        ))
        db.commit()
    except Exception as e:
        logger.exception(f"Failed to write admin action log: {e}")
        try:
            db.rollback()
        except Exception:
            pass