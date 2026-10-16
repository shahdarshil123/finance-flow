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
