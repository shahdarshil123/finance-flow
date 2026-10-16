import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.erp import service as erp_service
from app.erp.client import ERPClient
from app.erp.http_client import get_erp_client
from app.suppliers import service
from app.suppliers.models import Supplier
from app.suppliers.schemas import SupplierCreate, SupplierRead

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

DbSession = Annotated[Session, Depends(get_db)]
ErpClient = Annotated[ERPClient, Depends(get_erp_client)]


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(data: SupplierCreate, db: DbSession) -> Supplier:
    return service.create_supplier(db, data)


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier(supplier_id: uuid.UUID, db: DbSession) -> Supplier:
    return service.get_supplier(db, supplier_id)


@router.post("/import-from-erp/{external_supplier_id}", response_model=SupplierRead)
def import_supplier_from_erp(external_supplier_id: str, db: DbSession, erp: ErpClient) -> Supplier:
    """Create or update the local supplier for an ERP supplier. Idempotent."""
    return erp_service.import_supplier_from_erp(db, erp, external_supplier_id)
