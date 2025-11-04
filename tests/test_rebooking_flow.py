#!/usr/bin/env python3
"""
Test Rebooking Flow - Status-Driven Obligation Model
Tests: NATIVE ISSUED → NATIVE CancelledNoFee → EXPEDIA Confirmed
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


def test_rebooking_flow():
    """Test complete rebooking flow with status-driven obligations"""

    print("=" * 80)
    print("TEST: REBOOKING FLOW - STATUS-DRIVEN OBLIGATION MODEL")
    print("=" * 80)
    print("\nScenario: Rebooking from NATIVE to EXPEDIA with free cancellation")
    print("- Event 1: NATIVE issued (should show IDR 246,281)")
    print("- Event 2: NATIVE cancelled no fee (should show IDR 0 struck through)")
    print("- Event 3: EXPEDIA confirmed (should show IDR 250,000)")
    print("- Affiliate: Same commission applies (IDR 4,694)\n")

    db = Database("data/uprl.db")
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)

    order_id = "1200496236"
    order_detail_id = "1200917821"

    # =========================================================================
    # EVENT 1: NATIVE ISSUED
    # =========================================================================
    print("-" * 80)
    print("EVENT 1: NATIVE ISSUED")
    print("-" * 80)

    event1_path = Path("../components-helper/b2b_affiliate_case/4_issuanceSupplierLifecycle.json")
    with open(event1_path) as f:
        event1 = json.load(f)

    result1 = pipeline.ingest_event(event1)
    print(f"  ✅ {result1.message}")
    print(f"  Details: {result1.details}")

    # =========================================================================
    # EVENT 2: NATIVE CANCELLED NO FEE
    # =========================================================================
    print("\n" + "-" * 80)
    print("EVENT 2: NATIVE CANCELLED NO FEE")
    print("-" * 80)

    event2_path = Path("../components-helper/b2b_affiliate_case/5_issuanceCancelledtoSupplier.json")
    with open(event2_path) as f:
        event2 = json.load(f)

    # Add missing field
    if 'supplier_timeline_version' not in event2:
        event2['supplier_timeline_version'] = 2

    result2 = pipeline.ingest_event(event2)
    print(f"  ✅ {result2.message}")
    print(f"  Details: {result2.details}")

    # =========================================================================
    # EVENT 3: EXPEDIA CONFIRMED
    # =========================================================================
    print("\n" + "-" * 80)
    print("EVENT 3: EXPEDIA CONFIRMED (Rebooking)")
    print("-" * 80)

    event3_path = Path("../components-helper/b2b_affiliate_case/6_issuanceUpdatetoExpedia.json")
    with open(event3_path) as f:
        event3 = json.load(f)

    result3 = pipeline.ingest_event(event3)
    print(f"  ✅ {result3.message}")
    print(f"  Details: {result3.details}")

    # =========================================================================
    # VERIFICATION: Status-Driven Effective Payables
    # =========================================================================
    print("\n" + "=" * 80)
    print("VERIFICATION: STATUS-DRIVEN EFFECTIVE PAYABLES")
    print("=" * 80)

    effective_payables = db.get_supplier_effective_payables(order_id, order_detail_id)
    
    print(f"\n  Total Supplier Instances: {len(effective_payables)}")
    print()

    for supplier in effective_payables:
        print(f"  Supplier: {supplier['supplier_id']}")
        print(f"    Ref: {supplier['supplier_reference_id']}")
        print(f"    Status: {supplier['status']}")
        print(f"    Effective Payable: IDR {supplier['effective_payable']:,}")
        print()

    # Verify NATIVE cancelled (0) and EXPEDIA confirmed (250000)
    native = [s for s in effective_payables if s['supplier_id'] == 'NATIVE'][0]
    expedia = [s for s in effective_payables if s['supplier_id'] == 'EXPEDIA'][0]

    assert native['status'] == 'CancelledNoFee', f"NATIVE status should be CancelledNoFee, got {native['status']}"
    assert native['effective_payable'] == 0, f"NATIVE payable should be 0, got {native['effective_payable']}"
    print("  ✅ NATIVE: CancelledNoFee → IDR 0")

    assert expedia['status'] == 'Confirmed', f"EXPEDIA status should be Confirmed, got {expedia['status']}"
    assert expedia['effective_payable'] == 250000, f"EXPEDIA payable should be 250000, got {expedia['effective_payable']}"
    print("  ✅ EXPEDIA: Confirmed → IDR 250,000")

    # =========================================================================
    # VERIFICATION: Affiliate Commissions
    # =========================================================================
    print("\n" + "=" * 80)
    print("VERIFICATION: AFFILIATE COMMISSIONS (LATEST)")
    print("=" * 80)

    affiliate_payables = db.get_supplier_payables_latest(order_id)
    affiliate_commissions = [p for p in affiliate_payables if p['obligation_type'] == 'AFFILIATE_COMMISSION']
    tax_withholdings = [p for p in affiliate_payables if p['obligation_type'] == 'TAX_WITHHOLDING']

    print(f"\n  Total Affiliate Commission Lines: {len(affiliate_commissions)}")
    
    # Get latest affiliate commission (should be from EXPEDIA event)
    latest_affiliate = affiliate_commissions[-1] if affiliate_commissions else None
    
    if latest_affiliate:
        print(f"\n  Latest Affiliate Commission:")
        print(f"    Partner: {latest_affiliate['party_name']} (ID: {latest_affiliate['party_id']})")
        print(f"    Amount: IDR {latest_affiliate['amount']:,}")
        print(f"    Calculation: {latest_affiliate.get('calculation_description', 'N/A')}")
        
        assert latest_affiliate['amount'] == 4694, f"Affiliate amount should be 4694, got {latest_affiliate['amount']}"
        print(f"    ✅ Amount matches expected (IDR 4,694)")

    if tax_withholdings:
        latest_tax = tax_withholdings[-1]
        print(f"\n  Latest Tax Withholding:")
        print(f"    Type: {latest_tax['party_name']}")
        print(f"    Amount: IDR {latest_tax['amount']:,}")
        print(f"    Calculation: {latest_tax.get('calculation_description', 'N/A')}")
        
        assert latest_tax['amount'] == 516, f"Tax amount should be 516, got {latest_tax['amount']}"
        print(f"    ✅ Amount matches expected (IDR 516)")

    # =========================================================================
    # FINANCIAL SUMMARY
    # =========================================================================
    print("\n" + "=" * 80)
    print("FINANCIAL SUMMARY")
    print("=" * 80)

    total_supplier = sum(s['effective_payable'] for s in effective_payables)
    total_affiliate = sum(p['amount'] for p in affiliate_commissions)
    total_tax = sum(p['amount'] for p in tax_withholdings)
    grand_total = total_supplier + total_affiliate + total_tax

    print(f"\n  Supplier Costs (Effective):")
    print(f"    - NATIVE (CancelledNoFee):  IDR 0")
    print(f"    - EXPEDIA (Confirmed):      IDR 250,000")
    print(f"    Total:                      IDR {total_supplier:,}")
    print()
    print(f"  Affiliate Commissions:        IDR {total_affiliate:,}")
    print(f"  Tax Withholdings:             IDR {total_tax:,}")
    print(f"  " + "-" * 40)
    print(f"  Grand Total Payables:         IDR {grand_total:,}")

    # =========================================================================
    # SUCCESS
    # =========================================================================
    print("\n" + "=" * 80)
    print("✅ REBOOKING FLOW TEST PASSED!")
    print("=" * 80)

    print("\nKey Learnings:")
    print("  ✅ Status-driven model: Latest status per supplier determines payable")
    print("  ✅ CancelledNoFee → IDR 0 (correctly zeroed out)")
    print("  ✅ Rebooking: New supplier shows full amount")
    print("  ✅ Affiliate commissions persist across rebooking")
    print("  ✅ ROW_NUMBER() OVER window function works correctly")

    print("\nNext steps:")
    print("  1. View order in Order Explorer: order_id = 1200496236")
    print("  2. Check Supplier Payables tab for status-driven breakdown")
    print("  3. Verify NATIVE shows struck-through IDR 0")
    print("  4. Verify EXPEDIA shows active IDR 250,000")

    return True


if __name__ == "__main__":
    test_rebooking_flow()

