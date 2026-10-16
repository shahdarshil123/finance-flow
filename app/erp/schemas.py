"""Typed contracts for ERP responses. ERP data is untrusted until it validates here."""

import enum
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

from app.invoices.schemas import require_decimal_string

# Tolerant reader: unknown fields the ERP adds later are ignored, but every
# field we rely on must be present and well-typed.
_ERP_MODEL_CONFIG = ConfigDict(extra="ignore", frozen=True)

ERPIdentifier = Annotated[str, StringConstraints(min_length=1, max_length=64)]
# JSON numbers are rejected so amounts never pass through a binary float.
ERPDecimal = Annotated[Decimal, BeforeValidator(require_decimal_string)]


class PurchaseOrderStatus(enum.StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ERPSupplier(BaseModel):
    model_config = _ERP_MODEL_CONFIG

    external_supplier_id: ERPIdentifier
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    tax_id: str | None = None
    email: str | None = None


class ERPLineItem(BaseModel):
    model_config = _ERP_MODEL_CONFIG

    description: str
    quantity: ERPDecimal
    unit_price: ERPDecimal


class ERPPurchaseOrder(BaseModel):
    model_config = _ERP_MODEL_CONFIG

    po_number: ERPIdentifier
    external_supplier_id: ERPIdentifier
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    total_amount: ERPDecimal
    status: PurchaseOrderStatus
    line_items: list[ERPLineItem]


class VerificationOutcome(enum.StrEnum):
    VERIFIED = "VERIFIED"  # PO exists and belongs to the invoice's supplier
    MISMATCH = "MISMATCH"  # PO exists but belongs to another ERP supplier
    NOT_FOUND = "NOT_FOUND"  # ERP has no PO with this number
    UNAVAILABLE = "UNAVAILABLE"  # ERP unreachable or failing transiently; retry later


class PurchaseOrderVerification(BaseModel):
    invoice_id: uuid.UUID
    purchase_order_reference: str
    supplier_external_erp_id: str
    outcome: VerificationOutcome
    detail: str
    purchase_order: ERPPurchaseOrder | None
