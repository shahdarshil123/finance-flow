"""Shared input validation for text accepted at the request boundary."""

import unicodedata

# Cc: control characters, including NUL (which PostgreSQL text columns cannot
#     store), tab, newline, DEL, and C1 controls.
# Cs: lone UTF-16 surrogates. JSON allows "\ud800", but it cannot be encoded
#     as UTF-8, so PostgreSQL cannot store it either.
_UNSUPPORTED_CATEGORIES = frozenset({"Cc", "Cs"})


def reject_unsupported_characters(value: str) -> str:
    """Reject characters that are invalid in single-line text fields."""
    for char in value:
        if unicodedata.category(char) in _UNSUPPORTED_CATEGORIES:
            raise ValueError(f"contains unsupported character U+{ord(char):04X}")
    return value
