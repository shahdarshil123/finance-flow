"""Unit tests for invoice request validation. No database required."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.invoices.schemas import InvoiceCreate


def valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "supplier_id": str(uuid.uuid4()),
        "invoice_number": "INV-001",
        "invoice_date": "2026-10-01",
        "due_date": "2026-10-31",
        "currency": "EUR",
        "total_amount": "1250.00",
    }
    payload.update(overrides)
    return payload


def error_fields(exc: ValidationError) -> list[tuple[int | str, ...]]:
    return [tuple(error["loc"]) for error in exc.errors()]


def test_valid_invoice() -> None:
    invoice = InvoiceCreate.model_validate(valid_payload())

    assert invoice.total_amount == Decimal("1250.00")
    assert invoice.invoice_date == date(2026, 10, 1)
    assert invoice.purchase_order_reference is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", Decimal("0")),
        ("0.00", Decimal("0")),
        ("1250.5", Decimal("1250.5")),
        ("9999999999999999.99", Decimal("9999999999999999.99")),  # NUMERIC(18,2) max
    ],
)
def test_valid_amounts(raw: str, expected: Decimal) -> None:
    assert InvoiceCreate.model_validate(valid_payload(total_amount=raw)).total_amount == expected


@pytest.mark.parametrize(("raw", "expected"), [("0", "0.00"), ("7.5", "7.50"), ("7.50", "7.50")])
def test_amounts_are_padded_to_two_decimal_places(raw: str, expected: str) -> None:
    amount = InvoiceCreate.model_validate(valid_payload(total_amount=raw)).total_amount

    assert str(amount) == expected


def test_decimal_instance_is_accepted_from_python_callers() -> None:
    invoice = InvoiceCreate.model_validate(valid_payload(total_amount=Decimal("10.50")))

    assert invoice.total_amount == Decimal("10.50")


@pytest.mark.parametrize(
    "raw",
    [
        1250.00,
        1250,
        True,
        None,
        "-0.01",
        "1.234",
        "10000000000000000.00",
        "1e3",
        "NaN",
        "Infinity",
        "",
        " 12.00",
        "+12.00",
        "12.",
        ".5",
        "12,50",
        "abc",
    ],
    ids=[
        "json-float",
        "json-int",
        "bool",
        "null",
        "negative",
        "three-decimals",
        "exceeds-18-digits",
        "exponent",
        "nan",
        "infinity",
        "empty",
        "leading-space",
        "plus-sign",
        "trailing-dot",
        "leading-dot",
        "comma-separator",
        "non-numeric",
    ],
)
def test_invalid_amounts_are_rejected(raw: object) -> None:
    with pytest.raises(ValidationError) as exc_info:
        InvoiceCreate.model_validate(valid_payload(total_amount=raw))

    assert error_fields(exc_info.value) == [("total_amount",)]


@pytest.mark.parametrize("currency", ["eur", "EURO", "EU", "E1R", " EUR", ""])
def test_invalid_currency_is_rejected(currency: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        InvoiceCreate.model_validate(valid_payload(currency=currency))

    assert error_fields(exc_info.value) == [("currency",)]


def test_due_date_equal_to_invoice_date_is_accepted() -> None:
    invoice = InvoiceCreate.model_validate(valid_payload(due_date="2026-10-01"))

    assert invoice.due_date == invoice.invoice_date


def test_due_date_before_invoice_date_is_rejected() -> None:
    with pytest.raises(ValidationError, match="due_date must not be before invoice_date"):
        InvoiceCreate.model_validate(valid_payload(due_date="2026-09-30"))


@pytest.mark.parametrize("value", ["2026-02-30", "not-a-date", ""])
def test_invalid_dates_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        InvoiceCreate.model_validate(valid_payload(invoice_date=value))


def test_invoice_number_is_trimmed() -> None:
    invoice = InvoiceCreate.model_validate(valid_payload(invoice_number="  INV-001  "))

    assert invoice.invoice_number == "INV-001"


@pytest.mark.parametrize(
    "number",
    ["", "   ", "x" * 65, "INV\x00001", "INV\n001"],
    ids=["empty", "blank", "too-long", "nul", "newline"],
)
def test_invalid_invoice_number_is_rejected(number: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        InvoiceCreate.model_validate(valid_payload(invoice_number=number))

    assert error_fields(exc_info.value) == [("invoice_number",)]


def test_invoice_number_max_length_is_accepted() -> None:
    invoice = InvoiceCreate.model_validate(valid_payload(invoice_number="x" * 64))

    assert len(invoice.invoice_number) == 64


def test_purchase_order_reference_is_optional_and_trimmed() -> None:
    invoice = InvoiceCreate.model_validate(valid_payload(purchase_order_reference=" PO-42 "))

    assert invoice.purchase_order_reference == "PO-42"


@pytest.mark.parametrize("reference", ["", "   ", "x" * 65, "PO\x0042"])
def test_invalid_purchase_order_reference_is_rejected(reference: str) -> None:
    with pytest.raises(ValidationError):
        InvoiceCreate.model_validate(valid_payload(purchase_order_reference=reference))


@pytest.mark.parametrize("field", ["status", "id", "invoice_number_normalized"])
def test_server_controlled_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        InvoiceCreate.model_validate(valid_payload(**{field: "VALIDATED"}))

    assert error_fields(exc_info.value) == [(field,)]
