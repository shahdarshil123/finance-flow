"""API tests for supplier endpoints against the PostgreSQL test database."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.suppliers.models import Supplier

pytestmark = pytest.mark.integration

SUPPLIERS_URL = "/api/v1/suppliers"


def test_create_supplier_returns_201_and_persists(
    db_client: TestClient, db_session: Session
) -> None:
    payload = {"name": "ACME Test Supplier", "tax_id": "de123456789", "email": "ap@acme.example"}

    response = db_client.post(SUPPLIERS_URL, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "ACME Test Supplier"
    assert body["tax_id"] == "DE123456789"
    assert body["email"] == "ap@acme.example"
    assert uuid.UUID(body["id"])
    assert body["created_at"] and body["updated_at"]

    stored = db_session.scalar(select(Supplier).where(Supplier.id == uuid.UUID(body["id"])))
    assert stored is not None
    assert stored.tax_id == "DE123456789"


def test_create_supplier_with_only_name(db_client: TestClient) -> None:
    response = db_client.post(SUPPLIERS_URL, json={"name": "Minimal Test Supplier"})

    assert response.status_code == 201
    assert response.json()["tax_id"] is None
    assert response.json()["email"] is None


def test_get_supplier_returns_created_supplier(db_client: TestClient) -> None:
    created = db_client.post(SUPPLIERS_URL, json={"name": "ACME Test Supplier"}).json()

    response = db_client.get(f"{SUPPLIERS_URL}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_supplier_returns_404(db_client: TestClient) -> None:
    missing_id = uuid.uuid4()

    response = db_client.get(f"{SUPPLIERS_URL}/{missing_id}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "supplier_not_found", "message": f"Supplier {missing_id} was not found."}
    }


def test_get_supplier_with_malformed_id_returns_422(db_client: TestClient) -> None:
    assert db_client.get(f"{SUPPLIERS_URL}/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "   "},
        {"name": "x" * 256},
        {"name": "ACME Test Supplier", "email": "not-an-email"},
        {"name": "ACME Test Supplier", "tax_id": ""},
        {"name": "ACME Test Supplier", "unexpected": "field"},
    ],
    ids=[
        "missing-name",
        "blank-name",
        "name-too-long",
        "bad-email",
        "empty-tax-id",
        "unknown-field",
    ],
)
def test_create_supplier_with_invalid_input_returns_422(
    db_client: TestClient, db_session: Session, payload: dict
) -> None:
    response = db_client.post(SUPPLIERS_URL, json=payload)

    assert response.status_code == 422
    assert db_session.scalar(select(Supplier)) is None


def test_duplicate_tax_id_is_case_insensitive_and_returns_409(db_client: TestClient) -> None:
    first = db_client.post(
        SUPPLIERS_URL, json={"name": "First Test Supplier", "tax_id": "DE123456789"}
    )
    second = db_client.post(
        SUPPLIERS_URL, json={"name": "Second Test Supplier", "tax_id": "de123456789"}
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "supplier_tax_id_conflict"


def test_session_is_usable_after_conflict(db_client: TestClient) -> None:
    db_client.post(SUPPLIERS_URL, json={"name": "First Test Supplier", "tax_id": "DE1"})
    db_client.post(SUPPLIERS_URL, json={"name": "Second Test Supplier", "tax_id": "DE1"})

    response = db_client.post(SUPPLIERS_URL, json={"name": "Third Test Supplier", "tax_id": "DE2"})

    assert response.status_code == 201


def test_multiple_suppliers_without_tax_id_are_allowed(db_client: TestClient) -> None:
    first = db_client.post(SUPPLIERS_URL, json={"name": "Test Supplier A"})
    second = db_client.post(SUPPLIERS_URL, json={"name": "Test Supplier B"})

    assert first.status_code == 201
    assert second.status_code == 201


# Regression: each of these previously returned HTTP 500.
# Raw JSON bodies are used because escapes like \ud800 can't be sent via json=.
@pytest.mark.parametrize(
    ("body", "field"),
    [
        ('{"name": "ACME\\u0000Test"}', "name"),
        ('{"name": "ACME Test", "tax_id": "DE\\u0000123"}', "tax_id"),
        ('{"name": "ACME\\ud800Test"}', "name"),
        ('{"name": "ACME Test", "tax_id": "DE\\ud800123"}', "tax_id"),
        ('{"name": "ACME Test", "email": "ap\\ud800@acme.example"}', "email"),
        ('{"name": "' + "x" * 256 + '\\ud800"}', "name"),
        ('{"name": "ACME Test", "tax_id": "' + "ß" * 50 + '"}', "tax_id"),
        ('{"name": "ACME Test", "tax_id": "' + "ﬃ" * 20 + '"}', "tax_id"),
    ],
    ids=[
        "nul-in-name",
        "nul-in-tax-id",
        "surrogate-in-name",
        "surrogate-in-tax-id",
        "surrogate-in-email",
        "surrogate-echoed-in-422",
        "tax-id-sharp-s-uppercases-to-100-chars",
        "tax-id-ffi-uppercases-to-60-chars",
    ],
)
def test_previously_crashing_input_returns_422(
    db_client: TestClient, db_session: Session, body: str, field: str
) -> None:
    response = db_client.post(
        SUPPLIERS_URL, content=body.encode(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert db_session.scalar(select(Supplier)) is None


def test_non_ascii_tax_id_round_trips(db_client: TestClient) -> None:
    created = db_client.post(SUPPLIERS_URL, json={"name": "Test Supplier", "tax_id": "ß" * 25})

    assert created.status_code == 201
    assert created.json()["tax_id"] == "SS" * 25
    fetched = db_client.get(f"{SUPPLIERS_URL}/{created.json()['id']}")
    assert fetched.json()["tax_id"] == "SS" * 25


def test_database_rejects_blank_name_bypassing_api(db_session: Session) -> None:
    db_session.add(Supplier(name="   "))

    with pytest.raises(IntegrityError, match="ck_suppliers_name_not_blank"):
        db_session.flush()
