"""Contract tests for the mock ERP service (no database)."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from mock_erp.data import PURCHASE_ORDERS, SUPPLIERS
from mock_erp.main import app


@pytest.fixture
def erp() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def test_seed_data_has_at_least_three_suppliers_and_purchase_orders() -> None:
    assert len(SUPPLIERS) >= 3
    assert len(PURCHASE_ORDERS) >= 3
    assert {po["status"] for po in PURCHASE_ORDERS.values()} == {"OPEN", "CLOSED", "CANCELLED"}


def test_seed_purchase_orders_reference_known_suppliers_and_totals_add_up() -> None:
    for po in PURCHASE_ORDERS.values():
        assert po["external_supplier_id"] in SUPPLIERS
        line_total = sum(
            Decimal(item["quantity"]) * Decimal(item["unit_price"]) for item in po["line_items"]
        )
        assert line_total == Decimal(po["total_amount"])


def test_get_supplier_returns_contract(erp: TestClient) -> None:
    response = erp.get("/erp/suppliers/ERP-SUP-001")

    assert response.status_code == 200
    assert response.json() == {
        "external_supplier_id": "ERP-SUP-001",
        "name": "Northwind Office Supplies",
        "tax_id": "DE100000001",
        "email": "ap@northwind.example",
    }


def test_get_purchase_order_returns_contract_with_decimal_strings(erp: TestClient) -> None:
    response = erp.get("/erp/purchase-orders/PO-1001")

    assert response.status_code == 200
    body = response.json()
    assert body["po_number"] == "PO-1001"
    assert body["external_supplier_id"] == "ERP-SUP-001"
    assert body["currency"] == "EUR"
    assert body["status"] == "OPEN"
    assert body["total_amount"] == "1250.00"
    assert body["line_items"][0] == {
        "description": "A4 copy paper (box)",
        "quantity": "50",
        "unit_price": "20.00",
    }


def test_unknown_supplier_returns_404(erp: TestClient) -> None:
    response = erp.get("/erp/suppliers/ERP-SUP-999")

    assert response.status_code == 404
    assert response.json() == {"detail": "supplier_not_found"}


def test_unknown_purchase_order_returns_404(erp: TestClient) -> None:
    response = erp.get("/erp/purchase-orders/PO-9999")

    assert response.status_code == 404
    assert response.json() == {"detail": "purchase_order_not_found"}


def test_purchase_order_lookup_is_case_sensitive(erp: TestClient) -> None:
    assert erp.get("/erp/purchase-orders/po-1001").status_code == 404
