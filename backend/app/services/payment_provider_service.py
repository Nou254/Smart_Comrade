"""
Payment provider abstraction — Module 012.

Defines the PaymentProvider interface that every provider must implement.
Ships with stub implementations for M-Pesa, card, bank, and manual.

To integrate a real provider:
  1. Subclass PaymentProvider
  2. Implement initiate_charge / verify_webhook / parse_webhook / refund
  3. Register it in get_provider()

Business logic never talks to a provider SDK directly — it always goes
through this interface.
"""
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from typing import Protocol

from app.models.financial import (
    PROVIDER_MPESA, PROVIDER_CARD, PROVIDER_BANK, PROVIDER_MANUAL,
    ALL_PROVIDERS,
)


logger = logging.getLogger(__name__)


# ── exceptions ───────────────────────────────────────────────────────────

class PaymentProviderError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ── result types ─────────────────────────────────────────────────────────

@dataclass
class ChargeInitiation:
    """Returned by provider.initiate_charge() — tells the client what to do next."""
    provider_reference: str
    client_action_required: bool       # true if user must do something (enter PIN, 3DS)
    client_instructions: str | None    # e.g. "Enter your M-Pesa PIN to complete"
    checkout_url: str | None = None    # for redirect flows


@dataclass
class WebhookEvent:
    """Parsed webhook from a provider."""
    reference: str                     # platform reference (idempotency key)
    provider_reference: str
    status: str                        # successful | failed | pending
    amount: int
    currency: str
    raw_payload: dict


@dataclass
class RefundResult:
    provider_refund_reference: str
    status: str                        # processing | completed | failed
    message: str | None = None


# ── provider protocol ────────────────────────────────────────────────────

class PaymentProvider(Protocol):
    name: str

    def initiate_charge(
        self,
        *,
        amount: int,
        currency: str,
        reference: str,
        payer_phone: str | None,
        payer_email: str | None,
        description: str,
        callback_url: str,
    ) -> ChargeInitiation: ...

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool: ...

    def parse_webhook(self, raw_body: bytes) -> WebhookEvent: ...

    def refund(
        self,
        *,
        provider_reference: str,
        amount: int,
        reason: str,
    ) -> RefundResult: ...


# ── stub implementations ─────────────────────────────────────────────────

class _StubProvider:
    """
    Base stub. Simulates a charge initiation and webhook signing without
    talking to any external API.
    """
    name: str = "stub"
    webhook_secret: str = "dev_stub_secret"

    def initiate_charge(
        self, *, amount, currency, reference, payer_phone, payer_email,
        description, callback_url,
    ) -> ChargeInitiation:
        provider_ref = f"{self.name.upper()}-{secrets.token_hex(6).upper()}"
        logger.info(
            "[stub.%s] initiate_charge ref=%s amount=%s %s",
            self.name, reference, amount, currency,
        )
        return ChargeInitiation(
            provider_reference=provider_ref,
            client_action_required=True,
            client_instructions=(
                f"Enter your {self.name.upper()} confirmation to complete "
                f"the payment of {amount} {currency}."
            ),
            checkout_url=None,
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        """
        Stub signature verification. Real providers use HMAC over a
        secret; we simulate with a shared string check.
        """
        signature = headers.get("x-signature") or headers.get("X-Signature")
        if not signature:
            # Dev mode: accept unsigned webhooks
            return True
        expected = hmac.new(
            self.webhook_secret.encode(), raw_body, hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def parse_webhook(self, raw_body: bytes) -> WebhookEvent:
        import json
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as e:
            raise PaymentProviderError(f"Invalid webhook payload: {e}", 400)

        return WebhookEvent(
            reference=payload.get("reference", ""),
            provider_reference=payload.get("provider_reference", ""),
            status=payload.get("status", "pending"),
            amount=int(payload.get("amount", 0)),
            currency=payload.get("currency", "KES"),
            raw_payload=payload,
        )

    def refund(
        self, *, provider_reference, amount, reason,
    ) -> RefundResult:
        logger.info(
            "[stub.%s] refund provider_ref=%s amount=%s",
            self.name, provider_reference, amount,
        )
        return RefundResult(
            provider_refund_reference=f"RF-{secrets.token_hex(6).upper()}",
            status="processing",
            message="Refund accepted by stub provider.",
        )


class MpesaProvider(_StubProvider):
    name = PROVIDER_MPESA


class CardProvider(_StubProvider):
    name = PROVIDER_CARD


class BankProvider(_StubProvider):
    name = PROVIDER_BANK


class ManualProvider(_StubProvider):
    name = PROVIDER_MANUAL

    def initiate_charge(
        self, *, amount, currency, reference, payer_phone, payer_email,
        description, callback_url,
    ) -> ChargeInitiation:
        # Manual means an admin records the payment out-of-band
        return ChargeInitiation(
            provider_reference=f"MANUAL-{reference}",
            client_action_required=False,
            client_instructions=(
                "This payment is recorded manually by an administrator."
            ),
            checkout_url=None,
        )


# ── factory ──────────────────────────────────────────────────────────────

_PROVIDER_REGISTRY: dict[str, PaymentProvider] = {
    PROVIDER_MPESA: MpesaProvider(),
    PROVIDER_CARD: CardProvider(),
    PROVIDER_BANK: BankProvider(),
    PROVIDER_MANUAL: ManualProvider(),
}


def get_provider(name: str) -> PaymentProvider:
    if name not in _PROVIDER_REGISTRY:
        raise PaymentProviderError(
            f"Unknown provider '{name}'. Available: {sorted(_PROVIDER_REGISTRY)}",
            400,
        )
    return _PROVIDER_REGISTRY[name]


def register_provider(name: str, provider: PaymentProvider) -> None:
    """Called at app boot to plug real providers in."""
    if name not in ALL_PROVIDERS:
        raise PaymentProviderError(
            f"Provider name '{name}' is not a recognised slot.", 400,
        )
    _PROVIDER_REGISTRY[name] = provider
    logger.info("[provider] registered %s → %s", name, type(provider).__name__)


# ── helpers ──────────────────────────────────────────────────────────────

def generate_platform_reference() -> str:
    """Generate a unique, high-entropy platform reference for a transaction."""
    return f"SC-{secrets.token_hex(16)}"