"""Deterministic, synthetic seed data. Money values are decimal strings."""

from typing import Any

SUPPLIERS: dict[str, dict[str, Any]] = {
    "ERP-SUP-001": {
        "external_supplier_id": "ERP-SUP-001",
        "name": "Northwind Office Supplies",
        "tax_id": "DE100000001",
        "email": "ap@northwind.example",
    },
    "ERP-SUP-002": {
        "external_supplier_id": "ERP-SUP-002",
        "name": "Contoso Logistics",
        "tax_id": "GB200000002",
        "email": "billing@contoso.example",
    },
    "ERP-SUP-003": {
        "external_supplier_id": "ERP-SUP-003",
        "name": "Fabrikam Industrial Parts",
        "tax_id": None,
        "email": None,
    },
}

PURCHASE_ORDERS: dict[str, dict[str, Any]] = {
    "PO-1001": {
        "po_number": "PO-1001",
        "external_supplier_id": "ERP-SUP-001",
        "currency": "EUR",
        "total_amount": "1250.00",
        "status": "OPEN",
        "line_items": [
            {"description": "A4 copy paper (box)", "quantity": "50", "unit_price": "20.00"},
            {"description": "Toner cartridge", "quantity": "5", "unit_price": "50.00"},
        ],
    },
    "PO-1002": {
        "po_number": "PO-1002",
        "external_supplier_id": "ERP-SUP-002",
        "currency": "GBP",
        "total_amount": "980.50",
        "status": "CLOSED",
        "line_items": [
            {
                "description": "Pallet freight, Leeds to Bristol",
                "quantity": "1",
                "unit_price": "980.50",
            },
        ],
    },
    "PO-1003": {
        "po_number": "PO-1003",
        "external_supplier_id": "ERP-SUP-003",
        "currency": "USD",
        "total_amount": "4200.00",
        "status": "CANCELLED",
        "line_items": [
            {"description": "Hydraulic pump", "quantity": "2", "unit_price": "1600.00"},
            {"description": "Seal kit", "quantity": "10", "unit_price": "100.00"},
        ],
    },
    "PO-1004": {
        "po_number": "PO-1004",
        "external_supplier_id": "ERP-SUP-001",
        "currency": "EUR",
        "total_amount": "312.75",
        "status": "OPEN",
        "line_items": [
            {"description": "Desk organiser", "quantity": "15", "unit_price": "20.85"},
        ],
    },
}
