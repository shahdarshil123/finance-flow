"""In-memory ERPClient for FinanceFlow integration tests."""

from collections.abc import Callable

from app.erp.errors import ERPNotFoundError
from app.erp.schemas import ERPPurchaseOrder, ERPSupplier
from mock_erp.data import PURCHASE_ORDERS, SUPPLIERS


class FakeERP:
    """Serves the mock ERP seed data, or raises `error` when set.

    `on_call` runs before each lookup, e.g. to observe database state while
    the "network call" is in progress.
    """

    def __init__(self) -> None:
        self.purchase_orders = {
            k: ERPPurchaseOrder.model_validate(v) for k, v in PURCHASE_ORDERS.items()
        }
        self.suppliers = {k: ERPSupplier.model_validate(v) for k, v in SUPPLIERS.items()}
        self.error: Exception | None = None
        self.on_call: Callable[[], None] | None = None
        self.calls: list[str] = []

    def get_supplier(self, external_supplier_id: str) -> ERPSupplier:
        self._record(f"supplier:{external_supplier_id}")
        if external_supplier_id not in self.suppliers:
            raise ERPNotFoundError(external_supplier_id)
        return self.suppliers[external_supplier_id]

    def get_purchase_order(self, po_number: str) -> ERPPurchaseOrder:
        self._record(f"po:{po_number}")
        if po_number not in self.purchase_orders:
            raise ERPNotFoundError(po_number)
        return self.purchase_orders[po_number]

    def _record(self, call: str) -> None:
        self.calls.append(call)
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error
