"""
End-to-End Test Script for Supplier Lifecycle v2 Multi-Party Structure

Tests all 4 scenarios:
1. Scenario A: Issued → Effective Payables Includes All Parties
2. Scenario B: Issued → Cancelled → Affiliate Obligations Carried Forward (Projection)
3. Scenario C: Issued → Cancelled → Partner Penalty Persists
4. Scenario D: Issued → Cancelled with Adjusted Affiliate

Run this script to validate the complete implementation.
"""

import json
import os
from datetime import datetime, timezone
from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


# The original sample_events/supplier_v2/ fixtures were reorganized into
# supplier_and_payable_event/ — map the legacy names to their new homes
_RENAMED_FIXTURES = {
    "1_issued_with_parties.json":
        "supplier-lifecycle/001-supplier-issued-multi-party-with-amount-effect.json",
    "2_cancelled_with_fee_no_parties.json":
        "supplier-lifecycle/002-supplier-cancelled-projection-based.json",
    "3_cancelled_with_adjusted_affiliate.json":
        "supplier-lifecycle/003-supplier-cancelled-adjusted-affiliate.json",
    "4_affiliate_penalty.json":
        "partner-adjustment-SF/004-partner-adjustment-standalone-penalty.json",
}
_FIXTURE_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "sample_events", "supplier_and_payable_event")


def load_sample_event(filename):
    """Load sample event from file"""
    filepath = os.path.join(_FIXTURE_BASE, _RENAMED_FIXTURES.get(filename, filename))
    with open(filepath, 'r') as f:
        event = json.load(f)
    # Update timestamp
    event["emitted_at"] = datetime.now(timezone.utc).isoformat()
    return event


def print_section(title):
    """Print formatted section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_payables(payables):
    """Print formatted payables breakdown"""
    for detail in payables:
        print(f"\n📦 Order Detail: {detail['order_detail_id']}")
        baseline = detail['supplier_baseline']
        print(f"   Supplier: {baseline['supplier_id']} | Status: {baseline['status']}")
        print(f"   Baseline: {baseline['amount']} {baseline['currency']}", end="")
        if baseline.get('amount_basis'):
            print(f" ({baseline['amount_basis']})", end="")
        print()
        print(f"   Reason: {baseline['reason']}")

        if detail['party_obligations']:
            print(f"\n   Party Obligations:")
            for obl in detail['party_obligations']:
                effect_symbol = "🔺" if obl['amount_effect'] == 'INCREASES_PAYABLE' else "🔻"
                print(f"     {effect_symbol} {obl['obligation_type']}: {obl['amount']} {obl['currency']} ({obl['amount_effect']})")
                print(f"        Party: {obl['party_name']} (ID: {obl['party_id']})")

        print(f"\n   💰 Total Payable: {detail['total_payable']} {baseline['currency']}")
        print("   " + "-" * 76)


def test_scenario_a():
    """
    Scenario A: Issued → Effective Payables Includes All Parties

    Expected Outcome (per current fixture values):
    - Baseline: 1500000 IDR (gross)
    - Supplier commission retention: -150000 IDR (DECREASES_PAYABLE)
    - Affiliate commission: +4694 IDR (INCREASES_PAYABLE)
    - VAT on affiliate: +516 IDR (INCREASES_PAYABLE)
    - Total: 1500000 - 150000 + 4694 + 516 = 1355210 IDR
    """
    print_section("SCENARIO A: Issued with Multi-Party Obligations")

    # Setup
    db = Database(":memory:")
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)

    # Emit v1: Issued with parties
    event = load_sample_event("1_issued_with_parties.json")
    result = pipeline.ingest_event(event)

    print(f"✅ Ingestion: {result.message}")
    print(f"   Details: {result.details}")

    # Query payables
    payables = db.get_total_effective_payables("ORD-9001")
    print_payables(payables)

    # Validate
    assert len(payables) == 1, "Should have 1 order_detail"
    detail = payables[0]
    assert detail['supplier_baseline']['amount'] == 1500000, "Baseline should be 1500000"
    assert detail['supplier_baseline']['amount_basis'] == "gross", "Basis should be gross"
    assert len(detail['party_obligations']) == 3, "Should have 3 party obligations"

    # Validate amount_effect logic
    expected_total = 1500000 - 150000 + 4694 + 516  # 1355210
    assert detail['total_payable'] == expected_total, f"Total should be {expected_total}, got {detail['total_payable']}"

    print("\n✅ SCENARIO A PASSED: All party obligations included with correct amount_effect")


def test_scenario_b():
    """
    Scenario B: Issued → Cancelled → Affiliate Carried Forward (Projection)

    Expected Outcome:
    v1: Same as Scenario A (260210 IDR total)
    v2: CancelledWithFee, parties carry only CANCELLATION_FEE
    - Baseline: 0 (fee is a party line, not the legacy fee field)
    - v1 affiliate obligations EXCLUDED (only latest-version lines apply)
    - Obligations: CANCELLATION_FEE +50000
    - Total: 50000 IDR
    """
    print_section("SCENARIO B: Cancelled with Projection (Empty Parties Array)")

    # Setup
    db = Database(":memory:")
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)

    # Emit v1: Issued with parties
    event_v1 = load_sample_event("1_issued_with_parties.json")
    result_v1 = pipeline.ingest_event(event_v1)
    print(f"✅ v1 Ingestion: {result_v1.message}")

    # Emit v2: Cancelled with fee, NO parties array
    event_v2 = load_sample_event("2_cancelled_with_fee_no_parties.json")
    result_v2 = pipeline.ingest_event(event_v2)
    print(f"✅ v2 Ingestion: {result_v2.message}")

    # Query payables (should show v2 with cancelled status)
    payables = db.get_total_effective_payables("ORD-9001")
    print_payables(payables)

    # Validate
    detail = payables[0]
    assert detail['supplier_baseline']['status'] == "CancelledWithFee", "Status should be CancelledWithFee"
    assert detail['supplier_baseline']['amount'] == 0, "Baseline is 0 (fee is a party line)"
    assert len(detail['party_obligations']) == 1, "Only the latest-version CANCELLATION_FEE applies"
    assert detail['party_obligations'][0]['obligation_type'] == "CANCELLATION_FEE"
    assert detail['total_payable'] == 50000, "Total is the cancellation fee (50000)"

    print("\n✅ SCENARIO B PASSED: Projection correctly excludes timeline obligations on cancellation")


def test_scenario_c():
    """
    Scenario C: Issued → Cancelled → Partner Penalty Persists

    Expected Outcome:
    v1: Issued (260210 IDR)
    v2: Cancelled (50000 IDR baseline, timeline excluded)
    v3: Partner Penalty (standalone, version = -1)
    - Baseline: 0 (fee is a party line: CANCELLATION_FEE +50000)
    - Affiliate penalty: +500000 IDR (INCREASES_PAYABLE, version = -1)
    - Total: 50000 + 500000 = 550000 IDR
    """
    print_section("SCENARIO C: Standalone Partner Penalty Persists After Cancellation")

    # Setup
    db = Database(":memory:")
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)

    # Emit v1: Issued with parties
    event_v1 = load_sample_event("1_issued_with_parties.json")
    pipeline.ingest_event(event_v1)
    print("✅ v1: Issued")

    # Emit v2: Cancelled with fee
    event_v2 = load_sample_event("2_cancelled_with_fee_no_parties.json")
    pipeline.ingest_event(event_v2)
    print("✅ v2: Cancelled")

    # Emit partner adjustment (version = -1)
    event_penalty = load_sample_event("4_affiliate_penalty.json")
    result_penalty = pipeline.ingest_event(event_penalty)
    print(f"✅ Partner Adjustment: {result_penalty.message}")

    # Query payables
    payables = db.get_total_effective_payables("ORD-9001")
    print_payables(payables)

    # Validate
    detail = payables[0]
    assert detail['supplier_baseline']['status'] == "CancelledWithFee", "Status should be CancelledWithFee"
    assert len(detail['party_obligations']) == 2, "CANCELLATION_FEE (timeline) + penalty (standalone)"

    penalty_obl = next(o for o in detail['party_obligations']
                       if o['obligation_type'] == 'AFFILIATE_PENALTY')
    assert penalty_obl['obligation_type'] == "AFFILIATE_PENALTY", "Should be AFFILIATE_PENALTY"
    assert penalty_obl['amount'] == 500000, "Penalty amount should be 500000"
    assert penalty_obl['amount_effect'] == "INCREASES_PAYABLE", "Should increase payable"

    expected_total = 50000 + 500000  # 550000
    assert detail['total_payable'] == expected_total, f"Total should be {expected_total}"

    print("\n✅ SCENARIO C PASSED: Standalone penalty persists regardless of supplier status")


def test_scenario_d():
    """
    Scenario D: Issued → Cancelled with Adjusted Affiliate

    Expected Outcome:
    v1: Issued (original affiliate commission based on booking)
    v2: Cancelled with UPDATED parties array (affiliate adjusted to cancellation fee basis)
    - Baseline: 0 (fee is a party line)
    - v1 obligations EXCLUDED (only latest-version lines apply):
      - Cancellation fee: +75000 IDR (INCREASES_PAYABLE)
      - Affiliate commission: +2000 IDR (adjusted, INCREASES_PAYABLE)
      - VAT: +220 IDR (INCREASES_PAYABLE)
    - Total: 75000 + 2000 + 220 = 77220 IDR
    """
    print_section("SCENARIO D: Cancelled with Adjusted Affiliate Obligations")

    # Setup
    db = Database(":memory:")
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)

    # Same partition as fixture 003 (ORD-9001 / OD-001 / REF-AGODA-002)
    # Emit v1: Issued (we'll create a simple one inline)
    event_v1 = {
        "event_id": "evt_issued_v1_ord9001d",
        "event_type": "SupplierLifecycleEvent",
        "schema_version": "supplier.timeline.v2",
        "order_id": "ORD-9001",
        "order_detail_id": "OD-001",
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "supplier": {
            "status": "ISSUED",
            "supplier_id": "AGODA",
            "supplier_ref": "REF-AGODA-002",
            "amount_due": 350000,
            "amount_basis": "gross",
            "currency": "IDR"
        },
        "parties": [
            {
                "party_type": "AFFILIATE",
                "party_id": "100005361",
                "party_name": "Partner CFD",
                "lines": [
                    {
                        "obligation_type": "AFFILIATE_COMMISSION",
                        "amount": 5000,
                        "amount_effect": "INCREASES_PAYABLE",
                        "currency": "IDR"
                    }
                ]
            }
        ]
    }
    pipeline.ingest_event(event_v1)
    print("✅ v1: Issued with original affiliate commission (5000)")

    # Emit v2: Cancelled with adjusted affiliate
    event_v2 = load_sample_event("3_cancelled_with_adjusted_affiliate.json")
    result_v2 = pipeline.ingest_event(event_v2)
    print(f"✅ v2: {result_v2.message}")

    # Query payables
    payables = db.get_total_effective_payables("ORD-9001")
    print_payables(payables)

    # Validate
    detail = payables[0]
    assert detail['supplier_baseline']['status'] == "CancelledWithFee", "Status should be CancelledWithFee"
    assert detail['supplier_baseline']['amount'] == 0, "Baseline is 0 (fee is a party line)"

    # All 3 latest-version lines apply (fee + adjusted affiliate + VAT)
    assert len(detail['party_obligations']) == 3, f"Should have 3 obligations from v2, got {len(detail['party_obligations'])}"

    affiliate_comm = next(o for o in detail['party_obligations'] if o['obligation_type'] == 'AFFILIATE_COMMISSION')
    assert affiliate_comm['amount'] == 2000, "Affiliate commission should be adjusted to 2000"

    expected_total = 0 + 75000 + 2000 + 220  # 77220
    assert detail['total_payable'] == expected_total, f"Total should be {expected_total}, got {detail['total_payable']}"

    print("\n✅ SCENARIO D PASSED: Latest obligations win via party-level projection")


def run_all_tests():
    """Run all test scenarios"""
    print("\n" + "🧪" * 40)
    print("  COMPREHENSIVE END-TO-END TEST SUITE")
    print("  Multi-Party Supplier Lifecycle v2")
    print("🧪" * 40)

    try:
        test_scenario_a()
        test_scenario_b()
        test_scenario_c()
        test_scenario_d()

        print("\n" + "✅" * 40)
        print("  ALL TESTS PASSED!")
        print("  Multi-party structure with amount_effect working correctly")
        print("✅" * 40 + "\n")

        return True
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
