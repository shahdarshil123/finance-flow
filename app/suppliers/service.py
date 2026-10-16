import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import violated_constraint
from app.errors import ConflictError, NotFoundError
from app.suppliers.models import Supplier
from app.suppliers.schemas import SupplierCreate

TAX_ID_UNIQUE_CONSTRAINT = "uq_suppliers_tax_id"
EXTERNAL_ERP_ID_UNIQUE_CONSTRAINT = "uq_suppliers_external_erp_id"


def create_supplier(db: Session, data: SupplierCreate) -> Supplier:
    """Create a supplier in its own transaction (this function owns the commit)."""
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Rely on the database constraint, not a prior SELECT, so concurrent
        # requests with the same tax_id cannot both succeed.
        raise_supplier_conflict(exc)
        raise
    return supplier


def raise_supplier_conflict(exc: IntegrityError) -> None:
    """Translate a supplier uniqueness violation into a ConflictError, if it is one."""
    constraint = violated_constraint(exc)
    if constraint == TAX_ID_UNIQUE_CONSTRAINT:
        raise ConflictError(
            "supplier_tax_id_conflict", "A supplier with this tax_id already exists."
        ) from exc
    if constraint == EXTERNAL_ERP_ID_UNIQUE_CONSTRAINT:
        raise ConflictError(
            "supplier_external_erp_id_conflict",
            "A supplier with this external_erp_id already exists.",
        ) from exc


def get_supplier(db: Session, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundError("supplier_not_found", f"Supplier {supplier_id} was not found.")
    return supplier
