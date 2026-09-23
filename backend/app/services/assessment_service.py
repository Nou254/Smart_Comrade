"""
Assessment lifecycle — Module 005.

Design decisions:
  - No approval workflow: created → published → audience notified
  - Two modes: directed (audienced) + system_wide (catalog)
  - Creator role determines mandate type + subscription gating
  - Published assessments persist after creator leaves office
  - Audience resolved and snapshotted at publish time
  - Open assessments: end_at NULL means never closes
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.assessment import (
    Assessment, AssessmentAudienceSnapshot, AssessmentCatalogEntry,
    AssessmentAuditLog,
    MODE_DIRECTED, MODE_SYSTEM_WIDE,
    STATUS_DRAFT, STATUS_PUBLISHED, STATUS_IN_PROGRESS,
    STATUS_CLOSED, STATUS_ARCHIVED,
    MANDATE_INSTITUTION, MANDATE_PLATFORM, MANDATE_COMMUNITY,
    CREATOR_SUPER_ADMIN, CREATOR_REGIONAL_ADMIN, CREATOR_LECTURER,
    CREATOR_UNIT_SUPERVISOR, CREATOR_UNIT_REPRESENTATIVE, CREATOR_MENTOR,
    AUDIENCE_GROUP, AUDIENCE_UNIT_OFFERING, AUDIENCE_COURSE_YEAR,
    AUDIENCE_INSTITUTION, AUDIENCE_COUNTY, AUDIENCE_REGION, AUDIENCE_CUSTOM,
    AUDIT_CREATE, AUDIT_PUBLISH, AUDIT_CLOSE, AUDIT_ARCHIVE,
    AUDIT_AUDIENCE_CHANGE,
    DIFFICULTY_INTERMEDIATE,
)
from app.models.group import Group, GroupMembership
from app.models.academic import UnitMembership
from app.models.unit_offering import UnitOffering
from app.services.admin_audit_service import log_admin_action


logger = logging.getLogger(__name__)


class AssessmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# CREATOR ROLE → MANDATE MAPPING
# ─────────────────────────────────────────────────────────────────────────

ROLE_MANDATE_MAP: dict[str, str] = {
    CREATOR_SUPER_ADMIN: MANDATE_INSTITUTION,
    CREATOR_REGIONAL_ADMIN: MANDATE_INSTITUTION,
    CREATOR_LECTURER: MANDATE_INSTITUTION,
    CREATOR_UNIT_SUPERVISOR: MANDATE_INSTITUTION,
    CREATOR_UNIT_REPRESENTATIVE: MANDATE_PLATFORM,
    CREATOR_MENTOR: MANDATE_COMMUNITY,
}


def _mandate_for_role(role: str) -> str:
    mandate = ROLE_MANDATE_MAP.get(role)
    if not mandate:
        raise AssessmentError(
            f"Role '{role}' is not permitted to create assessments.", 403,
        )
    return mandate


def _is_gated(mandate: str) -> bool:
    return mandate == MANDATE_PLATFORM


# ─────────────────────────────────────────────────────────────────────────
# SCOPE VERIFICATION
# ─────────────────────────────────────────────────────────────────────────

def _verify_creator_scope(
    db: Session,
    *,
    creator_id: str,
    creator_role: str,
    unit_offering_id: str | None,
    group_id: str | None,
    institution_id: str | None,
    audience_scope: str | None,
) -> None:
    """
    Verify the creator is permitted to author for the given scope.
    Backend enforcement of the creator → audience matrix.
    """
    if creator_role == CREATOR_SUPER_ADMIN:
        return  # any scope

    if creator_role == CREATOR_REGIONAL_ADMIN:
        # Regional Admin — scope limits enforced by Module 008/region tables
        return  # trust at this layer; deeper region check in caller

    if creator_role == CREATOR_LECTURER:
        # Lecturers: directed → their units only; system_wide → any
        if audience_scope is None:
            return  # system-wide
        if not unit_offering_id:
            raise AssessmentError(
                "Lecturers may only create unit-directed assessments.", 403,
            )
        # Teaching relationship verified by the caller (lecturer_unit_assignments)
        return

    if creator_role == CREATOR_UNIT_SUPERVISOR:
        if not unit_offering_id:
            raise AssessmentError(
                "Unit Supervisors must specify a unit offering.", 400,
            )
        return

    if creator_role == CREATOR_UNIT_REPRESENTATIVE:
        if audience_scope not in (AUDIENCE_GROUP, AUDIENCE_UNIT_OFFERING):
            raise AssessmentError(
                "Unit Representatives may only create assessments for their "
                "group or their unit offering.", 403,
            )
        return

    if creator_role == CREATOR_MENTOR:
        if audience_scope is not None:
            raise AssessmentError(
                "Mentors may only create system-wide assessments.", 403,
            )
        return

    raise AssessmentError(
        f"Role '{creator_role}' is not permitted to create assessments.", 403,
    )


# ─────────────────────────────────────────────────────────────────────────
# AUDIENCE RESOLUTION
# ─────────────────────────────────────────────────────────────────────────

def resolve_audience(
    db: Session,
    *,
    audience_scope: str,
    audience_ref_id: str | None,
) -> list[str]:
    """
    Return the list of user IDs eligible for a directed assessment.

    Supports group, unit_offering, course_year, institution, county and
    region. Custom audiences have no reference id to resolve from; they
    are supplied explicitly as snapshot rows.
    """
    if audience_scope == AUDIENCE_GROUP:
        if not audience_ref_id:
            raise AssessmentError("audience_ref_id required for group scope.", 400)
        rows = db.query(GroupMembership.user_id).filter(
            GroupMembership.group_id == audience_ref_id,
            GroupMembership.status == "active",
        ).all()
        return [r[0] for r in rows]

    if audience_scope == AUDIENCE_UNIT_OFFERING:
        if not audience_ref_id:
            raise AssessmentError(
                "audience_ref_id required for unit_offering scope.", 400,
            )
        offering = db.query(UnitOffering).filter(
            UnitOffering.id == audience_ref_id,
        ).first()
        if not offering:
            raise AssessmentError("Unit offering not found.", 404)
        rows = db.query(UnitMembership.user_id).filter(
            UnitMembership.unit_id == offering.unit_id,
            UnitMembership.semester_id == offering.semester_id,
            UnitMembership.status == "active",
        ).all()
        return [r[0] for r in rows]

    if audience_scope == AUDIENCE_INSTITUTION:
        if not audience_ref_id:
            raise AssessmentError(
                "audience_ref_id required for institution scope.", 400,
            )
        from app.models.academic import StudentEnrollment
        return _active_enrollment_users(
            db, StudentEnrollment.institution_id == audience_ref_id,
        )

    if audience_scope == AUDIENCE_COURSE_YEAR:
        if not audience_ref_id:
            raise AssessmentError(
                "audience_ref_id required for course_year scope.", 400,
            )
        from app.models.academic import StudentEnrollment
        return _active_enrollment_users(
            db, StudentEnrollment.course_id == audience_ref_id,
        )

    if audience_scope == AUDIENCE_COUNTY:
        if not audience_ref_id:
            raise AssessmentError(
                "audience_ref_id required for county scope.", 400,
            )
        from app.models.academic import Institution, StudentEnrollment
        institution_ids = [
            r[0] for r in db.query(Institution.id).filter(
                Institution.county_id == audience_ref_id,
            ).all()
        ]
        if not institution_ids:
            return []
        return _active_enrollment_users(
            db, StudentEnrollment.institution_id.in_(institution_ids),
        )

    if audience_scope == AUDIENCE_REGION:
        if not audience_ref_id:
            raise AssessmentError(
                "audience_ref_id required for region scope.", 400,
            )
        from app.models.academic import (
            County, Institution, StudentEnrollment,
        )
        county_ids = [
            r[0] for r in db.query(County.id).filter(
                County.region_id == audience_ref_id,
            ).all()
        ]
        if not county_ids:
            return []
        institution_ids = [
            r[0] for r in db.query(Institution.id).filter(
                Institution.county_id.in_(county_ids),
            ).all()
        ]
        if not institution_ids:
            return []
        return _active_enrollment_users(
            db, StudentEnrollment.institution_id.in_(institution_ids),
        )

    if audience_scope == AUDIENCE_CUSTOM:
        raise AssessmentError(
            "Custom audiences must be supplied explicitly; there is no "
            "audience_ref_id to resolve.",
            400,
        )

    raise AssessmentError(f"Unknown audience scope '{audience_scope}'.", 400)


def _active_enrollment_users(db: Session, *criteria) -> list[str]:
    """Distinct user ids with an active enrollment matching the criteria."""
    from app.models.academic import StudentEnrollment

    rows = (
        db.query(StudentEnrollment.user_id)
        .filter(StudentEnrollment.status == "active", *criteria)
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


# ─────────────────────────────────────────────────────────────────────────
# CREATE — DIRECTED
# ─────────────────────────────────────────────────────────────────────────

def create_directed_assessment(
    db: Session,
    *,
    creator_id: str,
    creator_role: str,
    title: str,
    category: str,
    type: str,
    audience_scope: str,
    audience_ref_id: str | None,
    description: str | None = None,
    audience_resolution: str = "snapshot",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    duration_minutes: int | None = None,
    wall_clock_hard_end: bool = True,
    max_attempts: int = 1,
    passing_score: float | None = None,
    auto_grading_enabled: bool = False,
    ai_assisted_creation: bool = False,
    ai_model_used: str | None = None,
) -> Assessment:
    """
    Create a directed assessment. No approval step — direct to draft.
    """
    mandate = _mandate_for_role(creator_role)
    _verify_creator_scope(
        db,
        creator_id=creator_id,
        creator_role=creator_role,
        unit_offering_id=audience_ref_id
            if audience_scope == AUDIENCE_UNIT_OFFERING else None,
        group_id=audience_ref_id
            if audience_scope == AUDIENCE_GROUP else None,
        institution_id=audience_ref_id
            if audience_scope == AUDIENCE_INSTITUTION else None,
        audience_scope=audience_scope,
    )

    # Context extraction
    unit_offering_id = None
    group_id = None
    institution_id = None

    if audience_scope == AUDIENCE_UNIT_OFFERING:
        unit_offering_id = audience_ref_id
        offering = db.query(UnitOffering).filter(
            UnitOffering.id == audience_ref_id,
        ).first()
        if offering:
            institution_id = getattr(offering, "institution_id", None)

    elif audience_scope == AUDIENCE_GROUP:
        group_id = audience_ref_id
        grp = db.query(Group).filter(Group.id == audience_ref_id).first()
        if grp:
            institution_id = getattr(grp, "institution_id", None)

    elif audience_scope == AUDIENCE_INSTITUTION:
        institution_id = audience_ref_id

    assessment = Assessment(
        title=title,
        description=description,
        assessment_mode=MODE_DIRECTED,
        category=category,
        type=type,
        created_by=creator_id,
        created_by_role=creator_role,
        unit_offering_id=unit_offering_id,
        group_id=group_id,
        institution_id=institution_id,
        mandate_type=mandate,
        subscription_gated=_is_gated(mandate),
        audience_scope=audience_scope,
        audience_ref_id=audience_ref_id,
        audience_resolution=audience_resolution,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration_minutes,
        wall_clock_hard_end=wall_clock_hard_end,
        max_attempts=max_attempts,
        passing_score=passing_score,
        auto_grading_enabled=auto_grading_enabled,
        ai_assisted_creation=ai_assisted_creation,
        ai_model_used=ai_model_used,
        status=STATUS_DRAFT,
    )
    db.add(assessment)
    db.flush()

    _log_audit(
        db,
        assessment_id=assessment.id,
        actor_id=creator_id,
        action=AUDIT_CREATE,
        new_value=f"mode=directed scope={audience_scope}",
    )
    db.commit()
    db.refresh(assessment)
    return assessment


# ─────────────────────────────────────────────────────────────────────────
# CREATE — SYSTEM-WIDE
# ─────────────────────────────────────────────────────────────────────────

def create_system_wide_assessment(
    db: Session,
    *,
    creator_id: str,
    creator_role: str,
    title: str,
    category: str,
    type: str,
    description: str | None = None,
    specialty_unit_ids: list[str] | None = None,
    difficulty: str = DIFFICULTY_INTERMEDIATE,
    estimated_duration_minutes: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    duration_minutes: int | None = None,
    max_attempts: int = 1,
    passing_score: float | None = None,
    auto_grading_enabled: bool = False,
    ai_assisted_creation: bool = False,
    ai_model_used: str | None = None,
) -> Assessment:
    """
    Create a system-wide (public, voluntary) assessment.
    Only Super Admin, Regional Admin, Lecturer, Unit Supervisor, Mentor.
    """
    if creator_role not in (
        CREATOR_SUPER_ADMIN, CREATOR_REGIONAL_ADMIN, CREATOR_LECTURER,
        CREATOR_UNIT_SUPERVISOR, CREATOR_MENTOR,
    ):
        raise AssessmentError(
            f"Role '{creator_role}' cannot create system-wide assessments.", 403,
        )

    mandate = _mandate_for_role(creator_role)
    # Community contribution has no gate (mentor / lecturer public content)
    # Institution mandate also has no gate.

    assessment = Assessment(
        title=title,
        description=description,
        assessment_mode=MODE_SYSTEM_WIDE,
        category=category,
        type=type,
        created_by=creator_id,
        created_by_role=creator_role,
        specialty_unit_ids=specialty_unit_ids,
        mandate_type=mandate,
        subscription_gated=False,  # system-wide is never gated
        audience_scope=None,
        audience_ref_id=None,
        audience_resolution="live",
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration_minutes,
        wall_clock_hard_end=False,
        max_attempts=max_attempts,
        passing_score=passing_score,
        auto_grading_enabled=auto_grading_enabled,
        ai_assisted_creation=ai_assisted_creation,
        ai_model_used=ai_model_used,
        status=STATUS_DRAFT,
    )
    db.add(assessment)
    db.flush()

    # Catalog entry — created at publish, not at draft
    _log_audit(
        db,
        assessment_id=assessment.id,
        actor_id=creator_id,
        action=AUDIT_CREATE,
        new_value=f"mode=system_wide difficulty={difficulty}",
    )
    db.commit()
    db.refresh(assessment)
    return assessment


# ─────────────────────────────────────────────────────────────────────────
# PUBLISH
# ─────────────────────────────────────────────────────────────────────────

def publish_assessment(
    db: Session,
    *,
    assessment_id: str,
    actor_id: str,
    notify_audience: bool = True,
) -> Assessment:
    """
    Transition draft → published.
    - Directed: resolve audience, create snapshot rows, notify
    - System-wide: create catalog entry
    """
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id,
    ).first()
    if not assessment:
        raise AssessmentError("Assessment not found.", 404)
    if assessment.status != STATUS_DRAFT:
        raise AssessmentError(
            f"Only draft assessments can be published. Current: "
            f"{assessment.status}.", 409,
        )

    now = _now()
    assessment.status = STATUS_PUBLISHED
    assessment.published_at = now

    if assessment.assessment_mode == MODE_DIRECTED:
        _snapshot_audience(db, assessment)
    else:
        _ensure_catalog_entry(db, assessment)

    _log_audit(
        db,
        assessment_id=assessment.id,
        actor_id=actor_id,
        action=AUDIT_PUBLISH,
        new_value=f"status=published at={now.isoformat()}",
    )

    if notify_audience:
        _notify_audience(db, assessment)

    db.commit()
    db.refresh(assessment)
    return assessment


def _snapshot_audience(db: Session, assessment: Assessment) -> int:
    """Create audience snapshot rows for a directed assessment."""
    if assessment.audience_scope is None:
        return 0
    user_ids = resolve_audience(
        db,
        audience_scope=assessment.audience_scope,
        audience_ref_id=assessment.audience_ref_id,
    )
    now = _now()
    for uid in user_ids:
        existing = db.query(AssessmentAudienceSnapshot).filter(
            AssessmentAudienceSnapshot.assessment_id == assessment.id,
            AssessmentAudienceSnapshot.user_id == uid,
        ).first()
        if existing:
            existing.is_still_eligible = True
            existing.removed_at = None
            existing.removed_reason = None
        else:
            db.add(AssessmentAudienceSnapshot(
                assessment_id=assessment.id,
                user_id=uid,
                captured_at=now,
            ))
    assessment.audience_snapshot_at = now
    db.flush()
    return len(user_ids)


def _ensure_catalog_entry(db: Session, assessment: Assessment) -> None:
    """Create a catalog entry for a system-wide assessment."""
    existing = db.query(AssessmentCatalogEntry).filter(
        AssessmentCatalogEntry.assessment_id == assessment.id,
    ).first()
    if existing:
        return
    primary_unit = None
    if assessment.specialty_unit_ids:
        primary_unit = assessment.specialty_unit_ids[0]
    db.add(AssessmentCatalogEntry(
        assessment_id=assessment.id,
        primary_unit_id=primary_unit,
        specialty_unit_ids=assessment.specialty_unit_ids,
        difficulty=DIFFICULTY_INTERMEDIATE,
        estimated_duration_minutes=assessment.duration_minutes,
    ))
    db.flush()


def _notify_audience(db: Session, assessment: Assessment) -> None:
    """Queue persistent notifications for everyone in the audience snapshot."""
    from app.services.notification_store import create_for_users

    rows = db.query(AssessmentAudienceSnapshot).filter(
        AssessmentAudienceSnapshot.assessment_id == assessment.id,
        AssessmentAudienceSnapshot.is_still_eligible.is_(True),
    ).all()
    user_ids = [r.user_id for r in rows]
    if not user_ids:
        logger.info(
            "[assessment] no audience to notify for assessment=%s",
            assessment.id,
        )
        return

    body = (
        f"A new {assessment.type or 'assessment'} — '{assessment.title}' — "
        "has been published for you."
    )
    if assessment.start_at:
        body += f" It opens {assessment.start_at.isoformat()}."

    create_for_users(
        db,
        user_ids=user_ids,
        category="assessment",
        title=f"New assessment: {assessment.title}",
        body=body,
        priority="important",
        source_type="assessment",
        source_id=assessment.id,
        link_url=f"/assessments/{assessment.id}",
        is_system_generated=True,
        commit=False,
    )


# ─────────────────────────────────────────────────────────────────────────
# CLOSE / ARCHIVE
# ─────────────────────────────────────────────────────────────────────────

def close_assessment(
    db: Session, *, assessment_id: str, actor_id: str,
) -> Assessment:
    """Close an assessment — no new attempts."""
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id,
    ).first()
    if not assessment:
        raise AssessmentError("Assessment not found.", 404)
    if assessment.status not in (STATUS_PUBLISHED, STATUS_IN_PROGRESS):
        raise AssessmentError(
            f"Cannot close assessment in status '{assessment.status}'.", 409,
        )
    now = _now()
    assessment.status = STATUS_CLOSED
    assessment.closed_at = now
    _log_audit(
        db, assessment_id=assessment.id, actor_id=actor_id,
        action=AUDIT_CLOSE, new_value=f"status=closed at={now.isoformat()}",
    )
    db.commit()
    db.refresh(assessment)
    return assessment


def archive_assessment(
    db: Session, *, assessment_id: str, actor_id: str,
) -> Assessment:
    """Archive a closed assessment."""
    assessment = db.query(Assessment).filter(
        Assessment.id == assessment_id,
    ).first()
    if not assessment:
        raise AssessmentError("Assessment not found.", 404)
    if assessment.status != STATUS_CLOSED:
        raise AssessmentError(
            "Only closed assessments can be archived.", 409,
        )
    assessment.status = STATUS_ARCHIVED
    _log_audit(
        db, assessment_id=assessment.id, actor_id=actor_id,
        action=AUDIT_ARCHIVE, new_value="status=archived",
    )
    db.commit()
    db.refresh(assessment)
    return assessment


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def get_assessment(db: Session, assessment_id: str) -> Assessment:
    a = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not a:
        raise AssessmentError("Assessment not found.", 404)
    return a


def list_assessments(
    db: Session,
    *,
    creator_id: str | None = None,
    mode: str | None = None,
    status: str | None = None,
    unit_offering_id: str | None = None,
    group_id: str | None = None,
    institution_id: str | None = None,
    limit: int = 200,
) -> list[Assessment]:
    q = db.query(Assessment)
    if creator_id:
        q = q.filter(Assessment.created_by == creator_id)
    if mode:
        q = q.filter(Assessment.assessment_mode == mode)
    if status:
        q = q.filter(Assessment.status == status)
    if unit_offering_id:
        q = q.filter(Assessment.unit_offering_id == unit_offering_id)
    if group_id:
        q = q.filter(Assessment.group_id == group_id)
    if institution_id:
        q = q.filter(Assessment.institution_id == institution_id)
    return q.order_by(Assessment.created_at.desc()).limit(limit).all()


def list_available_for_student(
    db: Session, *, student_id: str, limit: int = 200,
) -> list[Assessment]:
    """
    List published assessments the student is in the audience of.
    Used by the App awareness layer.
    """
    now = _now()
    snapshot_rows = db.query(AssessmentAudienceSnapshot.assessment_id).filter(
        AssessmentAudienceSnapshot.user_id == student_id,
        AssessmentAudienceSnapshot.is_still_eligible.is_(True),
    ).all()
    assessment_ids = [r[0] for r in snapshot_rows]
    if not assessment_ids:
        return []

    q = db.query(Assessment).filter(
        Assessment.id.in_(assessment_ids),
        Assessment.status.in_((STATUS_PUBLISHED, STATUS_IN_PROGRESS)),
    )
    # Filter by timeline
    q = q.filter(
        (Assessment.start_at.is_(None)) | (Assessment.start_at <= now)
    )
    q = q.filter(
        (Assessment.end_at.is_(None)) | (Assessment.end_at >= now)
    )
    return q.order_by(Assessment.start_at.asc().nulls_last()).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────
# AUDIT HELPER
# ─────────────────────────────────────────────────────────────────────────

def _log_audit(
    db: Session,
    *,
    assessment_id: str | None,
    actor_id: str | None,
    action: str,
    old_value: str | None = None,
    new_value: str | None = None,
    reason: str | None = None,
) -> None:
    db.add(AssessmentAuditLog(
        assessment_id=assessment_id,
        actor_id=actor_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    ))
    db.flush()