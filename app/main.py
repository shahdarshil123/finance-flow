import json
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import health
from app.config import get_settings
from app.errors import (
    ConflictError,
    DomainError,
    InvalidReferenceError,
    InvalidStateError,
    NotFoundError,
    UpstreamError,
    UpstreamUnavailableError,
)
from app.invoices.router import router as invoices_router
from app.suppliers.router import router as suppliers_router

_DOMAIN_ERROR_STATUS: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidReferenceError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InvalidStateError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UpstreamError: status.HTTP_502_BAD_GATEWAY,
    UpstreamUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


class _AsciiJSONResponse(JSONResponse):
    """Escapes non-ASCII characters, so a lone surrogate in user input that is
    echoed back in an error response can't fail UTF-8 encoding."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=True, allow_nan=False).encode("ascii")


def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):  # registered for DomainError only
        raise exc
    status_code = _DOMAIN_ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
    error: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        error["details"] = exc.details
    return JSONResponse(status_code=status_code, content={"error": error})


def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # registered for it only
        raise exc
    # Same body as FastAPI's default handler; only the encoding differs.
    return _AsciiJSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(exc.errors())},
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.include_router(health.router)
    app.include_router(suppliers_router, prefix="/api/v1")
    app.include_router(invoices_router, prefix="/api/v1")
    return app


app = create_app()
