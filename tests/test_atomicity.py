"""
Per-event atomicity: an event's writes land all-or-nothing.

Run: pytest tests/test_atomicity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_event(event_id="EVT-ATOMIC-1"):
    return {
        "event_id": event_id,
        "event_type": "pricing.updated",
        "schema_version": "pricing.commerce.v1",
        "order_id": "ORD-ATOMIC",
        "version": 1,
        "components": [
            {"component_type": "BaseFare", "amount": 100, "currency": "IDR",
             "dimensions": {"order_detail_id": "OD-1"}},
            {"component_type": "Tax", "amount": 10, "currency": "IDR",
             "dimensions": {"order_detail_id": "OD-1"}},
        ],
        "emitted_at": "2026-07-04T10:00:00Z",
        "emitter_service": "test",
    }


def count_components(db):
    return db.conn.execute(
        "SELECT COUNT(*) FROM pricing_components_fact WHERE order_id='ORD-ATOMIC'"
    ).fetchone()[0]


def test_mid_event_failure_rolls_back_all_writes(pipeline, db):
    # Make the SECOND component insert blow up mid-event
    original = db.insert_pricing_component
    calls = {'n': 0}

    def failing_insert(component):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError("simulated storage failure")
        return original(component)

    db.insert_pricing_component = failing_insert
    result = pipeline.ingest_event(make_event())
    db.insert_pricing_component = original

    assert not result.success
    assert count_components(db) == 0, "first component must be rolled back"

    # The failure is recorded in the DLQ despite the rollback
    dlq = db.conn.execute("SELECT error_type FROM dlq").fetchall()
    assert len(dlq) == 1 and dlq[0][0] == "PIPELINE_ERROR"

    # And the event stays retryable under the same event_id
    retry = pipeline.ingest_event(make_event())
    assert retry.success, retry.message
    assert not retry.details.get('duplicate')
    assert count_components(db) == 2


def test_success_commits_facts_and_ledger_together(pipeline, db):
    result = pipeline.ingest_event(make_event("EVT-ATOMIC-2"))
    assert result.success
    assert count_components(db) == 2
    ledger = db.conn.execute(
        "SELECT COUNT(*) FROM processed_events WHERE event_id='EVT-ATOMIC-2'"
    ).fetchone()[0]
    assert ledger == 1
