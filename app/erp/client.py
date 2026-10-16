from typing import Protocol

from app.erp.schemas import ERPPurchaseOrder, ERPSupplier


class ERPClient(Protocol):
    """Read operations FinanceFlow needs from an ERP.

    Implementations raise app.erp.errors exceptions: ERPNotFoundError,
    ERPUnavailableError, ERPRequestError, or ERPInvalidResponseError.
    """

    def get_supplier(self, external_supplier_id: str) -> ERPSupplier: ...

    def get_purchase_order(self, po_number: str) -> ERPPurchaseOrder: ...
