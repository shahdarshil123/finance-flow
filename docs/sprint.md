Milestone	What we'll add
Sprint 1 — Foundation	FastAPI, SQLAlchemy, database sessions, transactions
Sprint 2 — Supplier & Invoice	CRUD, relationships, constraints, error handling
Sprint 3 — ERP Integration	External APIs, synchronization, idempotency, retries
Sprint 4 — Document Processing	PDF extraction, LLM structured outputs, validation
Sprint 5 — LangGraph	State management, checkpoints, human approval
Sprint 6 — RAG	Embeddings, retrieval, grounded answers, evaluation
Sprint 7 — Production Engineering	Security, observability, scalability, deployment

---

# Sprint 3 — ERP Integration (mock ERP)

## Scope

A working end-to-end integration with an external ERP, using a mock ERP
service, shaped so an ERPNext adapter can be added later without touching
the domain code.

- Separate mock ERP HTTP service with deterministic seed data.
- ERP client behind a `Protocol`, one HTTP adapter (httpx), typed contracts.
- Supplier ↔ ERP identity mapping (`suppliers.external_erp_id`).
- Invoice purchase-order verification endpoint.
- Bounded retries with exponential backoff for read-only requests.
- Idempotent supplier import from the ERP.

Out of scope: amount/line-item matching, ERPNext, background sync.

## Completed implementation

### Mock ERP service — `mock_erp/` (separate process, port 8001)

| Endpoint | Response |
|---|---|
| `GET /erp/suppliers/{external_supplier_id}` | supplier, or 404 `supplier_not_found` |
| `GET /erp/purchase-orders/{po_number}` | purchase order, or 404 `purchase_order_not_found` |

Seed data (`mock_erp/data.py`), all synthetic:

| PO | Supplier | Currency | Total | Status |
|---|---|---|---|---|
| PO-1001 | ERP-SUP-001 Northwind Office Supplies | EUR | 1250.00 | OPEN |
| PO-1002 | ERP-SUP-002 Contoso Logistics | GBP | 980.50 | CLOSED |
| PO-1003 | ERP-SUP-003 Fabrikam Industrial Parts | USD | 4200.00 | CANCELLED |
| PO-1004 | ERP-SUP-001 Northwind Office Supplies | EUR | 312.75 | OPEN |

Money, quantities and unit prices are decimal strings. Line items sum to each
total (checked by a test). FinanceFlow never imports `mock_erp`; only tests do,
to run it in-process.

### ERP client — `app/erp/`

| File | Responsibility |
|---|---|
| `client.py` | `ERPClient` Protocol: `get_supplier`, `get_purchase_order` |
| `http_client.py` | `HttpERPClient` (httpx) + `get_erp_client` FastAPI dependency |
| `schemas.py` | ERP response models; verification response and outcomes |
| `service.py` | `verify_invoice_purchase_order`, `import_supplier_from_erp` |
| `errors.py` | `ERPNotFoundError`, `ERPUnavailableError`, `ERPRequestError`, `ERPInvalidResponseError` |

Configuration (`app/config.py`, environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `ERP_BASE_URL` | `http://127.0.0.1:8001` | ERP root URL |
| `ERP_CONNECT_TIMEOUT_SECONDS` | 2.0 | per attempt |
| `ERP_READ_TIMEOUT_SECONDS` | 3.0 | per attempt (also write/pool) |
| `ERP_MAX_ATTEMPTS` | 3 | total attempts incl. the first (1–10) |
| `ERP_BACKOFF_BASE_SECONDS` | 0.2 | delay = base × 2^(attempt−1) |
| `ERP_BACKOFF_MAX_SECONDS` | 2.0 | cap per sleep; a longer `Retry-After` stops retrying |

Failure handling:

| ERP behaviour | Retried? | Client raises |
|---|---|---|
| 2xx, valid body | — | parsed model |
| 404 | no | `ERPNotFoundError` |
| other 4xx (400, 401, 403, 409, 422…) | no | `ERPRequestError` |
| 429 | yes; honours `Retry-After` seconds ≤ cap, else stops; HTTP-date → backoff | `ERPUnavailableError` when exhausted |
| 500, 502, 503, 504 | yes | `ERPUnavailableError` when exhausted |
| connect error, connect/read/pool timeout, server disconnect | yes | `ERPUnavailableError` when exhausted |
| other transport errors (e.g. bad URL scheme) | no | `ERPUnavailableError` |
| malformed JSON | no | `ERPInvalidResponseError` |
| valid JSON, wrong schema (float money, unknown status, missing field…) | no | `ERPInvalidResponseError` |

Path values are percent-encoded, so a PO number like `PO/1001` cannot change
the URL route. Unknown extra fields in ERP responses are ignored.

### Supplier ↔ ERP identity

- New column `suppliers.external_erp_id VARCHAR(64) NULL`, unique
  (`uq_suppliers_external_erp_id`) and not blank
  (`ck_suppliers_external_erp_id_not_blank`). Migration `d9894c31a299`.
- Local UUIDs stay the primary key; invoices still reference `suppliers.id`.
- `POST /api/v1/suppliers` accepts optional `external_erp_id` (trimmed, case
  preserved); duplicates → 409 `supplier_external_erp_id_conflict`.
  `SupplierRead` gains `external_erp_id` (additive).
- `POST /api/v1/suppliers/import-from-erp/{external_supplier_id}` fetches the
  ERP supplier and upserts it with `INSERT … ON CONFLICT (external_erp_id) DO
  UPDATE … WHERE <data changed>`. Repeated or concurrent imports produce one
  local supplier; unchanged data writes nothing; changed name/tax_id/email are
  updated. ERP data goes through the same `SupplierCreate` validation as the API.

  | Case | Response |
  |---|---|
  | imported / updated / unchanged | 200 `SupplierRead` |
  | ERP has no such supplier | 404 `erp_supplier_not_found` |
  | ERP tax_id belongs to another local supplier | 409 `supplier_tax_id_conflict` |
  | ERP data invalid / fails local validation | 502 `erp_invalid_response` |
  | ERP unavailable | 503 `erp_unavailable` |

### Invoice PO verification — `POST /api/v1/invoices/{invoice_id}/verify-po`

1. Load invoice and supplier, copy the PO reference and `external_erp_id`,
   then **commit to end the read transaction** before any network I/O.
2. Precondition errors (the ERP is not called):
   404 `invoice_not_found`, 422 `invoice_missing_po_reference`,
   422 `supplier_not_mapped_to_erp`.
3. Fetch the PO and compare `external_supplier_id` with the supplier's
   `external_erp_id` (exact match). Returns 200:

```json
{
  "invoice_id": "…",
  "purchase_order_reference": "PO-1001",
  "supplier_external_erp_id": "ERP-SUP-001",
  "outcome": "VERIFIED",
  "detail": "The purchase order belongs to the invoice's supplier.",
  "purchase_order": { "po_number": "PO-1001", "total_amount": "1250.00", "status": "OPEN", "...": "..." }
}
```

| Outcome | When | `purchase_order` |
|---|---|---|
| VERIFIED | PO belongs to the invoice's supplier (CLOSED/CANCELLED noted in `detail`) | present |
| MISMATCH | PO belongs to another ERP supplier | present |
| NOT_FOUND | ERP returned 404 | null |
| UNAVAILABLE | ERP unreachable / transient failures after retries | null |

An invalid or rejected ERP response is 502 (`erp_invalid_response`,
`erp_request_failed`), not UNAVAILABLE: retrying will not fix a contract bug.
Verification writes nothing and never changes invoice status.

## Acceptance criteria

| Criterion | Status |
|---|---|
| Mock ERP runs as a separate HTTP service with ≥3 suppliers and ≥3 POs | ✅ |
| PO has number, supplier ID, currency, total, status, line items; money as decimal strings | ✅ |
| `app/erp/` with Protocol, httpx adapter, schemas, service, errors | ✅ |
| Configurable base URL, timeouts, retries; dependency injection for tests | ✅ |
| `external_erp_id` with uniqueness; migration upgrade/downgrade; existing Supplier API unchanged | ✅ |
| `verify-po` returns VERIFIED / MISMATCH / NOT_FOUND / UNAVAILABLE; status not changed | ✅ |
| Only transient failures retried; 400/404 never retried; bounded attempts; Retry-After honoured | ✅ |
| No DB transaction held across ERP calls or backoff | ✅ (tested) |
| Idempotent supplier import keyed on the ERP ID | ✅ |
| ruff, pyright, pytest, alembic check pass | ✅ (see below) |

## Test results (2026-10-16)

```
uv run ruff check .          All checks passed!
uv run ruff format --check . 49 files already formatted
uv run pyright               0 errors, 0 warnings, 0 informations
uv run pytest -q             246 passed, 1 warning
alembic check (financeflow_test)  No new upgrade operations detected.
```

New tests: `test_mock_erp.py` 7, `test_erp_http_client.py` 41,
`test_supplier_erp_mapping.py` 20, `test_invoice_po_verification.py` 22,
`test_migrations.py` +1 (3 total). The single warning is Starlette's
`httpx`/`TestClient` deprecation notice, not from project code.

Also run: a live smoke test with both services as real processes
(import ×2, VERIFIED, MISMATCH, NOT_FOUND, invoice still RECEIVED, mock ERP
stopped → UNAVAILABLE after 3 logged attempts).

`alembic check` against the **local dev database** reports a pre-existing
drift unrelated to this sprint: `invoices.invoice_number_normalized` is
`TEXT` there but `VARCHAR(64)` in the migration and test database (the dev
database was created from an earlier draft of that migration). Rebuild the
dev database (`alembic downgrade 7f3851a76ffd && alembic upgrade head`,
which drops dev invoices) to clear it.

## Run locally

```bash
docker compose up -d                                   # PostgreSQL
uv run alembic upgrade head
uv run uvicorn mock_erp.main:app --port 8001           # terminal 1: mock ERP
uv run uvicorn app.main:app --port 8000 --reload       # terminal 2: FinanceFlow
```

Demo:

```bash
API=http://localhost:8000/api/v1
curl -X POST $API/suppliers/import-from-erp/ERP-SUP-001          # note the "id"
curl -X POST $API/invoices -H 'content-type: application/json' -d '{
  "supplier_id": "<id>", "invoice_number": "INV-DEMO-1",
  "invoice_date": "2026-10-01", "due_date": "2026-10-31",
  "currency": "EUR", "total_amount": "1250.00",
  "purchase_order_reference": "PO-1001"}'                       # note the invoice "id"
curl -X POST $API/invoices/<invoice-id>/verify-po                # VERIFIED
```

Use `PO-1002` for MISMATCH, `PO-9999` for NOT_FOUND, and stop the mock ERP for
UNAVAILABLE. On Windows a stopped local port times out instead of refusing
(~2.3 s per attempt), so UNAVAILABLE takes ~7.5 s with defaults; start
FinanceFlow with `ERP_CONNECT_TIMEOUT_SECONDS=1` for a quicker demo.

## Known limitations

- PO numbers are matched exactly (case-sensitive, after trimming at invoice
  creation); ERP supplier IDs are compared exactly.
- Verification results are not stored; there is no audit trail or history.
- Worst-case latency of one verification is bounded but not small:
  attempts × (connect + read timeout) + backoff ≈ 3 × 5 s + 0.6 s.
- Backoff has no jitter; many clients failing together retry in lockstep.
- No circuit breaker: every request retries against a down ERP.
- `MISMATCH` returns the other supplier's PO details; fine for internal AP
  users, revisit when roles/authorization exist.
- Linking an existing unmapped local supplier to an ERP ID needs a create
  with `external_erp_id` or an import; there is no update endpoint.
- The shared httpx client is created lazily and not closed on shutdown.

## Deferred

- **ERPNextAdapter**: implement `ERPClient` against ERPNext's REST API
  (auth, field mapping); no domain changes expected.
- **Amount and line-item matching** (two/three-way match) and any invoice
  status transitions it drives.
- **Advanced synchronization**: bulk/scheduled supplier sync, ERP-side
  deletions/deactivation, change detection (ERP `modified` timestamps),
  conflict resolution for locally edited suppliers.
- **Write operations to the ERP** (e.g. posting approved invoices): will need
  idempotency keys; not needed for read-only GETs.
- Verification history, circuit breaker, jittered backoff, metrics.
