import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EXTERNAL_ERP_ID_MAX_LENGTH = 64


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        # Mirrors schema validation so scripts and future workers can't bypass it.
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("btrim(external_erp_id) <> ''", name="external_erp_id_not_blank"),
    )
    # Load server-generated timestamps via INSERT ... RETURNING (no extra SELECT).
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    # Optional; unique when present (PostgreSQL allows multiple NULLs).
    tax_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    # Supplier identity in the external ERP, separate from the local UUID that
    # invoices reference. Optional; unique when present.
    external_erp_id: Mapped[str | None] = mapped_column(
        String(EXTERNAL_ERP_ID_MAX_LENGTH), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
