"""Supplier <-> ERP identity: external_erp_id on create, and idempotent ERP import."""

import uuid
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.erp.errors import ERPInvalidResponseError, ERPUnavailableError
from app.erp.http_client import get_erp_client
from app.erp.schemas import ERPSupplier
from app.suppliers.models import Supplier
from tests.fake_erp import FakeERP

pytestmark = pytest.mark.integration

SUPPLIERS_URL = "/api/v1/suppliers"


def import_url(external_id: str) -> str:
    return f"{SUPPLIERS_URL}/import-from-erp/{external_id}"


def supplier_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Supplier)) or 0


def row_version(db: Session, supplier_id: str) -> str:
    """Physical row location; every UPDATE writes a new row version, so it changes.
    (Timestamps can't show this here: now() is fixed within the test transaction.)"""
    return str(db.scalar(text("SELECT ctid FROM suppliers WHERE id = :id"), {"id": supplier_id}))


@pytest.fixture
def fake_erp(app: FastAPI) -> FakeERP:
    erp = FakeERP()
    app.dependency_overrides[get_erp_client] = lambda: erp
    return erp


# --- external_erp_id on the Supplier API ----------------------------------------


def test_create_supplier_with_external_erp_id_trims_and_keeps_case(db_client: TestClient) -> None:
    response = db_client.post(SUPPLIERS_URL, json={"name": "Mapped", "external_erp_id": " Erp-7 "})

    assert response.status_code == 201
    assert response.json()["external_erp_id"] == "Erp-7"
    fetched = db_client.get(f"{SUPPLIERS_URL}/{response.json()['id']}").json()
    assert fetched["external_erp_id"] == "Erp-7"


def test_external_erp_id_is_optional_and_null_by_default(db_client: TestClient) -> None:
    body = db_client.post(SUPPLIERS_URL, json={"name": "Unmapped"}).json()

    assert body["external_erp_id"] is None


def test_suppliers_without_erp_id_do_not_conflict(db_client: TestClient) -> None:
    assert db_client.post(SUPPLIERS_URL, json={"name": "A"}).status_code == 201
    assert db_client.post(SUPPLIERS_URL, json={"name": "B"}).status_code == 201


def test_duplicate_external_erp_id_is_409(db_client: TestClient) -> None:
    first = db_client.post(SUPPLIERS_URL, json={"name": "A", "external_erp_id": "ERP-SUP-001"})
    second = db_client.post(SUPPLIERS_URL, json={"name": "B", "external_erp_id": "ERP-SUP-001"})

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "supplier_external_erp_id_conflict"


def test_external_erp_id_uniqueness_is_case_sensitive(db_client: TestClient) -> None:
    db_client.post(SUPPLIERS_URL, json={"name": "A", "external_erp_id": "ERP-SUP-001"})

    response = db_client.post(SUPPLIERS_URL, json={"name": "B", "external_erp_id": "erp-sup-001"})

    assert response.status_code == 201


@pytest.mark.parametrize("value", ["", "   ", "x" * 65, "ERP\x00001", 42])
def test_invalid_external_erp_id_is_422(db_client: TestClient, value: object) -> None:
    response = db_client.post(SUPPLIERS_URL, json={"name": "A", "external_erp_id": value})

    assert response.status_code == 422


def test_database_enforces_external_erp_id_constraints(db_session: Session) -> None:
    db_session.execute(insert(Supplier).values(id=uuid.uuid4(), name="A", external_erp_id="X-1"))
    with pytest.raises(IntegrityError, match="uq_suppliers_external_erp_id"):
        with db_session.begin_nested():
            db_session.execute(
                insert(Supplier).values(id=uuid.uuid4(), name="B", external_erp_id="X-1")
            )
    with pytest.raises(IntegrityError, match="ck_suppliers_external_erp_id_not_blank"):
        with db_session.begin_nested():
            db_session.execute(
                insert(Supplier).values(id=uuid.uuid4(), name="C", external_erp_id="  ")
            )


# --- import from ERP --------------------------------------------------------------


def test_import_creates_mapped_supplier(
    db_client: TestClient, db_session: Session, fake_erp: FakeERP
) -> None:
    response = db_client.post(import_url("ERP-SUP-001"))

    assert response.status_code == 200
    body = response.json()
    assert body["external_erp_id"] == "ERP-SUP-001"
    assert body["name"] == "Northwind Office Supplies"
    assert body["tax_id"] == "DE100000001"
    assert body["email"] == "ap@northwind.example"
    assert uuid.UUID(body["id"])  # local identity is our own UUID
    assert body["id"] != "ERP-SUP-001"
    assert fake_erp.calls == ["supplier:ERP-SUP-001"]


def test_repeated_import_is_idempotent(
    db_client: TestClient, db_session: Session, fake_erp: FakeERP
) -> None:
    before = supplier_count(db_session)

    first = db_client.post(import_url("ERP-SUP-002")).json()
    version = row_version(db_session, first["id"])
    second = db_client.post(import_url("ERP-SUP-002")).json()

    assert first == second
    assert supplier_count(db_session) == before + 1
    assert row_version(db_session, first["id"]) == version  # unchanged data: no write


def test_import_updates_existing_mapping_when_erp_data_changes(
    db_client: TestClient, db_session: Session, fake_erp: FakeERP
) -> None:
    first = db_client.post(import_url("ERP-SUP-003")).json()
    version = row_version(db_session, first["id"])
    fake_erp.suppliers["ERP-SUP-003"] = ERPSupplier(
        external_supplier_id="ERP-SUP-003",
        name="Fabrikam Industrial Parts GmbH",
        tax_id="de300000003",
        email="ap@fabrikam.example",
    )

    second = db_client.post(import_url("ERP-SUP-003")).json()

    assert second["id"] == first["id"]
    assert second["name"] == "Fabrikam Industrial Parts GmbH"
    assert second["tax_id"] == "DE300000003"  # same normalization as the API
    assert second["email"] == "ap@fabrikam.example"
    assert row_version(db_session, first["id"]) != version


def test_import_links_to_supplier_created_with_same_erp_id(
    db_client: TestClient, db_session: Session, fake_erp: FakeERP
) -> None:
    created = db_client.post(
        SUPPLIERS_URL, json={"name": "Local name", "external_erp_id": "ERP-SUP-001"}
    ).json()

    imported = db_client.post(import_url("ERP-SUP-001")).json()

    assert imported["id"] == created["id"]
    assert imported["name"] == "Northwind Office Supplies"


def test_import_unknown_erp_supplier_is_404(
    db_client: TestClient, db_session: Session, fake_erp: FakeERP
) -> None:
    before = supplier_count(db_session)

    response = db_client.post(import_url("ERP-SUP-999"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "erp_supplier_not_found"
    assert supplier_count(db_session) == before


def test_import_when_erp_unavailable_is_503(db_client: TestClient, fake_erp: FakeERP) -> None:
    fake_erp.error = ERPUnavailableError("down")

    response = db_client.post(import_url("ERP-SUP-001"))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "erp_unavailable"


def test_import_invalid_erp_response_is_502(db_client: TestClient, fake_erp: FakeERP) -> None:
    fake_erp.error = ERPInvalidResponseError("bad")

    assert db_client.post(import_url("ERP-SUP-001")).status_code == 502


def test_import_erp_data_failing_local_validation_is_502(
    db_client: TestClient, db_session: Session, fake_erp: FakeERP
) -> None:
    before = supplier_count(db_session)
    fake_erp.suppliers["ERP-SUP-001"] = ERPSupplier(
        external_supplier_id="ERP-SUP-001", name="Bad email", email="not-an-email"
    )

    response = db_client.post(import_url("ERP-SUP-001"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "erp_invalid_response"
    assert supplier_count(db_session) == before


def test_import_tax_id_owned_by_another_local_supplier_is_409(
    db_client: TestClient, make_supplier: Callable[..., Supplier], fake_erp: FakeERP
) -> None:
    db_client.post(SUPPLIERS_URL, json={"name": "Local copy", "tax_id": "DE100000001"})

    response = db_client.post(import_url("ERP-SUP-001"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "supplier_tax_id_conflict"
