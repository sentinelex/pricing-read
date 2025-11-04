# UPRL Prototype Test Suite

Essential tests covering core functionality of the Unified Pricing Read Layer prototype.

## Test Files

### `test_b2b_real_files.py`
**Purpose:** Integration test using real production payloads from B2B affiliate case

**Coverage:**
- Complete lifecycle: Pricing → Payment → Supplier Issuance
- Multi-party payables (supplier, affiliate commission, tax withholding)
- Real production schema validation
- Customer context, detail context, FX context
- Reseller information handling

**Run:** `python tests/test_b2b_real_files.py`

---

### `test_rebooking_flow.py`
**Purpose:** Status-driven obligation model for supplier rebooking scenarios

**Coverage:**
- NATIVE issued → NATIVE cancelled no fee → EXPEDIA confirmed
- ROW_NUMBER() OVER window function for latest status
- Effective payable calculation based on status
- Cancellation fee scenarios
- Affiliate commission persistence across rebooking

**Run:** `python tests/test_rebooking_flow.py`

---

### `test_refund_issued.py`
**Purpose:** Refund component lineage and optional event_id handling

**Coverage:**
- RefundIssuedEvent with optional event_id
- Refund component with lineage pointer (refund_of_component_semantic_id)
- Order Core enrichment (pricing_snapshot_id, version)
- Negative amount validation

**Run:** `python tests/test_refund_issued.py`

---

### `test_payment_fee_scenario.py`
**Purpose:** Payment fee handling at order level (no order_detail_id)

**Coverage:**
- TransactionFee component at order level
- Dimension-less components
- Payment timeline with fees
- Latest breakdown aggregation

**Run:** `python tests/test_payment_fee_scenario.py`

---

### `test_b2b_affiliate.py`
**Purpose:** Manual B2B affiliate flow with programmatic event construction

**Coverage:**
- Complete 4-event flow (pricing, payment auth, payment captured, supplier)
- Nested affiliate object with shareback + VAT
- Payment instrument masking
- Entity context (merchant of record, supplier entity)

**Run:** `python tests/test_b2b_affiliate.py`

---

## Running All Tests

```bash
# Individual tests
python tests/test_b2b_real_files.py
python tests/test_rebooking_flow.py
python tests/test_refund_issued.py
python tests/test_payment_fee_scenario.py
python tests/test_b2b_affiliate.py

# Or use pytest (if installed)
pytest tests/
```

## Test Data Location

Test payloads are located in:
```
../components-helper/b2b_affiliate_case/
├── 1_pricingUpdated.json
├── 2_paymentAuth.json
├── 3_paymentCaptured.json
├── 4_issuanceSupplierLifecycle.json
├── 5_issuanceCancelledtoSupplier.json
├── 6_issuanceUpdatetoExpedia.json
├── 7_refundIssued.json
└── instrument.json
```

## Test Database

Tests use isolated databases in `data/`:
- `test_b2b_real_files.db` - Created fresh for each run
- `test_rebooking.db` - Created fresh for each run
- Main `uprl.db` - Not affected by tests

## Success Criteria

All tests should:
- ✅ Ingest events without validation errors
- ✅ Generate correct dual IDs (semantic_id + instance_id)
- ✅ Calculate accurate payables and breakdowns
- ✅ Handle zero-decimal currencies (IDR) correctly
- ✅ Support status-driven obligation model
- ✅ Maintain component lineage for refunds

