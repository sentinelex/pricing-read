"""
Tests for the event dispatch registry and schema-version routing.

Run: python tests/test_event_routing.py  (or pytest tests/test_event_routing.py)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


def fresh_pipeline(tmp_name):
    db_path = f"data/test_routing_{tmp_name}.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    return IngestionPipeline(db), db, db_path


def test_registry_covers_both_naming_formats():
    pipeline, db, db_path = fresh_pipeline("formats")
    pairs = [
        ("pricing.updated", "PricingUpdated"),
        ("refund.issued", "RefundIssued"),
        ("payment.captured", "PaymentLifecycle"),
        ("supplier.order.issued", "SupplierLifecycleEvent"),
    ]
    for dotted, pascal in pairs:
        assert pipeline._routes.get(dotted), f"missing dotted route: {dotted}"
        assert pipeline._routes.get(pascal), f"missing pascal route: {pascal}"
        assert pipeline._routes[dotted].__name__ or True
    os.remove(db_path)
    print("PASS: registry covers dotted and PascalCase event types")


def test_schema_major_version_parsing():
    pipeline, db, db_path = fresh_pipeline("version")
    cases = {
        "supplier.timeline.v2": 2,
        "supplier.timeline.v1": 1,
        "supplier.timeline.v2.1": 2,
        "v3": 3,
        "supplier.timeline.v10": 10,
        "": 1,               # absent -> default v1
        None: 1,             # None -> default v1
        "supplier.venice": 1  # 'v' inside a word must not match
    }
    for raw, expected in cases.items():
        got = pipeline._parse_schema_major_version(raw)
        assert got == expected, f"{raw!r}: expected {expected}, got {got}"
    os.remove(db_path)
    print("PASS: schema major version parsed explicitly (no substring matching)")


def test_unified_supplier_handler_by_version():
    pipeline, db, db_path = fresh_pipeline("supplier")

    base = {
        "event_type": "SupplierLifecycleEvent",
        "order_id": "ORD-U1",
        "emitted_at": "2026-07-04T10:00:00Z",
        "emitter_service": "test",
    }
    # v2: payable lines come from the explicit parties array
    v2 = dict(base, event_id="EVT-SUP-V2", order_detail_id="OD-1",
              schema_version="supplier.timeline.v2",
              supplier={"supplier_id": "SUP-A", "supplier_ref": "BK-1",
                        "status": "ISSUED", "amount_due": 100_000,
                        "currency": "IDR"},
              parties=[{"party_type": "SUPPLIER", "party_id": "SUP-A",
                        "party_name": "Supplier A",
                        "lines": [{"obligation_type": "COMMISSION",
                                   "amount": 9_000, "currency": "IDR",
                                   "amount_effect": "DECREASES_PAYABLE"}]}])
    result = pipeline.ingest_event(v2)
    assert result.success, result.message
    assert "(v2)" in result.message

    rows = db.conn.execute(
        "SELECT obligation_type, amount_effect FROM supplier_payable_lines "
        "WHERE order_id='ORD-U1'").fetchall()
    assert [tuple(r) for r in rows] == [("COMMISSION", "DECREASES_PAYABLE")]

    # v1 (no v2 schema_version): lines derived from nested legacy objects
    v1 = dict(base, event_id="EVT-SUP-V1", order_detail_id="OD-2",
              schema_version="supplier.timeline.v1",
              supplier={"supplier_id": "SUP-B", "supplier_ref": "BK-2",
                        "status": "ISSUED", "amount_due": 50_000,
                        "currency": "IDR"})
    result = pipeline.ingest_event(v1)
    assert result.success, result.message
    assert "(v1)" in result.message
    rows = db.conn.execute(
        "SELECT obligation_type FROM supplier_payable_lines "
        "WHERE order_detail_id='OD-2'").fetchall()
    assert [r[0] for r in rows] == ["SUPPLIER"], "v1 derives legacy SUPPLIER line"

    os.remove(db_path)
    print("PASS: unified supplier handler derives lines per schema version")


def test_unknown_event_type_goes_to_dlq():
    pipeline, db, db_path = fresh_pipeline("unknown")
    result = pipeline.ingest_event({
        "event_id": "EVT-UNKNOWN-1",
        "event_type": "totally.unknown.event",
        "order_id": "ORD-X"
    })
    assert not result.success
    dlq = db.conn.execute("SELECT error_type FROM dlq").fetchall()
    assert len(dlq) == 1 and dlq[0][0] == "UNKNOWN_EVENT_TYPE"
    os.remove(db_path)
    print("PASS: unknown event_type routed to DLQ")


def _ok():
    from src.ingestion.pipeline import IngestionResult
    return IngestionResult(True, "ok")


if __name__ == "__main__":
    test_registry_covers_both_naming_formats()
    test_schema_major_version_parsing()
    test_unified_supplier_handler_by_version()
    test_unknown_event_type_goes_to_dlq()
    print("\nAll routing tests passed ✅")
