"""HTTP ERP client tests on mocked transports: deterministic, no network, no sleeping."""

from collections.abc import Callable, Iterator
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.erp.errors import (
    ERPInvalidResponseError,
    ERPNotFoundError,
    ERPRequestError,
    ERPUnavailableError,
)
from app.erp.http_client import HttpERPClient
from app.erp.schemas import PurchaseOrderStatus
from mock_erp.main import app as mock_erp_app

Handler = Callable[[httpx.Request], httpx.Response]

PO_BODY = {
    "po_number": "PO-1001",
    "external_supplier_id": "ERP-SUP-001",
    "currency": "EUR",
    "total_amount": "1250.00",
    "status": "OPEN",
    "line_items": [{"description": "Paper", "quantity": "50", "unit_price": "25.00"}],
}
SUPPLIER_BODY = {
    "external_supplier_id": "ERP-SUP-001",
    "name": "Northwind Office Supplies",
    "tax_id": "DE100000001",
    "email": "ap@northwind.example",
}


class Recorder:
    """Transport handler replaying scripted responses and recording requests."""

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self._outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_client(sleeps: list[float]) -> Iterator[Callable[..., HttpERPClient]]:
    created: list[httpx.Client] = []

    def _make(handler: Handler, max_attempts: int = 3) -> HttpERPClient:
        http = httpx.Client(base_url="http://erp.test", transport=httpx.MockTransport(handler))
        created.append(http)
        return HttpERPClient(
            http,
            max_attempts=max_attempts,
            backoff_base_seconds=0.1,
            backoff_max_seconds=1.0,
            sleep=sleeps.append,
        )

    yield _make
    for http in created:
        http.close()


# --- success ------------------------------------------------------------------


def test_get_purchase_order_parses_decimal_strings(
    make_client: Callable[..., HttpERPClient],
) -> None:
    recorder = Recorder(httpx.Response(200, json=PO_BODY))

    po = make_client(recorder).get_purchase_order("PO-1001")

    assert recorder.requests[0].method == "GET"
    assert recorder.requests[0].url.path == "/erp/purchase-orders/PO-1001"
    assert po.total_amount == Decimal("1250.00")
    assert po.status is PurchaseOrderStatus.OPEN
    assert po.line_items[0].unit_price == Decimal("25.00")


def test_get_supplier(make_client: Callable[..., HttpERPClient]) -> None:
    recorder = Recorder(httpx.Response(200, json=SUPPLIER_BODY))

    supplier = make_client(recorder).get_supplier("ERP-SUP-001")

    assert recorder.requests[0].url.path == "/erp/suppliers/ERP-SUP-001"
    assert supplier.name == "Northwind Office Supplies"


def test_unknown_response_fields_are_ignored(make_client: Callable[..., HttpERPClient]) -> None:
    recorder = Recorder(httpx.Response(200, json={**SUPPLIER_BODY, "added_in_v2": True}))

    assert make_client(recorder).get_supplier("ERP-SUP-001").external_supplier_id == "ERP-SUP-001"


def test_path_values_are_percent_encoded(make_client: Callable[..., HttpERPClient]) -> None:
    recorder = Recorder(httpx.Response(404))

    with pytest.raises(ERPNotFoundError):
        make_client(recorder).get_purchase_order("PO/1001?x=1 #2")

    assert recorder.requests[0].url.raw_path == b"/erp/purchase-orders/PO%2F1001%3Fx%3D1%20%232"


def test_retry_then_success(make_client: Callable[..., HttpERPClient], sleeps: list[float]) -> None:
    recorder = Recorder(
        httpx.ConnectError("refused"), httpx.Response(503), httpx.Response(200, json=PO_BODY)
    )

    po = make_client(recorder).get_purchase_order("PO-1001")

    assert po.po_number == "PO-1001"
    assert len(recorder.requests) == 3
    assert sleeps == [0.1, 0.2]  # exponential backoff


# --- non-retryable failures -----------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 401, 403, 409, 422])
def test_client_errors_are_not_retried(
    make_client: Callable[..., HttpERPClient], sleeps: list[float], status_code: int
) -> None:
    recorder = Recorder(httpx.Response(status_code))

    with pytest.raises(ERPRequestError, match=str(status_code)):
        make_client(recorder).get_purchase_order("PO-1001")

    assert len(recorder.requests) == 1
    assert sleeps == []


def test_404_raises_not_found_without_retry(
    make_client: Callable[..., HttpERPClient], sleeps: list[float]
) -> None:
    recorder = Recorder(httpx.Response(404, json={"detail": "purchase_order_not_found"}))

    with pytest.raises(ERPNotFoundError):
        make_client(recorder).get_purchase_order("PO-9999")

    assert len(recorder.requests) == 1
    assert sleeps == []


def test_malformed_json_is_invalid_response_not_retried(
    make_client: Callable[..., HttpERPClient],
) -> None:
    recorder = Recorder(httpx.Response(200, content=b"{not json"))

    with pytest.raises(ERPInvalidResponseError, match="malformed JSON"):
        make_client(recorder).get_purchase_order("PO-1001")

    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        {**PO_BODY, "total_amount": 1250.0},  # JSON number, not a decimal string
        {**PO_BODY, "total_amount": "12e2"},  # exponent notation
        {**PO_BODY, "status": "DRAFT"},
        {**PO_BODY, "currency": "eur"},
        {k: v for k, v in PO_BODY.items() if k != "external_supplier_id"},
        {**PO_BODY, "line_items": [{"description": "x", "quantity": "1"}]},
        [PO_BODY],
    ],
    ids=["float-amount", "exponent", "status", "currency", "missing-supplier", "line-item", "list"],
)
def test_unexpected_schema_is_invalid_response(
    make_client: Callable[..., HttpERPClient], body: object
) -> None:
    recorder = Recorder(httpx.Response(200, json=body))

    with pytest.raises(ERPInvalidResponseError, match="ERPPurchaseOrder contract"):
        make_client(recorder).get_purchase_order("PO-1001")


def test_unsupported_transport_error_fails_without_retry(
    make_client: Callable[..., HttpERPClient],
) -> None:
    recorder = Recorder(httpx.UnsupportedProtocol("bad scheme"))

    with pytest.raises(ERPUnavailableError):
        make_client(recorder).get_purchase_order("PO-1001")

    assert len(recorder.requests) == 1


# --- transient failures and retry exhaustion ------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.ReadTimeout("read timeout"),
        httpx.RemoteProtocolError("server disconnected"),
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(503),
        httpx.Response(504),
        httpx.Response(429),
    ],
    ids=lambda f: type(f).__name__ if isinstance(f, Exception) else f"HTTP{f.status_code}",
)
def test_transient_failures_exhaust_retries(
    make_client: Callable[..., HttpERPClient],
    sleeps: list[float],
    failure: httpx.Response | Exception,
) -> None:
    recorder = Recorder(failure, failure, failure)

    with pytest.raises(ERPUnavailableError, match="after 3 attempt"):
        make_client(recorder).get_purchase_order("PO-1001")

    assert len(recorder.requests) == 3  # bounded: exactly max_attempts
    assert sleeps == [0.1, 0.2]  # no sleep after the final attempt


def test_backoff_is_capped(make_client: Callable[..., HttpERPClient], sleeps: list[float]) -> None:
    recorder = Recorder(*[httpx.Response(503)] * 6)

    with pytest.raises(ERPUnavailableError):
        make_client(recorder, max_attempts=6).get_purchase_order("PO-1001")

    assert sleeps == [0.1, 0.2, 0.4, 0.8, 1.0]


def test_single_attempt_never_sleeps(
    make_client: Callable[..., HttpERPClient], sleeps: list[float]
) -> None:
    recorder = Recorder(httpx.Response(503))

    with pytest.raises(ERPUnavailableError):
        make_client(recorder, max_attempts=1).get_purchase_order("PO-1001")

    assert sleeps == []


def test_max_attempts_must_be_positive() -> None:
    with httpx.Client() as http, pytest.raises(ValueError):
        HttpERPClient(http, max_attempts=0)


# --- Retry-After ------------------------------------------------------------------


def test_429_honors_retry_after_seconds(
    make_client: Callable[..., HttpERPClient], sleeps: list[float]
) -> None:
    recorder = Recorder(
        httpx.Response(429, headers={"Retry-After": "0.75"}), httpx.Response(200, json=PO_BODY)
    )

    make_client(recorder).get_purchase_order("PO-1001")

    assert sleeps == [0.75]


def test_429_retry_after_longer_than_cap_gives_up(
    make_client: Callable[..., HttpERPClient], sleeps: list[float]
) -> None:
    recorder = Recorder(httpx.Response(429, headers={"Retry-After": "120"}))

    with pytest.raises(ERPUnavailableError, match="retry after"):
        make_client(recorder).get_purchase_order("PO-1001")

    assert len(recorder.requests) == 1
    assert sleeps == []


@pytest.mark.parametrize("header", ["Wed, 21 Oct 2026 07:28:00 GMT", "-5", "nan", "inf", ""])
def test_429_unusable_retry_after_falls_back_to_backoff(
    make_client: Callable[..., HttpERPClient], sleeps: list[float], header: str
) -> None:
    recorder = Recorder(
        httpx.Response(429, headers={"Retry-After": header}), httpx.Response(200, json=PO_BODY)
    )

    make_client(recorder).get_purchase_order("PO-1001")

    assert sleeps == [0.1]


# --- configuration and real contract ----------------------------------------------


def test_from_settings_applies_base_url_and_timeouts() -> None:
    settings = Settings(
        erp_base_url="http://erp.internal:9000",
        erp_connect_timeout_seconds=1.5,
        erp_read_timeout_seconds=4.0,
        erp_max_attempts=5,
    )

    client = HttpERPClient.from_settings(settings)

    http = client._http  # pyright: ignore[reportPrivateUsage]
    assert str(http.base_url) == "http://erp.internal:9000"
    assert http.timeout.connect == 1.5
    assert http.timeout.read == 4.0
    assert client._max_attempts == 5  # pyright: ignore[reportPrivateUsage]
    http.close()


def test_contract_against_mock_erp_service() -> None:
    """The real adapter parses what the mock ERP actually serves."""
    with TestClient(mock_erp_app) as http:
        client = HttpERPClient(http, sleep=lambda _: None)

        po = client.get_purchase_order("PO-1003")
        supplier = client.get_supplier(po.external_supplier_id)
        with pytest.raises(ERPNotFoundError):
            client.get_purchase_order("PO-9999")

    assert po.status is PurchaseOrderStatus.CANCELLED
    assert po.total_amount == Decimal("4200.00")
    assert supplier.external_supplier_id == "ERP-SUP-003"
