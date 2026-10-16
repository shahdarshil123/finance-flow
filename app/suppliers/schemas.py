import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.validation import reject_unsupported_characters

TAX_ID_MAX_LENGTH = 50  # matches suppliers.tax_id VARCHAR(50)


def normalize_tax_id(value: str) -> str:
    """Trim, reject unsupported characters, uppercase, then check length.

    Length is checked after uppercasing because Unicode uppercasing can
    lengthen a string ("ß" -> "SS", "ﬃ" -> "FFI").
    """
    value = reject_unsupported_characters(value.strip()).upper()
    if not value:
        raise ValueError("must not be blank")
    if len(value) > TAX_ID_MAX_LENGTH:
        raise ValueError(f"must be at most {TAX_ID_MAX_LENGTH} characters after normalization")
    return value


SupplierName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    AfterValidator(reject_unsupported_characters),
]
TaxId = Annotated[
    str,
    AfterValidator(normalize_tax_id),
    Field(
        description=(
            "Supplier tax or registration identifier, stored exactly as normalized: "
            "surrounding whitespace trimmed and Unicode uppercased so duplicates are "
            "detected case-insensitively. Any jurisdiction's format is accepted (not "
            "limited to ASCII); internal spaces and punctuation are kept as given and "
            "the value is not checked against country-specific rules. Control "
            "characters are rejected. At most 50 characters after normalization."
        ),
    ),
]


class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SupplierName
    tax_id: TaxId | None = None
    email: EmailStr | None = None


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    tax_id: str | None
    email: str | None
    created_at: datetime
    updated_at: datetime
