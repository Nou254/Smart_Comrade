"""
Coverage + engagement analytics — Module 004.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.group import Group
from app.models.unit_offering import UnitOffering
from app.models.unit_representation import (
    UnitRepresentative, UnitNetwork, UnitNetworkMember,
    UnitIssue, UnitQuestion, UnitSharedResource, UnitDiscussion,
    REP_ACTIVE,
    ISSUE_RESOLVED, ISSUE_DISMISSED,
    SCAN_VERIFIED,
)


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# COVERAGE
# ─────────────────────────────────────────────────────────────────────────

def offering_coverage(
    db: Session, *, unit_offering_id: str,
) -> dict:
    """How many groups taking the offering have an active rep?"""
    # Total groups associated with the offering
    from app.models.group import Group as G
    total_groups = db.query(func.count(G.id)).filter(
        G.semester_id == (
            db.query(UnitOffering.semester_id)
            .filter(UnitOffering.id == unit_offering_id)
            .scalar_subquery()
        ),
    ).scalar() or 0

    active_reps = db.query(func.count(UnitRepresentative.id)).filter(
        UnitRepresentative.unit_offering_id == unit_offering_id,
        UnitRepresentative.status == REP_ACTIVE,
    ).scalar() or 0

    coverage_pct = round(
        (active_reps / total_groups) * 100, 2,
    ) if total_groups else 0.0

    return {
        "unit_offering_id": unit_offering_id,
        "total_groups": int(total_groups),
        "active_reps": int(active_reps),
        "coverage_percentage": coverage_pct,
    }


def global_rep_coverage(db: Session) -> dict:
    """How many unit offerings across the platform have at least one rep?"""
    total_offerings = db.query(func.count(UnitOffering.id)).scalar() or 0
    offerings_with_reps = db.query(
        func.count(func.distinct(UnitRepresentative.unit_offering_id)),
    ).filter(
        UnitRepresentative.status == REP_ACTIVE,
    ).scalar() or 0

    coverage = round(
        (offerings_with_reps / total_offerings) * 100, 2,
    ) if total_offerings else 0.0

    return {
        "total_offerings": int(total_offerings),
        "offerings_with_active_reps": int(offerings_with_reps),
        "coverage_percentage": coverage,
    }


# ─────────────────────────────────────────────────────────────────────────
# ENGAGEMENT
# ─────────────────────────────────────────────────────────────────────────

def network_activity(
    db: Session, *, network_id: str,
) -> dict:
    """Counts of members, discussions, issues, resources."""
    from app.models.unit_representation import (
        UnitCoordinationMessage, UnitDiscussion, UnitIssue,
        UnitSharedResource,
    )

    network = db.query(UnitNetwork).filter(
        UnitNetwork.id == network_id,
    ).first()
    if not network:
        return {}

    members = db.query(func.count(UnitNetworkMember.id)).filter(
        UnitNetworkMember.network_id == network_id,
        UnitNetworkMember.is_active.is_(True),
    ).scalar() or 0

    messages = db.query(func.count(UnitCoordinationMessage.id)).filter(
        UnitCoordinationMessage.network_id == network_id,
        UnitCoordinationMessage.is_deleted.is_(False),
    ).scalar() or 0

    discussions = db.query(func.count(UnitDiscussion.id)).filter(
        UnitDiscussion.unit_offering_id == network.unit_offering_id,
        UnitDiscussion.is_deleted.is_(False),
    ).scalar() or 0

    issues_open = db.query(func.count(UnitIssue.id)).filter(
        UnitIssue.unit_offering_id == network.unit_offering_id,
        UnitIssue.status.notin_((ISSUE_RESOLVED, ISSUE_DISMISSED)),
    ).scalar() or 0

    resources = db.query(func.count(UnitSharedResource.id)).filter(
        UnitSharedResource.unit_offering_id == network.unit_offering_id,
        UnitSharedResource.is_published.is_(True),
    ).scalar() or 0

    return {
        "network_id": network_id,
        "unit_offering_id": network.unit_offering_id,
        "is_active": network.is_active,
        "active_members": int(members),
        "coordination_messages": int(messages),
        "discussions": int(discussions),
        "open_issues": int(issues_open),
        "published_resources": int(resources),
    }


def rep_activity_summary(
    db: Session, *, representative_id: str,
) -> dict:
    """How active has a given rep been?"""
    from app.models.unit_representation import UnitCoordinationMessage

    rep = db.query(UnitRepresentative).filter(
        UnitRepresentative.id == representative_id,
    ).first()
    if not rep:
        return {}

    messages = db.query(func.count(UnitCoordinationMessage.id)).filter(
        UnitCoordinationMessage.sender_id == rep.user_id,
        UnitCoordinationMessage.is_deleted.is_(False),
    ).scalar() or 0

    issues = db.query(func.count(UnitIssue.id)).filter(
        UnitIssue.raised_by_representative_id == representative_id,
    ).scalar() or 0

    questions = db.query(func.count(UnitQuestion.id)).filter(
        UnitQuestion.raised_by_representative_id == representative_id,
    ).scalar() or 0

    resources = db.query(func.count(UnitSharedResource.id)).filter(
        UnitSharedResource.shared_by_user_id == rep.user_id,
        UnitSharedResource.is_published.is_(True),
    ).scalar() or 0

    return {
        "representative_id": representative_id,
        "user_id": rep.user_id,
        "status": rep.status,
        "coordination_messages": int(messages),
        "issues_raised": int(issues),
        "questions_posed": int(questions),
        "resources_shared": int(resources),
    }


# ─────────────────────────────────────────────────────────────────────────
# HEALTH / SLA
# ─────────────────────────────────────────────────────────────────────────

def ai_response_sla(db: Session) -> dict:
    """
    SLA check on the 5-minute AI response target.
    """
    from app.services.unit_question_service import find_late_ai_responses
    late = find_late_ai_responses(db, limit=10000)
    total_answered = db.query(func.count(UnitQuestion.id)).filter(
        UnitQuestion.ai_responded_at.isnot(None),
    ).scalar() or 0
    return {
        "total_ai_answered": int(total_answered),
        "late_responses": len(late),
        "sla_target_minutes": 5,
    }


def pending_resource_scans(db: Session) -> int:
    from app.services.unit_resource_service import list_pending_scans
    return len(list_pending_scans(db, limit=10000))