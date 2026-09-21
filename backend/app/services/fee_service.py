"""
Fee service — Module 012.

Domain-specific orchestrators for one-time fees. Each function wraps
transaction_service.initiate_transaction() with the right type, amount,
and related object.

Downstream modules call these, then listen for the payment-succeeded
event to complete their state changes.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.financial import (
    FEE_AMOUNTS,
    TXN_NOMINATION_SCHOOL, TXN_NOMINATION_INSTITUTION, TXN_NOMINATION_COUNTY,
    TXN_CLUB_ELECTION_FEE, TXN_CLUB_PROMOTION_FEE,
    TXN_EVENT_AD_PUBLIC, TXN_EVENT_AD_COUNTY, TXN_EVENT_AD_NATIONAL,
    TXN_TRANSFER_ORDINARY, TXN_TRANSFER_ELECTED,
    TXN_GROUP_TO_SOLO_EXIT, TXN_GROUP_LEADER_VACANCY,
)
from app.services.transaction_service import (
    initiate_transaction, TransactionError,
)


logger = logging.getLogger(__name__)


class FeeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# NOMINATION FEES
# ─────────────────────────────────────────────────────────────────────────

def initiate_nomination_fee(
    db: Session, *, candidate_id: str, level: str, provider_name: str,
    payer_user_id: str,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    type_map = {
        "school": TXN_NOMINATION_SCHOOL,
        "institution": TXN_NOMINATION_INSTITUTION,
        "county": TXN_NOMINATION_COUNTY,
    }
    if level not in type_map:
        raise FeeError(f"Unknown nomination level '{level}'.", 400)
    txn_type = type_map[level]
    return initiate_transaction(
        db,
        transaction_type=txn_type,
        amount=FEE_AMOUNTS[txn_type],
        provider_name=provider_name,
        payer_user_id=payer_user_id,
        related_object_type="election_candidate",
        related_object_id=candidate_id,
        description=f"Nomination fee — {level} representative",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip, ua=ua,
    )


# ─────────────────────────────────────────────────────────────────────────
# CLUB FEES
# ─────────────────────────────────────────────────────────────────────────

def initiate_club_election_fee(
    db: Session, *, cycle_id: str, provider_name: str,
    payer_user_id: str,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    return initiate_transaction(
        db,
        transaction_type=TXN_CLUB_ELECTION_FEE,
        amount=FEE_AMOUNTS[TXN_CLUB_ELECTION_FEE],
        provider_name=provider_name,
        payer_user_id=payer_user_id,
        related_object_type="club_election_cycle",
        related_object_id=cycle_id,
        description="Club election cycle fee",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip, ua=ua,
    )


def initiate_club_promotion_fee(
    db: Session, *, club_id: str, provider_name: str,
    payer_user_id: str,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    return initiate_transaction(
        db,
        transaction_type=TXN_CLUB_PROMOTION_FEE,
        amount=FEE_AMOUNTS[TXN_CLUB_PROMOTION_FEE],
        provider_name=provider_name,
        payer_user_id=payer_user_id,
        related_object_type="activity_club",
        related_object_id=club_id,
        description="Club county promotion fee",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip, ua=ua,
    )


# ─────────────────────────────────────────────────────────────────────────
# EVENT ADVERTISING
# ─────────────────────────────────────────────────────────────────────────

def initiate_event_advertisement(
    db: Session, *, event_id: str, scope: str, provider_name: str,
    payer_user_id: str,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    type_map = {
        "public": TXN_EVENT_AD_PUBLIC,
        "county": TXN_EVENT_AD_COUNTY,
        "national": TXN_EVENT_AD_NATIONAL,
    }
    if scope not in type_map:
        raise FeeError(f"Unknown event scope '{scope}'.", 400)
    txn_type = type_map[scope]
    return initiate_transaction(
        db,
        transaction_type=txn_type,
        amount=FEE_AMOUNTS[txn_type],
        provider_name=provider_name,
        payer_user_id=payer_user_id,
        related_object_type="event",
        related_object_id=event_id,
        description=f"Event advertising — {scope} scope, monthly",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip, ua=ua,
    )


# ─────────────────────────────────────────────────────────────────────────
# TRANSFERS
# ─────────────────────────────────────────────────────────────────────────

def initiate_transfer_fee(
    db: Session, *, transfer_id: str, transfer_type: str, provider_name: str,
    payer_user_id: str,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    if transfer_type not in ("ordinary", "elected"):
        raise FeeError("transfer_type must be 'ordinary' or 'elected'.", 400)
    txn_type = (
        TXN_TRANSFER_ELECTED if transfer_type == "elected"
        else TXN_TRANSFER_ORDINARY
    )
    return initiate_transaction(
        db,
        transaction_type=txn_type,
        amount=FEE_AMOUNTS[txn_type],
        provider_name=provider_name,
        payer_user_id=payer_user_id,
        related_object_type="group_transfer",
        related_object_id=transfer_id,
        description=f"Inter-group transfer — {transfer_type}",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip, ua=ua,
    )


# ─────────────────────────────────────────────────────────────────────────
# GROUP → SOLO EXIT
# ─────────────────────────────────────────────────────────────────────────

def initiate_group_to_solo_exit(
    db: Session, *, user_id: str, provider_name: str,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    return initiate_transaction(
        db,
        transaction_type=TXN_GROUP_TO_SOLO_EXIT,
        amount=FEE_AMOUNTS[TXN_GROUP_TO_SOLO_EXIT],
        provider_name=provider_name,
        payer_user_id=user_id,
        related_object_type="user",
        related_object_id=user_id,
        description="Group → solo exit fee",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip, ua=ua,
    )


# ─────────────────────────────────────────────────────────────────────────
# GROUP LEADER VACANCY (advancing to higher office)
# ─────────────────────────────────────────────────────────────────────────

def initiate_group_leader_vacancy(
    db: Session, *, group_id: str, user_id: str, provider_name: str,
    payer_phone: str | None = None,
    payer_email: str | None = None,
    ip: str | None = None, ua: str | None = None,
):
    return initiate_transaction(
        db,
        transaction_type=TXN_GROUP_LEADER_VACANCY,
        amount=FEE_AMOUNTS[TXN_GROUP_LEADER_VACANCY],
        provider_name=provider_name,
        payer_user_id=user_id,
        related_object_type="group",
        related_object_id=group_id,
        description="Group Leader vacancy fee — advancing to higher office",
        payer_phone=payer_phone,
        payer_email=payer_email,
        ip=ip, ua=ua,
    )


# ─────────────────────────────────────────────────────────────────────────
# PAYMENT SUCCESS DISPATCHER
# ─────────────────────────────────────────────────────────────────────────

def handle_payment_success(
    db: Session, transaction_id: str, reference: str,
) -> None:
    """
    Called by the webhook handler after a transaction is marked successful.
    Routes to the downstream domain service based on transaction type.

    Each branch either directly mutates the downstream model, or emits an
    internal event that the downstream service consumes.

    This is deliberately a big switch — it is the single integration point
    between Financial and every other module.
    """
    from app.models.financial import Transaction
    from app.models.financial import (
        TXN_GROUP_SUBSCRIPTION, TXN_GROUP_SUBSCRIPTION_ANNUAL,
        TXN_SOLO_SUBSCRIPTION, TXN_SOLO_SUBSCRIPTION_ANNUAL,
    )
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        return

    t = txn.transaction_type

    try:
        if t in (TXN_GROUP_SUBSCRIPTION, TXN_GROUP_SUBSCRIPTION_ANNUAL,
                 TXN_SOLO_SUBSCRIPTION, TXN_SOLO_SUBSCRIPTION_ANNUAL):
            _handle_subscription_success(db, txn)

        elif t in (TXN_NOMINATION_SCHOOL, TXN_NOMINATION_INSTITUTION,
                   TXN_NOMINATION_COUNTY):
            _handle_nomination_success(db, txn)

        elif t == TXN_CLUB_ELECTION_FEE:
            _handle_club_election_fee(db, txn)

        elif t == TXN_CLUB_PROMOTION_FEE:
            _handle_club_promotion_fee(db, txn)

        elif t in (TXN_EVENT_AD_PUBLIC, TXN_EVENT_AD_COUNTY, TXN_EVENT_AD_NATIONAL):
            _handle_event_ad_success(db, txn)

        elif t in (TXN_TRANSFER_ORDINARY, TXN_TRANSFER_ELECTED):
            _handle_transfer_success(db, txn)

        elif t == TXN_GROUP_TO_SOLO_EXIT:
            _handle_group_exit_success(db, txn)

        elif t == TXN_GROUP_LEADER_VACANCY:
            _handle_vacancy_success(db, txn)

        else:
            logger.warning("[fees] unhandled payment type '%s'", t)
    except Exception:
        logger.exception("[fees] downstream handler failed for %s", reference)


# ── downstream handlers (lightweight, idempotent) ────────────────────────

def _handle_subscription_success(db: Session, txn) -> None:
    from app.services.subscription_service import activate_subscription
    if txn.related_object_id:
        activate_subscription(db, txn.related_object_id, txn.id)


def _handle_nomination_success(db: Session, txn) -> None:
    from app.models.election import ElectionCandidate
    c = db.query(ElectionCandidate).filter(
        ElectionCandidate.id == txn.related_object_id,
    ).first()
    if c and not c.fee_paid:
        c.fee_paid = True
        c.fee_payment_reference = txn.provider_reference or txn.reference
        c.fee_paid_at = txn.paid_at
        c.status = "qualified"
        db.commit()


def _handle_club_election_fee(db: Session, txn) -> None:
    from app.models.activity_club import ActivityClubElectionCycle
    cycle = db.query(ActivityClubElectionCycle).filter(
        ActivityClubElectionCycle.id == txn.related_object_id,
    ).first()
    if cycle and not cycle.election_fee_paid:
        cycle.election_fee_paid = True
        cycle.election_fee_reference = txn.provider_reference or txn.reference
        cycle.election_fee_paid_at = txn.paid_at
        cycle.election_fee_method = txn.provider
        cycle.status = "positions_published"
        db.commit()


def _handle_club_promotion_fee(db: Session, txn) -> None:
    from app.models.activity_club import ActivityClub
    club = db.query(ActivityClub).filter(
        ActivityClub.id == txn.related_object_id,
    ).first()
    if club and club.current_level != "county":
        club.current_level = "county"
        club.promoted_to_county_at = txn.paid_at
        db.commit()


def _handle_event_ad_success(db: Session, txn) -> None:
    from app.models.financial import (
        EventAdvertisement, EVENT_AD_ACTIVE, EVENT_AD_PENDING,
    )
    from datetime import timedelta
    ad = db.query(EventAdvertisement).filter(
        EventAdvertisement.event_id == txn.related_object_id,
    ).order_by(EventAdvertisement.created_at.desc()).first()
    if not ad:
        # Create the ad record lazily
        ad = EventAdvertisement(
            event_id=txn.related_object_id,
            scope=_scope_from_type(txn.transaction_type),
            monthly_fee=txn.amount,
            currency=txn.currency,
            initial_transaction_id=txn.id,
            starts_at=txn.paid_at,
            current_period_start=txn.paid_at,
            current_period_end=txn.paid_at + timedelta(days=30),
            status=EVENT_AD_ACTIVE,
        )
        db.add(ad)
    else:
        ad.status = EVENT_AD_ACTIVE
        ad.last_renewal_transaction_id = txn.id
        ad.current_period_start = txn.paid_at
        ad.current_period_end = txn.paid_at + timedelta(days=30)
    db.commit()


def _handle_transfer_success(db: Session, txn) -> None:
    from app.models.group_transfer import GroupTransfer
    t = db.query(GroupTransfer).filter(
        GroupTransfer.id == txn.related_object_id,
    ).first()
    if t and not t.fee_paid:
        t.fee_paid = True
        t.payment_reference = txn.provider_reference or txn.reference
        t.fee_paid_at = txn.paid_at
        db.commit()


def _handle_group_exit_success(db: Session, txn) -> None:
    # Nothing to change here — the Module 003 solo service polls the
    # transaction when the user confirms exit.
    logger.info("[fees] group-to-solo exit paid for user %s", txn.payer_user_id)


def _handle_vacancy_success(db: Session, txn) -> None:
    logger.info("[fees] group leader vacancy paid for group %s",
                txn.related_object_id)


def _scope_from_type(txn_type: str) -> str:
    from app.models.financial import (
        TXN_EVENT_AD_PUBLIC, TXN_EVENT_AD_COUNTY, TXN_EVENT_AD_NATIONAL,
    )
    return {
        TXN_EVENT_AD_PUBLIC: "public",
        TXN_EVENT_AD_COUNTY: "county",
        TXN_EVENT_AD_NATIONAL: "national",
    }.get(txn_type, "public")