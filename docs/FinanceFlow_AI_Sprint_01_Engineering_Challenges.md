# FinanceFlow AI — Sprint 1 Engineering Challenges & System Design Notes

**Scope:** Backend foundation and early design discussions  
**Status:** Learning and design review; not a claim that all scenarios are implemented or tested  
**Companion document:** `docs/ENGINEERING_NOTES.md`  
**Purpose:** Record engineering judgment, failure modes, tradeoffs, and realistic industry scenarios—**without implementation code**.

---

## 1. Sprint boundary: what we have actually done

In this sprint, we reviewed the planned modular backend architecture and the application foundation: configuration, application initialization, database engine, session factory, and request-scoped database dependency. We discussed the proposed Supplier and Invoice models, API contracts, and testing strategy, but their full CRUD implementation was **not verified as completed** in the materials reviewed.

We also held conceptual design discussions about ERP integration, supplier synchronization, race conditions, and idempotency. These are **future engineering challenges**, not completed production protections.

**Foundation topics reviewed:**
- Responsibility boundaries between HTTP APIs, business services, ORM, and database.
- Environment-based configuration and cached settings.
- Database engine, connection pool, sessions, transactions, and dependency injection.
- A modular monolith as the starting architecture.
- Domain identity and relational integrity for Suppliers and Invoices.
- Why migrations, validation, and tests matter even in a small application.

**Not yet established by our review:** supplier/invoice endpoints working end-to-end; database migration success; passing test suite; production authentication; ERP integration; AI extraction; LangGraph; RAG. Verify these individually instead of calling them complete.

---

## 2. Engineering concept: separate responsibilities

### The problem
An API becomes hard to modify when HTTP handling, business decisions, database access, and integrations all sit in the same function. Small changes can unintentionally affect unrelated functionality.

### Our current architectural direction
- **HTTP boundary:** receives requests, returns responses, and handles transport-level concerns.
- **Validation boundary:** checks that incoming data has the expected structure and types.
- **Business/service boundary:** owns invoice and supplier rules and coordinates operations.
- **Persistence boundary:** manages database sessions, queries, constraints, and transactions.
- **External integration boundary (future):** communicates with ERP systems through a client/adapter instead of mixing vendor-specific APIs into core business logic.

A **modular monolith** keeps these boundaries within one deployable backend. This is simpler to operate than multiple services while still allowing the code to evolve by business feature.

### Industrial challenge
A product team adds approval rules for different customers. If rules live in router handlers, the team risks duplicating them across invoice creation, review, and batch processing. Clear ownership makes a rule change easier to identify, test, and deploy.

### Tradeoff
Too little separation creates tightly coupled code; too many layers create indirection and maintenance overhead. We chose a service layer without a separate repository abstraction for the current scale.

**Review questions**
1. If invoice validation changes, which module should change and which should remain untouched?
2. What is the smallest change that would justify introducing a repository interface?
3. How would you prevent an ERP vendor-specific field from spreading across your finance domain?

---

## 3. Engineering concept: database engine versus connection versus session versus transaction

### The problem
It is easy to confuse opening a database session with saving a record. A successful HTTP response does not, by itself, mean a transaction was committed.

### Key distinctions
- **Engine:** long-lived database connectivity and connection-pool configuration.
- **Connection:** a checked-out communication channel to PostgreSQL.
- **Session:** a unit-of-work interface tracking ORM objects and coordinating database access.
- **Transaction:** the database boundary within which changes succeed together or are rolled back together.
- **Flush:** sends pending changes to the database within the transaction; does not necessarily commit them.
- **Commit:** completes the transaction and makes the changes durable under the database's guarantees.
- **Close:** releases session resources; does not automatically commit uncommitted changes.

The current request-scoped session dependency simplifies cleanup, but **transaction boundaries still need to be decided explicitly** when business operations are implemented.

### Industrial scenario: partial invoice creation
A future operation creates an invoice and an audit event. The invoice insert succeeds, but the audit insert fails. If the two belong to one database transaction, both can be rolled back. If they are committed separately, the system might contain an invoice with an incomplete audit history.

### Industrial scenario: a database call hangs
A connection timeout only limits connection establishment; it does not necessarily bound execution time for every database query. A slow query, lock wait, and network issue require different controls and instrumentation.

### Improvement to consider when needed
Define clear transaction ownership, distinguish transient failures from data-validation failures, and add query/lock timeouts appropriate to the environment. Avoid scattering independent commits across helper functions when one business operation requires atomicity.

**Review questions**
1. Why is adding an ORM object different from committing a transaction?
2. Who owns the commit: a service, an explicit unit-of-work boundary, or request middleware—and what are the consequences?
3. What happens if the process crashes after the database commits but before the client receives a response?

---

## 4. Engineering concept: configuration and environment boundaries

### The problem
Development, test, and production environments require different databases, credentials, logging, and availability settings. Hardcoded configuration can leak secrets or point tests at the wrong database.

### Current approach
Centralized settings loaded from environment variables and a local development file, with settings cached for reuse.

### Industrial challenges
- **Wrong-environment risk:** A test or migration accidentally connects to production.
- **Credential management:** Development credentials cannot be considered safe defaults for production.
- **Configuration drift:** Different deployment environments silently use incompatible values.
- **Runtime changes:** Cached settings do not automatically refresh when a configuration file changes.

### Design improvements
Require explicit secure production configuration, validate startup configuration, protect secrets, and make test database selection unambiguous. Keep non-secret defaults convenient for local development.

**Review questions**
1. Should the application start in production if its database URL is missing?
2. Why does a configuration cache help, and what operational behavior does it complicate?
3. Which settings can safely have defaults, and which must be supplied explicitly?

---

## 5. Engineering concept: data modeling and database-enforced invariants

### The problem
An API may validate a request correctly while a background worker, migration script, or concurrent request bypasses or defeats those checks.

### Design choices we reviewed
- Separate Supplier and Invoice business entities.
- Relate each invoice to an existing supplier using a foreign key.
- Use exact decimal representations for money instead of binary floating-point arithmetic.
- Consider uniqueness of a supplier's invoice number to catch common duplicates.
- Avoid cascading deletion of financial history when a supplier is removed.
- Add invoice lifecycle state to support future validation and review.

### Industrial scenario: concurrent duplicate insertion
Two requests check whether invoice `INV-101` exists. Both see nothing. Both try to insert. A check-then-insert in application logic is subject to a race; a correctly scoped database uniqueness constraint is the final safeguard.

### Industrial scenario: changing requirements
A client needs credit notes, discounts, extra charges, or currency precision beyond two decimal places. A rigid initial rule that `total = subtotal + tax` or assumes exactly two fractional digits for every currency can become an obstacle. We simplified initial amounts to a single total and currency, deferring richer accounting rules until their meaning is defined.

### Important limitation
A unique supplier/invoice-number pair is **duplicate-record protection**, not comprehensive payment idempotency or fraud detection. A supplier can potentially submit the same invoice with a different reference; business deduplication may need more evidence.

**Review questions**
1. Why enforce a nonnegative amount in both application validation and the database?
2. What does a foreign key protect us from that a request schema does not?
3. Should invoice identifiers be case-sensitive, and where must normalization be enforced?
4. Which financial rules belong in schema constraints versus versioned business-policy rules?

---

## 6. Engineering concept: migrations and changing a live system

### The problem
A database already contains important records when a new feature adds a column, changes a constraint, or creates a relationship. Recreating tables is not an acceptable upgrade strategy.

### Current direction
Use versioned schema migrations and review generated migration scripts rather than assuming a model definition changes the live database automatically.

### Industrial scenario: adding invoice status
If invoices already exist when a required status field is introduced, the migration must define what value applies to historical rows. A safe staged rollout may add a nullable column, backfill existing records, then enforce a not-null constraint.

### Industrial scenario: deployment compatibility
During a rolling deployment, older application instances and newer instances might run against the same database. Schema changes must avoid breaking the old version before all instances are updated.

### Design improvement
Prefer backward-compatible expand–migrate–contract changes when evolving a populated production schema. Validate migration outcomes against realistic test data.

**Review questions**
1. How would you add a required field to a table with one million existing invoices?
2. Why is reviewing autogenerated migrations necessary?
3. How can a database migration be safe while an application deployment is still in progress?

---

## 7. Engineering concept: testing boundaries and evidence

### The problem
A working health endpoint does not prove the database works. Passing schema unit tests does not prove database constraints, concurrent inserts, or full HTTP behavior.

### Testing layers to distinguish
- **Unit tests:** validation or business rules without external infrastructure.
- **API tests:** HTTP status, payload validation, error mapping, and endpoint behavior.
- **Integration tests:** actual PostgreSQL behavior, relationships, constraints, and transactions.
- **Migration tests:** changes to a real database schema.
- **Concurrency tests (later):** simultaneous operations with distinct sessions and transactions.

### Industrial scenario: false confidence from SQLite
SQLite and PostgreSQL differ in types, constraints, timestamp behavior, and concurrency. Passing tests in SQLite does not automatically prove behavior in PostgreSQL. A representative integration test database can catch differences before deployment.

### Industrial scenario: misleading health checks
A basic `/health` route may return success while PostgreSQL is unavailable. **Liveness** (the process is running) and **readiness** (the application can serve required work) are different operational signals. Whether readiness checks query PostgreSQL should reflect the service's actual dependencies.

### Current limitation
We reviewed testing plans but did not receive the test output or health-route implementation. Do not record these tests as passed until the results are observed.

**Review questions**
1. Which tests can run without a database, and which must use PostgreSQL?
2. What would convince you that database uniqueness holds under concurrent requests?
3. What should a load balancer do if the application is alive but its required database is unavailable?

---

## 8. ERP integration: data ownership and eventual consistency (discussed; not built)

### Initial decision
Use an `ERPClient` to communicate with the external ERP. A local Supplier table may also be useful for fast reads and availability, while the ERP remains authoritative for supplier master data and eligibility where the business defines it as such.

### Industrial scenario: stale supplier status
FinanceFlow's local supplier record says **Active**, but the ERP blocked the supplier thirty minutes ago. Local reads can continue during an outage, but the local record might not be safe for a consequential decision.

### Tradeoff
- **Read-through external ERP on every operation:** fresher information, but higher latency and dependency on ERP availability.
- **Local synchronized copy:** faster and more available, but eventually consistent.
- **Hybrid:** local reads for routine work and authoritative validation at high-risk boundaries.

### System improvement to investigate
Track source identifiers, last-sync timestamps, versions, and sync failures. Define explicit freshness and verification policies **per business operation**. A payment-authorizing ERP should enforce its own current eligibility constraints where its API supports that guarantee.

**Review questions**
1. Which information can be stale safely, and which cannot?
2. What should happen during ERP downtime: reject, queue for verification, or permit a limited operation?
3. How would you detect that synchronization silently stopped working?

---

## 9. TOCTOU: a check is not the same as an atomic decision (discussed; not built)

**Time-of-check to time-of-use (TOCTOU)** occurs when a fact changes after verification but before the action depending on that fact.

### Industrial scenario
FinanceFlow checks that a supplier is active. A second later, the ERP blocks the supplier. FinanceFlow proceeds to approve using the previous result.

### Engineering lesson
Checking the ERP again narrows the window of stale information but does not inherently remove the race. Stronger guarantees require the authoritative system to validate and perform the protected operation within an appropriate atomic or conditional boundary, if its integration interface allows that.

### Important product distinction
Internal **invoice review or approval** is not identical to **authorizing or executing payment**. Different stages may have different consistency and risk requirements.

**Review questions**
1. Where is the final authority for approval or payment?
2. Which checks must be repeated, and which must be enforced at commit time?
3. What if the ERP offers no atomic validation-and-action API?

---

## 10. Idempotency and unknown outcomes (discussed; not built)

### Industrial scenario
FinanceFlow asks the ERP to approve an invoice. The ERP commits the approval, but its response is lost. FinanceFlow sees a timeout and cannot tell whether the operation succeeded.

### Engineering lesson
A retry is not automatically safe. If the external system treats each request as a new action, retries can duplicate business side effects.

### Important distinctions
- **Same logical operation:** retries must retain the same operation identity, not generate a fresh idempotency key each attempt.
- **Server support:** a header alone does not make an ERP operation idempotent; the recipient must honor a deduplication contract, or another reconciliation strategy is needed.
- **Unknown outcome:** a timeout means confirmation was lost, not necessarily that the action failed.
- **Local uniqueness versus distributed idempotency:** a unique invoice row does not guarantee exactly-once processing across independently managed systems.

### Potential future improvement
Use durable operation records, stable idempotency keys, state such as `OUTCOME_UNKNOWN`, ERP status reconciliation, controlled retries, and idempotent side-effect boundaries where supported.

**Review questions**
1. What goes wrong if a retry creates a new random idempotency key?
2. How do we distinguish failed, succeeded, and unknown outcomes?
3. What changes when the ERP does not support idempotency keys?

---

## 11. Extensibility challenges to introduce when we have working APIs

These are **deliberately deferred**, not ignored.

| New requirement | Engineering challenge | Likely areas affected |
|---|---|---|
| Different invoice rules per customer | Policy ownership and versioning | Validation service, schema, tests |
| Supplier identifiers differ between ERP systems | Data mapping and identity resolution | ERP adapter, supplier model |
| Invoice submitted twice concurrently | Race condition and duplicate protection | Unique constraint, service error handling |
| Invoice status changes after review | State transitions and concurrency | Service, database, audit model |
| Supplier status updated during approval | TOCTOU and authoritative validation | ERP integration, workflow |
| ERP call times out after successful write | Idempotency and outcome reconciliation | Client, durable operations |
| New finance documents have variable layouts | Extraction uncertainty and data provenance | Document-processing subsystem |
| AI provider becomes unavailable | Dependency resilience and safe fallback | AI adapter, job processing |

**Engineering discipline:** Do not add a new layer simply because we can imagine a future requirement. Prefer a small change that solves a demonstrated problem, with clear evidence and tests.

---

## 12. Architecture decisions and tradeoffs recorded this sprint

| Decision | Why we selected it | Cost / limitation | Status |
|---|---|---|---|
| Modular monolith | Simple deployment with meaningful feature boundaries | Cross-module discipline must be maintained | Proposed/reviewed |
| Service layer without repository layer | Keeps business logic outside HTTP without premature indirection | Services are initially coupled to SQLAlchemy | Proposed/reviewed |
| Synchronous SQLAlchemy | Easier initial implementation and tests | Blocking database operations require sensible worker sizing | Reviewed in current foundation |
| PostgreSQL integration tests | Tests closer to real database semantics | Requires database setup and CI care | Proposed, not verified |
| Exact decimal amounts | Avoids binary floating-point money errors | Currency-specific rules still need design | Proposed for Invoice |
| Minimal invoice total | Avoids premature tax/discount assumptions | Rich accounting detail deferred | Proposed for Invoice |
| Local Supplier plus ERP adapter | Supports fast local reads and integration isolation | Synchronization and stale-data risk | Future design discussion |
| Deterministic finance validation | Reproducible rules and auditability | Requires finance policy expertise | Future implementation |

---

## 13. Sprint 1 design-review practice

Before asking an AI coding tool to make a change, write short answers to these prompts:

1. **Requirement:** What specific business behavior is being requested?
2. **Data ownership:** Which system is authoritative for each piece of information?
3. **Invariants:** What must never be allowed to become inconsistent?
4. **Failure modes:** What happens on invalid input, a timeout, a retry, and a crash?
5. **Concurrency:** Can two requests update the same information simultaneously?
6. **Tradeoff:** What is the simplest workable approach and what does it give up?
7. **Verification:** Which tests or observations prove the requirement works?
8. **Evolution:** What would change if customer-specific rules or another ERP were added?

### Practice exercise A — Database integrity
A supplier exists, an invoice is created, and a second request simultaneously submits the same supplier/invoice-number pair. Explain how the application should respond and what PostgreSQL must enforce.

### Practice exercise B — Transaction boundaries
An invoice record is created, but the following audit write fails. Decide what must commit together and how you would recover from a failure.

### Practice exercise C — Supplier availability
ERP is down but local supplier data is available. Define which operations should continue and which should pause.

### Practice exercise D — Unknown external outcome
An external approval times out after the ERP commits the operation. Define what FinanceFlow should record and how it should reconcile the state.

---

## 14. Sprint exit checklist

**Reviewed conceptually**
- [x] FastAPI's role in receiving and routing HTTP requests
- [x] Pydantic's role in application input validation
- [x] SQLAlchemy ORM, engine, sessions, and transactions
- [x] Dependency-injected, request-scoped database sessions
- [x] Environment-based settings and configuration caching
- [x] Modular monolith and feature-based organization
- [x] Supplier/Invoice data modeling tradeoffs
- [x] ERP data ownership, stale data, TOCTOU, and idempotency discussions

**To verify in the running project**
- [ ] Application and health endpoint operate as expected
- [ ] PostgreSQL connectivity is verified independently of basic liveness
- [ ] Tests are actually executed and passing
- [ ] Supplier/Invoice migrations are implemented and tested
- [ ] Invoice and supplier API behavior is verified end-to-end
- [ ] Transaction and duplicate-invoice behavior is tested

---

## 15. What to revisit before Sprint 2

Prioritize only these four questions before implementing Supplier and Invoice CRUD:

1. **Transaction ownership:** Where will we commit and roll back a business operation?
2. **Entity identity:** How do supplier IDs, invoice numbers, and eventual external ERP IDs differ?
3. **Database integrity:** Which rules must be guaranteed by PostgreSQL rather than trusted to Pydantic alone?
4. **Minimal testing evidence:** Which one successful request and which two failure cases prove each endpoint behaves correctly?

The rest of the distributed-systems challenges are intentionally parked until working endpoints and integrations provide a concrete reason to address them.

---

**Learning principle:** A strong engineer can explain **what the system guarantees, what it does not guarantee, how failures appear, why a tradeoff was chosen, and what evidence would validate the design**. Record these judgments as the system evolves, not only its features.
