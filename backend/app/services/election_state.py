"""
Election state machine — Module 003 Phase 6.

Pure state constants and transition validation. No DB dependency so it
can be imported anywhere. The service layer (Wave 6.3) will use these
helpers to drive state changes with audit logging.
"""
from __future__ import annotations


# ============================================================================
# STATE CONSTANTS
# ============================================================================

DRAFT = "draft"
SCHEDULED = "scheduled"
NOMINATING = "nominating"
NOMINATIONAL_VOTING = "nominational_voting"
PAYMENT_WINDOW = "payment_window"
AWAITING_PAYMENT = "awaiting_payment"
REGIONAL_ADMIN_INTERIM = "regional_admin_interim"
BALLOT_FINALIZED = "ballot_finalized"
CAMPAIGNING = "campaigning"
VOTING = "voting"
COUNTING = "counting"
SUSPENSE_BLACKOUT = "suspense_blackout"
RESULT_DECLARED = "result_declared"
RUN_OFF_SCHEDULED = "run_off_scheduled"
RUN_OFF_VOTING = "run_off_voting"
APPEAL_WINDOW = "appeal_window"
APPEALED = "appealed"
DISPUTED = "disputed"
COMPLETED = "completed"


ALL_STATES: set[str] = {
    DRAFT, SCHEDULED, NOMINATING, NOMINATIONAL_VOTING,
    PAYMENT_WINDOW, AWAITING_PAYMENT, REGIONAL_ADMIN_INTERIM,
    BALLOT_FINALIZED, CAMPAIGNING, VOTING, COUNTING,
    SUSPENSE_BLACKOUT, RESULT_DECLARED, RUN_OFF_SCHEDULED,
    RUN_OFF_VOTING, APPEAL_WINDOW, APPEALED, DISPUTED, COMPLETED,
}


# ============================================================================
# VALID TRANSITIONS
# ============================================================================

# Group elections skip PAYMENT_WINDOW and AWAITING_PAYMENT because they
# have no nomination fee.
# School, Institution, County pass through PAYMENT_WINDOW.
# Institution and County pass through APPEAL_WINDOW on their way to
# COMPLETED.
# Run-offs at all levels resolve directly to COMPLETED (final).

VALID_TRANSITIONS: dict[str, set[str]] = {
    DRAFT: {SCHEDULED},

    SCHEDULED: {NOMINATING},

    NOMINATING: {NOMINATIONAL_VOTING},

    NOMINATIONAL_VOTING: {
        PAYMENT_WINDOW,      # levels with a fee
        BALLOT_FINALIZED,    # group elections skip payment
    },

    PAYMENT_WINDOW: {
        BALLOT_FINALIZED,    # some candidates paid
        AWAITING_PAYMENT,    # nobody paid
    },

    AWAITING_PAYMENT: {
        BALLOT_FINALIZED,         # some paid within the 30-day window
        REGIONAL_ADMIN_INTERIM,   # 30 days expired with no payer
    },

    REGIONAL_ADMIN_INTERIM: {
        BALLOT_FINALIZED,   # Super Admin assigned a candidate
        COMPLETED,          # Super Admin closed the position permanently
    },

    BALLOT_FINALIZED: {CAMPAIGNING},

    CAMPAIGNING: {VOTING},

    VOTING: {COUNTING},

    COUNTING: {SUSPENSE_BLACKOUT},

    SUSPENSE_BLACKOUT: {RESULT_DECLARED},

    RESULT_DECLARED: {
        RUN_OFF_SCHEDULED,   # tie detected
        APPEAL_WINDOW,       # institution / county non-tie
        COMPLETED,           # group / school non-tie, or appeals waived
    },

    RUN_OFF_SCHEDULED: {RUN_OFF_VOTING},

    RUN_OFF_VOTING: {COMPLETED},   # run-offs are final

    APPEAL_WINDOW: {
        APPEALED,    # an appeal was filed
        COMPLETED,   # window closed cleanly
    },

    APPEALED: {
        COMPLETED,   # appeal resolved
        # Overturned appeals may spawn a run-off via RUN_OFF_SCHEDULED
        # in a follow-up transition from COMPLETED handling — but that
        # is modelled by creating a new election, not by re-opening this one.
    },

    DISPUTED: {
        # A dispute is a parallel process; the election returns to
        # whatever state it was in. We keep a `disputed` marker for
        # visibility but the service layer must transition back via
        # `resolve_dispute_state`.
        RESULT_DECLARED,
        COMPLETED,
    },

    COMPLETED: set(),   # terminal
}


# ============================================================================
# VALIDATION
# ============================================================================

class InvalidStateTransition(Exception):
    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Cannot transition election from '{from_state}' to '{to_state}'."
        )


def can_transition(from_state: str, to_state: str) -> bool:
    if from_state not in VALID_TRANSITIONS:
        return False
    return to_state in VALID_TRANSITIONS[from_state]


def assert_transition(from_state: str, to_state: str) -> None:
    if not can_transition(from_state, to_state):
        raise InvalidStateTransition(from_state, to_state)


def next_states(state: str) -> set[str]:
    return set(VALID_TRANSITIONS.get(state, set()))


def is_terminal(state: str) -> bool:
    return state == COMPLETED


def is_voting_open(state: str) -> bool:
    return state == VOTING


def is_result_visible(state: str) -> bool:
    """
    The result is visible once it has been declared. Anything before
    RESULT_DECLARED is confidential.
    """
    return state in {RESULT_DECLARED, RUN_OFF_SCHEDULED, RUN_OFF_VOTING,
                     APPEAL_WINDOW, APPEALED, COMPLETED}


def is_appeal_phase(state: str) -> bool:
    return state in {APPEAL_WINDOW, APPEALED}