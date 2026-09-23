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
# Module 012 — Financial
from app.models.financial import (
    Subscription, Transaction, Invoice, Receipt, RefundRequest,
    EventAdvertisement, ReconciliationBatch, FinancialAuditLog,
    FinancialNotification,
)
# Module 003 Phase 10 — Activity Clubs
from app.models.activity_club import (
    ActivityClub, ActivityClubMembership,
    ActivityClubPosition, ActivityClubMilestone,
    ActivityClubMilestoneReport,
    ActivityClubElectionCycle, ActivityClubElectionCandidate,
    ActivityClubElectionVote,
    ActivityClubPositionApprovalVote, ActivityClubPositionApprovalBallot,
    ActivityClubDissolutionEvent, ActivityClubRevivalPetition,
    ActivityClubApprovalEvent,
)
# Module 003 Phase 9 — Impeachment
from app.models.impeachment import (
    ImpeachmentCase, ImpeachmentPetition,
    ImpeachmentSession, ImpeachmentVote,
)
# Module 004 — Unit Representation
from app.models.unit_representation import (
    UnitRepresentative,
    UnitNetwork,
    UnitNetworkMember,
    UnitCoordinationMessage,
    UnitDiscussion,
    UnitAnnouncement,
    UnitIssue,
    UnitIssueEscalation,
    UnitQuestion,
    UnitQuestionResponse,
    UnitSharedResource,
)
# Module 005 — Assessment
from app.models.assessment import (
    Assessment,
    QuestionBank,
    Question,
    Attempt,
    Response as AssessmentResponseModel,
    Submission,
    Result,
    Feedback,
    Appeal,
    AssessmentAuditLog,
    AssessmentAudienceSnapshot,
    AssessmentCatalogEntry,
    AIAssistanceLog,
)
from app.models.group_subscription import GroupSubscription
from app.models.group_unit import GroupUnit, GroupUnitConfirmation
from app.models.group_join_request import GroupJoinRequest
from app.models.solo_learner import SoloSubscription, SoloLearningSession

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
    Election, ElectionPosition, ElectionTicket, ElectionCandidate,
    ElectionVoterRoll, ElectionApprovalVote, ElectionBallot,
    ElectionResult, ElectionDispute, ElectionAppeal, ElectionReschedule,
    ElectionNoPayerEvent, ElectionAuditEvent,
)

# Module 003 Phase 7 — Cascade trigger events
from app.models.election_trigger_event import ElectionTriggerEvent

# Module 003 Phase 8 — Transfers
from app.models.group_transfer import GroupTransfer

# Module 003 Phase 11 — Communities
from app.models.community import (
    Community, CommunityMembership, CommunityMessage,
    CommunityMessageReport, CommunityModerationAction,
)

# ============================================================================
# Communication module — new
# ============================================================================
from app.models.messaging import (
    ConversationRequest,
    DirectConversation,
    DirectConversationParticipant,
    DirectMessage,
    UserBlock,
)
from app.models.announcement import (
    OfficialAnnouncement,
    OfficialAnnouncementAudience,
)
from app.models.notification import Notification
from app.models.file_share import SharedFile
from app.models.forum import (
    Forum,
    ForumApprovalRequest,
    ForumJoin,
    ForumTopic,
    ForumReply,
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
    "GroupSubscription", "GroupUnit", "GroupUnitConfirmation",
    "GroupJoinRequest",
    "EmailVerification", "PhoneVerification", "PasswordReset", "Session", "BackupCode",
    "AuthAuditLog", "TwoFactorChallenge",
    "AdminActionLog", "SystemConfig", "AdminInvitation",
    "TimetableUpload", "UploadFile", "UploadScannedPage", "ExtractedUnit",
    "ExternalProfile", "NotificationPreference",
    "Combination", "UnitOffering",
    "UnitProposal", "UnitProposalItem", "UnitProposalEvent",
    "InstitutionVerificationPeriod", "InstitutionRegistrationNumber",
    # Phase 6
    "Election", "ElectionPosition", "ElectionTicket", "ElectionCandidate",
    "ElectionVoterRoll", "ElectionApprovalVote", "ElectionBallot",
    "ElectionResult", "ElectionDispute", "ElectionAppeal",
    "ElectionReschedule", "ElectionNoPayerEvent", "ElectionAuditEvent",
    # Phase 7
    "ElectionTriggerEvent",
    # Phase 8
    "GroupTransfer",
    "ImpeachmentCase", "ImpeachmentPetition",
    "ImpeachmentSession", "ImpeachmentVote",
    # Phase 11
    "Community", "CommunityMembership", "CommunityMessage",
    "CommunityMessageReport", "CommunityModerationAction",
    "SoloSubscription", "SoloLearningSession",
    # Phase 10
    "ActivityClub", "ActivityClubMembership",
    "ActivityClubPosition", "ActivityClubMilestone",
    "ActivityClubMilestoneReport",
    "ActivityClubElectionCycle", "ActivityClubElectionCandidate",
    "ActivityClubElectionVote",
    "ActivityClubPositionApprovalVote", "ActivityClubPositionApprovalBallot",
    "ActivityClubDissolutionEvent", "ActivityClubRevivalPetition",
    "ActivityClubApprovalEvent",
    # Module 012
    "Subscription", "Transaction", "Invoice", "Receipt", "RefundRequest",
    "EventAdvertisement", "ReconciliationBatch", "FinancialAuditLog",
    "FinancialNotification",
    # Module 004
    "UnitRepresentative", "UnitNetwork", "UnitNetworkMember",
    "UnitCoordinationMessage", "UnitDiscussion", "UnitAnnouncement",
    "UnitIssue", "UnitIssueEscalation",
    "UnitQuestion", "UnitQuestionResponse", "UnitSharedResource",
    # Module 005
    "Assessment", "QuestionBank", "Question", "Attempt",
    "AssessmentResponseModel", "Submission", "Result", "Feedback",
    "Appeal", "AssessmentAuditLog", "AssessmentAudienceSnapshot",
    "AssessmentCatalogEntry", "AIAssistanceLog",
    # Communication module
    "ConversationRequest", "DirectConversation",
    "DirectConversationParticipant", "DirectMessage", "UserBlock",
    "OfficialAnnouncement", "OfficialAnnouncementAudience",
    "Notification",
    "SharedFile",
    "Forum", "ForumApprovalRequest", "ForumJoin",
    "ForumTopic", "ForumReply",
]