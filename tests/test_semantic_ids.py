"""
Tests for semantic ID stability and collision hardening.

Run: python tests/test_semantic_ids.py  (or pytest)
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion.id_generator import IDGenerator
from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


def test_registered_abbreviations_are_stable():
    # These exact IDs exist in stored events and cross-service references
    # (e.g. refund_of_component_semantic_id). They must never change.
    cases = [
        ({'order_detail_id': '1365755656', 'profile_id': '216709946'},
         'cs-1327314937-OD-1365755656-PRO-216709946-BaseFare'),
        ({'order_detail_id': '1366814317', 'passenger_id': '280357115'},
         'cs-1328340013-OD-1366814317-PAS-280357115-BaseFare'),
    ]
    for dims, expected in cases:
        order_id = expected.split('-')[1]
        got = IDGenerator.generate_semantic_id(order_id, 'BaseFare', dims)
        assert got == expected, f"format contract broken: {got} != {expected}"
    print("PASS: grandfathered abbreviations produce identical IDs")


def test_unknown_keys_use_full_name_not_truncation():
    # 'product_id' must NOT truncate to 'PRO' (which belongs to profile_id)
    sid = IDGenerator.generate_semantic_id('ORD-1', 'Fee', {'product_id': 'X1'})
    assert 'PRODUCT_ID-X1' in sid and 'PRO-X1' not in sid
    print("PASS: unregistered keys keep their full name (no lossy truncation)")


def test_abbreviation_collision_raises():
    # profile_id is registered as PRO; a crafted key 'pro' uppercases to PRO
    try:
        IDGenerator.generate_semantic_id(
            'ORD-1', 'Fee', {'profile_id': 'A', 'pro': 'B'}
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert 'collision' in str(e).lower()
    print("PASS: abbreviation collision raises instead of silently merging")


def test_snapshot_collision_goes_to_dlq():
    db_path = "data/test_semid.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    pipeline = IngestionPipeline(db)

    event = {
        "event_id": f"EVT-{uuid.uuid4().hex[:8]}",
        "event_type": "pricing.updated",
        "schema_version": "pricing.commerce.v1",
        "order_id": "ORD-COLLIDE",
        "components": [
            {"component_type": "Fee", "amount": 100, "currency": "IDR",
             "dimensions": {"a": "x-B-y"}},
            {"component_type": "Fee", "amount": 200, "currency": "IDR",
             "dimensions": {"a": "x", "b": "y"}},  # same rendered ID, different dims
        ],
        "emitted_at": "2026-07-04T10:00:00Z",
        "emitter_service": "test",
    }
    result = pipeline.ingest_event(event)
    assert not result.success
    dlq = db.conn.execute("SELECT error_type FROM dlq").fetchall()
    assert dlq and dlq[0][0] == "SEMANTIC_ID_COLLISION"
    # Nothing partially ingested
    count = db.conn.execute(
        "SELECT COUNT(*) FROM pricing_components_fact WHERE order_id='ORD-COLLIDE'"
    ).fetchone()[0]
    assert count == 0, "collision event must not partially ingest"
    db.close()
    os.remove(db_path)
    print("PASS: value-boundary collision detected at ingestion, no partial writes")


if __name__ == "__main__":
    test_registered_abbreviations_are_stable()
    test_unknown_keys_use_full_name_not_truncation()
    test_abbreviation_collision_raises()
    test_snapshot_collision_goes_to_dlq()
    print("\nAll semantic ID tests passed ✅")
