# Unified Pricing Read Layer (UPRL) — Product Proposal & Prototype Documentation

**Status**: Proposal — the product does not exist yet. This document and the accompanying prototype are the proposal artifacts.
**Audience**: Order Platform engineering, vertical service teams, finance/settlement stakeholders, architecture review.
**Prototype**: this repository (Streamlit + SQLite + Pydantic).
**Last updated**: 2026-07-04

---

## 1. Problem Statement

Tiket.com operates as a multi-vertical OTA: hotels, flights, trains, entertainment/attractions (passes), tours, transfers, and B2B affiliate distribution. Each vertical runs its own microservices, and each of those services holds a *partial, differently-shaped* view of what an order costs, what was paid, what we owe suppliers, and what was refunded:

- **Pricing** lives in vertical services, each with its own component vocabulary (BaseFare vs RoomRate vs ticket price), granularity (order / order-detail / pax / leg / night), and repricing behavior.
- **Payment state** lives in the payment service with its own lifecycle (checkout → authorized → captured → refunded/settled) and instruments (cards, wallets, loyalty points).
- **Supplier obligations** live in fulfillment/supplier services — with statuses, cancellation fees, commissions, and (for B2B) affiliate sharebacks and withholding taxes, all evolving after the initial booking.
- **Refunds** live in the refund service, referencing pricing components that may have been repriced since.

The consequences, observed across the organization:

1. **No single answer to "what is the financial state of this order?"** Answering it requires joining data from 4+ services with incompatible schemas, versioning rules, and identity schemes. Every consumer (finance, customer service, analytics, settlement, partner reporting) re-implements this join — differently.
2. **Point-in-time correctness is unreliable.** Services overwrite state in place. Once a supplier booking is cancelled or an order is repriced, the pre-change view is gone unless a consumer happened to snapshot it.
3. **Multi-party money flows are invisible.** A single B2B order can simultaneously involve a supplier payable, an affiliate shareback, VAT on that shareback, a withholding tax, and later a cancellation fee and a goodwill penalty. No system holds these as one coherent, signed ledger view.
4. **Fulfillment-time obligations don't fit booking-time models.** Passes redemptions, multi-leg transport, and recurring services generate *new payables per fulfillment instance* long after checkout. Systems keyed on (order, order_detail) alone cannot represent this.
5. **Cross-vertical products cannot be priced coherently.** Bundles and packages spanning verticals have no common read model to aggregate against.

## 2. Proposed Solution (One Paragraph)

**UPRL is an event-sourced read layer**: producer services (pricing, payment, supplier/fulfillment, refund) emit domain events onto the event bus; an ingestion service (Order Core) validates, versions, and normalizes them into **append-only fact tables**; derived **latest-state projections** answer the questions above for every consumer, uniformly, across all verticals. UPRL owns no business decisions — it is a truthful, replayable, versioned record of what the producers said, plus deterministic projection rules for "current state."

## 3. Goals

| # | Goal | Measure |
|---|------|---------|
| G1 | One query answers the full financial state of any order (pricing, payment, supplier payables, refunds) | Single API/read model, all verticals |
| G2 | Complete, immutable history — every version of every fact is retained and queryable | Append-only tables; no UPDATEs |
| G3 | Multi-party payables with directional semantics | Party-level projection with `amount_effect` |
| G4 | Multi-instance fulfillment support (passes, legs, tours, recurring) | `fulfillment_instance_id` scoping |
| G5 | Producer autonomy — verticals evolve their schemas without breaking consumers | Versioned event contracts, tolerant ingestion, DLQ |
| G6 | Deterministic, testable projection semantics | Pure projection module; golden/unit tests |
| G7 | Safe under real event-bus conditions | Idempotent ingestion, out-of-order tolerance, replayability |

### Non-Goals

- UPRL is **not a source of truth for writes** — it never originates pricing, payment, or supplier decisions.
- UPRL is **not an accounting/GL system** — component types are commerce concepts; GL mapping is downstream.
- UPRL does **not serve booking-flow reads** (availability, quotes) — it serves post-order state.
- The prototype does **not** attempt production scale, security, or infrastructure (see §9).

## 4. Scope

### In scope (demonstrated by the prototype)

1. **Four event families** ingested end-to-end: `PricingUpdated`, `PaymentLifecycle`, `SupplierLifecycleEvent` (v1 + v2), refund events (component refunds + refund timeline), plus standalone `PartnerAdjustmentEvent`.
2. **Five independent version families** — pricing snapshot, payment timeline, supplier timeline (per order-detail), refund timeline (per refund), issuance (reserved). Each increments independently; no artificial cross-family ordering.
3. **Dual component identity** — semantic ID (stable across repricing/refunds, carries lineage) + instance ID (unique per snapshot).
4. **Party-level payable projection** — status-driven inclusion rules, `INCREASES_PAYABLE`/`DECREASES_PAYABLE` math, standalone adjustments that survive cancellation.
5. **Multi-instance payables** — booking-level row plus per-redemption rows for the same order detail.
6. **Operational safety rails** — idempotency ledger, DLQ with replayable raw events, numbered schema migrations.
7. **Interactive exploration UI** — producer playground, order explorer, raw storage viewer, unified state projection, stress tests.

### Out of scope (production concerns, addressed in §9)

Kafka/PubSub integration, schema registry, horizontal scale, authN/Z, monitoring, retention/archival, disaster recovery, exactly-once semantics beyond idempotency keys.

## 5. Architecture

```
┌────────────┐  ┌────────────┐  ┌──────────────┐  ┌────────────┐
│  Vertical   │  │  Payment   │  │  Supplier /  │  │   Refund   │   producers
│  services   │  │  service   │  │  fulfillment │  │   service  │
└──────┬─────┘  └──────┬─────┘  └──────┬───────┘  └──────┬─────┘
       │  PricingUpdated│PaymentLifecycle│SupplierLifecycle │ RefundIssued / timeline
       ▼                ▼                ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                    ORDER CORE INGESTION (this layer)              │
│  1. Idempotency gate (processed_events ledger)                    │
│  2. Dispatch registry: (event_type, schema major version)         │
│  3. Pydantic validation → DLQ on failure (non-blocking)           │
│  4. Version assignment (monotonic per family scope)               │
│  5. Identity assignment (semantic + instance IDs, collision guard)│
│  6. Append-only insert                                            │
└──────────────────────────────────────────────────────────────────┘
       ▼                ▼                ▼                  ▼
 pricing_components  payment_timeline  supplier_timeline  refund_timeline
      _fact                            supplier_payable_lines        + dlq, processed_events, schema_migrations
       ▼                ▼                ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  PROJECTIONS (pure logic in src/projection/, latest-state views)  │
│  order_pricing_latest · payment_timeline_latest                   │
│  supplier_timeline_latest · refund_timeline_latest                │
│  get_total_effective_payables() — party-level, multi-instance     │
└──────────────────────────────────────────────────────────────────┘
       ▼
 Consumers: finance, CS tooling, settlement, partner reporting, analytics
```

### Key design decisions and their rationale

**Append-only facts + derived latest state (CQRS-lite).** Immutability gives audit history, point-in-time reconstruction, and replay for free, and makes out-of-order and duplicate delivery tractable — the hard problems of an event-driven read layer.

**Independent version families.** A payment capture must not bump pricing versions. Each family has its own monotonic counter with its own scope (order / order-detail / refund-id). Gaps are tolerated; order within a family is what matters.

**Dual identity for pricing components.**
- `component_semantic_id` = `cs-{order}-{canonical dimensions}-{type}` — stable across repricing; refunds link via `refund_of_component_semantic_id`.
- `component_instance_id` = hash(semantic_id + snapshot) — unique per snapshot, natural dedup key.
The format is a **cross-service contract**: producers reference these IDs. The prototype guards it with a closed abbreviation registry, collision detection at generation and at ingestion (`SEMANTIC_ID_COLLISION` → DLQ), and format-pinning tests. §8 explains why production should switch to opaque IDs.

**Party-level projection with `amount_effect`.** Obligations carry explicit direction (`INCREASES_PAYABLE` / `DECREASES_PAYABLE`) rather than sign conventions. Projection rules (all pure functions in `src/projection/payables.py`):
- Active statuses (Confirmed/ISSUED/Invoiced/Settled): baseline = timeline amount; include the **latest line per (party, obligation_type)** across versions.
- Cancelled statuses: baseline = 0; include **only lines re-stated on the latest version** (an empty parties array cuts carry-forward off); legacy `cancellation_fee_amount` fallback for old events.
- Standalone adjustments (version = −1, e.g. penalties): **always included**, surviving status changes; NULL-supplier-ref adjustments attach at the detail's booking level.

**Multi-instance payables.** Payables partition on `(order_id, order_detail_id, supplier_reference_id, fulfillment_instance_id)`, where NULL instance = booking level. One passes order projects as 1 booking row + N redemption rows, each with its own party breakdown.

**Non-blocking DLQ.** Validation failures never block the pipeline; raw events are stored for replay after fixes. Idempotency records only *successful* ingestions, so DLQ'd events stay retryable under the same event_id.

## 6. Event Contracts (Summary)

Full field-level reference: `docs/EVENT_FIELD_REFERENCE.md`. All events share the envelope: `event_id` (optional — Order Core derives a deterministic content-hash if absent, so redelivery still dedupes), `idempotency_key` (optional), `event_type` (dotted or PascalCase), `schema_version` (`domain.subdomain.vN` — major version parsed explicitly), `order_id`, `emitted_at`, `emitter_service`.

| Family | Types | Notes |
|--------|-------|-------|
| Pricing | `pricing.updated` / `PricingUpdated` | Components with dimensions; supports detail contexts (fx/entity); refund components carry lineage |
| Payment | `payment.checkout/authorized/captured/refunded/settled`, `PaymentLifecycle` | Instrument detail incl. loyalty points |
| Supplier | `supplier.order.confirmed/issued`, `supplier.invoice.received`, `SupplierLifecycleEvent` | v2: `parties[]` with `amount_effect`, `fulfillment_instance_id`; v1: legacy nested affiliate/commission/tax (see §8 landmine) |
| Refund | `refund.initiated/processing/issued/closed/failed`, `RefundIssued` | `refund.issued` is dual-shape: components ⇒ component-refund handler, otherwise timeline (see §8) |
| Adjustment | `PartnerAdjustmentEvent` | Standalone party line, version = −1 |

## 7. The Prototype

### What it is
A single-machine, fully-functional model of the architecture: Streamlit UI, SQLite storage, Pydantic validation. Every architectural claim in §5 is executable and covered by tests.

### Running it
```bash
./run.sh                 # creates venv, installs, launches Streamlit on :8501
pytest                   # 32 tests, ~1s (4 skipped: external fixtures)
```

### UI map
| Page | Purpose |
|------|---------|
| Producer Playground | Emit sample/custom events per producer; JSON editor + file loader |
| Order Explorer | Pricing versions & lineage, payment/supplier/refund timelines, multi-instance payables with party breakdown |
| Latest State Projection | One-page unified financial state per order |
| Raw Data Storage | Every fact table, unfiltered |
| Stress Tests | Out-of-order, duplicates (idempotency), invalid schema, DLQ inspection |

### Demo walkthroughs shipped as sample events
- **Entertainment passes (order 1322884534)**: booking-level confirmation (amount 0, redemption-triggered) + 3 redemptions, each a separate payable instance with supplier commission lines.
- **B2B affiliate (order 1200496236)**: shareback + VAT-on-commission party lines alongside the supplier payable.
- **Supplier cancellation scenarios A–D** (`tests/test_v2_scenarios.py`): issued multi-party → cancelled-with-fee via party lines → standalone penalty persisting → cancellation with re-stated (adjusted) affiliate obligations.
- **Train, hotel, flight-reschedule refunds** with component lineage.

### Code map
```
src/ingestion/pipeline.py    ingestion: idempotency gate, dispatch registry,
                             unified supplier handler, collision guards
src/ingestion/id_generator.py dual IDs, closed abbreviation registry
src/projection/payables.py   pure projection rules (unit-tested, no I/O)
src/storage/database.py      schema, numbered migrations, dumb queries
src/models/events.py         producer event contracts (Pydantic)
src/ui/*                     Streamlit pages
tests/                       pytest suite: unit + e2e (48-event corpus)
```

### Verification approach (how we know it's correct)
- **Golden-equivalence refactoring**: every structural change (projection extraction, handler unification) was proven byte-equivalent against snapshots of prior outputs across the full sample corpus.
- **Invariant tests**: ID format pinning, migration idempotency, standalone-adjustment survival, multi-instance splitting.
- **End-to-end net**: all 48 sample events must ingest cleanly on every run.

## 8. Honest Criticism — Known Weaknesses & Landmines

Recorded deliberately; each is either mitigated in the prototype or flagged as a production contract decision.

1. **`refund.issued` is overloaded.** The same event type arrives as a component-refund or a timeline-status event; the prototype disambiguates by payload shape (presence of `components`). *Production: split into two event types or discriminate by `schema_version`. Payload sniffing is not a contract.*
2. **Supplier v1 double-count landmine.** v1 events derive a synthetic `SUPPLIER` payable line equal to `amount_due`; storage defaults its missing `amount_effect` to `INCREASES_PAYABLE`. Any projection summing it double-counts against the timeline baseline. Preserved for compatibility and documented in the handler; *production: v1 must be migrated or its lines excluded from sums.*
3. **Semantic ID encodes business data in the key.** Values containing `-` remain structurally ambiguous (guarded at ingestion, not prevented); dimension keys are load-bearing. *Production: opaque hash IDs with dimensions as queryable columns; keep the readable form as a display name only.*
4. **NULL-as-meaning.** `fulfillment_instance_id = NULL` means "booking level" and forces `COALESCE(..., '__BOOKING_LEVEL__')` into every partition clause; version `−1` means "standalone." Both are documented sentinels with named constants, but *production should use explicit values* (`'BOOKING'`, an `is_standalone` flag).
5. **Per-event atomicity** *(resolved in prototype)*: each event's fact writes and its idempotency-ledger row now commit in one transaction; on failure, partial writes roll back while the DLQ entry survives, and the event stays retryable. *Production: same design; add producer-side outbox.*
6. **Obligation uniqueness is accidental.** Nothing constrains one line per (party, obligation_type, version); the projection deterministically keeps one, but *production needs a uniqueness constraint.*
7. **Found-by-testing regression (fixed, instructive):** introducing booking-scoped projection silently dropped NULL-ref standalone penalties — violating a documented invariant — and survived every manual demo until an automated scenario test was restored. *Lesson: projection semantics must be enforced by tests, not demos.*
8. **Prototype infrastructure is not the proposal.** SQLite (single-writer), Streamlit session DB connections, `print()` diagnostics, and pip-pinned deps are prototype conveniences, not architecture.

## 9. Production Migration Path

| Concern | Prototype | Production |
|---------|-----------|------------|
| Storage | SQLite | Spanner/PostgreSQL for facts; BigQuery for analytical replicas |
| Transport | UI button / file load | Kafka or Pub/Sub, consumer groups per family |
| Contracts | Pydantic + samples | Schema registry (Avro/Protobuf), CI contract tests, explicit major-version routing (already modeled) |
| Idempotency | `processed_events` ledger | Same design; unique constraint on (event_id), (idempotency_key); TTL'd |
| Atomicity | Per-row inserts | Transaction per event; outbox on producers |
| Projections | Pure Python + views | Same pure core; materialized views or streaming jobs; the projection module is the spec |
| Migrations | Numbered ledger (modeled) | Same discipline via standard tooling (Flyway/Liquibase-equivalent) |
| Identity | Readable contract IDs | Opaque IDs + dimension columns (§8.3) |
| Ops | — | Metrics (ingest lag, DLQ depth, version gaps), tracing, alerting, replay tooling, retention tiers, PITR |
| Access | — | Service authN/Z, PII handling in payment instruments, audit logging |

**Suggested rollout**: (1) shadow-ingest one vertical's real event streams into UPRL alongside existing systems; (2) reconcile UPRL projections against finance's current numbers for a full quarter cycle including cancellations and refunds; (3) cut consumers over read-model-by-read-model (CS tooling first, settlement last); (4) expand vertical by vertical, adding event types via the dispatch registry.

## 10. Open Questions for Review

1. Who owns the projection rules as a *product* (finance? platform?) — they encode money semantics, not plumbing.
2. Should refund timeline and component refunds be one producer contract or two (§8.1)?
3. Is `(party, obligation_type)` the right projection key, or do we need obligation-instance IDs for repeated same-type obligations?
4. Retention: how long must full version history stay hot vs. archived?
5. Does settlement need UPRL to be strongly consistent with payment capture, or is bounded staleness acceptable?

---

*Related docs: `ARCHITECTURE.md` (component detail), `EVENT_FIELD_REFERENCE.md` (field-level contracts), `PASSES_REDEMPTION_DESIGN.md` (multi-instance design), `B2B_AFFILIATE_GUIDE.md` (affiliate flows), `CLAUDE.md` (AI-assistant working guide).*
