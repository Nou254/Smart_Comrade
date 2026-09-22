"""
Unit shared resources — Module 004.

Design:
  - Every shared resource is scanned by AI to affirm its relevance
    to the unit offering before publishing.
  - The scan runs asynchronously; resources stay unpublished until
    the scan marks them verified_unit_match.
  - Flagged resources remain unpublished and are surfaced to the
    supervisor and the uploading rep.

In V1 the AI scan is STUBBED — it auto-verifies every resource with a
fixed confidence score. Wiring the real scanner is a Wave D+ task.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.unit_offering import UnitOffering
from app.models.unit_representation import (
    UnitSharedResource, UnitRepresentative,
    REP_ACTIVE,
    RESOURCE_TYPES, RESOURCE_VISIBILITY_NETWORK, RESOURCE_VISIBILITY_UNIT,
    SCAN_PENDING, SCAN_SCANNING, SCAN_VERIFIED, SCAN_FLAGGED, SCAN_FAILED,
)


logger = logging.getLogger(__name__)


class UnitResourceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# SHARE A RESOURCE
# ─────────────────────────────────────────────────────────────────────────

def share_resource(
    db: Session,
    *,
    unit_offering_id: str,
    shared_by_user_id: str,
    title: str,
    resource_type: str,
    description: str | None = None,
    file_url: str | None = None,
    external_url: str | None = None,
    content_text: str | None = None,
    visibility: str = RESOURCE_VISIBILITY_NETWORK,
    source_group_id: str | None = None,
) -> UnitSharedResource:
    """
    Share a resource. It enters the AI scan pipeline and stays
    unpublished until the scan marks it verified.
    """
    if resource_type not in RESOURCE_TYPES:
        raise UnitResourceError(
            f"Invalid resource_type '{resource_type}'. "
            f"Allowed: {RESOURCE_TYPES}.", 400,
        )
    if visibility not in (RESOURCE_VISIBILITY_NETWORK, RESOURCE_VISIBILITY_UNIT):
        raise UnitResourceError(
            f"Invalid visibility '{visibility}'.", 400,
        )
    if not any([file_url, external_url, content_text]):
        raise UnitResourceError(
            "A resource must have at least one of: file_url, external_url, "
            "or content_text.", 400,
        )

    offering = db.query(UnitOffering).filter(
        UnitOffering.id == unit_offering_id,
    ).first()
    if not offering:
        raise UnitResourceError("Unit offering not found.", 404)

    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.user_id == shared_by_user_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).first()
    if not rep:
        raise UnitResourceError(
            "Only active Unit Representatives may share resources.", 403,
        )

    resource = UnitSharedResource(
        unit_offering_id=unit_offering_id,
        shared_by_user_id=shared_by_user_id,
        source_group_id=source_group_id,
        title=title,
        description=description,
        resource_type=resource_type,
        file_url=file_url,
        external_url=external_url,
        content_text=content_text,
        visibility=visibility,
        ai_scan_status=SCAN_PENDING,
        is_published=False,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Fire the AI scan stub synchronously. In production this becomes
    # a background task that calls the LLM provider.
    _ai_scan_resource(db, resource)
    db.refresh(resource)
    return resource


# ─────────────────────────────────────────────────────────────────────────
# AI SCAN STUB
# ─────────────────────────────────────────────────────────────────────────

def _ai_scan_resource(
    db: Session, resource: UnitSharedResource,
) -> UnitSharedResource:
    """
    V1 stub — auto-verifies every resource with a fixed confidence score.
    The real scanner will:
      1. Extract text from the resource (PDF, doc, link scrape, code)
      2. Compare it against the unit's title, code, and learning outcomes
      3. Return a relevance score + explanation
      4. Mark verified or flagged
    """
    now = _now()
    resource.ai_scan_status = SCAN_VERIFIED
    resource.ai_scan_confidence = 0.95
    resource.ai_scan_notes = (
        "V1 stub — AI scanner not yet wired. Auto-verified at 0.95. "
        "Real scan will affirm unit relevance against the offering's "
        "learning outcomes."
    )
    resource.ai_scanned_at = now
    resource.is_published = True
    resource.published_at = now
    db.commit()
    db.refresh(resource)
    return resource


def force_rescan(
    db: Session, resource_id: str,
) -> UnitSharedResource:
    """Force a re-run of the AI scan (used by supervisors)."""
    resource = db.query(UnitSharedResource).filter(
        UnitSharedResource.id == resource_id,
    ).first()
    if not resource:
        raise UnitResourceError("Resource not found.", 404)

    resource.ai_scan_status = SCAN_PENDING
    resource.is_published = False
    db.commit()
    db.refresh(resource)
    return _ai_scan_resource(db, resource)


def supervisor_flag_resource(
    db: Session,
    *,
    resource_id: str,
    supervisor_user_id: str,
    reason: str,
) -> UnitSharedResource:
    """
    Supervisor manually flags a resource as off-topic. Unpublishes it
    and records the reason.
    """
    resource = db.query(UnitSharedResource).filter(
        UnitSharedResource.id == resource_id,
    ).first()
    if not resource:
        raise UnitResourceError("Resource not found.", 404)

    from app.models.unit_representation import UnitNetwork
    network = db.query(UnitNetwork).filter(
        UnitNetwork.unit_offering_id == resource.unit_offering_id,
    ).first()
    if not network or network.supervisor_user_id != supervisor_user_id:
        raise UnitResourceError(
            "Only the assigned Unit Supervisor may flag resources.", 403,
        )

    resource.ai_scan_status = SCAN_FLAGGED
    resource.ai_scan_notes = f"Supervisor flag: {reason}"
    resource.ai_scanned_at = _now()
    resource.is_published = False
    db.commit()
    db.refresh(resource)
    return resource


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_resource(db: Session, resource_id: str) -> UnitSharedResource:
    r = db.query(UnitSharedResource).filter(
        UnitSharedResource.id == resource_id,
    ).first()
    if not r:
        raise UnitResourceError("Resource not found.", 404)
    return r


def list_published_resources(
    db: Session,
    *,
    unit_offering_id: str,
    visibility: str | None = None,
    limit: int = 200,
) -> list[UnitSharedResource]:
    q = db.query(UnitSharedResource).filter(
        UnitSharedResource.unit_offering_id == unit_offering_id,
        UnitSharedResource.is_published.is_(True),
    )
    if visibility:
        q = q.filter(UnitSharedResource.visibility == visibility)
    return q.order_by(
        UnitSharedResource.published_at.desc(),
    ).limit(limit).all()


def list_network_resources(
    db: Session, unit_offering_id: str, limit: int = 200,
) -> list[UnitSharedResource]:
    """Rep-facing view — includes network-only resources."""
    return db.query(UnitSharedResource).filter(
        UnitSharedResource.unit_offering_id == unit_offering_id,
        UnitSharedResource.is_published.is_(True),
    ).order_by(
        UnitSharedResource.published_at.desc(),
    ).limit(limit).all()


def list_pending_scans(
    db: Session, limit: int = 100,
) -> list[UnitSharedResource]:
    """Resources stuck in the scan pipeline (used by cron)."""
    return db.query(UnitSharedResource).filter(
        UnitSharedResource.ai_scan_status.in_((SCAN_PENDING, SCAN_SCANNING)),
    ).limit(limit).all()