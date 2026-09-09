"""
Order Core ingestion pipeline.
Validates, canonicalizes, and normalizes producer events into storage format.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Union, Dict, Any, List
from pydantic import ValidationError

from src.models.events import (
    PricingUpdatedEvent, PaymentLifecycleEvent, SupplierLifecycleEvent,
    RefundLifecycleEvent, RefundIssuedEvent, PartnerAdjustmentEvent, EventType
)
from src.models.normalized import (
    NormalizedPricingComponent, NormalizedPaymentTimeline,
    NormalizedSupplierTimeline, NormalizedRefundTimeline, DLQEntry
)
from src.ingestion.id_generator import IDGenerator
from src.storage.database import Database


class IngestionResult:
    """Result of ingestion attempt"""

    def __init__(self, success: bool, message: str, details: Dict[str, Any] = None):
        self.success = success
        self.message = message
        self.details = details or {}


class _IngestionAborted(Exception):
    """Internal control flow: roll back an event's partial writes."""

    def __init__(self, result: IngestionResult):
        self.result = result


class IngestionPipeline:
    """Main ingestion pipeline for Order Core"""

    # Extracts the major schema version, e.g. "supplier.timeline.v2" -> 2
    SCHEMA_VERSION_PATTERN = re.compile(r'(?:^|\.)v(\d+)(?:\.|$)')

    def __init__(self, database: Database):
        self.db = database
        self.id_generator = IDGenerator()
        self._routes = self._build_event_routes()
        self._last_dlq_entry = None

    def _build_event_routes(self) -> Dict[str, Any]:
        """
        Dispatch registry: event_type -> handler.
        Supports both dotted ("pricing.updated") and PascalCase
        ("PricingUpdated") producer formats.
        """
        return {
            EventType.PRICING_UPDATED: self._ingest_pricing_updated,
            "PricingUpdated": self._ingest_pricing_updated,
            EventType.REFUND_ISSUED: self._route_refund_issued,
            "RefundIssued": self._route_refund_issued,
            EventType.PAYMENT_CHECKOUT: self._ingest_payment_lifecycle,
            EventType.PAYMENT_AUTHORIZED: self._ingest_payment_lifecycle,
            EventType.PAYMENT_CAPTURED: self._ingest_payment_lifecycle,
            EventType.PAYMENT_REFUNDED: self._ingest_payment_lifecycle,
            EventType.PAYMENT_SETTLED: self._ingest_payment_lifecycle,
            "PaymentLifecycle": self._ingest_payment_lifecycle,
            EventType.SUPPLIER_ORDER_CONFIRMED: self._ingest_supplier_lifecycle,
            EventType.SUPPLIER_ORDER_ISSUED: self._ingest_supplier_lifecycle,
            EventType.SUPPLIER_INVOICE_RECEIVED: self._ingest_supplier_lifecycle,
            "IssuanceSupplierLifecycle": self._ingest_supplier_lifecycle,
            "SupplierLifecycleEvent": self._ingest_supplier_lifecycle,
            "PartnerAdjustmentEvent": self._ingest_partner_adjustment,
            EventType.REFUND_INITIATED: self._ingest_refund_lifecycle,
            EventType.REFUND_PROCESSING: self._ingest_refund_lifecycle,
            EventType.REFUND_CLOSED: self._ingest_refund_lifecycle,
            EventType.REFUND_FAILED: self._ingest_refund_lifecycle,
        }

    def _route_refund_issued(self, event_data: Dict[str, Any]) -> IngestionResult:
        """
        refund.issued is emitted in two shapes: a component-refund event
        (with components lineage) and a timeline status event. Route by payload.
        """
        if 'components' in event_data:
            return self._ingest_refund_issued(event_data)
        return self._ingest_refund_lifecycle(event_data)

    def _generate_event_id(self, event_data: Dict[str, Any]) -> str:
        """
        Deterministic event_id from canonical payload content, so a
        redelivered payload without event_id still deduplicates.
        """
        canonical = json.dumps(event_data, sort_keys=True, default=str)
        return f"evt_gen_{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"

    def _parse_schema_major_version(self, schema_version: str) -> int:
        """Parse the major version from a schema_version string; 1 if absent."""
        match = self.SCHEMA_VERSION_PATTERN.search(schema_version or '')
        return int(match.group(1)) if match else 1

    def ingest_event(self, event_data: Dict[str, Any]) -> IngestionResult:
        """
        Main ingestion entry point.
        Routes event to appropriate handler based on event_type.
        """
        try:
            event_type = event_data.get('event_type')

            if not event_type:
                return self._send_to_dlq(
                    event_data, "MISSING_EVENT_TYPE", "Event missing event_type field"
                )

            # Per event contract event_id is optional: Order Core generates a
            # deterministic content-hash ID so redelivery still deduplicates
            event_id = event_data.get('event_id')
            if not event_id:
                event_id = self._generate_event_id(event_data)
                event_data['event_id'] = event_id

            # Idempotency check: acknowledge duplicates without reprocessing
            idempotency_key = event_data.get('idempotency_key')
            existing = self.db.find_processed_event(event_id, idempotency_key)
            if existing:
                return IngestionResult(
                    success=True,
                    message=f"Duplicate event ignored (already processed as {existing['event_id']})",
                    details={
                        'duplicate': True,
                        'event_id': event_id,
                        'original_event_id': existing['event_id'],
                        'original_ingested_at': existing['ingested_at']
                    }
                )

            # Atomicity: the event's fact writes and its idempotency-ledger
            # row commit together, or roll back together on any failure. A
            # failed handler's DLQ entry must survive the rollback, so it is
            # re-inserted after (tracked via _last_dlq_entry).
            self._last_dlq_entry = None
            try:
                with self.db.transaction():
                    result = self._route_event(event_type, event_data)
                    if not result.success:
                        raise _IngestionAborted(result)
                    # Record in idempotency ledger only on success, so failed
                    # events remain retryable after a fix
                    self.db.record_processed_event(
                        event_id=event_id,
                        event_type=str(event_type),
                        order_id=event_data.get('order_id'),
                        idempotency_key=idempotency_key,
                        ingested_at=datetime.now(timezone.utc).isoformat()
                    )
            except _IngestionAborted as aborted:
                # Partial fact writes are rolled back; restore the DLQ entry
                result = aborted.result
                if self._last_dlq_entry is not None:
                    self.db.insert_dlq(self._last_dlq_entry)
            return result

        except Exception as e:
            return self._send_to_dlq(
                event_data, "PIPELINE_ERROR", f"Pipeline error: {str(e)}"
            )

    def _route_event(self, event_type, event_data: Dict[str, Any]) -> IngestionResult:
        """Route event to the appropriate handler via the dispatch registry."""
        handler = self._routes.get(event_type)
        if handler is None:
            return self._send_to_dlq(
                event_data, "UNKNOWN_EVENT_TYPE", f"Unknown event_type: {event_type}"
            )
        return handler(event_data)

    def _ingest_pricing_updated(self, event_data: Dict[str, Any]) -> IngestionResult:
        """
        Handle PricingUpdated event (producer event).
        NORMALIZATION: Assigns pricing_snapshot_id and version during ingestion.

        OPTION A IMPLEMENTATION:
        Supports BOTH legacy detail_context (singular) and detail_contexts (array).
        - Legacy: detail_context applies to all components
        - New: detail_contexts array - each component matched by order_detail_id
        """
        try:
            # Validate with Pydantic (producer event - no enrichment fields)
            event = PricingUpdatedEvent(**event_data)

            # NORMALIZATION STEP 1: Generate pricing_snapshot_id (UUID)
            pricing_snapshot_id = str(uuid.uuid4())

            # NORMALIZATION STEP 2: Assign version (monotonic per order)
            # Get latest version for this order
            latest_version = self.db.get_latest_pricing_version(event.order_id)
            version = (latest_version or 0) + 1

            # NORMALIZATION STEP 2.5: Build context map for efficient lookup
            # Map order_detail_id -> DetailContext
            context_map = {}
            if event.detail_contexts:
                # New: Array of contexts
                for ctx in event.detail_contexts:
                    context_map[ctx.order_detail_id] = ctx
            elif event.detail_context:
                # Legacy: Single context (applies to all components with that order_detail_id)
                context_map[event.detail_context.order_detail_id] = event.detail_context

            # Collision guard (pre-pass, before any insert): distinct
            # components must not share a semantic ID — a silent collision
            # merges them in every downstream projection
            seen_semantic: Dict[str, Any] = {}
            for component in event.components:
                comp_type_str = component.component_type.value if hasattr(component.component_type, 'value') else component.component_type
                try:
                    semantic_id = self.id_generator.generate_semantic_id(
                        event.order_id, comp_type_str, component.dimensions
                    )
                except ValueError as e:
                    return self._send_to_dlq(event_data, "SEMANTIC_ID_COLLISION", str(e))
                prior_dims = seen_semantic.get(semantic_id)
                if prior_dims is not None:
                    reason = ("duplicate component" if prior_dims == component.dimensions
                              else f"different dimensions {prior_dims} vs {component.dimensions}")
                    return self._send_to_dlq(
                        event_data, "SEMANTIC_ID_COLLISION",
                        f"Semantic ID '{semantic_id}' generated twice in one snapshot ({reason})"
                    )
                seen_semantic[semantic_id] = component.dimensions

            # Normalize each component
            normalized_components = []
            ingested_at = datetime.now(timezone.utc).isoformat()

            # Handle emitted_at as string or datetime
            emitted_at_str = event.emitted_at if isinstance(event.emitted_at, str) else event.emitted_at.isoformat()

            for component in event.components:
                # NORMALIZATION STEP 3: Generate dual IDs
                # Handle component_type as enum or string
                comp_type_str = component.component_type.value if hasattr(component.component_type, 'value') else component.component_type

                ids = self.id_generator.generate_dual_ids(
                    order_id=event.order_id,
                    component_type=comp_type_str,
                    dimensions=component.dimensions,
                    pricing_snapshot_id=pricing_snapshot_id
                )

                # NORMALIZATION STEP 4: Match component to its context by order_detail_id
                # Extract order_detail_id from component dimensions
                component_order_detail_id = component.dimensions.get('order_detail_id')
                matched_context = None
                if component_order_detail_id and component_order_detail_id in context_map:
                    matched_context = context_map[component_order_detail_id]

                # Create normalized component with enrichment fields
                # Use 'meta' if present, otherwise 'metadata' (backward compatibility)
                component_metadata = component.meta if hasattr(component, 'meta') and component.meta else component.metadata if hasattr(component, 'metadata') else None

                # NORMALIZATION STEP 5: Enrich metadata with matched context
                # Store entity_context and fx_context in component metadata for downstream consumers
                if matched_context:
                    if component_metadata is None:
                        component_metadata = {}

                    # Add entity context if present
                    if matched_context.entity_context:
                        component_metadata['entity_context'] = matched_context.entity_context.model_dump()

                    # Add FX context if present
                    if matched_context.fx_context:
                        component_metadata['fx_context'] = matched_context.fx_context.model_dump()

                # Detect is_refund: producer can set explicitly OR it's inferred from refund_of_component_semantic_id presence
                is_refund_flag = False
                if hasattr(component, 'is_refund') and component.is_refund is not None:
                    is_refund_flag = component.is_refund
                elif component.refund_of_component_semantic_id is not None:
                    is_refund_flag = True

                normalized = NormalizedPricingComponent(
                    component_semantic_id=ids['component_semantic_id'],
                    component_instance_id=ids['component_instance_id'],
                    order_id=event.order_id,
                    pricing_snapshot_id=pricing_snapshot_id,  # Assigned by Order Core
                    version=version,  # Assigned by Order Core
                    component_type=comp_type_str,
                    amount=component.amount,
                    currency=component.currency,
                    dimensions=component.dimensions,
                    description=component.description,
                    is_refund=is_refund_flag,  # Detect refund flag
                    refund_of_component_semantic_id=component.refund_of_component_semantic_id,
                    emitter_service=event.emitter_service or "pricing-service",
                    ingested_at=ingested_at,
                    emitted_at=emitted_at_str,
                    metadata=component_metadata  # Now includes entity_context and fx_context if matched
                )

                normalized_components.append(normalized)

                # Insert into database
                self.db.insert_pricing_component(normalized.model_dump(mode='json'))

            return IngestionResult(
                success=True,
                message=f"Ingested {len(normalized_components)} components (v{version})",
                details={
                    'event_id': event.event_id,
                    'order_id': event.order_id,
                    'pricing_snapshot_id': pricing_snapshot_id,
                    'version': version,
                    'component_count': len(normalized_components),
                    'context_count': len(context_map)
                }
            )

        except ValidationError as e:
            return self._send_to_dlq(
                event_data, "VALIDATION_ERROR", f"Pydantic validation failed: {str(e)}"
            )

    def _ingest_refund_issued(self, event_data: Dict[str, Any]) -> IngestionResult:
        """
        Handle RefundIssued event (producer event with components).
        NORMALIZATION: Assigns pricing_snapshot_id and version during ingestion.
        """
        try:
            # Validate with Pydantic (producer event - no enrichment fields)
            event = RefundIssuedEvent(**event_data)

            # NORMALIZATION STEP 1: Generate event_id if missing
            event_id = event.event_id or str(uuid.uuid4())

            # NORMALIZATION STEP 2: Generate pricing_snapshot_id (UUID)
            pricing_snapshot_id = str(uuid.uuid4())

            # NORMALIZATION STEP 3: Assign version (monotonic per order)
            latest_version = self.db.get_latest_pricing_version(event.order_id)
            version = (latest_version or 0) + 1

            normalized_components = []
            ingested_at = datetime.now(timezone.utc).isoformat()

            for component in event.components:
                # NORMALIZATION STEP 4: Generate dual IDs
                comp_type_str = component.component_type.value if hasattr(component.component_type, 'value') else component.component_type

                # For refund components, include refund_id in semantic ID
                ids = self.id_generator.generate_dual_ids(
                    order_id=event.order_id,
                    component_type=comp_type_str,
                    dimensions=component.dimensions,
                    pricing_snapshot_id=pricing_snapshot_id,
                    refund_id=event.refund_id  # Include refund_id for unique semantic IDs
                )

                # Use 'meta' if present, otherwise 'metadata' (backward compatibility)
                component_metadata = component.meta if hasattr(component, 'meta') and component.meta else component.metadata if hasattr(component, 'metadata') else None

                # Detect is_refund: producer can set explicitly OR it's inferred from refund_of_component_semantic_id presence
                is_refund_flag = False
                if hasattr(component, 'is_refund') and component.is_refund is not None:
                    is_refund_flag = component.is_refund
                elif component.refund_of_component_semantic_id is not None:
                    is_refund_flag = True

                normalized = NormalizedPricingComponent(
                    component_semantic_id=ids['component_semantic_id'],
                    component_instance_id=ids['component_instance_id'],
                    order_id=event.order_id,
                    pricing_snapshot_id=pricing_snapshot_id,  # Assigned by Order Core
                    version=version,  # Assigned by Order Core
                    component_type=comp_type_str,
                    amount=component.amount,
                    currency=component.currency,
                    dimensions=component.dimensions,
                    description=component.description,
                    is_refund=is_refund_flag,  # Detect refund flag
                    refund_of_component_semantic_id=component.refund_of_component_semantic_id,
                    emitter_service=event.emitter_service,
                    ingested_at=ingested_at,
                    emitted_at=event.emitted_at.isoformat(),
                    metadata=component_metadata
                )

                normalized_components.append(normalized)
                self.db.insert_pricing_component(normalized.model_dump(mode='json'))

            return IngestionResult(
                success=True,
                message=f"Ingested refund with {len(normalized_components)} components (v{version})",
                details={
                    'event_id': event_id,
                    'order_id': event.order_id,
                    'refund_id': event.refund_id,
                    'pricing_snapshot_id': pricing_snapshot_id,
                    'version': version,
                    'component_count': len(normalized_components)
                }
            )

        except ValidationError as e:
            return self._send_to_dlq(
                event_data, "VALIDATION_ERROR", f"Validation failed: {str(e)}"
            )

    def _ingest_payment_lifecycle(self, event_data: Dict[str, Any]) -> IngestionResult:
        """
        Handle payment timeline events (producer event).
        NORMALIZATION: Assigns timeline_version during ingestion.
        """
        try:
            event = PaymentLifecycleEvent(**event_data)

            # NORMALIZATION STEP: Assign timeline_version (monotonic per order)
            latest_timeline_version = self.db.get_latest_payment_timeline_version(event.order_id)
            timeline_version = (latest_timeline_version or 0) + 1

            ingested_at = datetime.now(timezone.utc).isoformat()

            # Extract from nested payment object OR legacy flat structure
            if event.payment:
                # New schema: nested payment object with full payment state
                payment_method_str = event.payment.payment_method.channel
                status = event.payment.status
                payment_intent_id = event.payment.payment_id  # payment_id maps to Intent ID
                authorized_amount = event.payment.authorized_amount
                captured_amount = event.payment.captured_amount
                captured_amount_total = event.payment.captured_amount_total
                amount = captured_amount or authorized_amount or 0  # Legacy field
                currency = event.payment.currency
                pg_reference_id = event.payment.pg_reference_id  # pg_reference_id maps to PG Reference

                # Serialize instrument to JSON if present
                instrument_json = None
                if event.payment.instrument:
                    import json
                    instrument_json = json.dumps(event.payment.instrument.model_dump())
            else:
                # Legacy schema: flat structure
                payment_method_str = event.payment_method
                status = "Captured"  # Assume legacy events are captures
                payment_intent_id = None
                authorized_amount = None
                captured_amount = event.amount
                captured_amount_total = event.amount
                amount = event.amount
                currency = event.currency
                pg_reference_id = event.pg_reference_id
                instrument_json = None

            # Handle emitted_at as string or datetime
            emitted_at_str = event.emitted_at if isinstance(event.emitted_at, str) else event.emitted_at.isoformat()

            normalized = NormalizedPaymentTimeline(
                event_id=event.event_id or str(uuid.uuid4()),
                order_id=event.order_id,
                timeline_version=timeline_version,  # Assigned by Order Core
                event_type=event.event_type,
                status=status,
                payment_method=payment_method_str,
                payment_intent_id=payment_intent_id,
                authorized_amount=authorized_amount,
                captured_amount=captured_amount,
                captured_amount_total=captured_amount_total,
                amount=amount,  # Legacy field for backward compatibility
                currency=currency,
                instrument_json=instrument_json,
                pg_reference_id=pg_reference_id,
                emitter_service=event.emitter_service or "payment-core",
                ingested_at=ingested_at,
                emitted_at=emitted_at_str,
                metadata=event.metadata
            )

            self.db.insert_payment_timeline(normalized.model_dump(mode='json'))

            return IngestionResult(
                success=True,
                message=f"Ingested payment event: {event.event_type} (v{timeline_version})",
                details={
                    'event_id': normalized.event_id,
                    'order_id': event.order_id,
                    'timeline_version': timeline_version,  # Assigned by Order Core
                    'status': status,
                    'payment_method': payment_method_str,
                    'amount': amount
                }
            )

        except ValidationError as e:
            return self._send_to_dlq(
                event_data, "VALIDATION_ERROR", f"Validation failed: {str(e)}"
            )

    def _ingest_supplier_lifecycle(self, event_data: Dict[str, Any]) -> IngestionResult:
        """
        Unified supplier lifecycle handler (schema v1 and v2).
        NORMALIZATION: Assigns supplier_timeline_version during ingestion.

        Contract differences by major schema version:
        - v2: payable lines come from the explicit parties array (with
          amount_effect); timeline metadata is the event's meta/metadata
        - v1: payable lines are derived from nested affiliate / commission /
          tax objects; timeline metadata records entity_code + affiliate.
          WARNING (legacy contract): v1's synthetic SUPPLIER line duplicates
          the timeline baseline and receives the INCREASES_PAYABLE storage
          default — kept for compatibility, do not carry into production.
        """
        try:
            event = SupplierLifecycleEvent(**event_data)
            is_v2 = self._parse_schema_major_version(
                event_data.get('schema_version', '')) >= 2

            # NORMALIZATION STEP: Assign supplier_timeline_version (monotonic per order_detail)
            latest_supplier_version = self.db.get_latest_supplier_timeline_version(
                event.order_id, event.order_detail_id
            )
            supplier_timeline_version = (latest_supplier_version or 0) + 1

            ingested_at = datetime.now(timezone.utc).isoformat()

            amount_basis = None
            fx_context_json = None
            entity_context_json = None
            fulfillment_instance_id = None

            # Extract from nested supplier object OR legacy flat structure
            if event.supplier:
                supplier_id = event.supplier.supplier_id
                booking_code = event.supplier.booking_code
                supplier_reference_id = event.supplier.supplier_ref
                fulfillment_instance_id = getattr(event.supplier, 'fulfillment_instance_id', None)
                amount = event.supplier.amount_due
                amount_basis_val = event.supplier.amount_basis
                amount_basis = getattr(amount_basis_val, 'value', amount_basis_val) if amount_basis_val else None
                currency = event.supplier.currency
                status = event.supplier.status

                # Cancellation fee (DEPRECATED in v2 - use parties array with
                # obligation_type='CANCELLATION_FEE' instead)
                cancellation_fee_amount = None
                cancellation_fee_currency = None
                if event.supplier.cancellation:
                    cancellation_fee_amount = event.supplier.cancellation.fee_amount
                    cancellation_fee_currency = event.supplier.cancellation.fee_currency
                    if (cancellation_fee_amount and cancellation_fee_amount > 0
                            and not self._has_cancellation_fee_line(event)):
                        print(f"⚠️  MIGRATION WARNING: Event {event.event_id} uses deprecated "
                              f"cancellation.fee_amount field. Please update to use parties array "
                              f"with obligation_type='CANCELLATION_FEE'.")

                if event.supplier.fx_context:
                    fx_context_json = json.dumps(event.supplier.fx_context.model_dump())
                if event.supplier.entity_context:
                    entity_context_json = json.dumps(event.supplier.entity_context.model_dump())

                if is_v2:
                    metadata = event.meta if event.meta else event.metadata
                else:
                    # v1 contract: record entity + affiliate snapshot
                    metadata = {
                        'entity_code': event.supplier.entity_context.entity_code if event.supplier.entity_context else None,
                        'affiliate': event.supplier.affiliate.model_dump() if event.supplier.affiliate else None
                    }
            else:
                # Legacy v1 flat structure
                supplier_id = event.supplier_id
                booking_code = None
                supplier_reference_id = event.supplier_reference_id
                amount = event.amount
                currency = event.currency
                status = None
                cancellation_fee_amount = None
                cancellation_fee_currency = None
                metadata = event.metadata

            # Handle emitted_at as string or datetime
            emitted_at_str = event.emitted_at if isinstance(event.emitted_at, str) else event.emitted_at.isoformat()

            normalized = NormalizedSupplierTimeline(
                event_id=event.event_id or str(uuid.uuid4()),
                order_id=event.order_id,
                order_detail_id=event.order_detail_id,
                supplier_timeline_version=supplier_timeline_version,  # Assigned by Order Core
                event_type=event.event_type,
                supplier_id=supplier_id,
                booking_code=booking_code,
                supplier_reference_id=supplier_reference_id,
                fulfillment_instance_id=fulfillment_instance_id,
                amount=amount,
                currency=currency,
                status=status,
                cancellation_fee_amount=cancellation_fee_amount,
                cancellation_fee_currency=cancellation_fee_currency,
                emitter_service=event.emitter_service or "supplier-service",
                ingested_at=ingested_at,
                emitted_at=emitted_at_str,
                metadata=metadata
            )

            timeline_dict = normalized.model_dump(mode='json')
            timeline_dict['amount_basis'] = amount_basis
            timeline_dict['fx_context'] = fx_context_json
            timeline_dict['entity_context'] = entity_context_json
            self.db.insert_supplier_timeline(timeline_dict)

            if is_v2:
                payable_count = self._insert_party_lines(
                    event, normalized.event_id, supplier_reference_id,
                    fulfillment_instance_id, supplier_timeline_version, ingested_at
                )
            else:
                payable_count = self._insert_legacy_lines(
                    event, normalized.event_id, supplier_id, amount,
                    currency, supplier_timeline_version, ingested_at
                )

            return IngestionResult(
                success=True,
                message=f"Ingested supplier event ({'v2' if is_v2 else 'v1'}): {event.event_type}"
                        + (f" with {payable_count} payable lines" if payable_count > 0 else ""),
                details={
                    'event_id': normalized.event_id,
                    'order_id': event.order_id,
                    'order_detail_id': event.order_detail_id,
                    'supplier_id': supplier_id,
                    'amount': amount,
                    'amount_basis': amount_basis,
                    'payable_lines': payable_count
                }
            )

        except ValidationError as e:
            return self._send_to_dlq(
                event_data, "VALIDATION_ERROR", f"Validation failed: {str(e)}"
            )

    @staticmethod
    def _has_cancellation_fee_line(event) -> bool:
        """True if any party line carries obligation_type CANCELLATION_FEE."""
        for party in (event.parties or []):
            for line in party.lines:
                obligation = getattr(line.obligation_type, 'value', line.obligation_type)
                if obligation == 'CANCELLATION_FEE':
                    return True
        return False

    def _insert_party_lines(self, event, event_id: str, supplier_reference_id,
                            fulfillment_instance_id, supplier_timeline_version: int,
                            ingested_at: str) -> int:
        """v2: insert payable lines from the explicit parties array."""
        payable_count = 0
        for party in (event.parties or []):
            for line in party.lines:
                amount_effect = getattr(line.amount_effect, 'value', line.amount_effect)
                obligation_type = getattr(line.obligation_type, 'value', line.obligation_type)
                self.db.insert_payable_line({
                    'line_id': str(uuid.uuid4()),
                    'event_id': event_id,
                    'order_id': event.order_id,
                    'order_detail_id': event.order_detail_id,
                    'supplier_reference_id': supplier_reference_id,
                    'fulfillment_instance_id': fulfillment_instance_id,
                    'supplier_timeline_version': supplier_timeline_version,
                    'obligation_type': obligation_type,
                    'party_type': party.party_type,
                    'party_id': party.party_id,
                    'party_name': party.party_name,
                    'amount': int(line.amount) if isinstance(line.amount, float) else line.amount,
                    'amount_effect': amount_effect,
                    'currency': line.currency,
                    'calculation_basis': line.calculation.get('basis') if line.calculation else None,
                    'calculation_rate': line.calculation.get('rate') if line.calculation else None,
                    'calculation_description': line.description,
                    'ingested_at': ingested_at,
                    'metadata': None
                })
                payable_count += 1
        return payable_count

    def _insert_legacy_lines(self, event, event_id: str, supplier_id, amount,
                             currency, supplier_timeline_version: int,
                             ingested_at: str) -> int:
        """
        v1: derive payable lines from nested affiliate / commission / tax
        objects. Preserved verbatim from the legacy handler for compatibility.
        """
        payable_count = 0
        if event.supplier and amount is not None:
                # Only insert payable lines if amount_due exists (not for pure cancellation events)
                # 1. Insert supplier cost payable
                supplier_line = {
                    'line_id': f"{event_id}_SUPPLIER",
                    'event_id': event_id,
                    'order_id': event.order_id,
                    'order_detail_id': event.order_detail_id,
                    'supplier_timeline_version': supplier_timeline_version,  # Assigned by Order Core
                    'obligation_type': 'SUPPLIER',
                    'party_id': supplier_id,
                    'party_name': supplier_id,
                    'amount': amount,
                    'currency': currency,
                    'calculation_basis': None,
                    'calculation_rate': None,
                    'calculation_description': None,
                    'ingested_at': ingested_at,
                    'metadata': None
                }
                self.db.insert_payable_line(supplier_line)
                payable_count += 1

                # 2. If affiliate data exists, insert commission payable
                if event.supplier.affiliate:
                    shareback = event.supplier.affiliate.partnerShareback
                    # Get reseller info from affiliate object (hasattr is
                    # always True on Pydantic model fields — check the VALUE)
                    reseller_id = getattr(event.supplier.affiliate, 'reseller_id', None) or 'UNKNOWN'
                    reseller_name = getattr(event.supplier.affiliate, 'reseller_name', None) or 'Affiliate Partner'

                    affiliate_line = {
                        'line_id': f"{event_id}_AFFILIATE",
                        'event_id': event_id,
                        'order_id': event.order_id,
                        'order_detail_id': event.order_detail_id,
                        'supplier_timeline_version': supplier_timeline_version,  # Assigned by Order Core
                        'obligation_type': 'AFFILIATE_COMMISSION',
                        'party_id': reseller_id,
                        'party_name': reseller_name,
                        'amount': int(shareback.amount) if isinstance(shareback.amount, float) else shareback.amount,
                        'currency': shareback.currency,
                        'calculation_basis': shareback.basis,
                        'calculation_rate': shareback.rate,
                        'calculation_description': f"{shareback.rate*100:.0f}% of {shareback.basis}",
                        'ingested_at': ingested_at,
                        'metadata': None
                    }
                    self.db.insert_payable_line(affiliate_line)
                    payable_count += 1

                    # 3. Insert tax payables
                    for idx, tax in enumerate(event.supplier.affiliate.taxes):
                        tax_line = {
                            'line_id': f"{event_id}_TAX_{idx}",
                            'event_id': event_id,
                            'order_id': event.order_id,
                            'order_detail_id': event.order_detail_id,
                            'supplier_timeline_version': supplier_timeline_version,  # Assigned by Order Core
                            'obligation_type': 'TAX_WITHHOLDING',
                            'party_id': f"TAX_{tax.type}",
                            'party_name': f"{tax.type} Tax",
                            'amount': int(tax.amount) if isinstance(tax.amount, float) else tax.amount,
                            'currency': tax.currency,
                            'calculation_basis': tax.basis,
                            'calculation_rate': tax.rate,
                            'calculation_description': f"{tax.rate*100:.0f}% {tax.type} on {tax.basis}",
                            'ingested_at': ingested_at,
                            'metadata': None
                        }
                        self.db.insert_payable_line(tax_line)
                        payable_count += 1

                # 4. If supplier_commission exists, insert commission payable to supplier
                if event.supplier.supplier_commission:
                    commission = event.supplier.supplier_commission
                    supplier_commission_line = {
                        'line_id': f"{event_id}_SUPPLIER_COMMISSION",
                        'event_id': event_id,
                        'order_id': event.order_id,
                        'order_detail_id': event.order_detail_id,
                        'supplier_timeline_version': supplier_timeline_version,  # Assigned by Order Core
                        'obligation_type': 'SUPPLIER_COMMISSION',
                        'party_id': supplier_id,
                        'party_name': supplier_id,
                        'amount': int(commission.amount) if isinstance(commission.amount, float) else commission.amount,
                        'currency': commission.currency,
                        'calculation_basis': commission.basis if commission.basis else commission.commission_type,
                        'calculation_rate': commission.rate,
                        'calculation_description': commission.description or f"{commission.commission_type}",
                        'ingested_at': ingested_at,
                        'metadata': None
                    }
                    self.db.insert_payable_line(supplier_commission_line)
                    payable_count += 1

        return payable_count

    def _ingest_partner_adjustment(self, event_data: Dict[str, Any]) -> IngestionResult:
        """
        Handle standalone partner adjustment events (no supplier timeline version).
        These obligations persist regardless of supplier status (version = -1).
        """
        try:
            event = PartnerAdjustmentEvent(**event_data)

            ingested_at = datetime.now(timezone.utc).isoformat()

            # Extract party info
            party_type = event.party.get('party_type')
            party_id = event.party.get('party_id')
            party_name = event.party.get('party_name')

            # Extract line info
            line = event.line
            amount_effect_val = line.amount_effect
            amount_effect = amount_effect_val.value if hasattr(amount_effect_val, 'value') else amount_effect_val

            obligation_type_val = line.obligation_type
            obligation_type = obligation_type_val.value if hasattr(obligation_type_val, 'value') else obligation_type_val

            # Create payable line with version = -1 (standalone, always included)
            payable_line = {
                'line_id': str(uuid.uuid4()),
                'event_id': event.event_id or str(uuid.uuid4()),
                'order_id': event.order_id,
                'order_detail_id': event.order_detail_id,
                'supplier_timeline_version': -1,  # Standalone adjustment (no timeline linkage)
                'obligation_type': obligation_type,
                'party_type': party_type,  # NEW: Store party_type
                'party_id': party_id,
                'party_name': party_name,
                'amount': int(line.amount) if isinstance(line.amount, float) else line.amount,
                'amount_effect': amount_effect,
                'currency': line.currency,
                'calculation_basis': line.calculation.get('basis') if line.calculation else None,
                'calculation_rate': line.calculation.get('rate') if line.calculation else None,
                'calculation_description': line.description,
                'ingested_at': ingested_at,
                'metadata': event.meta if event.meta else None
            }
            self.db.insert_payable_line(payable_line)

            return IngestionResult(
                success=True,
                message=f"Ingested partner adjustment: {obligation_type} for {party_type}",
                details={
                    'event_id': payable_line['event_id'],
                    'order_id': event.order_id,
                    'order_detail_id': event.order_detail_id,
                    'party_id': party_id,
                    'obligation_type': obligation_type,
                    'amount': line.amount,
                    'amount_effect': amount_effect
                }
            )

        except ValidationError as e:
            return self._send_to_dlq(
                event_data, "VALIDATION_ERROR", f"Validation failed: {str(e)}"
            )

    def _ingest_refund_lifecycle(self, event_data: Dict[str, Any]) -> IngestionResult:
        """Handle refund timeline events (no components)"""
        try:
            event = RefundLifecycleEvent(**event_data)

            # Generate event_id if missing
            event_id = event.event_id or str(uuid.uuid4())

            ingested_at = datetime.now(timezone.utc).isoformat()

            # Assign refund_timeline_version (Order Core responsibility)
            # Get latest version for this refund_id and increment
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT MAX(refund_timeline_version)
                FROM refund_timeline
                WHERE order_id = ? AND refund_id = ?
            """, (event.order_id, event.refund_id))
            max_version = cursor.fetchone()[0]
            refund_timeline_version = (max_version or 0) + 1

            normalized = NormalizedRefundTimeline(
                event_id=event_id,
                order_id=event.order_id,
                refund_id=event.refund_id,
                refund_timeline_version=refund_timeline_version,
                event_type=event.event_type.value,
                status=event.status,  # NEW: Read status from producer event
                refund_amount=event.refund_amount,
                currency=event.currency,
                refund_reason=event.refund_reason,
                emitter_service=event.emitter_service,
                ingested_at=ingested_at,
                emitted_at=event.emitted_at.isoformat(),
                metadata=event.metadata
            )

            self.db.insert_refund_timeline(normalized.model_dump(mode='json'))

            return IngestionResult(
                success=True,
                message=f"Ingested refund event: {event.event_type.value} (version {refund_timeline_version})",
                details={
                    'event_id': event_id,
                    'order_id': event.order_id,
                    'refund_id': event.refund_id,
                    'refund_timeline_version': refund_timeline_version
                }
            )

        except ValidationError as e:
            return self._send_to_dlq(
                event_data, "VALIDATION_ERROR", f"Validation failed: {str(e)}"
            )

    def _send_to_dlq(self, event_data: Dict[str, Any], error_type: str, error_message: str) -> IngestionResult:
        """Send failed event to Dead Letter Queue"""
        import json

        dlq_entry = DLQEntry(
            dlq_id=str(uuid.uuid4()),
            event_id=event_data.get('event_id', 'unknown'),
            event_type=event_data.get('event_type', 'unknown'),
            order_id=event_data.get('order_id'),
            raw_event=json.dumps(event_data),
            error_type=error_type,
            error_message=error_message,
            failed_at=datetime.now(timezone.utc).isoformat(),
            retry_count=0
        )

        # Stash the entry so ingest_event can re-insert it if a surrounding
        # transaction rolls this insert back along with partial fact writes
        self._last_dlq_entry = dlq_entry.model_dump(mode='json')
        self.db.insert_dlq(self._last_dlq_entry)

        return IngestionResult(
            success=False,
            message=f"Event sent to DLQ: {error_message}",
            details={'dlq_id': dlq_entry.dlq_id, 'error_type': error_type}
        )
