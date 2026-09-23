"""
Shared file service — Communication module.

Scope list (per spec):
  direct    → direct_conversations.id
  unit      → unit_offerings.id
  community → communities.id

Access is inherited from the scope. No per-file ACL.
Versioning chains rows via parent_file_id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.file_share import SharedFile, VALID_SCOPE_TYPES


logger = logging.getLogger(__name__)


class FileShareError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# Scope access check
# ============================================================================

def _assert_scope_access(
    db: Session, *,
    scope_type: str, scope_ref_id: str, user_id: str,
) -> None:
    """Raise FileShareError(403) if the user is not a member of the scope."""
    if scope_type == "direct":
        from app.models.messaging import DirectConversationParticipant
        row = db.query(DirectConversationParticipant).filter(
            DirectConversationParticipant.conversation_id == scope_ref_id,
            DirectConversationParticipant.user_id == user_id,
        ).first()
        if not row:
            raise FileShareError(
                "Not a participant in this conversation.", 403,
            )

    elif scope_type == "unit":
        from app.models.unit_offering import UnitOffering
        from app.models.academic import UnitMembership
        offering = db.query(UnitOffering).filter(
            UnitOffering.id == scope_ref_id,
        ).first()
        if not offering:
            raise FileShareError("Unit offering not found.", 404)
        row = db.query(UnitMembership).filter(
            UnitMembership.user_id == user_id,
            UnitMembership.unit_id == offering.unit_id,
            UnitMembership.semester_id == offering.semester_id,
            UnitMembership.status == "active",
        ).first()
        if not row:
            raise FileShareError("Not enrolled in this unit.", 403)

    elif scope_type == "community":
        from app.models.community import CommunityMembership
        row = db.query(CommunityMembership).filter(
            CommunityMembership.community_id == scope_ref_id,
            CommunityMembership.user_id == user_id,
            CommunityMembership.is_active.is_(True),
        ).first()
        if not row:
            raise FileShareError(
                "Not a member of this community.", 403,
            )

    else:
        raise FileShareError(f"Unknown scope_type '{scope_type}'.", 400)


# ============================================================================
# Create
# ============================================================================

def create_shared_file(
    db: Session, *,
    owner_id: str,
    scope_type: str,
    scope_ref_id: str,
    file_name: str,
    file_url: str,
    file_size_bytes: int,
    mime_type: str,
    description: str | None = None,
    parent_file_id: str | None = None,
    tags: list[str] | None = None,
) -> SharedFile:
    if scope_type not in VALID_SCOPE_TYPES:
        raise FileShareError(f"Invalid scope_type '{scope_type}'.", 400)

    _assert_scope_access(
        db, scope_type=scope_type,
        scope_ref_id=scope_ref_id, user_id=owner_id,
    )

    version = 1
    if parent_file_id:
        parent = db.query(SharedFile).filter(
            SharedFile.id == parent_file_id,
        ).first()
        if not parent:
            raise FileShareError("Parent file not found.", 404)
        if (parent.scope_type != scope_type
                or parent.scope_ref_id != scope_ref_id):
            raise FileShareError(
                "Version parent belongs to a different scope.", 400,
            )
        version = parent.version + 1

    file = SharedFile(
        owner_id=owner_id,
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        file_name=file_name,
        file_url=file_url,
        file_size_bytes=file_size_bytes,
        mime_type=mime_type,
        description=description,
        parent_file_id=parent_file_id,
        version=version,
        tags=tags,
        malware_scan_status="pending",
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    return file


# ============================================================================
# Read
# ============================================================================

def get_file(
    db: Session, *, file_id: str, viewer_id: str,
) -> SharedFile:
    f = db.query(SharedFile).filter(SharedFile.id == file_id).first()
    if not f:
        raise FileShareError("File not found.", 404)
    if f.is_deleted:
        raise FileShareError("File has been deleted.", 410)
    _assert_scope_access(
        db, scope_type=f.scope_type, scope_ref_id=f.scope_ref_id,
        user_id=viewer_id,
    )
    return f


def list_files_for_scope(
    db: Session, *,
    scope_type: str, scope_ref_id: str, viewer_id: str,
    include_deleted: bool = False,
    limit: int = 100, cursor: str | None = None,
) -> dict:
    _assert_scope_access(
        db, scope_type=scope_type, scope_ref_id=scope_ref_id,
        user_id=viewer_id,
    )
    q = db.query(SharedFile).filter(
        SharedFile.scope_type == scope_type,
        SharedFile.scope_ref_id == scope_ref_id,
        SharedFile.parent_file_id.is_(None),  # latest versions only
    )
    if not include_deleted:
        q = q.filter(SharedFile.is_deleted.is_(False))
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            q = q.filter(SharedFile.created_at < cursor_dt)
        except ValueError:
            raise FileShareError("Invalid cursor.", 400)

    rows = q.order_by(
        SharedFile.created_at.desc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        rows[-1].created_at.isoformat() if rows and has_more else None
    )
    return {
        "files": rows,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def list_versions(
    db: Session, *, file_id: str, viewer_id: str,
) -> list[SharedFile]:
    """Walk to root then down to latest, oldest → newest."""
    f = get_file(db, file_id=file_id, viewer_id=viewer_id)

    # Up to root
    root = f
    seen = {root.id}
    while root.parent_file_id:
        parent = db.query(SharedFile).filter(
            SharedFile.id == root.parent_file_id,
        ).first()
        if not parent or parent.id in seen:
            break
        root = parent
        seen.add(root.id)

    # Down to latest
    chain = [root]
    cursor = root
    while True:
        child = db.query(SharedFile).filter(
            SharedFile.parent_file_id == cursor.id,
        ).order_by(SharedFile.version).first()
        if not child:
            break
        chain.append(child)
        cursor = child
    return chain


# ============================================================================
# Update / delete
# ============================================================================

def update_file_metadata(
    db: Session, *, file_id: str, owner_id: str,
    description: str | None = None,
    tags: list[str] | None = None,
) -> SharedFile:
    f = db.query(SharedFile).filter(SharedFile.id == file_id).first()
    if not f:
        raise FileShareError("File not found.", 404)
    if f.owner_id != owner_id:
        raise FileShareError(
            "Only the owner may edit file metadata.", 403,
        )
    if description is not None:
        f.description = description
    if tags is not None:
        f.tags = tags
    db.commit()
    db.refresh(f)
    return f


def delete_file(
    db: Session, *, file_id: str, actor_id: str,
) -> SharedFile:
    f = db.query(SharedFile).filter(SharedFile.id == file_id).first()
    if not f:
        raise FileShareError("File not found.", 404)
    if f.owner_id != actor_id:
        raise FileShareError(
            "Only the owner may delete this file.", 403,
        )
    f.is_deleted = True
    f.deleted_at = _now()
    f.deleted_by = actor_id
    db.commit()
    db.refresh(f)
    return f


# ============================================================================
# Malware scan callback
# ============================================================================

def record_scan_result(
    db: Session, *, file_id: str,
    status: str, notes: str | None = None,
) -> SharedFile:
    f = db.query(SharedFile).filter(SharedFile.id == file_id).first()
    if not f:
        raise FileShareError("File not found.", 404)
    f.malware_scan_status = status
    f.malware_scan_notes = notes
    f.malware_scanned_at = _now()
    db.commit()
    db.refresh(f)
    return f