"""
Pydantic schemas for election cascade triggers — Module 003 Phase 7.
"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ElectionTriggerEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    level: str
    constituency_id: str
    triggered_at: datetime
    reason: str
    status: str
    election_id: str | None
    blocked_by_election_id: str | None
    notes: str | None
    created_at: datetime


class CascadeCheckResponse(BaseModel):
    """
    Result of checking whether a level's threshold has been met.
    Returned by the manual-check endpoints.
    """
    level: str
    constituency_id: str
    threshold_met: bool
    current_count: int
    required_count: int
    compliant_children: list[dict]
    blockers: list[str]
    election_id: str | None
    message: str