#!/usr/bin/env python3
"""
Quick test to verify refund.issued event works with optional event_id
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


def test_refund_issued():
    """Test refund.issued event from JSON file"""
    
    print("=" * 80)
    print("TEST: Refund Issued Event (Optional event_id)")
    print("=" * 80)
    
    db = Database("data/uprl.db")
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)
    
    # Load refund JSON
    refund_path = Path("../components-helper/b2b_affiliate_case/7_refundIssued.json")
    with open(refund_path) as f:
        refund_event = json.load(f)
    
    print("\nRefund Event Data:")
    print(json.dumps(refund_event, indent=2))
    
    # Ingest refund event
    print("\nIngesting refund event...")
    result = pipeline.ingest_event(refund_event)
    
    if result.success:
        print(f"\n✅ {result.message}")
        print(f"Details: {result.details}")
        
        # Verify refund component was created
        order_id = refund_event['order_id']
        latest = db.get_order_pricing_latest(order_id)
        
        print(f"\nLatest pricing components for order {order_id}:")
        for comp in latest:
            print(f"  - {comp['component_type']}: {comp['amount']} {comp['currency']}")
            if comp['refund_of_component_semantic_id']:
                print(f"    Refund of: {comp['refund_of_component_semantic_id']}")
        
        print("\n✅ TEST PASSED - Refund event ingested successfully!")
    else:
        print(f"\n❌ {result.message}")
        print(f"Details: {result.details}")
        print("\n❌ TEST FAILED")
        return False
    
    return True


if __name__ == "__main__":
    test_refund_issued()

