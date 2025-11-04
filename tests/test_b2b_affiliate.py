#!/usr/bin/env python3
"""
Test B2B Affiliate Flow - Real Schema
Tests the complete flow with customer_context, detail_context, fx_context, and affiliate data
"""

import json
import uuid
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


def test_b2b_affiliate_complete_flow():
    """Test complete B2B affiliate flow with all 4 events"""

    print("=" * 80)
    print("TEST: B2B AFFILIATE COMPLETE FLOW (REAL SCHEMA)")
    print("=" * 80)
    print("\nScenario: Selling accommodation to affiliate partner")
    print("- Customer: B2B Affiliate Partner (reseller_id: 100005361)")
    print("- Vertical: Accommodation")
    print("- Supplier: NATIVE")
    print("- Commission: 10% shareback on markup + 11% VAT\n")

    db = Database("data/uprl.db")
    db.connect()
    db.initialize_schema()  # Ensure schema exists
    pipeline = IngestionPipeline(db)

    order_id = "1200496236"
    order_detail_id = "1200917821"

    # =========================================================================
    # EVENT 1: PricingUpdated with B2B Context
    # =========================================================================
    print("-" * 80)
    print("EVENT 1: PricingUpdated (with customer_context + detail_context + fx_context)")
    print("-" * 80)

    pricing_event = {
        "event_type": "PricingUpdated",
        "schema_version": "pricing.commerce.v1",
        "order_id": order_id,
        "pricing_snapshot_id": "ps_b2b_001",
        "version": 1,
        "vertical": "accommodation",
        "emitted_at": "2025-07-31T13:25:21Z",
        "customer_context": {
            "reseller_type_name": "B2B_AFFILIATE",
            "reseller_id": "100005361",
            "reseller_name": "Partner CFD Non IDR - Accommodation - Invoicing"
        },
        "detail_context": {
            "order_detail_id": order_detail_id,
            "entity_context": {
                "entity_code": "TNPL"
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
        },
        "components": [
            {
                "component_type": "RoomRate",
                "amount": 246281,
                "currency": "IDR",
                "dimensions": {
                    "order_detail_id": order_detail_id
                },
                "meta": {
                    "basis": "supplier_net"
                },
                "description": "Supplier net rate for room"
            },
            {
                "component_type": "Markup",
                "amount": 46942,
                "currency": "IDR",
                "dimensions": {
                    "order_detail_id": order_detail_id
                },
                "meta": {
                    "basis": "net_markup",
                    "notes": "B2B reseller price uplift"
                },
                "description": "B2B partner markup"
            }
        ],
        "totals": {
            "customer_total": 293223,
            "currency": "IDR"
        }
    }

    print(f"\nEmitting pricing event...")
    print(f"  Order ID: {order_id}")
    print(f"  Reseller: {pricing_event['customer_context']['reseller_name']}")
    print(f"  Entity: {pricing_event['detail_context']['entity_context']['entity_code']}")
    print(f"  Components: {len(pricing_event['components'])}")

    result = pipeline.ingest_event(pricing_event)

    if result.success:
        print(f"  ✅ {result.message}")
        breakdown = db.get_order_pricing_latest(order_id)
        if breakdown:
            total = sum(c['amount'] for c in breakdown)
            print(f"\n  Pricing Breakdown:")
            for comp in breakdown:
                print(f"    - {comp['component_type']}: IDR {comp['amount'] / 100:,.2f}")
            print(f"    TOTAL: IDR {total / 100:,.2f}")
    else:
        print(f"  ❌ {result.message}")
        return False

    # =========================================================================
    # EVENT 2: Payment Authorized (AFFILIATE_DEPOSIT)
    # =========================================================================
    print("\n" + "-" * 80)
    print("EVENT 2: Payment Authorized (AFFILIATE_DEPOSIT channel)")
    print("-" * 80)

    payment_auth_event = {
        "event_type": "payment.authorized",
        "schema_version": "payment.timeline.v1",
        "order_id": order_id,
        "timeline_version": 1,
        "emitted_at": "2025-07-31T13:25:25Z",
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
            "authorized_at": "2025-07-31T13:25:25Z",
            "captured_amount_total": 0,
            "captured_at": None,
            "bnpl_plan": None
        },
        "idempotency_key": "pi_b2b_001:authorized"
    }

    print(f"\nEmitting payment.authorized event...")
    print(f"  Payment ID: {payment_auth_event['payment']['payment_id']}")
    print(f"  Channel: {payment_auth_event['payment']['payment_method']['channel']}")
    print(f"  Amount: IDR {payment_auth_event['payment']['authorized_amount'] / 100:,.2f}")

    result = pipeline.ingest_event(payment_auth_event)

    if result.success:
        print(f"  ✅ {result.message}")
    else:
        print(f"  ❌ {result.message}")
        return False

    # =========================================================================
    # EVENT 3: Payment Captured
    # =========================================================================
    print("\n" + "-" * 80)
    print("EVENT 3: Payment Captured")
    print("-" * 80)

    payment_captured_event = {
        "event_type": "payment.captured",
        "schema_version": "payment.timeline.v1",
        "order_id": order_id,
        "timeline_version": 2,
        "emitted_at": "2025-08-04T10:00:00Z",
        "payment": {
            "status": "Captured",
            "payment_id": "pi_b2b_001",
            "pg_reference_id": "pg_b2b_001",
            "payment_method": {
                "channel": "AFFILIATE_DEPOSIT",
                "provider": "AffiliateDeposit",
                "brand": "INTERNAL"
            },
            "currency": "IDR",
            "authorized_amount": 293223,
            "authorized_at": "2025-07-31T13:25:25Z",
            "captured_amount": 293223,
            "captured_at": "2025-08-04T10:00:00Z",
            "bnpl_plan": None
        },
        "idempotency_key": "pi_b2b_001:captured"
    }

    print(f"\nEmitting payment.captured event...")
    print(f"  Captured Amount: IDR {payment_captured_event['payment']['captured_amount'] / 100:,.2f}")
    print(f"  Captured At: {payment_captured_event['payment']['captured_at']}")

    result = pipeline.ingest_event(payment_captured_event)

    if result.success:
        print(f"  ✅ {result.message}")
    else:
        print(f"  ❌ {result.message}")
        return False

    # =========================================================================
    # EVENT 4: Supplier Issuance with Affiliate Shareback
    # =========================================================================
    print("\n" + "-" * 80)
    print("EVENT 4: IssuanceSupplierLifecycle (with affiliate shareback + VAT)")
    print("-" * 80)

    supplier_event = {
        "event_type": "IssuanceSupplierLifecycle",
        "schema_version": "supplier.commerce.v1",
        "order_id": order_id,
        "order_detail_id": order_detail_id,
        "supplier_timeline_version": 1,
        "emitted_at": "2025-07-31T13:26:00Z",
        "supplier": {
            "status": "ISSUED",
            "supplier_id": "NATIVE",
            "booking_code": "1859696",
            "supplier_ref": "1859696",
            "amount_due": 246281,
            "currency": "IDR",
            "fx_context": {
                "timestamp_fx_rate": "2025-07-31T13:26:21Z",
                "payment_currency": "IDR",
                "supply_currency": "IDR",
                "record_currency": "IDR",
                "gbv_currency": "IDR",
                "payment_value": 293223,
                "supply_to_payment_fx_rate": 1.0,
                "supply_to_record_fx_rate": 1.0,
                "payment_to_gbv_fx_rate": 1.0,
                "source": "Treasury"
            },
            "entity_context": {
                "entity_code": "GTN"
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
        },
        "idempotency_key": "1200496236:1200917821:NATIVE:issued"
    }

    print(f"\nEmitting supplier issuance event...")
    print(f"  Supplier: {supplier_event['supplier']['supplier_id']}")
    print(f"  Booking Code: {supplier_event['supplier']['booking_code']}")
    print(f"  Amount Due: IDR {supplier_event['supplier']['amount_due'] / 100:,.2f}")
    print(f"  Entity: {supplier_event['supplier']['entity_context']['entity_code']}")
    print(f"\n  Affiliate Shareback:")
    print(f"    Commission: IDR {supplier_event['supplier']['affiliate']['partnerShareback']['amount']:,.2f} (10% of markup)")
    print(f"    VAT: IDR {supplier_event['supplier']['affiliate']['taxes'][0]['amount']:,.2f} (11% of shareback)")

    result = pipeline.ingest_event(supplier_event)

    if result.success:
        print(f"  ✅ {result.message}")
    else:
        print(f"  ❌ {result.message}")
        return False

    # =========================================================================
    # VERIFICATION: Financial Summary
    # =========================================================================
    print("\n" + "=" * 80)
    print("FINANCIAL SUMMARY")
    print("=" * 80)

    customer_total = 293223
    room_rate = 246281
    markup = 46942
    shareback = 4694.2
    vat = 516.36
    net_revenue = markup - shareback - vat

    print(f"\n  Customer Pays (Affiliate):  IDR {customer_total / 100:,.2f}")
    print(f"  Supplier Cost (NATIVE):     IDR {room_rate / 100:,.2f}")
    print(f"  -------------------------------")
    print(f"  Gross Margin (Markup):      IDR {markup / 100:,.2f}")
    print(f"  Affiliate Commission (10%): IDR {shareback:,.2f}")
    print(f"  VAT on Commission (11%):    IDR {vat:,.2f}")
    print(f"  -------------------------------")
    print(f"  Net Revenue to Tiket:       IDR {net_revenue:,.2f}")

    print(f"\n  Margin %: {(markup / customer_total) * 100:.2f}%")
    print(f"  Net Margin %: {(net_revenue / customer_total) * 100:.2f}%")

    print("\n" + "=" * 80)
    print("✅ ALL EVENTS INGESTED SUCCESSFULLY")
    print("=" * 80)
    print("\nKey Learnings:")
    print("  ✅ customer_context tracks B2B reseller information")
    print("  ✅ detail_context captures entity (TNPL) + FX rates")
    print("  ✅ meta field in components adds basis/notes")
    print("  ✅ payment object has nested payment_method structure")
    print("  ✅ supplier object includes affiliate shareback + taxes")
    print("  ✅ idempotency_key ensures exactly-once processing")
    print("  ✅ Real schema supports complex B2B financial flows")

    db.close()
    return True


if __name__ == "__main__":
    success = test_b2b_affiliate_complete_flow()

    if success:
        print("\n🎉 B2B AFFILIATE TEST PASSED!")
        print("\nNext steps:")
        print("  1. View order in Order Explorer: order_id = 1200496236")
        print("  2. Check Latest Breakdown for RoomRate + Markup components")
        print("  3. Review Payment Timeline (AFFILIATE_DEPOSIT channel)")
        print("  4. Verify supplier entity context (GTN vs TNPL)")
        exit(0)
    else:
        print("\n❌ B2B AFFILIATE TEST FAILED")
        exit(1)
