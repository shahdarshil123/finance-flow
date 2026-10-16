import logging
import math
import time
from collections.abc import Callable
from functools import lru_cache
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.erp.client import ERPClient
from app.erp.errors import (
    ERPInvalidResponseError,
    ERPNotFoundError,
    ERPRequestError,
    ERPUnavailableError,
)
from app.erp.schemas import ERPPurchaseOrder, ERPSupplier

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Failures where the request may not have reached the ERP or the ERP may
# recover. Other transport errors (e.g. an unsupported URL scheme) are
# configuration problems and fail without retrying.
RETRYABLE_TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


class HttpERPClient:
    """ERP client over HTTP with bounded exponential backoff.

    Only used for idempotent GETs, so retrying is safe. It never touches the
    database; callers must not hold a transaction open while calling it.
    """

    def __init__(
        self,
        http: httpx.Client,
        *,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.2,
        backoff_max_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._http = http
        self._max_attempts = max_attempts
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> "HttpERPClient":
        http = httpx.Client(
            base_url=settings.erp_base_url,
            timeout=httpx.Timeout(
                settings.erp_read_timeout_seconds, connect=settings.erp_connect_timeout_seconds
            ),
        )
        return cls(
            http,
            max_attempts=settings.erp_max_attempts,
            backoff_base_seconds=settings.erp_backoff_base_seconds,
            backoff_max_seconds=settings.erp_backoff_max_seconds,
        )

    def get_supplier(self, external_supplier_id: str) -> ERPSupplier:
        return self._get(f"/erp/suppliers/{_path_segment(external_supplier_id)}", ERPSupplier)

    def get_purchase_order(self, po_number: str) -> ERPPurchaseOrder:
        return self._get(f"/erp/purchase-orders/{_path_segment(po_number)}", ERPPurchaseOrder)

    def _get[ModelT: BaseModel](self, path: str, model: type[ModelT]) -> ModelT:
        for attempt in range(1, self._max_attempts + 1):
            retry_after: float | None = None
            cause: Exception | None = None
            try:
                response = self._http.get(path)
            except RETRYABLE_TRANSPORT_ERRORS as exc:
                failure = type(exc).__name__
                cause = exc
            except httpx.HTTPError as exc:
                raise ERPUnavailableError(f"ERP request failed: {type(exc).__name__}") from exc
            else:
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    return _parse(response, model)
                failure = f"HTTP {response.status_code}"
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response)

            if attempt == self._max_attempts:
                raise ERPUnavailableError(
                    f"ERP unavailable after {attempt} attempt(s): {failure}"
                ) from cause
            delay = self._backoff_delay(attempt, retry_after)
            if delay is None:
                # Retrying sooner than the ERP asked would not help; give up now.
                raise ERPUnavailableError(
                    f"ERP asked to retry after {retry_after}s, longer than allowed"
                ) from cause
            logger.warning(
                "ERP GET %s failed (%s), attempt %d/%d; retrying in %.2fs",
                path,
                failure,
                attempt,
                self._max_attempts,
                delay,
            )
            self._sleep(delay)
        raise AssertionError("unreachable")  # the loop always returns or raises

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float | None:
        if retry_after is not None:
            return retry_after if retry_after <= self._backoff_max_seconds else None
        return min(self._backoff_max_seconds, self._backoff_base_seconds * 2 ** (attempt - 1))


def _path_segment(value: str) -> str:
    # Encode "/", "?", "#", spaces, etc. so the value cannot change the URL path.
    return quote(value, safe="")


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Retry-After in delta-seconds form; HTTP-date form falls back to backoff."""
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _parse[ModelT: BaseModel](response: httpx.Response, model: type[ModelT]) -> ModelT:
    if response.status_code == 404:
        raise ERPNotFoundError(f"ERP record not found: {response.request.url.path}")
    if not response.is_success:
        raise ERPRequestError(f"ERP rejected the request with HTTP {response.status_code}")
    try:
        return model.model_validate_json(response.content)
    except ValidationError as exc:
        if any(error["type"] == "json_invalid" for error in exc.errors()):
            raise ERPInvalidResponseError("ERP returned malformed JSON") from exc
        raise ERPInvalidResponseError(
            f"ERP response did not match the {model.__name__} contract"
        ) from exc


@lru_cache
def get_erp_client() -> ERPClient:
    """FastAPI dependency: one shared, thread-safe client (connection pooling).
    Tests override it with a fake or a client on httpx.MockTransport."""
    return HttpERPClient.from_settings(get_settings())
