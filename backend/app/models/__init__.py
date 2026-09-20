from app.models.base import Base
from app.models.user import User
from app.models.role import Role, Permission, RolePermission, UserRole
from app.models.academic import (
    Region, County, Institution, School, Course, Unit,
    AcademicYear, Semester, StudentEnrollment, UnitMembership,
    AcademicStructureAudit,
    InstitutionTransition, InstitutionTransitionRequest,
)
from app.models.group import (
    Group, GroupMembership, GroupOfficial,
    GroupMeeting, GroupMeetingAttendee,
    GroupActivity, GroupAnnouncement,
    GroupTimetable, GroupTimetableEntry, GroupTimetableApproval,
)
from app.models.group_subscription import GroupSubscription
from app.models.group_unit import GroupUnit, GroupUnitConfirmation
from app.models.group_join_request import GroupJoinRequest

from app.models.auth_extension import (
    EmailVerification, PhoneVerification, PasswordReset, Session, BackupCode,
)
from app.models.auth_audit import AuthAuditLog
from app.models.two_factor import TwoFactorChallenge
from app.models.admin_action import AdminActionLog
from app.models.system_config import SystemConfig
from app.models.admin_invitation import AdminInvitation

from app.models.upload import (
    TimetableUpload, UploadFile, UploadScannedPage, ExtractedUnit,
)

# Module 001 completeness
from app.models.external_profile import ExternalProfile
from app.models.notification_preference import NotificationPreference

# Module 002 completion
from app.models.combination import Combination
from app.models.unit_offering import UnitOffering
from app.models.unit_proposal import (
    UnitProposal, UnitProposalItem, UnitProposalEvent,
)
from app.models.registration_verification import (
    InstitutionVerificationPeriod,
    InstitutionRegistrationNumber,
)

# Module 003 Phase 6 — Elections
from app.models.election import (
    Election,
    ElectionPosition,
    ElectionTicket,
    ElectionCandidate,
    ElectionVoterRoll,
    ElectionApprovalVote,
    ElectionBallot,
    ElectionResult,
    ElectionDispute,
    ElectionAppeal,
    ElectionReschedule,
    ElectionNoPayerEvent,
    ElectionAuditEvent,
)


__all__ = [
    "Base", "User",
    "Role", "Permission", "RolePermission", "UserRole",
    "Region", "County", "Institution", "School", "Course", "Unit",
    "AcademicYear", "Semester", "StudentEnrollment", "UnitMembership",
    "AcademicStructureAudit",
    "InstitutionTransition", "InstitutionTransitionRequest",
    "Group", "GroupMembership", "GroupOfficial",
    "GroupMeeting", "GroupMeetingAttendee",
    "GroupActivity", "GroupAnnouncement",
    "GroupTimetable", "GroupTimetableEntry", "GroupTimetableApproval",
    "GroupSubscription",
    "GroupUnit", "GroupUnitConfirmation",
    "GroupJoinRequest",
    "EmailVerification", "PhoneVerification", "PasswordReset", "Session", "BackupCode",
    "AuthAuditLog", "TwoFactorChallenge",
    "AdminActionLog", "SystemConfig", "AdminInvitation",
    "TimetableUpload", "UploadFile", "UploadScannedPage", "ExtractedUnit",
    "ExternalProfile", "NotificationPreference",
    "Combination",
    "UnitOffering",
    "UnitProposal", "UnitProposalItem", "UnitProposalEvent",
    "InstitutionVerificationPeriod", "InstitutionRegistrationNumber",
    # Module 003 Phase 6
    "Election",
    "ElectionPosition",
    "ElectionTicket",
    "ElectionCandidate",
    "ElectionVoterRoll",
    "ElectionApprovalVote",
    "ElectionBallot",
    "ElectionResult",
    "ElectionDispute",
    "ElectionAppeal",
    "ElectionReschedule",
    "ElectionNoPayerEvent",
    "ElectionAuditEvent",
]