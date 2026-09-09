"""
Party-level payable projection.

Pure business logic: given the latest supplier timeline status for a
fulfillment instance and ALL of its payable lines, compute the effective
payable per party. No database access — fully unit-testable.

Status rules:
- Confirmed/ISSUED/Invoiced/Settled: baseline = timeline amount,
  include latest obligation per (party_id, obligation_type) across versions
- CancelledWithFee: baseline = 0 (fee arrives as a CANCELLATION_FEE party
  line); if the latest timeline version carries lines, include ONLY those,
  otherwise exclude all timeline obligations. Legacy events without a
  CANCELLATION_FEE line fall back to the cancellation_fee_amount field.
- CancelledNoFee/Voided: baseline = 0, same latest-version-only rule
- Standalone adjustments (supplier_timeline_version = -1) are ALWAYS included

Amount effect:
- INCREASES_PAYABLE adds to the party's adjustment
- DECREASES_PAYABLE subtracts from it
"""
from collections import defaultdict
from typing import Any, Dict, List

# Sentinel for booking-level (single-instance) scoping, mirrored in SQL COALESCE
BOOKING_LEVEL = '__BOOKING_LEVEL__'

# Timeline versions: >= 1 are event-linked, STANDALONE_VERSION marks
# partner adjustments that persist across status changes
STANDALONE_VERSION = -1

ACTIVE_STATUSES = ('Confirmed', 'ISSUED', 'Invoiced', 'Settled')
CANCELLED_NO_FEE_STATUSES = ('CancelledNoFee', 'Voided')

OBLIGATION_FIELDS = ('obligation_type', 'party_type', 'party_id', 'party_name',
                     'amount', 'amount_effect', 'currency')


def resolve_baseline(status_row: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the supplier baseline and obligation-inclusion policy from status."""
    status = status_row['status']
    amount_basis = status_row.get('amount_basis')

    if status in ACTIVE_STATUSES:
        return {
            'amount': status_row.get('amount') or 0,
            'reason': f"Supplier cost (status: {status}"
                      + (f", basis: {amount_basis}" if amount_basis else "") + ")",
            'include_timeline_obligations': True,
        }
    if status == 'CancelledWithFee':
        return {
            'amount': 0,
            'reason': f"Cancelled (status: {status}, fee in party lines)",
            'include_timeline_obligations': False,
        }
    if status in CANCELLED_NO_FEE_STATUSES:
        return {
            'amount': 0,
            'reason': f"Cancelled without fee (status: {status})",
            'include_timeline_obligations': False,
        }
    return {
        'amount': 0,
        'reason': f"Unknown status: {status}",
        'include_timeline_obligations': False,
    }


def _strip(line: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a payable line to the public obligation fields."""
    return {k: line.get(k) for k in OBLIGATION_FIELDS}


def select_timeline_obligations(lines: List[Dict[str, Any]],
                                latest_version: int,
                                include_all: bool) -> List[Dict[str, Any]]:
    """
    Choose which timeline-linked obligations apply.

    include_all (active statuses): latest line per (party_id, obligation_type)
    across all versions >= 1 — the party-level projection.

    Otherwise (cancelled statuses): only lines emitted at the latest timeline
    version, if any (Scenario D: cancellation re-states the parties).
    An empty parties array on the latest version excludes everything
    (Scenario B: projection carry-forward is cut off).
    """
    timeline_lines = [l for l in lines
                      if (l.get('supplier_timeline_version') or 0) >= 1]

    if include_all:
        latest_per_key: Dict[tuple, Dict[str, Any]] = {}
        for line in timeline_lines:
            key = (line['party_id'], line['obligation_type'])
            current = latest_per_key.get(key)
            if current is None or line['supplier_timeline_version'] > current['supplier_timeline_version']:
                latest_per_key[key] = line
        return [_strip(l) for l in latest_per_key.values()]

    return [_strip(l) for l in timeline_lines
            if l['supplier_timeline_version'] == latest_version]


def project_instance_payables(status_row: Dict[str, Any],
                              lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Project effective payables for one fulfillment instance.

    status_row: latest supplier_timeline row for the instance
    lines: ALL supplier_payable_lines scoped to the same
           (order_id, order_detail_id, supplier_reference_id, instance)
    """
    status = status_row['status']
    baseline = resolve_baseline(status_row)
    baseline_amount = baseline['amount']
    baseline_reason = baseline['reason']

    timeline_obligations = select_timeline_obligations(
        lines,
        latest_version=status_row['supplier_timeline_version'],
        include_all=baseline['include_timeline_obligations'],
    )
    standalone_obligations = [_strip(l) for l in lines
                              if l.get('supplier_timeline_version') == STANDALONE_VERSION]
    obligations = timeline_obligations + standalone_obligations

    # Group by party and apply amount_effect directionality
    party_groups = defaultdict(lambda: {'obligations': [], 'total_adjustment': 0})
    for obl in obligations:
        group = party_groups[obl['party_id']]
        group['obligations'].append(obl)
        group['party_type'] = obl.get('party_type', 'UNKNOWN')
        group['party_name'] = obl['party_name']
        if obl['amount_effect'] == 'INCREASES_PAYABLE':
            group['total_adjustment'] += obl['amount']
        elif obl['amount_effect'] == 'DECREASES_PAYABLE':
            group['total_adjustment'] -= obl['amount']

    supplier_party_id = status_row['supplier_id']
    supplier_group = party_groups.get(supplier_party_id, {'obligations': [], 'total_adjustment': 0})

    # Legacy fallback: CancelledWithFee events predating CANCELLATION_FEE
    # party lines carry the fee in cancellation_fee_amount
    if status == 'CancelledWithFee' and status_row.get('cancellation_fee_amount'):
        has_fee_line = any(o['obligation_type'] == 'CANCELLATION_FEE'
                           for o in supplier_group['obligations'])
        if not has_fee_line and status_row['cancellation_fee_amount'] > 0:
            baseline_amount = status_row['cancellation_fee_amount']
            baseline_reason = "Cancellation fee (legacy - from cancellation_fee_amount field)"

    parties_payables = [{
        'party_id': supplier_party_id,
        'party_type': 'SUPPLIER',
        'party_name': status_row['supplier_id'],
        'baseline': baseline_amount,
        'baseline_reason': baseline_reason,
        'obligations': supplier_group['obligations'],
        'total_adjustment': supplier_group['total_adjustment'],
        'total_payable': baseline_amount + supplier_group['total_adjustment'],
        'currency': status_row['currency'],
    }]
    for party_id, group in party_groups.items():
        if party_id == supplier_party_id:
            continue
        parties_payables.append({
            'party_id': party_id,
            'party_type': group['party_type'],
            'party_name': group['party_name'],
            'baseline': 0,
            'baseline_reason': 'No baseline (non-supplier party)',
            'obligations': group['obligations'],
            'total_adjustment': group['total_adjustment'],
            'total_payable': group['total_adjustment'],
            'currency': status_row['currency'],
        })

    return {
        'order_detail_id': status_row['order_detail_id'],
        'supplier_reference_id': status_row['supplier_reference_id'],
        'fulfillment_instance_id': status_row['fulfillment_instance_id'],
        'supplier_baseline': {
            'supplier_id': status_row['supplier_id'],
            'amount': baseline_amount,
            'amount_basis': status_row.get('amount_basis'),
            'reason': baseline_reason,
            'status': status,
            'currency': status_row['currency'],
        },
        'parties': parties_payables,
        'party_obligations': obligations,  # DEPRECATED: backward compatibility
        'total_payable': sum(p['total_payable'] for p in parties_payables),
    }
