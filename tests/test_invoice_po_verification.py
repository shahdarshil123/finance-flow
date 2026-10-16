"""POST /invoices/{id}/verify-po against the test database with a fake or real ERP client."""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.erp.errors import ERPInvalidResponseError, ERPRequestError, ERPUnavailableError
from app.erp.http_client import HttpERPClient, get_erp_client
from app.invoices.models import Invoice, InvoiceStatus
from app.suppliers.models import Supplier
from mock_erp.main import app as mock_erp_app
from tests.fake_erp import FakeERP

pytestmark = pytest.mark.integration


@pytest.fixture
def fake_erp(app: FastAPI) -> FakeERP:
    erp = FakeERP()
    app.dependency_overrides[get_erp_client] = lambda: erp
    return erp


@pytest.fixture
def make_invoice(db_client: TestClient) -> Callable[..., dict[str, Any]]:
    def _make(supplier: Supplier, po_reference: str | None = "PO-1001") -> dict[str, Any]:
        body: dict[str, Any] = {
            "supplier_id": str(supplier.id),
            "invoice_number": f"INV-{uuid.uuid4().hex[:8]}",
            "invoice_date": "2026-10-01",
            "due_date": "2026-10-31",
            "currency": "EUR",
            "total_amount": "1250.00",
            "purchase_order_reference": po_reference,
        }
        response = db_client.post("/api/v1/invoices", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return _make


def verify_url(invoice_id: str | uuid.UUID) -> str:
    return f"/api/v1/invoices/{invoice_id}/verify-po"


# --- outcomes -------------------------------------------------------------------


def test_verified_returns_po_details_and_leaves_invoice_status(
    db_client: TestClient,
    db_session: Session,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"))

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "VERIFIED"
    assert body["invoice_id"] == invoice["id"]
    assert body["purchase_order_reference"] == "PO-1001"
    assert body["supplier_external_erp_id"] == "ERP-SUP-001"
    po = body["purchase_order"]
    assert po["po_number"] == "PO-1001"
    assert po["status"] == "OPEN"
    assert po["total_amount"] == "1250.00"  # money stays a decimal string
    assert po["line_items"][0]["unit_price"] == "20.00"
    assert fake_erp.calls == ["po:PO-1001"]

    stored = db_session.get(Invoice, uuid.UUID(invoice["id"]))
    assert stored is not None
    assert stored.status is InvoiceStatus.RECEIVED  # never auto-VALIDATED


@pytest.mark.parametrize(("po_number", "status"), [("PO-1002", "CLOSED"), ("PO-1003", "CANCELLED")])
def test_non_open_po_is_verified_and_reports_status(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
    po_number: str,
    status: str,
) -> None:
    owner = fake_erp.purchase_orders[po_number].external_supplier_id
    invoice = make_invoice(make_supplier(external_erp_id=owner), po_reference=po_number)

    body = db_client.post(verify_url(invoice["id"])).json()

    assert body["outcome"] == "VERIFIED"
    assert body["purchase_order"]["status"] == status
    assert status in body["detail"]


def test_po_of_another_supplier_is_mismatch(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    # PO-1002 belongs to ERP-SUP-002.
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"), po_reference="PO-1002")

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "MISMATCH"
    assert body["purchase_order"]["external_supplier_id"] == "ERP-SUP-002"
    assert "ERP-SUP-002" in body["detail"]


def test_supplier_id_comparison_is_exact(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="erp-sup-001"))

    assert db_client.post(verify_url(invoice["id"])).json()["outcome"] == "MISMATCH"


def test_unknown_po_is_not_found(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"), po_reference="PO-9999")

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 200
    assert response.json()["outcome"] == "NOT_FOUND"
    assert response.json()["purchase_order"] is None


def test_erp_unavailable_is_reported_as_outcome(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"))
    fake_erp.error = ERPUnavailableError("after 3 attempt(s): ConnectError")

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "UNAVAILABLE"
    assert body["purchase_order"] is None
    assert "ConnectError" not in body["detail"]  # internals stay in the logs


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ERPInvalidResponseError("malformed JSON"), "erp_invalid_response"),
        (ERPRequestError("HTTP 401"), "erp_request_failed"),
    ],
)
def test_invalid_or_rejected_erp_response_is_502(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
    error: Exception,
    code: str,
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"))
    fake_erp.error = error

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == code


def test_erp_returning_a_different_po_is_502(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"))
    fake_erp.purchase_orders["PO-1001"] = fake_erp.purchase_orders["PO-1004"]

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "erp_invalid_response"


# --- preconditions (ERP is never called) ----------------------------------------


def test_missing_invoice_is_404(db_client: TestClient, fake_erp: FakeERP) -> None:
    response = db_client.post(verify_url(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invoice_not_found"
    assert fake_erp.calls == []


def test_invoice_without_po_reference_is_422(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"), po_reference=None)

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invoice_missing_po_reference"
    assert fake_erp.calls == []


def test_supplier_without_erp_mapping_is_422(
    db_client: TestClient,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    supplier = make_supplier()  # no external_erp_id
    invoice = make_invoice(supplier)

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "supplier_not_mapped_to_erp"
    assert error["details"] == {"supplier_id": str(supplier.id)}
    assert fake_erp.calls == []


def test_invalid_invoice_id_is_422(db_client: TestClient, fake_erp: FakeERP) -> None:
    assert db_client.post(verify_url("not-a-uuid")).status_code == 422


# --- idempotency and transactions -------------------------------------------------


def test_repeated_verification_is_stable_and_writes_nothing(
    db_client: TestClient,
    db_session: Session,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"))

    first = db_client.post(verify_url(invoice["id"])).json()
    second = db_client.post(verify_url(invoice["id"])).json()

    assert first == second
    assert fake_erp.calls == ["po:PO-1001", "po:PO-1001"]
    after = db_client.get(f"/api/v1/invoices/{invoice['id']}").json()
    assert after == invoice  # same status and updated_at


def test_no_database_transaction_is_open_during_erp_call(
    db_client: TestClient,
    db_session: Session,
    fake_erp: FakeERP,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"))
    observed: list[bool] = []
    fake_erp.on_call = lambda: observed.append(db_session.in_transaction())

    db_client.post(verify_url(invoice["id"]))

    assert observed == [False]


# --- end to end through the real HTTP adapter --------------------------------------


@pytest.fixture
def real_http_erp(app: FastAPI) -> Iterator[None]:
    """HttpERPClient talking HTTP to the mock ERP app (in-process, no server)."""
    with TestClient(mock_erp_app) as http:
        client = HttpERPClient(http, sleep=lambda _: None)
        app.dependency_overrides[get_erp_client] = lambda: client
        yield


@pytest.mark.usefixtures("real_http_erp")
@pytest.mark.parametrize(
    ("external_erp_id", "po_number", "outcome"),
    [
        ("ERP-SUP-001", "PO-1001", "VERIFIED"),
        ("ERP-SUP-001", "PO-1004", "VERIFIED"),
        ("ERP-SUP-002", "PO-1001", "MISMATCH"),
        ("ERP-SUP-001", "PO-9999", "NOT_FOUND"),
        ("ERP-SUP-001", "PO/1001", "NOT_FOUND"),  # encoded, not a different route
    ],
)
def test_end_to_end_with_mock_erp(
    db_client: TestClient,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
    external_erp_id: str,
    po_number: str,
    outcome: str,
) -> None:
    invoice = make_invoice(make_supplier(external_erp_id=external_erp_id), po_reference=po_number)

    response = db_client.post(verify_url(invoice["id"]))

    assert response.status_code == 200
    assert response.json()["outcome"] == outcome


def test_end_to_end_unreachable_erp_retries_then_reports_unavailable(
    app: FastAPI,
    db_client: TestClient,
    make_supplier: Callable[..., Supplier],
    make_invoice: Callable[..., dict[str, Any]],
) -> None:
    attempts: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("connection refused")

    sleeps: list[float] = []
    with httpx.Client(base_url="http://erp.test", transport=httpx.MockTransport(refuse)) as http:
        client = HttpERPClient(http, max_attempts=3, sleep=sleeps.append)
        app.dependency_overrides[get_erp_client] = lambda: client
        invoice = make_invoice(make_supplier(external_erp_id="ERP-SUP-001"))

        response = db_client.post(verify_url(invoice["id"]))

    assert response.json()["outcome"] == "UNAVAILABLE"
    assert len(attempts) == 3
    assert len(sleeps) == 2
