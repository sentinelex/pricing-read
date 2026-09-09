"""
Tests for event idempotency enforcement at ingestion.

Run: python tests/test_idempotency.py  (or pytest tests/test_idempotency.py)
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


def make_pricing_event(event_id=None, idempotency_key=None, order_id="ORD-IDEM-1"):
    return {
        "event_id": event_id or f"EVT-{uuid.uuid4().hex[:8]}",
        "idempotency_key": idempotency_key,
        "event_type": "pricing.updated",
        "schema_version": "pricing.commerce.v1",
        "order_id": order_id,
        "pricing_snapshot_id": str(uuid.uuid4()),
        "version": 1,
        "components": [
            {
                "component_type": "BaseFare",
                "amount": 50000000,
                "currency": "IDR",
                "dimensions": {"order_detail_id": "OD-001"},
                "description": "Test component"
            }
        ],
        "emitted_at": "2026-07-04T10:00:00Z",
        "emitter_service": "test-service"
    }


def fresh_pipeline(tmp_name):
    db_path = f"data/test_idem_{tmp_name}.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    return IngestionPipeline(db), db, db_path


def test_duplicate_event_id_is_acknowledged_not_reprocessed():
    pipeline, db, db_path = fresh_pipeline("dup_id")
    event = make_pricing_event(event_id="EVT-FIXED-001")

    first = pipeline.ingest_event(event)
    assert first.success, first.message
    assert not first.details.get('duplicate')

    second = pipeline.ingest_event(event)
    assert second.success, second.message
    assert second.details.get('duplicate') is True

    rows = db.conn.execute(
        "SELECT COUNT(*) FROM pricing_components_fact WHERE order_id = ?",
        (event['order_id'],)
    ).fetchone()[0]
    assert rows == 1, f"Expected 1 component row, got {rows}"
    os.remove(db_path)
    print("PASS: duplicate event_id acknowledged without reprocessing")


def test_duplicate_idempotency_key_with_different_event_id():
    pipeline, db, db_path = fresh_pipeline("dup_key")
    key = "IDEM-KEY-42"

    first = pipeline.ingest_event(make_pricing_event(idempotency_key=key))
    assert first.success

    second = pipeline.ingest_event(make_pricing_event(idempotency_key=key))
    assert second.success
    assert second.details.get('duplicate') is True

    count = db.conn.execute("SELECT COUNT(*) FROM processed_events").fetchone()[0]
    assert count == 1, f"Expected 1 ledger row, got {count}"
    os.remove(db_path)
    print("PASS: duplicate idempotency_key deduplicated across event_ids")


def test_failed_event_stays_retryable():
    pipeline, db, db_path = fresh_pipeline("retry")
    bad = make_pricing_event(event_id="EVT-BAD-001")
    bad['components'] = "not-a-list"  # forces validation failure -> DLQ

    first = pipeline.ingest_event(bad)
    assert not first.success

    # Retry with fixed payload and the SAME event_id must be processed
    good = make_pricing_event(event_id="EVT-BAD-001")
    retry = pipeline.ingest_event(good)
    assert retry.success, retry.message
    assert not retry.details.get('duplicate'), "Failed event must not be in ledger"
    os.remove(db_path)
    print("PASS: failed events are not recorded and remain retryable")


def test_missing_event_id_gets_deterministic_generated_id():
    pipeline, db, db_path = fresh_pipeline("no_id")
    event = make_pricing_event()
    del event['event_id']
    del event['idempotency_key']

    first = pipeline.ingest_event(dict(event))
    assert first.success, first.message

    # Redelivery of the identical payload must deduplicate via content hash
    second = pipeline.ingest_event(dict(event))
    assert second.success
    assert second.details.get('duplicate') is True

    ledger = db.conn.execute("SELECT event_id FROM processed_events").fetchall()
    assert len(ledger) == 1 and ledger[0][0].startswith("evt_gen_")
    os.remove(db_path)
    print("PASS: missing event_id generated deterministically, redelivery dedupes")


if __name__ == "__main__":
    test_duplicate_event_id_is_acknowledged_not_reprocessed()
    test_duplicate_idempotency_key_with_different_event_id()
    test_failed_event_stays_retryable()
    test_missing_event_id_gets_deterministic_generated_id()
    print("\nAll idempotency tests passed ✅")
