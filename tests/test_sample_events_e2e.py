"""
End-to-end regression net: every sample event in sample_events/ must
ingest cleanly, and the projections for known orders must stay sane.

Run: pytest tests/test_sample_events_e2e.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'sample_events')


def iter_sample_events():
    for path in sorted(glob.glob(f'{SAMPLE_DIR}/**/*.json', recursive=True)):
        with open(path) as fh:
            data = json.load(fh)
        for event in (data if isinstance(data, list) else [data]):
            yield path, event


def test_all_sample_events_ingest(pipeline):
    failures = []
    total = 0
    for path, event in iter_sample_events():
        total += 1
        result = pipeline.ingest_event(event)
        if not result.success:
            failures.append(f"{os.path.relpath(path, SAMPLE_DIR)}: {result.message[:100]}")
    assert not failures, "sample events failed ingestion:\n" + "\n".join(failures)
    assert total >= 48, f"expected the full sample corpus, saw only {total} events"


def test_multi_instance_passes_order_projects_all_instances(pipeline, db):
    for _, event in iter_sample_events():
        pipeline.ingest_event(event)

    # Order 1322884534 is the multi-instance passes order:
    # 1 booking-level row + 3 redemptions
    payables = db.get_total_effective_payables('1322884534')
    assert len(payables) == 4, f"expected 4 instances, got {len(payables)}"
    instance_ids = {p['fulfillment_instance_id'] for p in payables}
    assert None in instance_ids, "booking-level (NULL instance) must be present"
    assert len(instance_ids - {None}) == 3, "three redemption instances expected"
    for p in payables:
        assert p['total_payable'] >= 0
        assert p['parties'], "every instance must have at least the supplier party"
