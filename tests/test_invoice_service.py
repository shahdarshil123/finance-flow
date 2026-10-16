"""Service-level tests: transaction ownership, rollback, and database constraints."""

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, InvalidReferenceError, NotFoundError
from app.invoices.models import Invoice, InvoiceStatus
from app.invoices.schemas import InvoiceCreate
from app.invoices.service import create_invoice, get_invoice, list_supplier_invoices
from app.suppliers.models import Supplier

pytestmark = pytest.mark.integration


def invoice_data(supplier_id: uuid.UUID, **overrides: Any) -> InvoiceCreate:
    fields: dict[str, Any] = {
        "supplier_id": supplier_id,
        "invoice_number": "INV-001",
        "invoice_date": date(2026, 10, 1),
        "due_date": date(2026, 10, 31),
        "currency": "EUR",
        "total_amount": Decimal("1250.00"),
    }
    fields.update(overrides)
    return InvoiceCreate(**fields)


def invoice_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Invoice)) or 0


def test_create_invoice_sets_server_defaults(
    db_session: Session, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()

    invoice = create_invoice(db_session, invoice_data(supplier.id, invoice_number="inv-001"))

    assert invoice.status is InvoiceStatus.RECEIVED
    assert invoice.invoice_number == "inv-001"
    assert invoice.invoice_number_normalized == "INV-001"
    assert invoice.total_amount == Decimal("1250.00")
    assert get_invoice(db_session, invoice.id) is invoice


def test_duplicate_rolls_back_only_the_failed_invoice(
    db_session: Session, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()
    first = create_invoice(db_session, invoice_data(supplier.id))

    with pytest.raises(ConflictError) as exc_info:
        create_invoice(db_session, invoice_data(supplier.id, invoice_number=" inv-001 "))

    assert exc_info.value.code == "invoice_duplicate"
    assert exc_info.value.details == {"existing_invoice_id": str(first.id)}
    # Earlier committed work survives; the session remains usable.
    assert invoice_count(db_session) == 1
    second = create_invoice(db_session, invoice_data(supplier.id, invoice_number="INV-002"))
    assert invoice_count(db_session) == 2
    assert second.id != first.id


def test_unknown_supplier_raises_and_leaves_no_invoice(db_session: Session) -> None:
    with pytest.raises(InvalidReferenceError) as exc_info:
        create_invoice(db_session, invoice_data(uuid.uuid4()))

    assert exc_info.value.code == "supplier_not_found"
    assert invoice_count(db_session) == 0


def test_session_is_usable_after_unknown_supplier(
    db_session: Session, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()
    with pytest.raises(InvalidReferenceError):
        create_invoice(db_session, invoice_data(uuid.uuid4()))

    create_invoice(db_session, invoice_data(supplier.id))

    assert invoice_count(db_session) == 1


def test_unexpected_constraint_violation_is_reraised_and_rolled_back(
    db_session: Session, make_supplier: Callable[..., Supplier]
) -> None:
    """A database CHECK is the last line of defense if validation is bypassed
    (model_construct skips Pydantic). It must not be mistranslated as a 409/422."""
    supplier = make_supplier()
    fields: dict[str, Any] = invoice_data(supplier.id).model_dump()
    fields["total_amount"] = Decimal("-1.00")
    unvalidated = InvoiceCreate.model_construct(**fields)

    with pytest.raises(IntegrityError, match="ck_invoices_total_amount_non_negative"):
        create_invoice(db_session, unvalidated)

    assert invoice_count(db_session) == 0
    assert db_session.get(Supplier, supplier.id) is not None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"currency": "eur"}, "ck_invoices_currency_iso_4217_format"),
        ({"due_date": date(2026, 9, 1)}, "ck_invoices_due_date_not_before_invoice_date"),
        ({"invoice_number": "   "}, "ck_invoices_invoice_number_not_blank"),
    ],
    ids=["lowercase-currency", "due-before-invoice", "blank-number"],
)
def test_database_constraints_reject_invalid_rows(
    db_session: Session,
    make_supplier: Callable[..., Supplier],
    overrides: dict[str, Any],
    constraint: str,
) -> None:
    supplier = make_supplier()
    db_session.add(Invoice(**(invoice_data(supplier.id).model_dump() | overrides)))

    with pytest.raises(IntegrityError, match=constraint):
        db_session.flush()


def test_database_rejects_unknown_status(
    db_session: Session, make_supplier: Callable[..., Supplier]
) -> None:
    # Raw SQL: the ORM Enum type would reject "PAID" before reaching PostgreSQL.
    invoice = create_invoice(db_session, invoice_data(make_supplier().id))

    with pytest.raises(IntegrityError, match="ck_invoices_status_valid"):
        db_session.execute(
            text("UPDATE invoices SET status = 'PAID' WHERE id = :id"), {"id": invoice.id}
        )


def test_list_unknown_supplier_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        list_supplier_invoices(db_session, uuid.uuid4(), limit=50, offset=0)
