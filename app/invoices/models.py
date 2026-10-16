import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

INVOICE_NUMBER_MAX_LENGTH = 64
AMOUNT_PRECISION = 18
AMOUNT_SCALE = 2


class InvoiceStatus(enum.StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        # Duplicate protection: one invoice number per supplier, case-insensitive.
        UniqueConstraint(
            "supplier_id",
            "invoice_number_normalized",
            name="uq_invoices_supplier_id_invoice_number_normalized",
        ),
        # Mirror schema validation so scripts and future workers can't bypass it.
        CheckConstraint("btrim(invoice_number) <> ''", name="invoice_number_not_blank"),
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        CheckConstraint("due_date >= invoice_date", name="due_date_not_before_invoice_date"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_4217_format"),
        # Declared explicitly: Enum(create_constraint=True) emits a duplicate,
        # unconventionally named constraint under our naming convention.
        CheckConstraint(
            "status IN ({})".format(", ".join(f"'{s.value}'" for s in InvoiceStatus)),
            name="status_valid",
        ),
        Index("ix_invoices_supplier_id_invoice_date", "supplier_id", "invoice_date"),
    )
    # Load server-generated values via INSERT ... RETURNING (no extra SELECT).
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    # As submitted (trimmed), for display and audit.
    invoice_number: Mapped[str] = mapped_column(String(INVOICE_NUMBER_MAX_LENGTH))
    # Computed by PostgreSQL so every writer (API, scripts, future extraction
    # workers) normalizes identically; the uniqueness constraint uses it.
    invoice_number_normalized: Mapped[str] = mapped_column(
        String(INVOICE_NUMBER_MAX_LENGTH), Computed("upper(invoice_number)", persisted=True)
    )
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(AMOUNT_PRECISION, AMOUNT_SCALE))
    # VARCHAR + CHECK rather than a native PostgreSQL enum: adding states later
    # (e.g. for AI extraction review) is a simple constraint change.
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, native_enum=False, length=20, validate_strings=True),
        server_default=InvoiceStatus.RECEIVED.value,
    )
    # Free-text reference for future purchase order matching; not a foreign key
    # because purchase orders are not modeled yet.
    purchase_order_reference: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
