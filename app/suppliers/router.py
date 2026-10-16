import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.suppliers import service
from app.suppliers.models import Supplier
from app.suppliers.schemas import SupplierCreate, SupplierRead

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(data: SupplierCreate, db: DbSession) -> Supplier:
    return service.create_supplier(db, data)


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier(supplier_id: uuid.UUID, db: DbSession) -> Supplier:
    return service.get_supplier(db, supplier_id)
