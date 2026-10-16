class DomainError(Exception):
    """Base class for expected business errors. Free of HTTP concerns;
    app.main maps each subclass to a status code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass
