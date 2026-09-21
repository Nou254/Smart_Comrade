"""
Club audit helper — writes to activity_club_approval_events.
Shared by all club services.
"""
import logging

from sqlalchemy.orm import Session

from app.models.activity_club import ActivityClubApprovalEvent


logger = logging.getLogger(__name__)


def log_club_event(
    db: Session,
    club_id: str,
    event_type: str,
    actor_id: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
    details: dict | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> None:
    db.add(ActivityClubApprovalEvent(
        club_id=club_id,
        event_type=event_type,
        actor_id=actor_id,
        from_state=from_state,
        to_state=to_state,
        details_json=details,
        ip_address=ip,
        user_agent=(ua or "")[:255] or None,
    ))