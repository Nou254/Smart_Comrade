"""
Payment provider abstraction — Module 012.

Defines the PaymentProvider interface that every provider must implement,
plus working HTTP integrations for M-Pesa (Safaricom Daraja), card and
bank gateways, and manual/offline recording.

Credentials are read from settings; a provider that is missing them
raises PaymentProviderError(503) at call time rather than at import time,
so the app still boots without payment credentials.

To integrate a different provider:
  1. Implement initiate_charge / verify_webhook / parse_webhook / refund
     / verify_payment / transaction_list
  2. Register it in get_provider()

Business logic never talks to a provider SDK directly — it always goes
through this interface.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx

from app.core.config import settings
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


@dataclass
class ProviderTransaction:
    """One transaction as reported by a provider's own ledger."""
    provider_reference: str
    reference: str | None = None       # platform reference, if echoed back
    status: str = "unknown"            # successful | failed | pending
    amount: int = 0
    currency: str = "KES"
    raw_payload: dict | None = None


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

    def verify_payment(
        self,
        *,
        reference: str,
        amount: int | None = None,
        provider_reference: str | None = None,
    ) -> bool: ...

    def transaction_list(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> list[ProviderTransaction]: ...


# ── shared helpers ───────────────────────────────────────────────────────

def _nairobi_timestamp() -> str:
    """Daraja expects an EAT (UTC+3) `YYYYMMDDHHmmss` timestamp."""
    return datetime.now(timezone(timedelta(hours=3))).strftime("%Y%m%d%H%M%S")


def _normalize_msisdn(phone: str) -> str:
    """Normalise a Kenyan phone number to the 254XXXXXXXXX form Daraja wants."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if digits.startswith("0"):
        return "254" + digits[1:]
    if digits.startswith(("7", "1")):
        return "254" + digits
    return digits


def _decode_json(raw_body: bytes) -> dict:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise PaymentProviderError(f"Invalid webhook payload: {e}", 400)
    if not isinstance(payload, dict):
        raise PaymentProviderError("Webhook payload must be a JSON object.", 400)
    return payload


def _json_or_error(resp: httpx.Response, label: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise PaymentProviderError(f"{label} returned a non-JSON response.", 502)
    if resp.status_code >= 400:
        message = (
            data.get("errorMessage")
            or data.get("ResponseDescription")
            or resp.text[:200]
        )
        raise PaymentProviderError(
            f"{label} failed ({resp.status_code}): {message}", 502,
        )
    return data if isinstance(data, dict) else {"data": data}


def _hmac_ok(secret: str, raw_body: bytes, headers: dict) -> bool:
    """
    Verify an `X-Signature` HMAC-SHA256 over the raw body. Unsigned
    webhooks are accepted only in DEBUG (local development).
    """
    signature = headers.get("x-signature") or headers.get("X-Signature")
    if not signature:
        return bool(settings.DEBUG)
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


# ── M-Pesa (Safaricom Daraja) ────────────────────────────────────────────

class MpesaProvider:
    """Safaricom Daraja (M-Pesa) provider — STK push + status query."""

    name = PROVIDER_MPESA

    _SANDBOX = "https://sandbox.safaricom.co.ke"
    _PRODUCTION = "https://api.safaricom.co.ke"

    @property
    def webhook_secret(self) -> str:
        return settings.PAYMENT_WEBHOOK_SECRET

    def _base_url(self) -> str:
        if (settings.MPESA_ENVIRONMENT or "").lower() == "production":
            return self._PRODUCTION
        return self._SANDBOX

    def _require_credentials(self) -> None:
        required = {
            "MPESA_CONSUMER_KEY": settings.MPESA_CONSUMER_KEY,
            "MPESA_CONSUMER_SECRET": settings.MPESA_CONSUMER_SECRET,
            "MPESA_SHORTCODE": settings.MPESA_SHORTCODE,
            "MPESA_PASSKEY": settings.MPESA_PASSKEY,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise PaymentProviderError(
                "M-Pesa is not configured. Missing: " + ", ".join(missing) + ".",
                503,
            )

    def _access_token(self) -> str:
        self._require_credentials()
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(
                    f"{self._base_url()}/oauth/v1/generate",
                    params={"grant_type": "client_credentials"},
                    auth=(
                        settings.MPESA_CONSUMER_KEY,
                        settings.MPESA_CONSUMER_SECRET,
                    ),
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(f"M-Pesa auth request failed: {e}", 502)
        data = _json_or_error(resp, "M-Pesa auth")
        token = data.get("access_token")
        if not token:
            raise PaymentProviderError("M-Pesa auth returned no access token.", 502)
        return token

    def _password(self, timestamp: str) -> str:
        raw = f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}"
        return base64.b64encode(raw.encode()).decode()

    def initiate_charge(
        self, *, amount, currency, reference, payer_phone, payer_email,
        description, callback_url,
    ) -> ChargeInitiation:
        self._require_credentials()
        if not payer_phone:
            raise PaymentProviderError(
                "M-Pesa requires the payer's phone number.", 400,
            )
        callback = callback_url or settings.MPESA_CALLBACK_URL
        if not callback:
            raise PaymentProviderError("MPESA_CALLBACK_URL is not configured.", 503)

        token = self._access_token()
        timestamp = _nairobi_timestamp()
        msisdn = _normalize_msisdn(payer_phone)
        payload = {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "TransactionType": settings.MPESA_TRANSACTION_TYPE,
            "Amount": int(amount),
            "PartyA": msisdn,
            "PartyB": settings.MPESA_SHORTCODE,
            "PhoneNumber": msisdn,
            "CallBackURL": callback,
            "AccountReference": reference[:12],
            "TransactionDesc": (description or "Payment")[:60],
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{self._base_url()}/mpesa/stkpush/v1/processrequest",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(f"M-Pesa STK push failed: {e}", 502)

        data = _json_or_error(resp, "M-Pesa STK push")
        checkout_id = data.get("CheckoutRequestID")
        if str(data.get("ResponseCode")) != "0" or not checkout_id:
            raise PaymentProviderError(
                data.get("ResponseDescription")
                or data.get("errorMessage")
                or "M-Pesa rejected the STK push.",
                502,
            )
        return ChargeInitiation(
            provider_reference=str(checkout_id),
            client_action_required=True,
            client_instructions=(
                f"Enter your M-Pesa PIN on {msisdn} to complete the payment "
                f"of {amount} {currency}."
            ),
            checkout_url=None,
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        # Daraja does not sign callbacks. Accept only an explicit shared
        # secret header, or unsigned callbacks in DEBUG.
        secret = (
            headers.get("x-callback-secret")
            or headers.get("X-Callback-Secret")
        )
        if secret:
            return hmac.compare_digest(secret, settings.PAYMENT_WEBHOOK_SECRET)
        return bool(settings.DEBUG)

    def parse_webhook(self, raw_body: bytes) -> WebhookEvent:
        payload = _decode_json(raw_body)
        cb = (payload.get("Body") or {}).get("stkCallback") or payload
        items = ((cb.get("CallbackMetadata") or {}).get("Item")) or []
        meta = {
            item.get("Name"): item.get("Value")
            for item in items
            if isinstance(item, dict)
        }
        status = "successful" if str(cb.get("ResultCode")) == "0" else "failed"
        return WebhookEvent(
            reference=str(
                cb.get("AccountReference") or payload.get("reference") or ""
            ),
            provider_reference=str(cb.get("CheckoutRequestID") or ""),
            status=status,
            amount=int(meta.get("Amount") or payload.get("amount") or 0),
            currency=str(payload.get("currency") or "KES"),
            raw_payload=payload,
        )

    def refund(
        self, *, provider_reference, amount, reason,
    ) -> RefundResult:
        if not settings.MPESA_INITIATOR_NAME or not settings.MPESA_SECURITY_CREDENTIAL:
            raise PaymentProviderError(
                "M-Pesa refunds require MPESA_INITIATOR_NAME and "
                "MPESA_SECURITY_CREDENTIAL.",
                503,
            )
        result_url = settings.MPESA_CALLBACK_URL
        if not result_url:
            raise PaymentProviderError("MPESA_CALLBACK_URL is not configured.", 503)
        token = self._access_token()
        payload = {
            "Initiator": settings.MPESA_INITIATOR_NAME,
            "SecurityCredential": settings.MPESA_SECURITY_CREDENTIAL,
            "CommandID": "TransactionReversal",
            "TransactionID": provider_reference,
            "Amount": int(amount),
            "ReceiverParty": settings.MPESA_SHORTCODE,
            "RecieverIdentifierType": "11",
            "ResultURL": result_url,
            "QueueTimeOutURL": result_url,
            "Remarks": (reason or "Refund")[:100],
            "Occasion": "Refund",
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{self._base_url()}/mpesa/reversal/v1/request",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(f"M-Pesa reversal failed: {e}", 502)
        data = _json_or_error(resp, "M-Pesa reversal")
        return RefundResult(
            provider_refund_reference=str(
                data.get("ConversationID") or provider_reference
            ),
            status="processing",
            message=data.get("ResponseDescription"),
        )

    def verify_payment(
        self, *, reference, amount=None, provider_reference=None,
    ) -> bool:
        """Query the STK push status for a checkout request id."""
        if not provider_reference:
            raise PaymentProviderError(
                "M-Pesa verification requires provider_reference.", 400,
            )
        self._require_credentials()
        token = self._access_token()
        timestamp = _nairobi_timestamp()
        payload = {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": self._password(timestamp),
            "Timestamp": timestamp,
            "CheckoutRequestID": provider_reference,
        }
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(
                    f"{self._base_url()}/mpesa/stkpushquery/v1/query",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(f"M-Pesa status query failed: {e}", 502)
        data = _json_or_error(resp, "M-Pesa status query")
        return str(data.get("ResultCode")) == "0"

    def transaction_list(self, *, period_start, period_end):
        # Daraja exposes per-transaction status, not a ledger listing.
        raise PaymentProviderError(
            "M-Pesa does not expose a transaction list; reconcile with "
            "verify_payment() per reference instead.",
            501,
        )


# ── Card / bank gateways ─────────────────────────────────────────────────

class _GatewayProvider:
    """
    Shared HTTP gateway implementation for card and bank rails.

    Expects a REST gateway exposing:
      POST {base}/charges
      POST {base}/refunds
      GET  {base}/transactions/{reference}
      GET  {base}/transactions?from=&to=
    """

    name: str = "gateway"

    @property
    def webhook_secret(self) -> str:
        return settings.PAYMENT_WEBHOOK_SECRET

    def _base_url(self) -> str:
        if not settings.PAYMENT_GATEWAY_BASE_URL:
            raise PaymentProviderError(
                f"{self.name} gateway is not configured "
                "(PAYMENT_GATEWAY_BASE_URL missing).",
                503,
            )
        return settings.PAYMENT_GATEWAY_BASE_URL.rstrip("/")

    def _headers(self) -> dict:
        if not settings.PAYMENT_GATEWAY_API_KEY:
            raise PaymentProviderError(
                f"{self.name} gateway is not configured "
                "(PAYMENT_GATEWAY_API_KEY missing).",
                503,
            )
        return {
            "Authorization": f"Bearer {settings.PAYMENT_GATEWAY_API_KEY}",
            "Content-Type": "application/json",
        }

    def initiate_charge(
        self, *, amount, currency, reference, payer_phone, payer_email,
        description, callback_url,
    ) -> ChargeInitiation:
        payload = {
            "provider": self.name,
            "amount": int(amount),
            "currency": currency,
            "reference": reference,
            "phone": payer_phone,
            "email": payer_email,
            "description": description,
            "callback_url": callback_url,
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{self._base_url()}/charges",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(
                f"{self.name} gateway unreachable: {e}", 502,
            )
        data = _json_or_error(resp, f"{self.name} charge")
        provider_ref = data.get("id") or data.get("provider_reference")
        if not provider_ref:
            raise PaymentProviderError(
                f"{self.name} gateway returned no reference.", 502,
            )
        status = str(data.get("status") or "").lower()
        return ChargeInitiation(
            provider_reference=str(provider_ref),
            client_action_required=status not in (
                "succeeded", "successful", "paid",
            ),
            client_instructions=data.get("instructions") or (
                f"Complete the {self.name} payment of {amount} {currency}."
            ),
            checkout_url=data.get("checkout_url"),
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        return _hmac_ok(settings.PAYMENT_WEBHOOK_SECRET, raw_body, headers)

    def parse_webhook(self, raw_body: bytes) -> WebhookEvent:
        payload = _decode_json(raw_body)
        return WebhookEvent(
            reference=str(payload.get("reference") or ""),
            provider_reference=str(
                payload.get("provider_reference") or payload.get("id") or ""
            ),
            status=str(payload.get("status") or "pending"),
            amount=int(payload.get("amount") or 0),
            currency=str(payload.get("currency") or "KES"),
            raw_payload=payload,
        )

    def refund(
        self, *, provider_reference, amount, reason,
    ) -> RefundResult:
        payload = {
            "provider_reference": provider_reference,
            "amount": int(amount),
            "reason": reason,
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{self._base_url()}/refunds",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(f"{self.name} refund failed: {e}", 502)
        data = _json_or_error(resp, f"{self.name} refund")
        return RefundResult(
            provider_refund_reference=str(
                data.get("id")
                or data.get("refund_reference")
                or f"RF-{secrets.token_hex(6).upper()}"
            ),
            status=str(data.get("status") or "processing"),
            message=data.get("message"),
        )

    def verify_payment(
        self, *, reference, amount=None, provider_reference=None,
    ) -> bool:
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(
                    f"{self._base_url()}/transactions/{reference}",
                    headers=self._headers(),
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(
                f"{self.name} verification failed: {e}", 502,
            )
        if resp.status_code == 404:
            return False
        data = _json_or_error(resp, f"{self.name} verification")
        status = str(data.get("status") or "").lower()
        if status not in ("succeeded", "successful", "paid", "settled"):
            return False
        if amount is not None and int(data.get("amount") or 0) != int(amount):
            return False
        return True

    def transaction_list(self, *, period_start, period_end):
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{self._base_url()}/transactions",
                    headers=self._headers(),
                    params={
                        "from": period_start.isoformat(),
                        "to": period_end.isoformat(),
                    },
                )
        except httpx.HTTPError as e:
            raise PaymentProviderError(
                f"{self.name} transaction list failed: {e}", 502,
            )
        data = _json_or_error(resp, f"{self.name} transaction list")
        rows = data.get("data") or data.get("transactions") or []
        out: list[ProviderTransaction] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append(ProviderTransaction(
                provider_reference=str(
                    r.get("id") or r.get("provider_reference") or ""
                ),
                reference=r.get("reference"),
                status=str(r.get("status") or "unknown"),
                amount=int(r.get("amount") or 0),
                currency=str(r.get("currency") or "KES"),
                raw_payload=r,
            ))
        return out


class CardProvider(_GatewayProvider):
    name = PROVIDER_CARD


class BankProvider(_GatewayProvider):
    name = PROVIDER_BANK


# ── Manual / offline ─────────────────────────────────────────────────────

class ManualProvider:
    """Manual payments recorded out-of-band by an administrator."""

    name = PROVIDER_MANUAL

    @property
    def webhook_secret(self) -> str:
        return settings.PAYMENT_WEBHOOK_SECRET

    def initiate_charge(
        self, *, amount, currency, reference, payer_phone, payer_email,
        description, callback_url,
    ) -> ChargeInitiation:
        return ChargeInitiation(
            provider_reference=f"MANUAL-{reference}",
            client_action_required=False,
            client_instructions=(
                "This payment is recorded manually by an administrator."
            ),
            checkout_url=None,
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        return _hmac_ok(settings.PAYMENT_WEBHOOK_SECRET, raw_body, headers)

    def parse_webhook(self, raw_body: bytes) -> WebhookEvent:
        payload = _decode_json(raw_body)
        return WebhookEvent(
            reference=str(payload.get("reference") or ""),
            provider_reference=str(payload.get("provider_reference") or ""),
            status=str(payload.get("status") or "pending"),
            amount=int(payload.get("amount") or 0),
            currency=str(payload.get("currency") or "KES"),
            raw_payload=payload,
        )

    def refund(
        self, *, provider_reference, amount, reason,
    ) -> RefundResult:
        logger.info(
            "[manual] refund queued provider_ref=%s amount=%s",
            provider_reference, amount,
        )
        return RefundResult(
            provider_refund_reference=f"RF-{secrets.token_hex(6).upper()}",
            status="processing",
            message="Manual refund queued for administrator action.",
        )

    def verify_payment(
        self, *, reference, amount=None, provider_reference=None,
    ) -> bool:
        # The manual ledger is our own ledger; a recorded manual payment is
        # authoritative by definition.
        return True

    def transaction_list(self, *, period_start, period_end):
        return []


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