class DomainError(Exception):
    """Base class for expected business errors. Free of HTTP concerns;
    app.main maps each subclass to a status code."""

    def __init__(self, code: str, message: str, details: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class InvalidReferenceError(DomainError):
    """A request refers to another entity (e.g. a supplier) that does not exist."""


class InvalidStateError(DomainError):
    """The entity exists but lacks what the operation needs (e.g. a PO reference)."""


class UpstreamError(DomainError):
    """An external system (e.g. the ERP) returned an invalid or rejected response."""


class UpstreamUnavailableError(DomainError):
    """An external system could not be reached or kept failing transiently."""
