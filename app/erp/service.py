"""ERP integration operations.

Pattern for every operation: read local state, end the database transaction,
call the ERP (which may retry and sleep), then open a new short transaction
only if something must be written. No transaction is held across network I/O.
"""

import logging
import uuid

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.erp.client import ERPClient
from app.erp.errors import (
    ERPError,
    ERPInvalidResponseError,
    ERPNotFoundError,
    ERPUnavailableError,
)
from app.erp.schemas import (
    ERPPurchaseOrder,
    PurchaseOrderStatus,
    PurchaseOrderVerification,
    VerificationOutcome,
)
from app.errors import (
    DomainError,
    InvalidStateError,
    NotFoundError,
    UpstreamError,
    UpstreamUnavailableError,
)
from app.invoices.service import get_invoice
from app.suppliers.models import Supplier
from app.suppliers.schemas import SupplierCreate
from app.suppliers.service import (
    EXTERNAL_ERP_ID_UNIQUE_CONSTRAINT,
    get_supplier,
    raise_supplier_conflict,
)

logger = logging.getLogger(__name__)

# Fields an ERP import may overwrite on an already-imported supplier.
_SYNCED_SUPPLIER_FIELDS = ("name", "tax_id", "email")


def verify_invoice_purchase_order(
    db: Session, erp: ERPClient, invoice_id: uuid.UUID
) -> PurchaseOrderVerification:
    """Check that the invoice's PO exists in the ERP and belongs to its supplier.

    Read-only: nothing is persisted and the invoice status is never changed,
    so repeated calls are safe. Amount and line-item matching come later.
    """
    invoice = get_invoice(db, invoice_id)
    supplier = get_supplier(db, invoice.supplier_id)
    po_reference = invoice.purchase_order_reference
    supplier_id = supplier.id
    external_erp_id = supplier.external_erp_id
    # End the read-only transaction (returning its connection to the pool)
    # before network I/O, so ERP retries and backoff sleeps never hold it.
    db.commit()

    if po_reference is None:
        raise InvalidStateError(
            "invoice_missing_po_reference",
            f"Invoice {invoice_id} has no purchase_order_reference to verify.",
        )
    if external_erp_id is None:
        raise InvalidStateError(
            "supplier_not_mapped_to_erp",
            f"Supplier {supplier_id} has no external_erp_id, so its ERP purchase orders "
            "cannot be identified.",
            details={"supplier_id": str(supplier_id)},
        )

    def result(
        outcome: VerificationOutcome, detail: str, po: ERPPurchaseOrder | None = None
    ) -> PurchaseOrderVerification:
        logger.info("PO verification invoice=%s po=%s: %s", invoice_id, po_reference, outcome)
        return PurchaseOrderVerification(
            invoice_id=invoice_id,
            purchase_order_reference=po_reference,
            supplier_external_erp_id=external_erp_id,
            outcome=outcome,
            detail=detail,
            purchase_order=po,
        )

    try:
        po = erp.get_purchase_order(po_reference)
    except ERPNotFoundError:
        return result(
            VerificationOutcome.NOT_FOUND, "The ERP has no purchase order with this number."
        )
    except ERPUnavailableError:
        logger.warning("ERP unavailable during PO verification", exc_info=True)
        return result(
            VerificationOutcome.UNAVAILABLE, "The ERP could not be reached. Try again later."
        )
    except ERPError as exc:
        raise _to_domain_error(exc) from exc

    if po.po_number != po_reference:
        raise UpstreamError(
            "erp_invalid_response", "The ERP returned a different purchase order than requested."
        )
    if po.external_supplier_id != external_erp_id:
        return result(
            VerificationOutcome.MISMATCH,
            f"The purchase order belongs to ERP supplier {po.external_supplier_id}, "
            f"not {external_erp_id}.",
            po,
        )
    detail = "The purchase order belongs to the invoice's supplier."
    if po.status is not PurchaseOrderStatus.OPEN:
        detail += f" Note: the purchase order is {po.status.value}."
    return result(VerificationOutcome.VERIFIED, detail, po)


def import_supplier_from_erp(db: Session, erp: ERPClient, external_supplier_id: str) -> Supplier:
    """Create or update the local supplier mapped to an ERP supplier.

    Idempotent: keyed on the stable ERP identifier and resolved atomically by
    the unique constraint (INSERT ... ON CONFLICT), so repeated or concurrent
    imports leave one local supplier. Re-importing unchanged data writes nothing.
    """
    try:
        erp_supplier = erp.get_supplier(external_supplier_id)
    except ERPNotFoundError as exc:
        raise NotFoundError(
            "erp_supplier_not_found", f"ERP supplier {external_supplier_id} was not found."
        ) from exc
    except ERPError as exc:
        raise _to_domain_error(exc) from exc

    if erp_supplier.external_supplier_id != external_supplier_id:
        raise UpstreamError(
            "erp_invalid_response", "The ERP returned a different supplier than requested."
        )
    try:
        # Same validation and normalization as suppliers created through the API.
        data = SupplierCreate(
            name=erp_supplier.name,
            tax_id=erp_supplier.tax_id,
            email=erp_supplier.email,
            external_erp_id=erp_supplier.external_supplier_id,
        )
    except ValidationError as exc:
        raise UpstreamError(
            "erp_invalid_response", "The ERP supplier record failed local validation."
        ) from exc

    columns = Supplier.__table__.c
    statement = insert(Supplier).values(id=uuid.uuid4(), **data.model_dump())
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        constraint=EXTERNAL_ERP_ID_UNIQUE_CONSTRAINT,
        set_={**{f: excluded[f] for f in _SYNCED_SUPPLIER_FIELDS}, "updated_at": func.now()},
        # Skip the write (and the updated_at bump) when nothing changed.
        where=or_(*(columns[f].is_distinct_from(excluded[f]) for f in _SYNCED_SUPPLIER_FIELDS)),
    )
    try:
        db.execute(statement)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # e.g. the ERP tax_id already belongs to a different local supplier.
        raise_supplier_conflict(exc)
        raise

    supplier = db.scalar(
        select(Supplier)
        .where(Supplier.external_erp_id == data.external_erp_id)
        .execution_options(populate_existing=True)
    )
    assert supplier is not None  # just inserted or updated under the unique key
    return supplier


def _to_domain_error(exc: ERPError) -> DomainError:
    if isinstance(exc, ERPUnavailableError):
        return UpstreamUnavailableError("erp_unavailable", "The ERP could not be reached.")
    if isinstance(exc, ERPInvalidResponseError):
        return UpstreamError("erp_invalid_response", "The ERP returned an invalid response.")
    return UpstreamError("erp_request_failed", "The ERP rejected the request.")
