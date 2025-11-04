#!/usr/bin/env python3
"""
Test Payment Fee Scenario
Tests the case where payment team adds a TransactionFee at order level (no order_detail_id dimension)
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


def test_payment_fee_scenario():
    """Test payment fee added at order level"""

    print("=" * 80)
    print("TEST: PAYMENT FEE AT ORDER LEVEL")
    print("=" * 80)
    print("\nScenario: Payment team adds transaction fee after payment method selection")
    print("- Version 1: Initial pricing (RoomRate + Markup)")
    print("- Version 2: Payment fee added (order-level dimension)\n")

    db = Database("data/uprl.db")
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)

    order_id = "1200496236"
    order_detail_id = "1200917821"

    # =========================================================================
    # EVENT 1: Initial Pricing (v1)
    # =========================================================================
    print("-" * 80)
    print("EVENT 1: Initial PricingUpdated (v1 - No Payment Fee)")
    print("-" * 80)

    with open('../components-helper/b2b_affiliate_case/1_pricingUpdated.json', 'r') as f:
        pricing_event_v1 = json.load(f)

    print(f"\nEmitting pricing event v1...")
    print(f"  Order ID: {pricing_event_v1['order_id']}")
    print(f"  Components: {len(pricing_event_v1['components'])}")
    print(f"  Customer Total: IDR {pricing_event_v1['totals']['customer_total']:,}")

    result = pipeline.ingest_event(pricing_event_v1)

    if result.success:
        print(f"  ✅ {result.message}")
    else:
        print(f"  ❌ {result.message}")
        return False

    # Verify v1 breakdown
    breakdown_v1 = db.get_order_pricing_latest(order_id)
    print(f"\n  Pricing Breakdown (v1):")
    for comp in breakdown_v1:
        print(f"    - {comp['component_type']}: IDR {comp['amount']:,}")
        print(f"      Dimensions: {comp['dimensions']}")
    total_v1 = sum(c['amount'] for c in breakdown_v1)
    print(f"    TOTAL: IDR {total_v1:,}")

    # =========================================================================
    # EVENT 2: Payment Fee Added (v2)
    # =========================================================================
    print("\n" + "-" * 80)
    print("EVENT 2: PricingUpdated with Payment Fee (v2 - TransactionFee Added)")
    print("-" * 80)

    with open('../components-helper/b2b_affiliate_case/1b_pricingUpdated_paymentFee.json', 'r') as f:
        pricing_event_v2 = json.load(f)

    print(f"\nEmitting pricing event v2...")
    print(f"  Order ID: {pricing_event_v2['order_id']}")
    print(f"  Components: {len(pricing_event_v2['components'])}")
    print(f"  Customer Total: IDR {pricing_event_v2['totals']['customer_total']:,}")
    print(f"  Trigger: {pricing_event_v2.get('meta', {}).get('trigger', 'N/A')}")

    result = pipeline.ingest_event(pricing_event_v2)

    if result.success:
        print(f"  ✅ {result.message}")
    else:
        print(f"  ❌ {result.message}")
        return False

    # =========================================================================
    # VERIFICATION: Latest Breakdown (v2)
    # =========================================================================
    print("\n" + "=" * 80)
    print("VERIFICATION: Latest Breakdown (v2)")
    print("=" * 80)

    breakdown_v2 = db.get_order_pricing_latest(order_id)
    print(f"\n  Total Components: {len(breakdown_v2)}")
    print(f"\n  Pricing Breakdown (v2):")

    order_level_components = []
    detail_level_components = []

    for comp in breakdown_v2:
        dims = json.loads(comp['dimensions'])
        if not dims or dims == {}:
            order_level_components.append(comp)
        else:
            detail_level_components.append(comp)

        print(f"    - {comp['component_type']}: IDR {comp['amount']:,}")
        print(f"      Dimensions: {comp['dimensions']}")
        if comp['description']:
            print(f"      Description: {comp['description']}")

    total_v2 = sum(c['amount'] for c in breakdown_v2)
    print(f"    -------------------------------")
    print(f"    TOTAL: IDR {total_v2:,}")

    # =========================================================================
    # VERIFICATION: Component Granularity
    # =========================================================================
    print("\n" + "=" * 80)
    print("COMPONENT GRANULARITY ANALYSIS")
    print("=" * 80)

    print(f"\n  Order-Level Components (dimensions = empty): {len(order_level_components)}")
    for comp in order_level_components:
        print(f"    - {comp['component_type']}: IDR {comp['amount']:,}")

    print(f"\n  Order_Detail-Level Components: {len(detail_level_components)}")
    for comp in detail_level_components:
        dims = json.loads(comp['dimensions'])
        print(f"    - {comp['component_type']}: IDR {comp['amount']:,}")
        print(f"      order_detail_id: {dims.get('order_detail_id')}")

    # =========================================================================
    # VERIFICATION: Version History
    # =========================================================================
    print("\n" + "=" * 80)
    print("VERSION HISTORY")
    print("=" * 80)

    history = db.get_order_pricing_history(order_id)
    print(f"\n  Total Versions: {len(history)}")
    for row in history:
        print(f"\n  Version {row['version']}:")
        print(f"    Snapshot ID: {row['pricing_snapshot_id']}")
        print(f"    Components: {row['component_count']}")
        print(f"    Total: IDR {row['total_amount']:,}")
        print(f"    Emitted At: {row['emitted_at']}")

    # =========================================================================
    # ASSERTIONS
    # =========================================================================
    print("\n" + "=" * 80)
    print("ASSERTIONS")
    print("=" * 80)

    # Version 2 should have 3 components
    assert len(breakdown_v2) == 3, f"Expected 3 components in v2, got {len(breakdown_v2)}"
    print("  ✅ Version 2 has 3 components")

    # Should have 1 order-level component (TransactionFee)
    assert len(order_level_components) == 1, f"Expected 1 order-level component, got {len(order_level_components)}"
    assert order_level_components[0]['component_type'] == 'TransactionFee'
    assert order_level_components[0]['amount'] == 3000
    print("  ✅ TransactionFee at order level (dimensions = {})")

    # Should have 2 order_detail-level components
    assert len(detail_level_components) == 2, f"Expected 2 detail-level components, got {len(detail_level_components)}"
    print("  ✅ RoomRate and Markup at order_detail level")

    # Total should match customer_total from event
    assert total_v2 == 296223, f"Expected total 296223, got {total_v2}"
    print("  ✅ Total matches customer_total (IDR 296,223)")

    # Verify semantic IDs are different for order-level vs detail-level
    transaction_fee = order_level_components[0]
    room_rate = [c for c in detail_level_components if c['component_type'] == 'RoomRate'][0]

    print(f"\n  Semantic ID Comparison:")
    print(f"    TransactionFee (order-level): {transaction_fee['component_semantic_id']}")
    print(f"    RoomRate (detail-level): {room_rate['component_semantic_id']}")

    # Check that order-level component has "ORDER" marker and detail-level has "OD" marker
    assert '-ORDER-' in transaction_fee['component_semantic_id']
    assert '-OD-' in room_rate['component_semantic_id']
    print("  ✅ Semantic IDs correctly reflect dimension scope (ORDER vs OD)")

    print("\n" + "=" * 80)
    print("✅ ALL ASSERTIONS PASSED")
    print("=" * 80)

    print("\nKey Learnings:")
    print("  ✅ Order-level components have empty dimensions {}")
    print("  ✅ Order_detail-level components have order_detail_id in dimensions")
    print("  ✅ TransactionFee correctly added at order level (applicable to entire order)")
    print("  ✅ Version history preserved (v1 → v2)")
    print("  ✅ Semantic IDs distinguish between component scopes")
    print("  ✅ Customer total updated from 293,223 → 296,223 (+3,000 fee)")

    db.close()
    return True


if __name__ == "__main__":
    success = test_payment_fee_scenario()

    if success:
        print("\n🎉 PAYMENT FEE SCENARIO TEST PASSED!")
        print("\nNext steps:")
        print("  1. Open Order Explorer: order_id = 1200496236")
        print("  2. Check Latest Breakdown tab")
        print("  3. Verify 3 components shown:")
        print("     - RoomRate (order_detail_id: 1200917821)")
        print("     - Markup (order_detail_id: 1200917821)")
        print("     - TransactionFee (order-level, no dimensions)")
        print("  4. Check Version History tab to see v1 → v2 evolution")
        exit(0)
    else:
        print("\n❌ PAYMENT FEE SCENARIO TEST FAILED")
        exit(1)
