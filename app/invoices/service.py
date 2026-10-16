import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import violated_constraint
from app.errors import ConflictError, InvalidReferenceError, NotFoundError
from app.invoices.models import Invoice
from app.invoices.schemas import InvoiceCreate
from app.suppliers.service import get_supplier

SUPPLIER_FOREIGN_KEY = "fk_invoices_supplier_id_suppliers"
INVOICE_NUMBER_UNIQUE_CONSTRAINT = "uq_invoices_supplier_id_invoice_number_normalized"


def create_invoice(db: Session, data: InvoiceCreate) -> Invoice:
    """Create an invoice in its own transaction (this function owns the commit).

    New invoices start as RECEIVED (database default). Not HTTP-specific, so a
    future extraction pipeline can call it with an already-validated InvoiceCreate.
    """
    invoice = Invoice(**data.model_dump())
    db.add(invoice)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Constraints decide, not prior SELECTs, so concurrent requests can't
        # slip past a check-then-insert window.
        constraint = violated_constraint(exc)
        if constraint == SUPPLIER_FOREIGN_KEY:
            raise InvalidReferenceError(
                "supplier_not_found", f"Supplier {data.supplier_id} was not found."
            ) from exc
        if constraint == INVOICE_NUMBER_UNIQUE_CONSTRAINT:
            existing_id = _find_invoice_id(db, data.supplier_id, data.invoice_number)
            raise ConflictError(
                "invoice_duplicate",
                "This supplier already has an invoice with this invoice number.",
                details={"existing_invoice_id": str(existing_id)} if existing_id else None,
            ) from exc
        raise
    return invoice


def get_invoice(db: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("invoice_not_found", f"Invoice {invoice_id} was not found.")
    return invoice


def list_supplier_invoices(
    db: Session, supplier_id: uuid.UUID, limit: int, offset: int
) -> Sequence[Invoice]:
    """Newest invoices first; id breaks ties so pages are stable."""
    get_supplier(db, supplier_id)  # raises NotFoundError for unknown suppliers
    return db.scalars(
        select(Invoice)
        .where(Invoice.supplier_id == supplier_id)
        .order_by(Invoice.invoice_date.desc(), Invoice.id)
        .limit(limit)
        .offset(offset)
    ).all()


def _find_invoice_id(db: Session, supplier_id: uuid.UUID, invoice_number: str) -> uuid.UUID | None:
    # Normalize with the same PostgreSQL function as the computed column.
    return db.scalar(
        select(Invoice.id).where(
            Invoice.supplier_id == supplier_id,
            Invoice.invoice_number_normalized == func.upper(invoice_number),
        )
    )
