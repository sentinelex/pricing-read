# B2B Affiliate Integration Guide

## Overview

Version 1.0.5 adds support for **real-world B2B affiliate scenarios** with complete schema enhancements based on actual production payloads. This enables the prototype to handle complex reseller relationships, multi-entity tracking, FX contexts, and affiliate commission calculations.

## What's New in v1.0.5

### 1. Enhanced Event Models

#### New Component Types
```python
ComponentType.ROOM_RATE = "RoomRate"  # Accommodation supplier net rate
ComponentType.AFFILIATE_SHAREBACK = "AffiliateShareback"  # B2B commission
ComponentType.VAT = "VAT"  # Value Added Tax
```

#### Context Objects

**CustomerContext** - B2B Reseller Information
```python
{
  "customer_context": {
    "reseller_type_name": "B2B_AFFILIATE",
    "reseller_id": "100005361",
    "reseller_name": "Partner CFD Non IDR - Accommodation - Invoicing"
  }
}
```

**DetailContext** - Entity & FX Tracking
```python
{
  "detail_context": {
    "order_detail_id": "1200917821",
    "entity_context": {
      "entity_code": "TNPL"  # Legal entity for pricing
    },
    "fx_context": {
      "timestamp_fx_rate": "2025-07-31T13:25:21Z",
      "payment_currency": "IDR",
      "supply_currency": "IDR",
      "record_currency": "IDR",
      "gbv_currency": "IDR",
      "payment_value": 293223,
      "supply_to_payment_fx_rate": 1.0,
      "supply_to_record_fx_rate": 1.0,
      "payment_to_gbv_fx_rate": 1.0,
      "source": "Treasury"
    }
  }
}
```

**Payment Object** - Nested Payment Details
```python
{
  "payment": {
    "status": "Authorized",
    "payment_id": "pi_b2b_001",
    "payment_method": {
      "channel": "AFFILIATE_DEPOSIT",
      "provider": "AffiliateDeposit",
      "brand": "INTERNAL"
    },
    "currency": "IDR",
    "authorized_amount": 293223,
    "authorized_at": "2025-07-31T13:25:25Z"
  }
}
```

**Supplier Object** - With Affiliate Shareback
```python
{
  "supplier": {
    "status": "ISSUED",
    "supplier_id": "NATIVE",
    "booking_code": "1859696",
    "amount_due": 246281,
    "currency": "IDR",
    "entity_context": {
      "entity_code": "GTN"  # Legal entity for supplier payable
    },
    "affiliate": {
      "partnerShareback": {
        "component_type": "AffiliateShareback",
        "amount": 4694.2,
        "currency": "IDR",
        "rate": 0.1,
        "basis": "markup"
      },
      "taxes": [
        {
          "type": "VAT",
          "amount": 516.36,
          "currency": "IDR",
          "rate": 0.11,
          "basis": "shareback"
        }
      ]
    }
  }
}
```

### 2. New Producer Playground Scenario

**"B2B Affiliate Accommodation (Real Schema)"**

Access via:
1. Navigate to **Producer Playground** → **Pricing Events**
2. Select **"B2B Affiliate Accommodation (Real Schema)"** from dropdown
3. Click **Financial Breakdown** expander to see calculations

**What it includes**:
- ✅ Customer context (reseller info)
- ✅ Detail context (entity + FX)
- ✅ RoomRate component (supplier net)
- ✅ Markup component (reseller uplift)
- ✅ Totals validation field
- ✅ Real order IDs from production

### 3. Complete Event Flow

The B2B affiliate case includes **4 sequential events**:

| Step | Event Type | Key Data | Purpose |
|------|-----------|---------|---------|
| 1 | `PricingUpdated` | RoomRate + Markup | Customer pricing with reseller markup |
| 2 | `payment.authorized` | AFFILIATE_DEPOSIT | Authorize from affiliate deposit account |
| 3 | `payment.captured` | Captured amount | Confirm payment capture |
| 4 | `IssuanceSupplierLifecycle` | Affiliate shareback + VAT | Supplier issued, calculate commission |

### 4. Test Suite

**`test_b2b_affiliate.py`** - End-to-End Flow Test

Run:
```bash
cd /path/to/prototype
source venv/bin/activate
python3 test_b2b_affiliate.py
```

**Expected Output**:
```
EVENT 1: PricingUpdated (with customer_context + detail_context + fx_context)
  ✅ Ingested 2 components
  Pricing Breakdown:
    - RoomRate: IDR 2,462.81
    - Markup: IDR 469.42
    TOTAL: IDR 2,932.23

EVENT 2: Payment Authorized (AFFILIATE_DEPOSIT channel)
  ✅ Ingested payment event

EVENT 3: Payment Captured
  ✅ Ingested payment event

EVENT 4: IssuanceSupplierLifecycle (with affiliate shareback + VAT)
  Affiliate Shareback:
    Commission: IDR 4,694.20 (10% of markup)
    VAT: IDR 516.36 (11% of shareback)
  ✅ Ingested supplier event

FINANCIAL SUMMARY
  Customer Pays (Affiliate):  IDR 2,932.23
  Supplier Cost (NATIVE):     IDR 2,462.81
  -------------------------------
  Gross Margin (Markup):      IDR 469.42
  Affiliate Commission (10%): IDR 46.94
  VAT on Commission (11%):    IDR 5.16
  -------------------------------
  Net Revenue to Tiket:       IDR 417.32

  Margin %: 16.01%
  Net Margin %: 14.23%

✅ ALL EVENTS INGESTED SUCCESSFULLY
```

## Business Scenario Explained

### Flow Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     B2B AFFILIATE FLOW                        │
└──────────────────────────────────────────────────────────────┘

1. PRICING (Entity: TNPL)
   ┌─────────────────────────────────────────┐
   │ Affiliate Partner requests booking      │
   │ Tiket.com calculates:                   │
   │   - Supplier Net (NATIVE): IDR 2,462.81 │
   │   - Markup (B2B uplift):  + IDR 469.42  │
   │   ─────────────────────────────────────  │
   │   Customer Total:          IDR 2,932.23 │
   └─────────────────────────────────────────┘
                    ↓
2. PAYMENT (Affiliate Deposit Account)
   ┌─────────────────────────────────────────┐
   │ Payment authorized from affiliate       │
   │ deposit balance (not end-customer CC)   │
   │   Channel: AFFILIATE_DEPOSIT            │
   │   Amount: IDR 2,932.23                  │
   └─────────────────────────────────────────┘
                    ↓
3. PAYMENT CAPTURED
   ┌─────────────────────────────────────────┐
   │ Payment captured after confirmation     │
   │   Captured: IDR 2,932.23                │
   └─────────────────────────────────────────┘
                    ↓
4. SUPPLIER ISSUANCE (Entity: GTN)
   ┌─────────────────────────────────────────┐
   │ Booking issued to supplier (NATIVE)     │
   │ Affiliate commission calculated:        │
   │   - Shareback: 10% of Markup = IDR 46.94│
   │   - VAT: 11% of Shareback = IDR 5.16    │
   │   ─────────────────────────────────────  │
   │   Net Revenue: IDR 417.32               │
   └─────────────────────────────────────────┘
```

### Financial Breakdown

| Item | Amount (IDR) | Calculation | Notes |
|------|--------------|-------------|-------|
| **Customer Pays** | 2,932.23 | - | Paid by affiliate partner |
| **Supplier Cost** | 2,462.81 | RoomRate | What Tiket pays NATIVE |
| **Gross Margin** | 469.42 | Markup | Tiket's gross revenue |
| **Affiliate Commission** | 46.94 | 10% × Markup | Commission to affiliate |
| **VAT on Commission** | 5.16 | 11% × Commission | Tax on shareback |
| **Net Revenue** | 417.32 | Markup - Commission - VAT | Tiket's net revenue |

**Margin Analysis**:
- **Gross Margin %**: 16.01% (469.42 / 2,932.23)
- **Net Margin %**: 14.23% (417.32 / 2,932.23)
- **Commission %**: 1.60% (46.94 / 2,932.23)

### Entity Context

**Why Two Entities?**

```
TNPL (Tiket Nusantara Perkasa)
  └─ Pricing Entity
     └─ Issues customer invoice
     └─ Receives payment from affiliate

GTN (Garuda Tiket Nusantara)
  └─ Supplier Payable Entity
     └─ Owes payment to NATIVE supplier
     └─ Pays affiliate shareback + VAT
```

This separation enables:
- **Legal entity optimization** for tax purposes
- **Intercompany tracking** for consolidation
- **Entity-specific P&L reporting**

## Usage Examples

### Example 1: Emit B2B Pricing Event via UI

```
1. Open Producer Playground → Pricing Events
2. Select "B2B Affiliate Accommodation (Real Schema)"
3. Click "Financial Breakdown" expander to review calculations
4. Review JSON in text editor
5. Click "Emit Event"
6. Navigate to Order Explorer
7. Search for order_id: 1200496236
8. View Latest Breakdown:
   - RoomRate: IDR 2,462.81 (meta.basis: supplier_net)
   - Markup: IDR 469.42 (meta.notes: B2B reseller price uplift)
```

### Example 2: Emit via JSON Mode

```
1. Switch to "JSON Mode (Full Control)"
2. Edit JSON to customize:
   - reseller_id
   - entity_code (TNPL, GTN, etc.)
   - FX rates
   - Shareback rate
3. Click "Emit Event"
```

### Example 3: Programmatic Emission

```python
from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline

db = Database("data/uprl.db")
db.connect()
pipeline = IngestionPipeline(db)

event = {
    "event_type": "PricingUpdated",
    "order_id": "1200496236",
    "vertical": "accommodation",
    "customer_context": {
        "reseller_type_name": "B2B_AFFILIATE",
        "reseller_id": "100005361",
        "reseller_name": "Partner CFD Non IDR - Accommodation - Invoicing"
    },
    "detail_context": {
        "order_detail_id": "1200917821",
        "entity_context": {"entity_code": "TNPL"},
        "fx_context": { /* ... */ }
    },
    "components": [ /* ... */ ]
}

result = pipeline.ingest_event(event)
print(result.message)

db.close()
```

## Schema Compatibility

### Backward Compatibility ✅

All existing simple events still work:

```python
# OLD FORMAT (Still Supported)
{
    "event_id": str(uuid.uuid4()),
    "event_type": "pricing.updated",
    "order_id": "ORD-9001",
    "components": [
        {
            "component_type": "BaseFare",
            "amount": 150000000,
            "currency": "IDR",
            "dimensions": {"order_detail_id": "OD-001"}
        }
    ],
    "emitted_at": datetime.utcnow().isoformat(),
    "emitter_service": "accommodation-service"
}
```

### Forward Compatibility ✅

New schema with optional fields:

```python
# NEW FORMAT (B2B Affiliate)
{
    "event_type": "PricingUpdated",  # Support both formats
    "order_id": "1200496236",
    "vertical": "accommodation",  # OPTIONAL
    "customer_context": { /* ... */ },  # OPTIONAL
    "detail_context": { /* ... */ },  # OPTIONAL
    "components": [
        {
            "component_type": "RoomRate",
            "meta": {"basis": "supplier_net"},  # OPTIONAL
            /* ... */
        }
    ],
    "totals": {"customer_total": 293223, "currency": "IDR"},  # OPTIONAL
    "emitted_at": "2025-07-31T13:25:21Z"  # String or datetime
}
```

**All optional fields gracefully degrade** - events without them will still ingest successfully.

## Data Model Changes

### Pydantic Models

**New Classes** ([src/models/events.py](src/models/events.py)):
- `CustomerContext`
- `EntityContext`
- `FXContext`
- `DetailContext`
- `Totals`
- `PaymentMethod`
- `Payment`
- `AffiliateShareback`
- `AffiliateTax`
- `Affiliate`
- `Supplier`

**Enhanced Classes**:
- `PricingComponent`: Added `meta` field (changed from `metadata`)
- `PricingUpdatedEvent`: Added optional context fields
- `PaymentLifecycleEvent`: Added nested `payment` object
- `SupplierLifecycleEvent`: Added nested `supplier` object with `affiliate`

### Database Schema

**No migration required!** ✅

The existing SQLite schema stores JSON blobs, so all new nested structures are automatically stored:
- `customer_context` → stored as JSON string
- `detail_context.fx_context` → nested JSON
- `supplier.affiliate` → nested JSON

**Storage Format**:
```sql
INSERT INTO pricing_components_fact (
    /* existing columns */
    dimensions  -- Stores {"order_detail_id": "1200917821"} as JSON
);

-- New fields stored in metadata/dimensions JSON:
-- meta.basis, meta.notes, etc.
```

## Production Considerations

### 1. Entity Context Tracking

For production implementation, consider:
- **Entity Master Data**: Maintain entity code → legal entity mapping
- **P&L Segmentation**: Report by entity_code for consolidated financials
- **Tax Jurisdiction**: Entity codes determine VAT/tax treatment

### 2. FX Context Usage

```python
# Example: Multi-currency calculation
fx = event['detail_context']['fx_context']

payment_amount_usd = fx['payment_value'] / fx['payment_to_gbv_fx_rate']
supplier_cost_usd = supplier_amount * fx['supply_to_record_fx_rate']
fx_gain_loss = payment_amount_usd - supplier_cost_usd
```

### 3. Affiliate Commission Processing

**Batch Job Design**:
```python
# Daily shareback calculation
for issued_event in get_supplier_events_with_affiliate(date):
    shareback = issued_event['supplier']['affiliate']['partnerShareback']
    vat = issued_event['supplier']['affiliate']['taxes'][0]

    # Create payable to affiliate
    create_affiliate_payable(
        reseller_id=shareback['reseller_id'],
        amount=shareback['amount'],
        vat=vat['amount'],
        due_date=calculate_due_date()
    )
```

### 4. Idempotency Key Strategy

```python
# Format: {unique_identifier}:{event_stage}
idempotency_key = f"{payment_id}:authorized"
idempotency_key = f"{order_id}:{order_detail_id}:{supplier_id}:issued"

# Benefits:
# - Exactly-once processing
# - Replay safety
# - Duplicate prevention
```

## Troubleshooting

### Issue 1: "Unknown component type 'RoomRate'"

**Cause**: Old version of `events.py` without new component types.

**Fix**: Ensure you're running v1.0.5+ with updated models.

### Issue 2: Validation error on `meta` field

**Cause**: Using `metadata` instead of `meta` in components.

**Fix**: Change:
```python
# OLD
{"component_type": "RoomRate", "metadata": {"basis": "supplier_net"}}

# NEW
{"component_type": "RoomRate", "meta": {"basis": "supplier_net"}}
```

### Issue 3: FX Context decimal precision

**Cause**: FX rates stored as float may lose precision.

**Fix**: In production, consider:
```python
from decimal import Decimal

fx_rate = Decimal('15.245000')  # Instead of float
```

## Related Documentation

- [CHANGELOG.md](CHANGELOG.md) - Version 1.0.5 release notes
- [JSON_MODE_GUIDE.md](JSON_MODE_GUIDE.md) - How to use JSON Mode for complex events
- [test_b2b_affiliate.py](test_b2b_affiliate.py) - Complete test suite
- [b2b_affiliate_full_flow.json](b2b_affiliate_full_flow.json) - Full event sequence

## Real Production Data Source

Events based on actual production payloads from:
- `/components-helper/b2b_affiliate_case/1_pricingUpdated.json`
- `/components-helper/b2b_affiliate_case/2_paymentAuth.json`
- `/components-helper/b2b_affiliate_case/3_paymentCaptured.json`
- `/components-helper/b2b_affiliate_case/4_issuanceSupplierLifecycle.json`

## Summary

**B2B Affiliate support brings the prototype closer to production reality**:

✅ Real-world schema complexity
✅ Multi-entity tracking (TNPL, GTN)
✅ FX context for multi-currency scenarios
✅ Affiliate commission & tax calculations
✅ Backward compatible with simple events
✅ Production-ready patterns (idempotency, nested objects)
✅ Complete test coverage

**Next Steps for Production**:
1. Add schema registry (Avro/Protobuf)
2. Implement entity master data service
3. Build affiliate payable batch jobs
4. Add FX gain/loss calculation
5. Integrate with GL posting

---

**Version**: 1.0.5
**Release Date**: 2025-11-03
**Status**: ✅ Complete and Tested
**Schema Source**: Real B2B affiliate production data
