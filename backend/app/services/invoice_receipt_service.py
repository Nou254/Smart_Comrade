"""
Invoice + receipt service — Module 012.

Every transaction gets:
  - an invoice at initiation
  - a receipt at success
Both have PDF URLs (storage integration TBD) and are never mutated,
only voided + reissued.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.financial import (
    Invoice, Receipt, Transaction, FinancialAuditLog,
    TXN_SUCCESSFUL, TXN_SETTLED,
)
from app.services.transaction_service import get_by_id


logger = logging.getLogger(__name__)


class InvoiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────
# NUMBERING
# ─────────────────────────────────────────────────────────────────────────

def _next_invoice_number(db: Session) -> str:
    year = _now().year
    last = db.query(Invoice).filter(
        Invoice.invoice_number.like(f"INV-{year}-%"),
    ).order_by(Invoice.created_at.desc()).first()
    seq = 1
    if last:
        try:
            seq = int(last.invoice_number.split("-")[-1]) + 1
        except Exception:
            seq = 1
    return f"INV-{year}-{seq:06d}"


def _next_receipt_number(db: Session) -> str:
    year = _now().year
    last = db.query(Receipt).filter(
        Receipt.receipt_number.like(f"RCP-{year}-%"),
    ).order_by(Receipt.created_at.desc()).first()
    seq = 1
    if last:
        try:
            seq = int(last.receipt_number.split("-")[-1]) + 1
        except Exception:
            seq = 1
    return f"RCP-{year}-{seq:06d}"


# ─────────────────────────────────────────────────────────────────────────
# INVOICE
# ─────────────────────────────────────────────────────────────────────────

def generate_invoice(
    db: Session, transaction_id: str, line_items: list | None = None,
) -> Invoice:
    txn = get_by_id(db, transaction_id)

    existing = db.query(Invoice).filter(
        Invoice.transaction_id == transaction_id,
    ).first()
    if existing:
        return existing

    if not line_items:
        line_items = [{
            "description": txn.description or txn.transaction_type,
            "quantity": 1,
            "unit_price": txn.amount,
            "subtotal": txn.amount,
        }]

    inv = Invoice(
        invoice_number=_next_invoice_number(db),
        transaction_id=txn.id,
        payer_user_id=txn.payer_user_id,
        payer_group_id=txn.payer_group_id,
        line_items_json=line_items,
        subtotal=txn.amount,
        tax=0,
        total=txn.amount,
        currency=txn.currency,
        status="issued",
        issued_at=_now(),
        due_at=txn.grace_ends_at,
    )
    db.add(inv)
    _log(db, txn.id, "invoice.generated", details={
        "invoice_number": inv.invoice_number,
    })
    db.commit()
    db.refresh(inv)
    return inv


def mark_invoice_paid(db: Session, invoice_id: str) -> Invoice:
    inv = _get_invoice(db, invoice_id)
    if inv.status == "paid":
        return inv
    inv.status = "paid"
    inv.paid_at = _now()
    db.commit()
    db.refresh(inv)
    return inv


def void_invoice(
    db: Session, invoice_id: str, reason: str,
) -> Invoice:
    inv = _get_invoice(db, invoice_id)
    inv.status = "void"
    inv.voided_at = _now()
    inv.voided_reason = reason
    db.commit()
    db.refresh(inv)
    return inv


# ─────────────────────────────────────────────────────────────────────────
# RECEIPT
# ─────────────────────────────────────────────────────────────────────────

def generate_receipt(
    db: Session, transaction_id: str,
) -> Receipt:
    txn = get_by_id(db, transaction_id)
    if txn.status not in (TXN_SUCCESSFUL, TXN_SETTLED):
        raise InvoiceError(
            f"Cannot issue receipt for transaction in status '{txn.status}'.", 409,
        )

    existing = db.query(Receipt).filter(
        Receipt.transaction_id == transaction_id,
    ).first()
    if existing:
        return existing

    inv = db.query(Invoice).filter(
        Invoice.transaction_id == transaction_id,
    ).first()

    rcp = Receipt(
        receipt_number=_next_receipt_number(db),
        transaction_id=txn.id,
        invoice_id=inv.id if inv else None,
        payer_user_id=txn.payer_user_id,
        payer_group_id=txn.payer_group_id,
        amount=txn.amount,
        currency=txn.currency,
        payment_method=txn.provider,
        provider_reference=txn.provider_reference or txn.reference,
        status="issued",
        issued_at=_now(),
    )
    db.add(rcp)

    if inv:
        inv.status = "paid"
        inv.paid_at = _now()

    _log(db, txn.id, "receipt.issued", details={
        "receipt_number": rcp.receipt_number,
    })
    db.commit()
    db.refresh(rcp)
    return rcp


def void_receipt(db: Session, receipt_id: str, reason: str) -> Receipt:
    rcp = _get_receipt(db, receipt_id)
    rcp.status = "void"
    rcp.voided_at = _now()
    rcp.voided_reason = reason
    db.commit()
    db.refresh(rcp)
    return rcp


# ─────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────

def list_invoices(
    db: Session, *,
    payer_user_id: str | None = None,
    payer_group_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[Invoice]:
    q = db.query(Invoice)
    if payer_user_id:
        q = q.filter(Invoice.payer_user_id == payer_user_id)
    if payer_group_id:
        q = q.filter(Invoice.payer_group_id == payer_group_id)
    if status:
        q = q.filter(Invoice.status == status)
    return q.order_by(Invoice.issued_at.desc()).limit(limit).all()


def list_receipts(
    db: Session, *,
    payer_user_id: str | None = None,
    payer_group_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[Receipt]:
    q = db.query(Receipt)
    if payer_user_id:
        q = q.filter(Receipt.payer_user_id == payer_user_id)
    if payer_group_id:
        q = q.filter(Receipt.payer_group_id == payer_group_id)
    if status:
        q = q.filter(Receipt.status == status)
    return q.order_by(Receipt.issued_at.desc()).limit(limit).all()


def get_invoice(db: Session, invoice_id: str) -> Invoice:
    return _get_invoice(db, invoice_id)


def get_receipt(db: Session, receipt_id: str) -> Receipt:
    return _get_receipt(db, receipt_id)


# ─────────────────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────────────────

def _get_invoice(db: Session, invoice_id: str) -> Invoice:
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise InvoiceError("Invoice not found.", 404)
    return inv


def _get_receipt(db: Session, receipt_id: str) -> Receipt:
    rcp = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not rcp:
        raise InvoiceError("Receipt not found.", 404)
    return rcp


def _log(
    db: Session, transaction_id: str, event_type: str,
    details: dict | None = None,
) -> None:
    db.add(FinancialAuditLog(
        event_type=event_type,
        transaction_id=transaction_id,
        details_json=details,
    ))