class ERPError(Exception):
    """Base class for ERP integration failures. Free of HTTP-API concerns;
    app.erp.service translates them into verification outcomes or DomainErrors."""


class ERPNotFoundError(ERPError):
    """The ERP answered that the requested record does not exist (HTTP 404)."""


class ERPUnavailableError(ERPError):
    """The ERP could not be reached or kept failing transiently after retries."""


class ERPRequestError(ERPError):
    """The ERP rejected the request with a non-retryable status (e.g. 400, 401)."""


class ERPInvalidResponseError(ERPError):
    """The ERP returned malformed JSON or a body that violates the expected contract."""
