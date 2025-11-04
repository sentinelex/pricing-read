# Database Improvement Summary

## 1. Overview

This document summarizes the recommended database schema improvements and patch recommendations for the Unified Pricing Read Layer. The focus is on optimizing data organization, query performance, and maintainability when handling complex payloads such as `IssuanceSupplierLifecycle`. The recommendations include schema normalization, index creation, and patching strategies to handle rebooking scenarios effectively.

## 2. Key Objectives

- Normalize tables to reduce data duplication and improve data integrity.
- Improve query performance by adding appropriate indexes.
- Provide clear patch scripts with explanations for easy implementation.
- Handle rebooking logic efficiently to maintain data consistency.
- Prepare the schema for future scalability and feature enhancements.

## 3. Patch Summary Table

| Category                | Rationale                                                                 | SQL Snippet Reference      |
|-------------------------|---------------------------------------------------------------------------|---------------------------|
| Table Normalization     | Separate repeated or nested data into dedicated tables to avoid duplication | Section 4.1                |
| Index Addition          | Add indexes on frequently queried columns to speed up lookups             | Section 4.2                |
| Rebooking Handling      | Add columns and constraints to manage rebooking lifecycle states          | Section 4.3                |
| Data Integrity          | Add foreign key constraints to enforce relationships                      | Section 4.4                |

## 4. Detailed SQL Patches

### 4.1 Table Normalization

**Explanation:**  
To reduce duplication and improve maintainability, nested objects in the payload such as `Supplier`, `Issuance`, and `Lifecycle` should be stored in separate tables with appropriate foreign keys.

```sql
-- Create Supplier table
CREATE TABLE Supplier (
    supplier_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(100),
    UNIQUE(name, type)
);

-- Create Issuance table
CREATE TABLE Issuance (
    issuance_id SERIAL PRIMARY KEY,
    supplier_id INT NOT NULL REFERENCES Supplier(supplier_id),
    issuance_date TIMESTAMP NOT NULL,
    status VARCHAR(50),
    -- other relevant columns
);

-- Create Lifecycle table
CREATE TABLE Lifecycle (
    lifecycle_id SERIAL PRIMARY KEY,
    issuance_id INT NOT NULL REFERENCES Issuance(issuance_id),
    event_type VARCHAR(50),
    event_timestamp TIMESTAMP NOT NULL,
    details JSONB
);
```

### 4.2 Index Addition

**Explanation:**  
Indexes on foreign keys and frequently queried columns will improve query performance.

```sql
CREATE INDEX idx_issuance_supplier_id ON Issuance(supplier_id);
CREATE INDEX idx_lifecycle_issuance_id ON Lifecycle(issuance_id);
CREATE INDEX idx_lifecycle_event_type ON Lifecycle(event_type);
```

### 4.3 Rebooking Handling

**Explanation:**  
To manage rebooking lifecycle states, add columns to track original booking references and rebooking status.

```sql
ALTER TABLE Issuance
ADD COLUMN original_booking_reference VARCHAR(100),
ADD COLUMN is_rebooked BOOLEAN DEFAULT FALSE;
```

### 4.4 Data Integrity

**Explanation:**  
Ensure foreign key constraints are in place to maintain referential integrity.

```sql
ALTER TABLE Issuance
ADD CONSTRAINT fk_issuance_supplier FOREIGN KEY (supplier_id) REFERENCES Supplier(supplier_id);

ALTER TABLE Lifecycle
ADD CONSTRAINT fk_lifecycle_issuance FOREIGN KEY (issuance_id) REFERENCES Issuance(issuance_id);
```

## 4.5 FX & Entity Enrichment (Order‑Detail Scoped)

**Principles**

- FX context **and** Entity context are modeled **at `order_detail_id` scope** (not only order_id), because different items in the same order can be fulfilled by different suppliers/currencies/entities.
- Context is **append‑only** and **versioned by event**; consumers should read “latest effective” records per `order_id + order_detail_id`.
- Producers **may omit** FX/Entity (e.g., Salesforce); Order Core (or an enrichment job) will attach the latest known context snapshot.

### 4.5.1 Tables (normalized; JSONB fallback allowed for prototype)

```sql
-- FX context snapshots captured at the time of each event (e.g., issuance, refund)
CREATE TABLE IF NOT EXISTS FXContextSnapshot (
    fx_ctx_id            TEXT PRIMARY KEY,         -- e.g. event_id or ULID
    order_id             TEXT NOT NULL,
    order_detail_id      TEXT NOT NULL,
    source_event_id      TEXT NOT NULL,            -- links back to supplier/pricing/refund event
    context_scope        TEXT NOT NULL,            -- 'supplier','pricing','refund','payment'
    effective_at         TIMESTAMP NOT NULL,       -- when the FX context became effective
    payment_currency     TEXT NOT NULL,
    supply_currency      TEXT NOT NULL,
    record_currency      TEXT NOT NULL,
    gbv_currency         TEXT NOT NULL,
    payment_value        NUMERIC,                  -- customer total in payment currency (if known)
    supply_to_payment_fx_rate NUMERIC,             -- rate used at this moment
    supply_to_record_fx_rate  NUMERIC,
    payment_to_gbv_fx_rate    NUMERIC,
    source               TEXT,                     -- 'Treasury','PSP','Vertical','Internal'
    fx_chain             JSONB,                    -- optional multi-hop representation
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fx_ctx_latest
ON FXContextSnapshot(order_id, order_detail_id, effective_at DESC);

-- Entity context snapshots (legal entities involved)
CREATE TABLE IF NOT EXISTS EntityContextSnapshot (
    entity_ctx_id        TEXT PRIMARY KEY,
    order_id             TEXT NOT NULL,
    order_detail_id      TEXT NOT NULL,
    source_event_id      TEXT NOT NULL,
    context_scope        TEXT NOT NULL,            -- 'supplier','pricing','refund','payment'
    effective_at         TIMESTAMP NOT NULL,
    merchant_of_record   TEXT,                     -- e.g., GTN, TNPL
    supplier_entity      TEXT,                     -- who pays supplier
    customer_entity      TEXT,                     -- who invoices the customer
    additional_attrs     JSONB,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entity_ctx_latest
ON EntityContextSnapshot(order_id, order_detail_id, effective_at DESC);
```

> **Prototype note:** If staying with SQLite, keep `fx_context` and `entity_context` as JSON on `supplier_timeline` **and** insert to the normalized snapshots above. The views below will always read from the normalized snapshots; JSON is a write‑through cache.

### 4.5.2 “Latest effective” views

```sql
-- Latest FX per order_detail
CREATE VIEW IF NOT EXISTS fx_context_latest AS
SELECT t.*
FROM (
  SELECT
    fx_ctx_id, order_id, order_detail_id, source_event_id, context_scope,
    effective_at, payment_currency, supply_currency, record_currency, gbv_currency,
    payment_value, supply_to_payment_fx_rate, supply_to_record_fx_rate, payment_to_gbv_fx_rate,
    source, fx_chain, created_at,
    ROW_NUMBER() OVER (PARTITION BY order_id, order_detail_id ORDER BY effective_at DESC, fx_ctx_id DESC) AS rn
  FROM FXContextSnapshot
) t
WHERE t.rn = 1;

-- Latest Entity per order_detail
CREATE VIEW IF NOT EXISTS entity_context_latest AS
SELECT t.*
FROM (
  SELECT
    entity_ctx_id, order_id, order_detail_id, source_event_id, context_scope,
    effective_at, merchant_of_record, supplier_entity, customer_entity, additional_attrs, created_at,
    ROW_NUMBER() OVER (PARTITION BY order_id, order_detail_id ORDER BY effective_at DESC, entity_ctx_id DESC) AS rn
  FROM EntityContextSnapshot
) t
WHERE t.rn = 1;
```

### 4.5.3 Payables join (status‑driven) with latest FX/Entity

```sql
-- Example: supplier effective payable + latest FX/Entity for display/recon
WITH latest_supplier AS (
  SELECT *
  FROM supplier_timeline
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY order_id, order_detail_id, supplier_id, supplier_reference_id
    ORDER BY supplier_timeline_version DESC, emitted_at DESC
  ) = 1
)
SELECT
  s.order_id,
  s.order_detail_id,
  s.supplier_id,
  s.supplier_reference_id,
  s.status,
  CASE
    WHEN s.status IN ('Confirmed','ISSUED','Invoiced','Settled') THEN COALESCE(s.amount, 0)
    WHEN s.status = 'CancelledWithFee' THEN COALESCE(s.cancellation_fee_amount, 0)
    ELSE 0
  END AS effective_payable,
  s.currency,
  fx.payment_currency, fx.supply_currency, fx.record_currency, fx.gbv_currency,
  fx.supply_to_payment_fx_rate, fx.supply_to_record_fx_rate, fx.payment_to_gbv_fx_rate,
  ent.merchant_of_record, ent.supplier_entity, ent.customer_entity
FROM latest_supplier s
LEFT JOIN fx_context_latest   fx
  ON fx.order_id = s.order_id AND fx.order_detail_id = s.order_detail_id
LEFT JOIN entity_context_latest ent
  ON ent.order_id = s.order_id AND ent.order_detail_id = s.order_detail_id;
```

### 4.5.4 Ingestion & enrichment rules

- **When event includes FX/Entity:**  
  - Write through to `supplier_timeline` JSON for traceability (prototype), **and** insert a snapshot row in `FXContextSnapshot` / `EntityContextSnapshot` using `source_event_id = event_id`, `context_scope` based on event family.
- **When event omits FX/Entity (e.g., Salesforce penalty):**  
  - Enrichment job attaches the **latest** snapshot from the same `order_id + order_detail_id`.  
  - Mark provenance in `additional_attrs` (e.g., `{ "enriched": true, "source":"fx_context_latest@ingestion" }`).
- **Rebooking:**  
  - A new supplier instance (new `supplier_id+supplier_ref`) should **not** inherit FX blindly; insert a new FX snapshot if the supply currency/entity changes. Otherwise, enrichment can copy forward.

---

## 5. Example Insertion Walkthrough

Given a real `IssuanceSupplierLifecycle` payload, the insertion process would be:

1. Insert or find the `Supplier` based on `name` and `type`.
2. Insert the `Issuance` record linked to the `Supplier`.
3. Insert multiple `Lifecycle` events linked to the `Issuance`.
4. If the payload indicates a rebooking, update the `Issuance` record with `original_booking_reference` and set `is_rebooked` to `TRUE`.

```sql
-- Step 1: Insert Supplier
INSERT INTO Supplier (name, type)
VALUES ('SupplierName', 'SupplierType')
ON CONFLICT (name, type) DO UPDATE SET name=EXCLUDED.name
RETURNING supplier_id;

-- Step 2: Insert Issuance
INSERT INTO Issuance (supplier_id, issuance_date, status, original_booking_reference, is_rebooked)
VALUES (1, '2024-06-01 12:00:00', 'issued', NULL, FALSE)
RETURNING issuance_id;

-- Step 3: Insert Lifecycle events
INSERT INTO Lifecycle (issuance_id, event_type, event_timestamp, details)
VALUES
(1, 'created', '2024-06-01 12:00:00', '{"info":"Initial issuance"}'),
(1, 'updated', '2024-06-02 15:30:00', '{"info":"Updated details"}');
```

### Including FX/Entity Snapshots

```sql
-- After inserting Issuance / SupplierTimeline row:
INSERT INTO FXContextSnapshot (
  fx_ctx_id, order_id, order_detail_id, source_event_id, context_scope, effective_at,
  payment_currency, supply_currency, record_currency, gbv_currency, payment_value,
  supply_to_payment_fx_rate, supply_to_record_fx_rate, payment_to_gbv_fx_rate, source, fx_chain
) VALUES (
  :event_id, :order_id, :order_detail_id, :event_id, 'supplier', :emitted_at,
  :payment_currency, :supply_currency, :record_currency, :gbv_currency, :payment_value,
  :s2p_rate, :s2r_rate, :p2g_rate, :fx_source, :fx_chain_json
);

INSERT INTO EntityContextSnapshot (
  entity_ctx_id, order_id, order_detail_id, source_event_id, context_scope, effective_at,
  merchant_of_record, supplier_entity, customer_entity, additional_attrs
) VALUES (
  :event_id, :order_id, :order_detail_id, :event_id, 'supplier', :emitted_at,
  :mor, :supplier_entity, :customer_entity, :attrs_json
);
```

## 6. Rebooking Handling Notes

- Use the `original_booking_reference` to trace the lineage of bookings.
- The `is_rebooked` flag helps filter or identify rebooked records in queries.
- Lifecycle events should contain detailed JSONB `details` to capture event-specific metadata.
- Consider implementing triggers or application logic to enforce consistency when rebooking occurs.

## 7. Future Enhancements

- Introduce partitioning on large tables such as `Lifecycle` based on date ranges for performance.
- Add materialized views or summary tables for frequently accessed aggregated data.
- Implement audit logging for lifecycle changes.
- Explore JSON schema validation for the `details` column to enforce data consistency.
- Consider caching strategies for supplier and issuance lookups to reduce database load.
- Introduce **FX variance analytics** views to compute expected vs. actual (capture vs. settlement) at `order_detail_id` scope.
- Backfill utility to derive FX/Entity snapshots for legacy events using nearest‑prior logic per `order_detail_id`.
- Add **data quality checks**: missing FX/Entity snapshot rate, currency mismatches between supplier and FX context.
