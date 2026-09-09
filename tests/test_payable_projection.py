"""
Unit tests for the pure payable projection logic (src/projection/payables.py).
No database required — this is the point of the extraction.

Run: python tests/test_payable_projection.py  (or pytest)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.projection.payables import (
    project_instance_payables, resolve_baseline, select_timeline_obligations,
    STANDALONE_VERSION,
)


def status_row(**overrides):
    row = {
        'order_id': 'ORD-1', 'order_detail_id': 'OD-1',
        'supplier_id': 'SUP-1', 'supplier_reference_id': 'BK-1',
        'fulfillment_instance_id': None, 'status': 'ISSUED',
        'amount': 100_000, 'amount_basis': 'gross',
        'cancellation_fee_amount': None, 'currency': 'IDR',
        'supplier_timeline_version': 2,
    }
    row.update(overrides)
    return row


def line(version, party='SUP-1', obligation='COMMISSION', amount=10_000,
         effect='DECREASES_PAYABLE', party_type='SUPPLIER'):
    return {
        'supplier_timeline_version': version, 'obligation_type': obligation,
        'party_type': party_type, 'party_id': party, 'party_name': party,
        'amount': amount, 'amount_effect': effect, 'currency': 'IDR',
    }


def test_baseline_per_status():
    assert resolve_baseline(status_row(status='ISSUED'))['amount'] == 100_000
    assert resolve_baseline(status_row(status='Confirmed'))['include_timeline_obligations']
    for s in ('CancelledWithFee', 'CancelledNoFee', 'Voided', 'SomethingNew'):
        policy = resolve_baseline(status_row(status=s))
        assert policy['amount'] == 0
        assert not policy['include_timeline_obligations']
    print("PASS: baseline policy per status")


def test_latest_per_party_projection():
    lines = [
        line(1, amount=5_000),                       # superseded
        line(2, amount=8_000),                       # latest COMMISSION for SUP-1
        line(1, party='AFF-1', obligation='SHAREBACK',
             amount=3_000, effect='INCREASES_PAYABLE', party_type='AFFILIATE'),
    ]
    selected = select_timeline_obligations(lines, latest_version=2, include_all=True)
    amounts = {(o['party_id'], o['obligation_type']): o['amount'] for o in selected}
    assert amounts == {('SUP-1', 'COMMISSION'): 8_000, ('AFF-1', 'SHAREBACK'): 3_000}
    print("PASS: latest obligation per (party, obligation_type) wins")


def test_cancelled_uses_only_latest_version_lines():
    lines = [line(1, amount=5_000), line(3, obligation='CANCELLATION_FEE',
                                         amount=2_000, effect='INCREASES_PAYABLE')]
    selected = select_timeline_obligations(lines, latest_version=3, include_all=False)
    assert len(selected) == 1 and selected[0]['obligation_type'] == 'CANCELLATION_FEE'

    # Scenario B: empty parties on latest version cuts off carry-forward
    selected = select_timeline_obligations([line(1)], latest_version=3, include_all=False)
    assert selected == []
    print("PASS: cancelled statuses restrict to latest-version lines")


def test_amount_effect_math_and_totals():
    result = project_instance_payables(status_row(), [
        line(2, obligation='COMMISSION', amount=8_000, effect='DECREASES_PAYABLE'),
        line(2, obligation='PENALTY', amount=1_000, effect='INCREASES_PAYABLE'),
    ])
    supplier = result['parties'][0]
    assert supplier['total_adjustment'] == -7_000
    assert supplier['total_payable'] == 93_000
    assert result['total_payable'] == 93_000
    print("PASS: amount_effect directionality applied to totals")


def test_standalone_adjustments_survive_cancellation():
    result = project_instance_payables(
        status_row(status='CancelledNoFee'),
        [line(1, amount=8_000),  # timeline obligation, must be dropped
         line(STANDALONE_VERSION, party='PARTNER-1', obligation='GOODWILL',
              amount=4_000, effect='INCREASES_PAYABLE', party_type='INTERNAL')]
    )
    assert result['parties'][0]['total_payable'] == 0  # supplier: no baseline, no timeline lines
    partner = [p for p in result['parties'] if p['party_id'] == 'PARTNER-1'][0]
    assert partner['total_payable'] == 4_000
    assert result['total_payable'] == 4_000
    print("PASS: standalone (version=-1) adjustments persist across cancellation")


def test_legacy_cancellation_fee_fallback():
    result = project_instance_payables(
        status_row(status='CancelledWithFee', cancellation_fee_amount=25_000), []
    )
    baseline = result['supplier_baseline']
    assert baseline['amount'] == 25_000
    assert 'legacy' in baseline['reason']

    # With an explicit CANCELLATION_FEE line the fallback must NOT fire
    result = project_instance_payables(
        status_row(status='CancelledWithFee', cancellation_fee_amount=25_000,
                   supplier_timeline_version=3),
        [line(3, obligation='CANCELLATION_FEE', amount=25_000,
              effect='INCREASES_PAYABLE')]
    )
    assert result['supplier_baseline']['amount'] == 0
    assert result['parties'][0]['total_payable'] == 25_000
    print("PASS: legacy cancellation_fee_amount fallback only without fee line")


def test_non_supplier_parties_separated():
    result = project_instance_payables(status_row(), [
        line(2, party='AFF-9', obligation='SHAREBACK', amount=6_000,
             effect='INCREASES_PAYABLE', party_type='AFFILIATE'),
    ])
    assert len(result['parties']) == 2
    affiliate = result['parties'][1]
    assert affiliate['party_type'] == 'AFFILIATE'
    assert affiliate['baseline'] == 0 and affiliate['total_payable'] == 6_000
    assert result['total_payable'] == 100_000 + 6_000
    print("PASS: non-supplier parties get baseline-less separated payables")


if __name__ == "__main__":
    test_baseline_per_status()
    test_latest_per_party_projection()
    test_cancelled_uses_only_latest_version_lines()
    test_amount_effect_math_and_totals()
    test_standalone_adjustments_survive_cancellation()
    test_legacy_cancellation_fee_fallback()
    test_non_supplier_parties_separated()
    print("\nAll projection tests passed ✅")
