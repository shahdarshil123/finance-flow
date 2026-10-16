"""Mock ERP HTTP API. Run with: uv run uvicorn mock_erp.main:app --port 8001"""

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mock_erp.data import PURCHASE_ORDERS, SUPPLIERS


class ERPSupplier(BaseModel):
    external_supplier_id: str
    name: str
    tax_id: str | None
    email: str | None


class ERPLineItem(BaseModel):
    description: str
    quantity: str
    unit_price: str


class ERPPurchaseOrder(BaseModel):
    po_number: str
    external_supplier_id: str
    currency: str
    total_amount: str
    status: Literal["OPEN", "CLOSED", "CANCELLED"]
    line_items: list[ERPLineItem]


app = FastAPI(title="Mock ERP", version="0.1.0")


@app.get("/erp/suppliers/{external_supplier_id}", response_model=ERPSupplier)
def get_supplier(external_supplier_id: str) -> dict[str, object]:
    supplier = SUPPLIERS.get(external_supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="supplier_not_found")
    return supplier


@app.get("/erp/purchase-orders/{po_number}", response_model=ERPPurchaseOrder)
def get_purchase_order(po_number: str) -> dict[str, object]:
    purchase_order = PURCHASE_ORDERS.get(po_number)
    if purchase_order is None:
        raise HTTPException(status_code=404, detail="purchase_order_not_found")
    return purchase_order
