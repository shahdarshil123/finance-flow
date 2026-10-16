"""Unit tests for supplier request validation. No database required."""

import pytest
from pydantic import ValidationError

from app.suppliers.schemas import SupplierCreate


def test_minimal_supplier_is_valid() -> None:
    supplier = SupplierCreate(name="ACME Test Supplier")

    assert supplier.name == "ACME Test Supplier"
    assert supplier.tax_id is None
    assert supplier.email is None


def test_name_and_tax_id_are_normalized() -> None:
    supplier = SupplierCreate(name="  ACME Test Supplier  ", tax_id="  de123456789 ")

    assert supplier.name == "ACME Test Supplier"
    assert supplier.tax_id == "DE123456789"


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_name_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        SupplierCreate(name=name)


def test_name_length_boundary() -> None:
    assert SupplierCreate(name="x" * 255).name == "x" * 255
    with pytest.raises(ValidationError):
        SupplierCreate(name="x" * 256)


@pytest.mark.parametrize("tax_id", ["", "   ", "x" * 51])
def test_invalid_tax_id_is_rejected(tax_id: str) -> None:
    with pytest.raises(ValidationError):
        SupplierCreate(name="ACME Test Supplier", tax_id=tax_id)


def test_invalid_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SupplierCreate(name="ACME Test Supplier", email="not-an-email")


def test_non_string_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SupplierCreate.model_validate({"name": 12345})


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SupplierCreate.model_validate(
            {"name": "ACME Test Supplier", "id": "11111111-1111-1111-1111-111111111111"}
        )


@pytest.mark.parametrize(
    "char",
    ["\x00", "\x07", "\t", "\n", "\x7f", "\x85", "\ud800"],
    ids=["NUL", "BEL", "TAB", "LF", "DEL", "C1-NEL", "lone-surrogate"],
)
@pytest.mark.parametrize("field", ["name", "tax_id"])
def test_control_characters_and_surrogates_are_rejected(field: str, char: str) -> None:
    payload = {"name": "ACME Test Supplier", field: f"AB{char}CD"}

    # Pydantic itself rejects some of these (e.g. surrogates) before our validator
    # runs, so assert on the failing field rather than the message.
    with pytest.raises(ValidationError) as exc_info:
        SupplierCreate.model_validate(payload)

    assert [error["loc"] for error in exc_info.value.errors()] == [(field,)]


def test_non_ascii_tax_id_is_accepted_and_uppercased() -> None:
    assert SupplierCreate(name="Test", tax_id="çé-123").tax_id == "ÇÉ-123"


@pytest.mark.parametrize(
    ("raw", "normalized_length"),
    [("ß" * 25, 50), ("ﬃ" * 16 + "AB", 50)],
    ids=["sharp-s", "ffi-ligature"],
)
def test_tax_id_expanding_to_exactly_max_length_is_accepted(
    raw: str, normalized_length: int
) -> None:
    tax_id = SupplierCreate(name="Test", tax_id=raw).tax_id

    assert tax_id is not None
    assert len(tax_id) == normalized_length


@pytest.mark.parametrize(
    "raw", ["ß" * 26, "ß" * 50, "ﬃ" * 17], ids=["sharp-s-51", "sharp-s-100", "ffi-51"]
)
def test_tax_id_exceeding_max_length_after_uppercasing_is_rejected(raw: str) -> None:
    assert len(raw) <= 50  # passes a naive pre-normalization length check

    with pytest.raises(ValidationError, match="after normalization"):
        SupplierCreate(name="Test", tax_id=raw)
