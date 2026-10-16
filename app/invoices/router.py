import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.erp import service as erp_service
from app.erp.client import ERPClient
from app.erp.http_client import get_erp_client
from app.erp.schemas import PurchaseOrderVerification
from app.invoices import service
from app.invoices.models import Invoice
from app.invoices.schemas import InvoiceCreate, InvoicePage, InvoiceRead

router = APIRouter(tags=["invoices"])

DbSession = Annotated[Session, Depends(get_db)]
ErpClient = Annotated[ERPClient, Depends(get_erp_client)]


@router.post("/invoices", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create_invoice(data: InvoiceCreate, db: DbSession) -> Invoice:
    return service.create_invoice(db, data)


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: uuid.UUID, db: DbSession) -> Invoice:
    return service.get_invoice(db, invoice_id)


@router.get("/suppliers/{supplier_id}/invoices", response_model=InvoicePage)
def list_supplier_invoices(
    supplier_id: uuid.UUID,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Sequence[Invoice] | int]:
    items = service.list_supplier_invoices(db, supplier_id, limit, offset)
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/invoices/{invoice_id}/verify-po", response_model=PurchaseOrderVerification)
def verify_purchase_order(
    invoice_id: uuid.UUID, db: DbSession, erp: ErpClient
) -> PurchaseOrderVerification:
    """Check the invoice's PO against the ERP. Read-only; never changes invoice status.

    ERP outcomes (VERIFIED, MISMATCH, NOT_FOUND, UNAVAILABLE) return 200.
    """
    return erp_service.verify_invoice_purchase_order(db, erp, invoice_id)
