# UPRL Prototype - Claude AI Guidance

This document provides comprehensive guidance for Claude AI when working with this prototype codebase.

## Project Overview

**Unified Pricing Read Layer (UPRL) Prototype** - An interactive Streamlit application demonstrating event-driven architecture for order pricing, payment, supplier lifecycle, and refund management at Tiket.com.

**Purpose**: Educational prototype to visualize data flow from producer events through Order Core ingestion to normalized storage.

**Technology Stack**:
- **UI**: Streamlit 1.32+
- **Storage**: SQLite (append-only fact tables)
- **Validation**: Pydantic v2
- **Language**: Python 3.12+

## Core Capabilities

### 1. Event Ingestion Pipeline

**Location**: `src/ingestion/pipeline.py`

The system ingests 4 types of producer events:

#### A. Pricing Events (`PricingUpdated`)
- **Source**: Vertical services (hotel, flight, train, entertainment, etc.)
- **Purpose**: Track pricing components per order
- **Key Features**:
  - Dual ID generation (semantic + instance)
  - Version assignment (monotonic per order)
  - Component dimensions support (order, order_detail, granular)
  - Refund lineage tracking (`refund_of_component_semantic_id`)
- **Storage**: `pricing_components_fact` table

#### B. Payment Events (`PaymentLifecycle`)
- **Source**: Payment service
- **Purpose**: Track payment status through lifecycle
- **Key Features**:
  - Timeline version (monotonic per order)
  - Payment method tracking (including LOYALTY/TiketPoints)
  - Payment instrument details (cards, wallets, loyalty)
  - Amount tracking (authorized, captured, refunded)
- **Storage**: `payment_timeline` table

#### C. Supplier Lifecycle Events v2 (`SupplierLifecycleEvent`)
- **Source**: Supplier/fulfillment services
- **Purpose**: Track supplier booking status and payables
- **Key Features**:
  - **Multi-instance payables** (`fulfillment_instance_id`)
  - **Party-level projection** with amount_effect directionality
  - Status-driven obligations (Confirmed, ISSUED, CancelledWithFee, etc.)
  - FX context and entity context tracking
  - Support for passes redemptions, train legs, tours, transfers
- **Storage**:
  - `supplier_timeline` table (status/amount baseline)
  - `supplier_payable_lines` table (party obligations)

#### D. Refund Events (`RefundIssued`, refund timeline)
- **Source**: Refund service
- **Purpose**: Track refund lifecycle and component refunds
- **Key Features**:
  - Refund timeline version (monotonic per refund_id)
  - Component lineage (links to original components)
  - Status tracking (INITIATED, PROCESSING, ISSUED, CLOSED)
- **Storage**: `refund_timeline`, `pricing_components_fact` (with is_refund=true)

### 2. Multi-Instance Payables (NEW)

**Purpose**: Handle scenarios where 1 order + 1 order_detail generates multiple supplier payables over time during fulfillment.

**Use Cases**:
- **Passes/Tickets**: Each redemption generates separate payable
- **Multi-ride Transport**: Each journey leg may have separate costs
- **Tours**: Each tour instance with separate supplier obligations
- **Recurring Services**: Each service delivery generates payable

**Implementation**:
- **Field**: `fulfillment_instance_id` in `Supplier` model and database tables
- **Scoping**: Payables partitioned by `(order_id, order_detail_id, supplier_reference_id, fulfillment_instance_id)`
- **NULL handling**: `fulfillment_instance_id=NULL` represents booking-level (single-instance model)
- **Query logic**: Uses `COALESCE(fulfillment_instance_id, '__BOOKING_LEVEL__')` for partitioning

**Example** (Entertainment Passes):
```json
// Booking event (fulfillment_instance_id: null, amount: 0)
{
  "supplier": {
    "status": "Confirmed",
    "fulfillment_instance_id": null,
    "amount_due": 0,
    "amount_basis": "redemption-triggered"
  }
}

// Redemption event (fulfillment_instance_id: "ticket_code_XXX", amount: 127500)
{
  "supplier": {
    "status": "ISSUED",
    "fulfillment_instance_id": "ticket_code_1757809185001",
    "amount_due": 150000,
    "amount_basis": "gross"
  },
  "parties": [
    {
      "party_type": "SUPPLIER",
      "lines": [
        {"obligation_type": "COMMISSION", "amount": 20025, "amount_effect": "DECREASES_PAYABLE"}
      ]
    }
  ]
}
```

### 3. Party-Level Projection with Amount Effect

**Purpose**: Track multi-party obligations (supplier, affiliate, tax, internal costs) with directional effects.

**Amount Effect Types**:
- `INCREASES_PAYABLE`: We owe more (supplier cost, affiliate commission, tax, penalties)
- `DECREASES_PAYABLE`: We owe less (supplier commission retention, credits)

**Party Types**:
- `SUPPLIER`: Main supplier obligation
- `AFFILIATE`: B2B affiliate shareback/commission
- `TAX_AUTHORITY`: VAT, withholding tax
- `INTERNAL`: Platform internal costs (subsidies, operational fees)

**Projection Logic**:
```sql
-- Latest obligation per (party_id, obligation_type) across timeline versions
-- Apply amount_effect: INCREASES += amount, DECREASES -= amount
-- Status-driven filtering:
--   - ISSUED/Confirmed: include ALL obligations
--   - CancelledWithFee: include ONLY latest version (with CANCELLATION_FEE)
--   - CancelledNoFee: include ONLY standalone adjustments (version = -1)
```

**Storage**: `supplier_payable_lines` table with fields:
- `party_type`, `party_id`, `party_name`
- `obligation_type` (SUPPLIER_COST, COMMISSION, COMMISSION_VAT, CANCELLATION_FEE, etc.)
- `amount_effect` (INCREASES_PAYABLE / DECREASES_PAYABLE)
- `supplier_timeline_version` (-1 for standalone, >= 1 for timeline-linked)

### 4. Dual ID System

**Purpose**: Stable component identity across repricing and refunds while maintaining snapshot uniqueness.

**Semantic ID** (`component_semantic_id`):
- Format: `cs-{order_id}-{dimensions}-{component_type}`
- Example: `cs-1322884534-OD-1359185528-BaseFare`
- Stable across repricing, refunds, lifecycle changes
- Used for component lineage and aggregation

**Instance ID** (`component_instance_id`):
- Format: `ci_{hash(semantic_id + snapshot_id)}`
- Example: `ci_a1b2c3d4e5f60001`
- Unique per pricing snapshot
- Used for deduplication within snapshot

### 5. Version Families (Independent Evolution)

The system tracks **5 separate version dimensions**:

1. **Pricing Snapshot Version** (`pricing_snapshot_id` + `version`)
   - Scope: Per order
   - Assigned by: Order Core during PricingUpdated ingestion
   - Monotonic: Always increments

2. **Payment Timeline Version** (`timeline_version`)
   - Scope: Per order
   - Tracks: checkout → authorized → captured → refunded
   - Assigned by: Order Core during PaymentLifecycle ingestion

3. **Supplier Timeline Version** (`supplier_timeline_version`)
   - Scope: Per (order_id, order_detail_id)
   - Tracks: Confirmed → ISSUED → Invoiced → Settled → Cancelled
   - Assigned by: Order Core during SupplierLifecycleEvent ingestion

4. **Refund Timeline Version** (`refund_timeline_version`)
   - Scope: Per refund_id
   - Tracks: INITIATED → PROCESSING → ISSUED → CLOSED
   - Assigned by: Order Core during refund event ingestion

5. **Issuance Timeline Version** (`issuance_version`)
   - Scope: Per (order_id, order_detail_id)
   - Future use for ticket issuance tracking

### 6. UI Features

#### A. Producer Playground (`src/ui/producer_playground.py`)
- Emit sample events from various producers
- **Sub-tabs**:
  - Pricing Events (hotel, flight, train, entertainment)
  - Payment Events (lifecycle states)
  - Supplier & Payable Events (v2 with parties)
  - Refund Events (timeline and components)
- **Features**:
  - Pre-built sample JSON events
  - JSON editor with syntax highlighting
  - File loader for batch emission
  - Real-time ingestion feedback

#### B. Order Explorer (`src/ui/order_explorer.py`)
- Browse orders and view detailed breakdowns
- **Sub-tabs**:
  - Latest Pricing: Current pricing breakdown with component cards
  - Version History: All pricing versions with diff view
  - Component Lineage: Refund chains and repricing history
  - Payment Timeline: Payment lifecycle events
  - Supplier Timeline: Supplier status changes
  - Supplier Payables v2: Multi-instance payables with party-level projection
  - Refund Timeline: Refund status tracking
- **Features**:
  - Multi-instance payables display (booking + redemptions)
  - Party-separated obligations
  - Amount effect visualization
  - Status-driven baseline calculation

#### C. Raw Data Storage (`src/ui/raw_storage_viewer.py`)
- View raw table contents
- **Tables**:
  - pricing_components_fact
  - payment_timeline
  - supplier_timeline
  - supplier_payable_lines
  - refund_timeline
  - dlq
- **Features**:
  - All columns visible
  - Pagination support
  - Order filtering

#### D. Latest State Projection (`src/ui/unified_order_view.py`)
- Unified view of order state
- **Sections**:
  - Latest pricing breakdown
  - Payment status
  - Supplier timeline (per order_detail)
  - Refund summary
  - Supplier payables (with multi-instance support)
- **Features**:
  - One-page comprehensive view
  - Real-time aggregation

#### E. Stress Tests (`src/ui/stress_tests.py`)
- Test edge cases
- **Tests**:
  - Out-of-order events (v3 before v2)
  - Duplicate event handling
  - Invalid schema validation
  - Missing required fields
  - Negative amount validation
  - Version gap detection
- **Features**:
  - Pre-configured test scenarios
  - DLQ inspection
  - Idempotency verification

#### F. JSON Editor & Loader (`src/ui/json_editor.py`, `src/ui/json_loader.py`)
- Edit and validate JSON events
- Load events from filesystem
- **Features**:
  - Syntax highlighting
  - Validation feedback
  - File browser for sample_events/

### 7. Database Schema

#### Fact Tables (Append-Only)

**pricing_components_fact**:
- Primary key: `component_instance_id`
- Semantic key: `component_semantic_id`
- Version keys: `pricing_snapshot_id`, `version`
- Dimensions: JSON (order_detail_id, pax_id, leg_id, etc.)
- Lineage: `refund_of_component_semantic_id`

**payment_timeline**:
- Primary key: `event_id`
- Version key: `timeline_version` (per order)
- Fields: status, payment_method, authorized_amount, captured_amount, etc.

**supplier_timeline**:
- Primary key: `event_id`
- Version key: `supplier_timeline_version` (per order_detail_id)
- NEW: `fulfillment_instance_id` for multi-instance payables
- Fields: status, amount, amount_basis, currency, fx_context, entity_context

**supplier_payable_lines**:
- Primary key: `line_id`
- Foreign key: Links to supplier_timeline via `supplier_timeline_version`
- NEW: `fulfillment_instance_id` for multi-instance payables
- Fields: party_type, party_id, obligation_type, amount, amount_effect

**refund_timeline**:
- Primary key: `event_id`
- Version key: `refund_timeline_version` (per refund_id)
- Fields: status, refund_amount, currency, refund_reason

**dlq** (Dead Letter Queue):
- Primary key: `dlq_id`
- Fields: event_id, error_type, error_message, raw_event, retry_count

#### Derived Views (Latest State)

**order_pricing_latest**:
- Latest pricing per semantic_id
- Query: `MAX(version) GROUP BY order_id, component_semantic_id`

**payment_timeline_latest**:
- Latest payment status per order
- Query: `MAX(timeline_version) GROUP BY order_id`

**supplier_timeline_latest**:
- Latest supplier status per order_detail
- Query: `MAX(supplier_timeline_version) GROUP BY order_id, order_detail_id`

**refund_timeline_latest**:
- Latest refund status per refund
- Query: `MAX(refund_timeline_version) GROUP BY order_id, refund_id`

### 8. Key Query Patterns

#### Get Total Effective Payables (Multi-Instance)
```python
db.get_total_effective_payables(order_id)
# Returns: List of payable instances per (order_detail_id, supplier_ref, fulfillment_instance_id)
# Each instance contains:
#   - supplier_baseline (from supplier_timeline.amount)
#   - parties (party-level obligations with amount_effect)
#   - total_payable (baseline + sum of adjustments)
```

#### Party-Level Projection Logic
```sql
-- Step 1: Get latest status per (order_detail_id, supplier_ref, fulfillment_instance_id)
WITH latest_status AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY order_id, order_detail_id, supplier_reference_id,
                 COALESCE(fulfillment_instance_id, '__BOOKING_LEVEL__')
    ORDER BY supplier_timeline_version DESC
  ) as rn
  FROM supplier_timeline
  WHERE order_id = ?
)
SELECT * FROM latest_status WHERE rn = 1

-- Step 2: Get latest obligation per (party_id, obligation_type) for this instance
WITH latest_per_party AS (
  SELECT party_id, obligation_type, MAX(supplier_timeline_version) as latest_version
  FROM supplier_payable_lines
  WHERE order_id = ? AND order_detail_id = ?
    AND supplier_reference_id = ?
    AND COALESCE(fulfillment_instance_id, '__BOOKING_LEVEL__') = ?
    AND supplier_timeline_version >= 1  -- Timeline-linked
  GROUP BY party_id, obligation_type
)
-- Step 3: Fetch lines from latest version and apply amount_effect
```

## File Structure

```
prototype/
├── app.py                          # Main Streamlit app (navigation, pages)
├── requirements.txt                # Python dependencies
├── run.sh                          # Launch script
├── debug_multi_instance.py         # Debug tool for multi-instance payables
│
├── src/
│   ├── models/
│   │   ├── events.py              # Producer event schemas (Pydantic)
│   │   │   - PricingUpdatedEvent
│   │   │   - PaymentLifecycleEvent
│   │   │   - SupplierLifecycleEvent (v2 with fulfillment_instance_id)
│   │   │   - RefundIssuedEvent
│   │   │   - PartnerAdjustmentEvent
│   │   └── normalized.py          # Normalized storage models
│   │       - NormalizedPricingComponent
│   │       - NormalizedSupplierTimeline
│   │
│   ├── ingestion/
│   │   ├── pipeline.py            # Order Core ingestion logic
│   │   │   - IngestionPipeline class
│   │   │   - _ingest_pricing_updated()
│   │   │   - _ingest_payment_lifecycle()
│   │   │   - _ingest_supplier_lifecycle_v2()  (NEW: multi-instance)
│   │   │   - _ingest_refund_issued()
│   │   │   - _ingest_partner_adjustment()
│   │   └── id_generator.py        # Dual ID generation
│   │       - generate_dual_ids()
│   │       - _construct_semantic_id()
│   │
│   ├── storage/
│   │   └── database.py            # SQLite schema and queries
│   │       - Database class
│   │       - initialize_schema()
│   │       - _run_migrations()  (handles schema evolution)
│   │       - get_total_effective_payables()  (multi-instance support)
│   │       - insert_supplier_timeline()
│   │       - insert_payable_line()
│   │
│   └── ui/
│       ├── producer_playground.py # Event emission UI
│       ├── order_explorer.py      # Order browsing UI
│       │   - render_supplier_payables()  (multi-instance display)
│       │   - _render_party_payables()  (helper for party display)
│       ├── unified_order_view.py  # Latest state projection UI
│       ├── raw_storage_viewer.py  # Raw table viewer UI
│       ├── stress_tests.py        # Edge case testing UI
│       ├── json_editor.py         # JSON editing UI
│       └── json_loader.py         # File loading UI
│
├── sample_events/                  # Sample JSON events
│   ├── pricing_events/
│   │   └── hotel-3-night-simple.json
│   ├── payment_timeline/
│   │   ├── 010-checkout.json
│   │   ├── 020-authorized.json
│   │   ├── 030-captured.json
│   │   └── ttd-passes-prod-1322884534/
│   │       └── 001-captured.json  (LOYALTY/TiketPoints payment)
│   ├── supplier_and_payable_event/
│   │   ├── supplier-lifecycle/
│   │   │   ├── 001-supplier-issued-multi-party-with-amount-effect.json
│   │   │   └── 002-supplier-cancelled-projection-based.json
│   │   ├── ttd-passes-prod-1322884534/  (NEW: multi-instance example)
│   │   │   ├── 001-booking-confirmed.json
│   │   │   ├── 002-redemption-1.json
│   │   │   ├── 003-redemption-2.json
│   │   │   └── 004-redemption-3.json
│   │   ├── b2b-affiliate/
│   │   └── partner-adjustment-SF/
│   └── refund_timeline/
│       └── refund-lifecycle/
│
├── tests/                          # Test suite
│   ├── test_b2b_real_files.py
│   ├── test_rebooking_flow.py
│   ├── test_refund_issued.py
│   └── test_payment_fee_scenario.py
│
├── data/
│   └── uprl.db                    # SQLite database (gitignored)
│
└── docs/                          # Documentation (organized)
    ├── ARCHITECTURE.md
    ├── PASSES_REDEMPTION_DESIGN.md
    ├── B2B_AFFILIATE_GUIDE.md
    ├── EVENT_FIELD_REFERENCE.md
    └── ...
```

## Common Tasks for Claude

### Task 1: Add Support for New Event Type

**Steps**:
1. Define Pydantic model in `src/models/events.py`
2. Create normalized model in `src/models/normalized.py`
3. Add ingestion method in `src/ingestion/pipeline.py`
4. Update `ingest_event()` routing logic
5. Create database table/indexes in `database.py`
6. Add UI tab in `producer_playground.py`
7. Create sample events in `sample_events/`
8. Update documentation

### Task 2: Debug Multi-Instance Payables

**Tools**:
- Run `debug_multi_instance.py` to emit test events and inspect database
- Check `supplier_timeline` table for `fulfillment_instance_id` values
- Check `supplier_payable_lines` table for party obligations
- Verify `get_total_effective_payables()` returns correct instance count
- Inspect UI in Order Explorer → Supplier Payables

**Common Issues**:
- Missing `fulfillment_instance_id` field in Pydantic model → Add to `Supplier` class
- NULL values stored when field exists in JSON → Check `getattr(event.supplier, 'fulfillment_instance_id', None)`
- Instances not splitting → Verify `COALESCE(fulfillment_instance_id, '__BOOKING_LEVEL__')` in query
- UI showing merged payables → Check `has_multi_instance` detection logic

### Task 3: Add New Sample Event

**Steps**:
1. Create JSON file in appropriate `sample_events/` subdirectory
2. Follow naming convention: `001-description.json`, `002-description.json`
3. Ensure required fields: `event_id`, `event_type`, `order_id`, `emitted_at`
4. Use `idempotency_key` for deduplication
5. Test emission in Producer Playground
6. Verify ingestion in Order Explorer
7. Check DLQ if event fails

### Task 4: Update Database Schema

Schema changes are numbered migrations tracked in the `schema_migrations`
table (version, description, applied_at). Never renumber or edit a shipped
entry — always append.

**Steps**:
1. Append an entry to `Database.MIGRATIONS` in `database.py`:
   ```python
   {
       'version': <next integer>,
       'description': 'Add new_column to table_name (YYYY-MM-DD)',
       'table': 'table_name',
       'column': 'new_column',
       'sql': "ALTER TABLE table_name ADD COLUMN new_column TYPE",
   }
   ```
   A migration is recorded as satisfied without running when its target
   table doesn't exist yet (fresh DB) or the column is already present.
2. Update `initialize_schema()` CREATE TABLE so new databases are current
3. Update insertion methods to include new columns
4. Update query methods to return new columns
5. Run `python tests/test_migrations.py` — it covers fresh, legacy, and
   idempotent re-run paths
6. Test with fresh database and existing database

### Task 5: Fix Pydantic Model Issues

**Common patterns**:
- Optional fields: Use `Optional[Type] = None`
- Union types for backward compatibility: `Union[Model, str]`
- Enum values: Extract with `getattr(field, 'value', field)`
- Nested models: Define separate classes for reusability
- JSON fields: Use `Dict[str, Any]` for flexible schemas

## Testing Strategy

### Unit Tests
- Located in `tests/` directory
- Use temporary databases: `Database("data/test_xyz.db")`
- Test individual ingestion methods
- Verify database state after ingestion

### Integration Tests
- Test complete event flows (pricing → payment → supplier → refund)
- Verify multi-instance scenarios (booking + multiple redemptions)
- Test B2B affiliate calculations
- Verify party-level projection correctness

### UI Tests
- Manual testing via Streamlit app
- Use debug scripts for automation
- Verify display of multi-instance payables
- Check edge cases (NULL values, empty arrays)

## Production Migration Considerations

**For Production Implementation**:
1. **Database**: Replace SQLite with production database (Spanner, PostgreSQL, BigQuery)
2. **Event Bus**: Integrate with Kafka/Pub/Sub for real event consumption
3. **Schema Registry**: Use Avro/Protobuf for event versioning
4. **Idempotency**: Add unique constraint on `(event_id, idempotency_key)`
5. **Monitoring**: Add metrics, traces, alerts
6. **Retry Logic**: Implement exponential backoff for transient failures
7. **Data Retention**: Define archival policies (hot/warm/cold storage)
8. **Access Control**: Add authentication, authorization, audit logging
9. **Performance**: Add caching, read replicas, query optimization
10. **Disaster Recovery**: Implement backups, point-in-time recovery

## Important Notes

### Multi-Instance Payables
- **Always use** `COALESCE(fulfillment_instance_id, '__BOOKING_LEVEL__')` in partition clauses
- **NULL semantics**: NULL = single-instance (traditional model), non-NULL = multi-instance
- **Backward compatible**: Existing events without field work seamlessly
- **Cross-vertical**: Applicable to entertainment, transport, tours, recurring services

### Party-Level Projection
- **Amount Effect Directionality**: INCREASES_PAYABLE (add), DECREASES_PAYABLE (subtract)
- **Status-Driven Filtering**: Different obligation inclusion rules per status
- **Standalone Adjustments**: version=-1 obligations always included (persist across status changes)
- **Projection Carry-Forward**: Empty parties array → obligations carried via projection

### Version Families
- **Independent Evolution**: Each version family increments independently
- **No Gaps**: Versions should be monotonic but gaps are tolerated
- **Immutability**: Never update existing versions, always create new ones

### DLQ Philosophy
- **Non-Blocking**: Validation failures go to DLQ, don't block pipeline
- **Replayable**: DLQ entries can be retried after fix
- **Auditable**: All failures logged with raw event for debugging

## Quick Reference Commands

```bash
# Start prototype
streamlit run app.py

# Run the full test suite (single entry point)
pytest

# Run one suite
pytest tests/test_payable_projection.py

# Debug multi-instance
python debug_multi_instance.py

# Clear database
rm data/uprl.db
# OR use Settings → Clear All Data in UI

# Install dependencies
pip install -r requirements.txt

# Check database schema
sqlite3 data/uprl.db ".schema supplier_timeline"

# Query multi-instance payables
sqlite3 data/uprl.db "
  SELECT order_detail_id, supplier_timeline_version,
         fulfillment_instance_id, status, amount
  FROM supplier_timeline
  WHERE order_id='1322884534'
  ORDER BY supplier_timeline_version
"
```

## Contact & Resources

- **Codebase**: `/home/user/order-pm/order-pm-documentation/Unified-Pricing-Read-Layer/prototype/`
- **Documentation**: See `docs/` directory (ARCHITECTURE.md, PASSES_REDEMPTION_DESIGN.md, etc.)
- **Sample Events**: `sample_events/` directory with organized subdirectories
- **Assessment**: `PRD_user_stories_and_ac/assessment.md` (converted from HTML)

---

**Last Updated**: 2025-11-13
**Version**: 2.0.0 (with multi-instance payables support)
