import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.invoices.models import (
    AMOUNT_PRECISION,
    AMOUNT_SCALE,
    INVOICE_NUMBER_MAX_LENGTH,
    InvoiceStatus,
)
from app.validation import reject_unsupported_characters

# Plain decimal notation only: no exponent, sign prefix "+", or surrounding spaces.
_DECIMAL_STRING = re.compile(r"-?\d+(\.\d+)?")


def require_decimal_string(value: object) -> object:
    """Accept money only as a decimal string (or Decimal from Python callers).

    JSON numbers are rejected: many JSON parsers decode them as binary floats,
    so the exact value may already be lost before it reaches the API.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str) and _DECIMAL_STRING.fullmatch(value):
        return value
    raise ValueError('must be a decimal string, e.g. "1250.00"')


def to_amount_scale(value: Decimal) -> Decimal:
    """Pad to the database scale ("7.5" -> "7.50") so responses match stored values.

    Never rounds: decimal_places validation has already rejected extra digits.
    """
    return value.quantize(Decimal(1).scaleb(-AMOUNT_SCALE))


Money = Annotated[
    Decimal,
    BeforeValidator(require_decimal_string),
    Field(
        ge=0,
        max_digits=AMOUNT_PRECISION,
        decimal_places=AMOUNT_SCALE,
        description='Decimal string with at most 2 decimal places, e.g. "1250.00".',
    ),
    AfterValidator(to_amount_scale),
]
InvoiceNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=INVOICE_NUMBER_MAX_LENGTH),
    AfterValidator(reject_unsupported_characters),
    Field(description="Supplier's invoice number. Unique per supplier, case-insensitive."),
]
PurchaseOrderReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    AfterValidator(reject_unsupported_characters),
]
CurrencyCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z]{3}$"),
    Field(description="ISO 4217 format: three uppercase letters, e.g. EUR."),
]


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: uuid.UUID
    invoice_number: InvoiceNumber
    invoice_date: date
    due_date: date
    currency: CurrencyCode
    total_amount: Money
    purchase_order_reference: PurchaseOrderReference | None = None

    @model_validator(mode="after")
    def due_date_not_before_invoice_date(self) -> Self:
        if self.due_date < self.invoice_date:
            raise ValueError("due_date must not be before invoice_date")
        return self


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    invoice_number: str
    invoice_date: date
    due_date: date
    currency: str
    total_amount: Decimal  # serialized as a JSON string
    status: InvoiceStatus
    purchase_order_reference: str | None
    created_at: datetime
    updated_at: datetime


class InvoicePage(BaseModel):
    items: list[InvoiceRead]
    limit: int
    offset: int
