# Unified Pricing Read Layer (UPRL) Prototype

An interactive Streamlit prototype demonstrating the **Unified Pricing Read Layer** architecture for a travel e-commerce Order Platform.

## Overview

This prototype simulates the complete data flow from producer events through Order Core ingestion to normalized storage, showcasing:

- **Event-driven architecture** with standardized producer events
- **Dual ID strategy** (semantic + instance IDs) for stable component identity
- **Version families** for independent evolution of pricing, payment, supplier, and refund timelines
- **Append-only storage** with immutable audit trails
- **Component lineage tracking** through refunds and repricing

## Key Files

### Core Application Files

| File | Lines | Purpose |
|------|-------|---------|
| [app.py](app.py) | ~262 | Main Streamlit entry point with 6-page navigation |
| [src/models/events.py](src/models/events.py) | ~200+ | Producer event schemas (11 event types, 11+ component types) |
| [src/models/normalized.py](src/models/normalized.py) | ~150+ | Normalized storage models with dual IDs & versions |
| [src/ingestion/pipeline.py](src/ingestion/pipeline.py) | ~400+ | Order Core ingestion: validation, routing, normalization |
| [src/ingestion/id_generator.py](src/ingestion/id_generator.py) | ~167 | Dual ID strategy implementation (semantic + instance) |
| [src/storage/database.py](src/storage/database.py) | ~500+ | SQLite schema with fact tables & derived views |
| [src/ui/producer_playground.py](src/ui/producer_playground.py) | - | Event emission UI for all producer services |
| [src/ui/order_explorer.py](src/ui/order_explorer.py) | - | Order browsing with lineage & timeline visualization |
| [src/ui/stress_tests.py](src/ui/stress_tests.py) | - | Edge case testing (out-of-order, duplicates, validation) |

### Test Files

| File | Purpose |
|------|---------|
| [tests/test_b2b_real_files.py](tests/test_b2b_real_files.py) | B2B affiliate integration using real production payloads |
| [tests/test_rebooking_flow.py](tests/test_rebooking_flow.py) | Status-driven obligations & supplier rebooking scenarios |
| [tests/test_refund_issued.py](tests/test_refund_issued.py) | Refund component lineage tracking |
| [tests/test_payment_fee_scenario.py](tests/test_payment_fee_scenario.py) | Payment transaction fee handling |
| [tests/test_b2b_affiliate.py](tests/test_b2b_affiliate.py) | Manual affiliate flow construction |

### Test Data & Documentation

| Directory/File | Contents |
|----------------|----------|
| [components-helper/b2b_affiliate_case/](components-helper/b2b_affiliate_case/) | Real B2B event sequence (7 events: pricing → payment → supplier → refund) |
| [components-helper/train_case_va/](components-helper/train_case_va/) | Train booking test case (4 events) |
| [components-helper/multi_order_detail_case/](components-helper/multi_order_detail_case/) | Multi-detail booking scenario |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design & data flow documentation |
| [QUICKSTART.md](QUICKSTART.md) | 5-minute setup guide |
| [B2B_AFFILIATE_GUIDE.md](B2B_AFFILIATE_GUIDE.md) | B2B affiliate feature documentation |

## Features

### 🎮 Producer Playground
Emit sample events from:
- **Vertical Services** (Hotel, Flight, Airport Transfer) - PricingUpdated events
- **Payment Service** - Payment lifecycle events (checkout, captured, refunded)
- **Supplier Services** - Supplier timeline events (confirmed, issued, invoice received)
- **Refund Service** - Refund timeline and component events

### ⚙️ Ingestion Console
- View Dead Letter Queue (DLQ) entries for failed events
- Monitor ingestion statistics
- Inspect validation errors and schema violations

### 🔍 Order Explorer
- Browse latest pricing breakdowns by order
- View version history with snapshot details
- Trace component lineage including refunds
- Explore payment and supplier timelines

### 🧪 Stress Tests
Test edge cases:
- Out-of-order event processing
- Duplicate event handling (idempotency)
- Invalid schema validation
- Missing required fields
- Negative amount validation
- Version gap detection

## Architecture

```
Producers (Vertical/Payment/Refund)
       ↓ emit standardized events
Order Core Ingestion Pipeline
       ├─ Schema validation (Pydantic)
       ├─ Dual ID generation (semantic + instance)
       ├─ Version key assignment
       └─ Normalization
          ↓
Unified Pricing Read Layer
       ├─ Hot Store (latest projections via views)
       └─ Cold Store (append-only fact tables)
```

## Installation

### Prerequisites
- Python 3.9 or higher
- pip

### Setup

1. **Create virtual environment**:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

## Running the Prototype

Start the Streamlit app:

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`

## Running Tests

All tests are now organized in the `tests/` directory:

```bash
# Activate virtual environment
source venv/bin/activate

# Run individual tests
python tests/test_b2b_real_files.py       # B2B affiliate integration test
python tests/test_rebooking_flow.py       # Status-driven obligations
python tests/test_refund_issued.py        # Refund lineage
python tests/test_payment_fee_scenario.py # Payment fees
python tests/test_b2b_affiliate.py        # Manual affiliate flow
```

See `tests/README.md` for detailed test documentation.

## Project Structure

```
pricing-read/
├── app.py                          # Main Streamlit application entry point
├── requirements.txt                # Python dependencies (streamlit, pydantic, pandas, plotly)
├── run.sh                          # Quick-start bash script (setup + launch)
├── .gitignore                      # Git ignore rules
│
├── Documentation/
│   ├── README.md                       # This file - main project documentation
│   ├── ARCHITECTURE.md                 # System design & data flow
│   ├── QUICKSTART.md                   # Getting started guide (5-minute setup)
│   ├── B2B_AFFILIATE_GUIDE.md          # B2B affiliate feature documentation
│   ├── IMPLEMENTATION_SUMMARY.md       # Technical implementation details
│   ├── SCHEMA_COMPATIBILITY_SUMMARY.md # Event & model schema reference
│   ├── CHANGELOG.md                    # Version history & release notes
│   └── CLEANUP_SUMMARY.md              # Cleanup & refactoring notes
│
├── src/                            # Core Application Code
│   ├── models/                     # Data Models
│   │   ├── events.py              # Producer event schemas (Pydantic)
│   │   │                          # - 11 event types, 11+ component types
│   │   │                          # - PricingUpdated, Payment, Supplier, Refund events
│   │   │                          # - Context models (Customer, Entity, FX)
│   │   └── normalized.py          # Normalized storage models
│   │                              # - Enriched with dual IDs & versions
│   │                              # - DLQ entry model
│   │
│   ├── ingestion/                 # Event Processing
│   │   ├── pipeline.py            # Order Core ingestion logic (~400 lines)
│   │   │                          # - Event validation, routing, normalization
│   │   │                          # - Version assignment per family
│   │   │                          # - DLQ handling for failures
│   │   └── id_generator.py        # Dual ID generation strategy
│   │                              # - Semantic ID: stable logical identity
│   │                              # - Instance ID: unique per snapshot
│   │
│   ├── storage/                   # Data Persistence
│   │   └── database.py            # SQLite wrapper (~500 lines)
│   │                              # - Fact tables: pricing, payment, supplier, refund, dlq
│   │                              # - Derived views for latest state
│   │                              # - Query methods for all entities
│   │
│   └── ui/                        # Streamlit UI Components
│       ├── producer_playground.py # Event emission interface
│       │                          # - Sample events (hotel, flight, train, transfer)
│       │                          # - Payment & refund event editors
│       ├── order_explorer.py      # Data visualization & browsing
│       │                          # - Latest pricing, version history
│       │                          # - Component lineage, payment/supplier timelines
│       └── stress_tests.py        # Edge case testing
│                                  # - Out-of-order, duplicates, validation errors
│
├── tests/                          # Test Suite
│   ├── README.md                   # Test documentation
│   ├── test_b2b_real_files.py      # B2B affiliate integration (uses real payloads)
│   ├── test_rebooking_flow.py      # Status-driven obligations & rebooking
│   ├── test_refund_issued.py       # Refund component lineage
│   ├── test_payment_fee_scenario.py# Payment transaction fees
│   └── test_b2b_affiliate.py       # Manual affiliate flow construction
│
├── components-helper/              # Test Data & Documentation
│   ├── b2b_affiliate_case/         # Real B2B event sequence (7 events)
│   │   ├── 1_pricingUpdated.json
│   │   ├── 1b_pricingUpdated_paymentFee.json
│   │   ├── 2_paymentAuth.json
│   │   ├── 3_paymentCaptured.json
│   │   ├── 4_issuanceSupplierLifecycle.json
│   │   ├── 5_issuanceCancelledtoSupplier.json
│   │   ├── 6_issuanceUpdatetoExpedia.json
│   │   ├── 7_refundIssued.json
│   │   └── instrument.json         # Masked payment instrument
│   │
│   ├── train_case_va/              # Train booking test case (4 events)
│   │   ├── 1_pricingUpdated_train.json
│   │   ├── 2_paymentAuth.json
│   │   ├── 3_paymentCaptured.json
│   │   └── 4_issuanceSupplierLifecycle.json
│   │
│   ├── multi_order_detail_case/    # Multi-detail booking scenario
│   │   └── 1_pricingUpdated_multi_detail.json
│   │
│   ├── db_improvement.md           # Database schema enhancement notes
│   ├── refundInstruction.md        # Refund processing guide
│   ├── accomRoomRateInfo.txt       # Room rate information format
│   └── orderCartFlight.txt         # Flight booking format
│
├── data/
│   └── uprl.db                     # SQLite database (created at runtime, gitignored)
│
└── venv/                           # Python virtual environment (gitignored)
```

## Key Concepts

### 1. Dual ID Strategy

Each pricing component has two IDs:

- **Semantic ID**: Stable logical identity (e.g., `cs-ORD-9001-OD-001-BaseFare`)
  - Constructed from: `{order_id}-{dimensions}-{component_type}`
  - Stays constant across repricing, refunds, or lifecycle changes

- **Instance ID**: Unique per snapshot (e.g., `ci_f0a1d2c3b4a50001`)
  - Hash of semantic ID + snapshot ID
  - Identifies specific occurrence in a pricing snapshot

### 2. Version Families

The system tracks **5 separate version dimensions** that evolve independently:

- **Pricing Snapshot Version** (`pricing_snapshot_id` + `version`) - per order
- **Payment Timeline Version** (`timeline_version`) - per order
- **Supplier Timeline Version** (`supplier_timeline_version`) - per order_detail_id
- **Issuance Timeline Version** (`issuance_version`) - per order_detail_id
- **Refund Timeline Version** (`refund_timeline_version`) - per refund_id

### 3. Append-Only Architecture

- All changes create new versions
- History is immutable (no updates or deletes)
- Refunds create new components with `refund_of_component_semantic_id` pointing to originals
- Enables complete audit trail and time-travel queries

### 4. Component Granularity

Components can exist at different scopes:
- **Order-level**: Platform fees, markup (empty `dimensions`)
- **Order detail-level**: Base fare per room/journey (`{"order_detail_id": "OD-001"}`)
- **Granular**: Per-passenger, per-leg, per-night (`{"order_detail_id": "OD-001", "pax_id": "A1", "leg_id": "CGK-SIN"}`)

## Usage Examples

### Example 1: Simple Hotel Booking

1. Go to **Producer Playground** → **Pricing Events**
2. Select "Hotel 3-Night Booking (Simple)"
3. Click "Emit Event"
4. Go to **Order Explorer** → Select the order → View breakdown

Result: See base fare, tax, and fee components with semantic IDs

### Example 2: Hotel with Refund

1. Emit "Hotel 3-Night Booking" (version 1)
2. Go to **Producer Playground** → **Refund Events** → "Component Events"
3. Update `order_id` to match the hotel booking
4. Set `version` to 2
5. Emit the refund event
6. Go to **Order Explorer** → **Component Lineage**

Result: See original component and refund component with lineage pointer

### Example 3: Out-of-Order Events

1. Go to **Stress Tests** → "Out-of-Order Events"
2. Emit Version 3 first
3. Emit Version 2 second
4. Go to **Order Explorer** → **Version History**

Result: Both versions stored; latest view correctly shows v3

### Example 4: Payment Timeline

1. Emit a pricing event to create an order
2. Go to **Producer Playground** → **Payment Events**
3. Emit sequence: checkout → authorized → captured
4. Go to **Order Explorer** → **Payment Timeline**

Result: See complete payment lifecycle with timeline versions

## Database Schema

### Fact Tables (Append-Only)

- **pricing_components_fact**: All pricing components with dual IDs
- **payment_timeline**: Payment lifecycle events
- **supplier_timeline**: Supplier order lifecycle
- **refund_timeline**: Refund lifecycle events
- **dlq**: Dead Letter Queue for failed events

### Derived Views (Latest State)

- **order_pricing_latest**: Latest pricing breakdown per order
- **payment_timeline_latest**: Latest payment status per order
- **supplier_timeline_latest**: Latest supplier status per order_detail
- **refund_timeline_latest**: Latest refund status per refund_id

## Testing

### Validation Tests

Test Pydantic schema validation:
- Invalid component types → DLQ
- Missing required fields → DLQ
- Invalid enum values → DLQ

### Edge Cases

- Out-of-order events (v3 before v2) → Both stored
- Duplicate event IDs → Currently allowed (production should add uniqueness constraint)
- Version gaps (v1 → v3) → Accepted but could be monitored
- Negative amounts → Valid for Subsidy, Discount, Refund

## Production Considerations

This prototype demonstrates core concepts. For production:

1. **Replace SQLite with production database** (Spanner, PostgreSQL)
2. **Add event uniqueness constraint** on `event_id` for idempotency
3. **Implement version gap monitoring** and alerting
4. **Add authentication and authorization**
5. **Implement event replay** for backfills
6. **Add schema registry** (Avro/Protobuf) for event evolution
7. **Implement transactional outbox pattern** for atomic event publishing
8. **Add monitoring and observability** (metrics, traces, logs)
9. **Implement rate limiting** and backpressure handling
10. **Add data retention policies** and archival

## Troubleshooting

### App won't start
- Ensure Python 3.9+ is installed: `python --version`
- Activate virtual environment: `source venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

### Database errors
- Delete `data/uprl.db` and restart (will reinitialize schema)
- Or use **Settings** → "Clear All Data" in the app

### Events not appearing
- Check **Ingestion Console** for DLQ entries
- Verify JSON format in Producer Playground
- Ensure required fields are present

## Documentation References

- **PRD**: `../prd_v2.md` - Comprehensive product requirements
- **Architecture Decision**: `../../workshop-prep/price-components-workshop/Order_Platform_Architecture_Decision_Report.html`
- **Prototype Plan**: `./prototype.md` - Detailed implementation guide

## Contributing

This is an educational prototype. For production implementation, consult:
- Order Platform Engineering team
- Finance/EDP stakeholders
- Vertical service owners

## License

Educational and demonstration purposes - Open source

---

**Built with**: Streamlit, SQLite, Pydantic, Python 3.9+

**Purpose**: Educational demonstration of event-driven pricing architecture

**Version**: 1.0.0
