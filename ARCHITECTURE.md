# UPRL Prototype Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        UPRL Prototype System                         │
│                                                                      │
│  ┌──────────────────┐                                               │
│  │ Streamlit UI     │   User Interface Layer                        │
│  │ (app.py)         │                                               │
│  └────────┬─────────┘                                               │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────┐   ┌──────────────────┐   ┌─────────────────┐│
│  │ Producer         │   │ Order Explorer   │   │ Stress Tests    ││
│  │ Playground       │   │                  │   │                 ││
│  └────────┬─────────┘   └────────┬─────────┘   └────────┬────────┘│
│           │                       │                      │          │
│           └───────────────────────┼──────────────────────┘          │
│                                   │                                 │
│                                   ▼                                 │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │         Order Core Ingestion Pipeline                   │       │
│  │         (src/ingestion/pipeline.py)                     │       │
│  │                                                          │       │
│  │  1. Validate Schema (Pydantic)                          │       │
│  │  2. Generate Dual IDs (semantic + instance)             │       │
│  │  3. Assign Version Keys                                 │       │
│  │  4. Normalize to Storage Format                         │       │
│  │  5. Insert into Database / Send to DLQ                  │       │
│  └────────┬────────────────────────────────────────────────┘       │
│           │                                                          │
│           ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │         SQLite Database (src/storage/database.py)       │       │
│  │                                                          │       │
│  │  Fact Tables (Append-Only):                             │       │
│  │  • pricing_components_fact                              │       │
│  │  • payment_timeline                                     │       │
│  │  • supplier_timeline                                    │       │
│  │  • refund_timeline                                      │       │
│  │  • dlq                                                  │       │
│  │                                                          │       │
│  │  Derived Views (Latest State):                          │       │
│  │  • order_pricing_latest                                 │       │
│  │  • payment_timeline_latest                              │       │
│  │  • supplier_timeline_latest                             │       │
│  │  • refund_timeline_latest                               │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## Event Flow

### Producer Event → Normalized Storage

```
Producer Event                Order Core Processing             Storage
━━━━━━━━━━━━━━                ━━━━━━━━━━━━━━━━━━━━━             ━━━━━━━

┌──────────────┐              ┌──────────────┐                ┌──────────────┐
│ Vertical     │──────────────▶ Validate      │                │              │
│ Service      │              │ Schema        │                │              │
│              │              │ (Pydantic)    │                │              │
│ Emits:       │              └──────┬───────┘                │              │
│ PricingUpdated              │      ▼                        │              │
└──────────────┘              │ ┌──────────────┐              │              │
                              │ │ Generate     │              │              │
{                             │ │ Dual IDs     │              │              │
  "event_id": "...",          │ │              │              │              │
  "order_id": "ORD-9001",     │ │ semantic_id: │              │              │
  "version": 1,               │ │ cs-ORD-9001- │              │ pricing_     │
  "components": [             │ │ OD-001-BaseFare             │ components_  │
    {                         │ │              │              │ fact         │
      "component_type":       │ │ instance_id: │              │              │
        "BaseFare",           │ │ ci_abc123... │──────────────▶              │
      "amount": 150000000,    │ └──────┬───────┘              │ - semantic_id│
      "currency": "IDR",      │        ▼                      │ - instance_id│
      "dimensions": {         │ ┌──────────────┐              │ - version    │
        "order_detail_id":    │ │ Normalize    │              │ - amount     │
        "OD-001"              │ │ to Storage   │              │ - currency   │
      }                       │ │ Format       │              │ - dimensions │
    }                         │ └──────┬───────┘              │ - ...        │
  ]                           │        │                      │              │
}                             │        └──────────────────────▶              │
                              └──────────────┘                └──────────────┘
```

## Data Model - Dual ID System

### Component Identity Evolution

```
Version 1: Initial Pricing
━━━━━━━━━━━━━━━━━━━━━━━━━━
pricing_snapshot_id: snap-001
version: 1

Component:
├─ component_semantic_id: cs-ORD-9001-OD-OD-001-BaseFare  ◀─ STABLE
├─ component_instance_id: ci_abc123...                    ◀─ UNIQUE per snapshot
├─ amount: 150000000
└─ dimensions: {"order_detail_id": "OD-001"}


Version 2: Repricing (Lower rate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pricing_snapshot_id: snap-002
version: 2

Component:
├─ component_semantic_id: cs-ORD-9001-OD-OD-001-BaseFare  ◀─ SAME (stable!)
├─ component_instance_id: ci_def456...                    ◀─ NEW (different snapshot)
├─ amount: 140000000                                      ◀─ CHANGED
└─ dimensions: {"order_detail_id": "OD-001"}


Version 3: Refund
━━━━━━━━━━━━━━━━━━━━━━━━━━
pricing_snapshot_id: snap-003
version: 3

Refund Component:
├─ component_semantic_id: cs-ORD-9001-OD-OD-001-Refund    ◀─ NEW semantic ID
├─ component_instance_id: ci_ghi789...
├─ amount: -50000000                                      ◀─ NEGATIVE
├─ refund_of_component_semantic_id:                       ◀─ LINEAGE POINTER
│    cs-ORD-9001-OD-OD-001-BaseFare
└─ dimensions: {"order_detail_id": "OD-001"}
```

### Lineage Tracing

```
Original Component (v1)          Refund Component (v3)
━━━━━━━━━━━━━━━━━━━━━━          ━━━━━━━━━━━━━━━━━━━━
semantic_id:                     semantic_id:
cs-ORD-9001-OD-OD-001-BaseFare   cs-ORD-9001-OD-OD-001-Refund
      ▲                                   │
      │                                   │
      │    refund_of_component_semantic_id
      └───────────────────────────────────┘
                  (points back)
```

## Version Families - Independent Evolution

```
Order: ORD-9001
━━━━━━━━━━━━━━━

Pricing Track                     Payment Track
━━━━━━━━━━━━━                     ━━━━━━━━━━━━━
Version 1: Initial pricing        timeline_version 1: checkout
Version 2: Repricing              timeline_version 2: authorized
Version 3: Refund issued          timeline_version 3: captured
                                  timeline_version 4: refunded
        │                                  │
        │                                  │
        └──────────────┬───────────────────┘
                       │
              ┌────────▼────────┐
              │  Order Detail   │
              │    OD-001       │
              └────────┬────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼                             ▼
Supplier Track                   Refund Track
━━━━━━━━━━━━━                    ━━━━━━━━━━━━
supplier_timeline_version 1:     refund_timeline_version 1:
  confirmed                        initiated
supplier_timeline_version 2:     refund_timeline_version 2:
  issued                           closed
supplier_timeline_version 3:
  invoice received


KEY INSIGHT: Each track evolves independently!
Payment can be captured (v3) while pricing is still v1.
Supplier can issue (v2) while payment is still checkout (v1).
```

## Database Schema - Fact Tables & Views

```
┌────────────────────────────────────────────────────────────────────┐
│                    FACT TABLES (Append-Only)                       │
└────────────────────────────────────────────────────────────────────┘

pricing_components_fact
━━━━━━━━━━━━━━━━━━━━━━━
• component_semantic_id (indexed)
• component_instance_id (PK)
• order_id (indexed)
• pricing_snapshot_id
• version (indexed)
• component_type
• amount
• currency
• dimensions (JSON)
• refund_of_component_semantic_id
• emitter_service
• ingested_at
• emitted_at

payment_timeline                 supplier_timeline
━━━━━━━━━━━━━━━                  ━━━━━━━━━━━━━━━━
• event_id (PK)                  • event_id (PK)
• order_id                       • order_id
• timeline_version               • order_detail_id
• event_type                     • supplier_timeline_version
• payment_method                 • event_type
• amount                         • supplier_id
• ...                            • ...

refund_timeline                  dlq (Dead Letter Queue)
━━━━━━━━━━━━━━                   ━━━━━━━━━━━━━━━━━━━━━━
• event_id (PK)                  • dlq_id (PK)
• order_id                       • event_id
• refund_id                      • event_type
• refund_timeline_version        • raw_event (JSON)
• event_type                     • error_type
• refund_amount                  • error_message
• ...                            • failed_at

┌────────────────────────────────────────────────────────────────────┐
│                    DERIVED VIEWS (Latest State)                    │
└────────────────────────────────────────────────────────────────────┘

order_pricing_latest
━━━━━━━━━━━━━━━━━━━━
SELECT * FROM pricing_components_fact
WHERE (order_id, version) IN (
  SELECT order_id, MAX(version)
  FROM pricing_components_fact
  GROUP BY order_id
)

Similar views for:
• payment_timeline_latest
• supplier_timeline_latest
• refund_timeline_latest
```

## Ingestion Pipeline - Detailed Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Event Ingestion Pipeline                          │
└──────────────────────────────────────────────────────────────────────┘

1. Event Arrives
   ┌────────────────┐
   │ Raw JSON Event │
   └────────┬───────┘
            │
            ▼
2. Validate Schema
   ┌────────────────┐     Valid?
   │ Pydantic       │────────────┐
   │ Validation     │            │
   └────────┬───────┘            │
            │ Invalid            │ Valid
            ▼                    ▼
   ┌────────────────┐   ┌────────────────┐
   │ Send to DLQ    │   │ Continue       │
   │ with error     │   │ Processing     │
   └────────────────┘   └────────┬───────┘
                                  │
                                  ▼
3. Route by Event Type
   ┌────────────────────────────────────┐
   │ if pricing.updated:                │
   │   → _ingest_pricing_updated()      │
   │ elif payment.captured:             │
   │   → _ingest_payment_lifecycle()    │
   │ elif supplier.order.confirmed:     │
   │   → _ingest_supplier_lifecycle()   │
   │ ...                                │
   └────────────────┬───────────────────┘
                    │
                    ▼
4. Generate Dual IDs (for pricing/refund components only)
   ┌────────────────────────────────────┐
   │ For each component:                │
   │                                    │
   │ semantic_id = f"cs-{order_id}-     │
   │   {sorted_dimensions}-{type}"      │
   │                                    │
   │ instance_id = sha256(              │
   │   semantic_id + snapshot_id        │
   │ )[:16]                             │
   └────────────────┬───────────────────┘
                    │
                    ▼
5. Normalize to Storage Format
   ┌────────────────────────────────────┐
   │ NormalizedPricingComponent(        │
   │   component_semantic_id=...,       │
   │   component_instance_id=...,       │
   │   order_id=...,                    │
   │   version=...,                     │
   │   amount=...,                      │
   │   ingested_at=now()                │
   │ )                                  │
   └────────────────┬───────────────────┘
                    │
                    ▼
6. Insert into Database
   ┌────────────────────────────────────┐
   │ db.insert_pricing_component(...)   │
   │   OR                               │
   │ db.insert_payment_timeline(...)    │
   │   OR                               │
   │ db.insert_supplier_timeline(...)   │
   └────────────────┬───────────────────┘
                    │
                    ▼
7. Return Result
   ┌────────────────────────────────────┐
   │ IngestionResult(                   │
   │   success=True,                    │
   │   message="Ingested X components", │
   │   details={...}                    │
   │ )                                  │
   └────────────────────────────────────┘
```

## Query Patterns

### Query 1: Latest Breakdown

```sql
SELECT * FROM order_pricing_latest
WHERE order_id = 'ORD-9001'
ORDER BY component_type, dimensions
```

**Use Case**: Show customer current total breakdown in CS tool

### Query 2: Version History

```sql
SELECT version, pricing_snapshot_id,
       COUNT(*) as component_count,
       SUM(amount) as total_amount,
       emitted_at
FROM pricing_components_fact
WHERE order_id = 'ORD-9001'
GROUP BY version, pricing_snapshot_id, emitted_at
ORDER BY version DESC
```

**Use Case**: Finance reconciliation, audit trail

### Query 3: Component Lineage

```sql
-- Original component
SELECT * FROM pricing_components_fact
WHERE component_semantic_id = 'cs-ORD-9001-OD-OD-001-BaseFare'
ORDER BY version ASC

-- Refund components pointing to it
SELECT * FROM pricing_components_fact
WHERE refund_of_component_semantic_id = 'cs-ORD-9001-OD-OD-001-BaseFare'
ORDER BY version ASC
```

**Use Case**: Trace refund impact, calculate net amount

### Query 4: Payment Timeline

```sql
SELECT * FROM payment_timeline
WHERE order_id = 'ORD-9001'
ORDER BY timeline_version ASC
```

**Use Case**: Show payment lifecycle in CS tool

## Error Handling - DLQ Flow

```
Invalid Event
━━━━━━━━━━━━━
Example: Unknown component_type "InvalidType"

┌────────────────┐
│ Producer Emits │
│ Invalid Event  │
└────────┬───────┘
         │
         ▼
┌────────────────┐       ┌──────────────┐
│ Pydantic       │──────▶│ ValidationError
│ Validation     │       │ raised       │
└────────────────┘       └──────┬───────┘
                                │
                                ▼
                      ┌────────────────────┐
                      │ _send_to_dlq()     │
                      │                    │
                      │ DLQEntry(          │
                      │   dlq_id=uuid(),   │
                      │   event_id=...,    │
                      │   error_type=      │
                      │     "VALIDATION_   │
                      │      ERROR",       │
                      │   error_message=   │
                      │     "Pydantic...", │
                      │   raw_event=json   │
                      │ )                  │
                      └─────────┬──────────┘
                                │
                                ▼
                      ┌────────────────────┐
                      │ db.insert_dlq()    │
                      │                    │
                      │ Stored in DLQ table│
                      │ for inspection     │
                      └────────────────────┘

Retrieval:
- UI: Ingestion Console page
- Query: SELECT * FROM dlq ORDER BY failed_at DESC
- Action: Manual review, fix producer, retry
```

## Deployment Architecture (Production)

```
Current Prototype            Production Target
━━━━━━━━━━━━━━━━            ━━━━━━━━━━━━━━━━━

Streamlit (localhost)   →   Web UI (React/Vue)
                            + REST/GraphQL API

SQLite (local file)     →   Google Cloud Spanner
                            (distributed SQL)

In-memory pipeline      →   Apache Kafka / Pub/Sub
                            (event streaming)

No schema registry      →   Avro/Protobuf Registry
                            (schema evolution)

No monitoring           →   Prometheus + Grafana
                            (observability)

No auth                 →   OAuth2 + RBAC
                            (security)

Single-process          →   Kubernetes Deployment
                            (scalability)
```

---

**Key Takeaway**: This prototype demonstrates the **data model and pipeline logic** that will power the production UPRL. The architecture is designed to scale from local SQLite to distributed Spanner with minimal changes to core ingestion logic.

