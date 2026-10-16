"""API tests for invoice endpoints against the PostgreSQL test database."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.invoices.models import Invoice
from app.suppliers.models import Supplier

pytestmark = pytest.mark.integration

INVOICES_URL = "/api/v1/invoices"


def payload(supplier_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "supplier_id": str(supplier_id),
        "invoice_number": "INV-001",
        "invoice_date": "2026-10-01",
        "due_date": "2026-10-31",
        "currency": "EUR",
        "total_amount": "1250.00",
    }
    body.update(overrides)
    return body


def supplier_invoices_url(supplier_id: uuid.UUID | str) -> str:
    return f"/api/v1/suppliers/{supplier_id}/invoices"


def invoice_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Invoice)) or 0


# --- create -----------------------------------------------------------------


def test_create_invoice_returns_201(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()

    response = db_client.post(
        INVOICES_URL, json=payload(supplier.id, purchase_order_reference="PO-42")
    )

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["supplier_id"] == str(supplier.id)
    assert body["invoice_number"] == "INV-001"
    assert body["invoice_date"] == "2026-10-01"
    assert body["due_date"] == "2026-10-31"
    assert body["currency"] == "EUR"
    assert body["total_amount"] == "1250.00"  # string, never a JSON float
    assert body["status"] == "RECEIVED"
    assert body["purchase_order_reference"] == "PO-42"
    assert "invoice_number_normalized" not in body


def test_amount_is_returned_at_database_scale(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    created = db_client.post(INVOICES_URL, json=payload(make_supplier().id, total_amount="7.5"))
    fetched = db_client.get(f"{INVOICES_URL}/{created.json()['id']}")

    # Create and retrieve must agree on the representation.
    assert created.json()["total_amount"] == "7.50"
    assert fetched.json()["total_amount"] == "7.50"


def test_unknown_supplier_returns_422_and_creates_nothing(
    db_client: TestClient, db_session: Session
) -> None:
    missing_id = uuid.uuid4()

    response = db_client.post(INVOICES_URL, json=payload(missing_id))

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "supplier_not_found", "message": f"Supplier {missing_id} was not found."}
    }
    assert invoice_count(db_session) == 0


@pytest.mark.parametrize(
    "amount",
    [1250.0, 1250, "-1.00", "1.234", "10000000000000000.00", "1e3", "NaN", ""],
    ids=[
        "json-float",
        "json-int",
        "negative",
        "three-decimals",
        "too-many-digits",
        "exponent",
        "nan",
        "empty",
    ],
)
def test_invalid_amount_returns_422(
    db_client: TestClient,
    db_session: Session,
    make_supplier: Callable[..., Supplier],
    amount: object,
) -> None:
    response = db_client.post(INVOICES_URL, json=payload(make_supplier().id, total_amount=amount))

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "total_amount"]
    assert invoice_count(db_session) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"currency": "eur"},
        {"due_date": "2026-09-30"},
        {"invoice_number": "   "},
        {"status": "VALIDATED"},
        {"supplier_id": "not-a-uuid"},
    ],
    ids=["lowercase-currency", "due-before-invoice", "blank-number", "client-status", "bad-uuid"],
)
def test_invalid_payload_returns_422(
    db_client: TestClient, make_supplier: Callable[..., Supplier], overrides: dict[str, Any]
) -> None:
    body = payload(make_supplier().id) | overrides

    response = db_client.post(INVOICES_URL, json=body)

    assert response.status_code == 422


def test_duplicate_invoice_number_returns_409_with_existing_id(
    db_client: TestClient, db_session: Session, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()
    first = db_client.post(INVOICES_URL, json=payload(supplier.id, invoice_number="INV-001"))

    # Case and surrounding whitespace differ; it is still the same invoice number.
    second = db_client.post(INVOICES_URL, json=payload(supplier.id, invoice_number="  inv-001 "))

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invoice_duplicate"
    assert second.json()["error"]["details"] == {"existing_invoice_id": first.json()["id"]}
    assert invoice_count(db_session) == 1


def test_same_invoice_number_for_different_suppliers_is_allowed(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    supplier_a = make_supplier("Test Supplier A")
    supplier_b = make_supplier("Test Supplier B")

    first = db_client.post(INVOICES_URL, json=payload(supplier_a.id))
    second = db_client.post(INVOICES_URL, json=payload(supplier_b.id))

    assert first.status_code == 201
    assert second.status_code == 201


def test_requests_succeed_after_a_rolled_back_failure(
    db_client: TestClient, db_session: Session, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()
    db_client.post(INVOICES_URL, json=payload(supplier.id))
    assert db_client.post(INVOICES_URL, json=payload(supplier.id)).status_code == 409
    assert db_client.post(INVOICES_URL, json=payload(uuid.uuid4())).status_code == 422

    response = db_client.post(INVOICES_URL, json=payload(supplier.id, invoice_number="INV-002"))

    assert response.status_code == 201
    assert invoice_count(db_session) == 2


# --- retrieve ---------------------------------------------------------------


def test_get_invoice_returns_created_invoice(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    created = db_client.post(INVOICES_URL, json=payload(make_supplier().id)).json()

    response = db_client.get(f"{INVOICES_URL}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_invoice_returns_404(db_client: TestClient) -> None:
    missing_id = uuid.uuid4()

    response = db_client.get(f"{INVOICES_URL}/{missing_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invoice_not_found"


def test_get_invoice_with_malformed_id_returns_422(db_client: TestClient) -> None:
    assert db_client.get(f"{INVOICES_URL}/not-a-uuid").status_code == 422


# --- list by supplier -------------------------------------------------------


def test_list_returns_newest_first_with_stable_paging(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()
    dates = ["2026-10-01", "2026-10-03", "2026-10-02"]
    for number, invoice_date in enumerate(dates, start=1):
        db_client.post(
            INVOICES_URL,
            json=payload(
                supplier.id,
                invoice_number=f"INV-{number}",
                invoice_date=invoice_date,
                due_date="2026-12-31",
            ),
        )

    first_page = db_client.get(supplier_invoices_url(supplier.id), params={"limit": 2}).json()
    second_page = db_client.get(
        supplier_invoices_url(supplier.id), params={"limit": 2, "offset": 2}
    ).json()

    assert [i["invoice_date"] for i in first_page["items"]] == ["2026-10-03", "2026-10-02"]
    assert [i["invoice_date"] for i in second_page["items"]] == ["2026-10-01"]
    assert (first_page["limit"], first_page["offset"]) == (2, 0)
    assert (second_page["limit"], second_page["offset"]) == (2, 2)


def test_list_only_includes_the_suppliers_own_invoices(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    supplier_a = make_supplier("Test Supplier A")
    supplier_b = make_supplier("Test Supplier B")
    db_client.post(INVOICES_URL, json=payload(supplier_a.id, invoice_number="A-1"))
    db_client.post(INVOICES_URL, json=payload(supplier_b.id, invoice_number="B-1"))

    items = db_client.get(supplier_invoices_url(supplier_a.id)).json()["items"]

    assert [i["invoice_number"] for i in items] == ["A-1"]


def test_list_for_supplier_without_invoices_is_empty(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    response = db_client.get(supplier_invoices_url(make_supplier().id))

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 50, "offset": 0}


def test_list_offset_past_end_is_empty(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    supplier = make_supplier()
    db_client.post(INVOICES_URL, json=payload(supplier.id))

    response = db_client.get(supplier_invoices_url(supplier.id), params={"offset": 10})

    assert response.json()["items"] == []


def test_list_for_unknown_supplier_returns_404(db_client: TestClient) -> None:
    response = db_client.get(supplier_invoices_url(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "supplier_not_found"


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "ten"}],
    ids=["limit-zero", "limit-over-max", "negative-offset", "non-integer"],
)
def test_list_with_invalid_paging_returns_422(
    db_client: TestClient, make_supplier: Callable[..., Supplier], params: dict[str, Any]
) -> None:
    response = db_client.get(supplier_invoices_url(make_supplier().id), params=params)

    assert response.status_code == 422


def test_list_limit_boundaries_are_accepted(
    db_client: TestClient, make_supplier: Callable[..., Supplier]
) -> None:
    url = supplier_invoices_url(make_supplier().id)

    assert db_client.get(url, params={"limit": 1}).status_code == 200
    assert db_client.get(url, params={"limit": 100}).status_code == 200
