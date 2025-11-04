"""
Order Core ingestion pipeline.
Validates, canonicalizes, and normalizes producer events into storage format.
"""
import uuid
from datetime import datetime
from typing import Union, Dict, Any, List
from pydantic import ValidationError

from src.models.events import (
    PricingUpdatedEvent, PaymentLifecycleEvent, SupplierLifecycleEvent,
    RefundLifecycleEvent, RefundIssuedEvent, EventType
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


class IngestionPipeline:
    """Main ingestion pipeline for Order Core"""

    def __init__(self, database: Database):
        self.db = database
        self.id_generator = IDGenerator()

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

            # Route to appropriate handler
            # Support both "pricing.updated" and "PricingUpdated" formats
            if event_type in [EventType.PRICING_UPDATED, "PricingUpdated"]:
                return self._ingest_pricing_updated(event_data)
            elif event_type in [EventType.REFUND_ISSUED, "RefundIssued"]:
                return self._ingest_refund_issued(event_data)
            elif event_type in [EventType.PAYMENT_CHECKOUT, EventType.PAYMENT_AUTHORIZED,
                                EventType.PAYMENT_CAPTURED, EventType.PAYMENT_REFUNDED,
                                EventType.PAYMENT_SETTLED, "PaymentLifecycle"]:
                return self._ingest_payment_lifecycle(event_data)
            elif event_type in [EventType.SUPPLIER_ORDER_CONFIRMED, EventType.SUPPLIER_ORDER_ISSUED,
                                EventType.SUPPLIER_INVOICE_RECEIVED, "IssuanceSupplierLifecycle"]:
                return self._ingest_supplier_lifecycle(event_data)
            elif event_type in [EventType.REFUND_INITIATED, EventType.REFUND_CLOSED]:
                return self._ingest_refund_lifecycle(event_data)
            else:
                return self._send_to_dlq(
                    event_data, "UNKNOWN_EVENT_TYPE", f"Unknown event_type: {event_type}"
                )

        except Exception as e:
            return self._send_to_dlq(
                event_data, "PIPELINE_ERROR", f"Pipeline error: {str(e)}"
            )

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

            # Normalize each component
            normalized_components = []
            ingested_at = datetime.utcnow().isoformat()

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
                self.db.insert_pricing_component(normalized.model_dump())

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
            ingested_at = datetime.utcnow().isoformat()

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
                self.db.insert_pricing_component(normalized.model_dump())

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

            ingested_at = datetime.utcnow().isoformat()

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

            self.db.insert_payment_timeline(normalized.model_dump())

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
        Handle supplier timeline events (producer event).
        NORMALIZATION: Assigns supplier_timeline_version during ingestion.
        """
        try:
            event = SupplierLifecycleEvent(**event_data)

            # NORMALIZATION STEP: Assign supplier_timeline_version (monotonic per order_detail)
            latest_supplier_version = self.db.get_latest_supplier_timeline_version(
                event.order_id, event.order_detail_id
            )
            supplier_timeline_version = (latest_supplier_version or 0) + 1

            ingested_at = datetime.utcnow().isoformat()

            # Extract from nested supplier object OR legacy flat structure
            if event.supplier:
                # New schema: nested supplier object
                supplier_id = event.supplier.supplier_id
                booking_code = event.supplier.booking_code
                supplier_reference_id = event.supplier.supplier_ref
                amount = event.supplier.amount_due
                currency = event.supplier.currency
                status = event.supplier.status

                # Extract cancellation fee if present
                cancellation_fee_amount = None
                cancellation_fee_currency = None
                if event.supplier.cancellation:
                    cancellation_fee_amount = event.supplier.cancellation.fee_amount
                    cancellation_fee_currency = event.supplier.cancellation.fee_currency

                # Store rich supplier data in metadata
                metadata = {
                    'entity_code': event.supplier.entity_context.entity_code if event.supplier.entity_context else None,
                    'affiliate': event.supplier.affiliate.model_dump() if event.supplier.affiliate else None
                }
            else:
                # Legacy schema: flat structure
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

            self.db.insert_supplier_timeline(normalized.model_dump())

            # Extract and insert payable lines for B2B affiliate cases
            payable_count = 0
            if event.supplier and amount is not None:
                # Only insert payable lines if amount_due exists (not for pure cancellation events)
                # 1. Insert supplier cost payable
                supplier_line = {
                    'line_id': f"{normalized.event_id}_SUPPLIER",
                    'event_id': normalized.event_id,
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
                    # Get reseller info from affiliate object
                    reseller_id = event.supplier.affiliate.reseller_id if hasattr(event.supplier.affiliate, 'reseller_id') else 'UNKNOWN'
                    reseller_name = event.supplier.affiliate.reseller_name if hasattr(event.supplier.affiliate, 'reseller_name') else 'Affiliate Partner'

                    affiliate_line = {
                        'line_id': f"{normalized.event_id}_AFFILIATE",
                        'event_id': normalized.event_id,
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
                            'line_id': f"{normalized.event_id}_TAX_{idx}",
                            'event_id': normalized.event_id,
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

            return IngestionResult(
                success=True,
                message=f"Ingested supplier event: {event.event_type}" + (f" with {payable_count} payable lines" if payable_count > 0 else ""),
                details={
                    'event_id': normalized.event_id,
                    'order_id': event.order_id,
                    'order_detail_id': event.order_detail_id,
                    'supplier_id': supplier_id,
                    'amount': amount,
                    'payable_lines': payable_count
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

            ingested_at = datetime.utcnow().isoformat()

            normalized = NormalizedRefundTimeline(
                event_id=event_id,
                order_id=event.order_id,
                refund_id=event.refund_id,
                refund_timeline_version=event.refund_timeline_version,
                event_type=event.event_type.value,
                refund_amount=event.refund_amount,
                currency=event.currency,
                refund_reason=event.refund_reason,
                emitter_service=event.emitter_service,
                ingested_at=ingested_at,
                emitted_at=event.emitted_at.isoformat(),
                metadata=event.metadata
            )

            self.db.insert_refund_timeline(normalized.model_dump())

            return IngestionResult(
                success=True,
                message=f"Ingested refund event: {event.event_type.value}",
                details={
                    'event_id': event_id,
                    'order_id': event.order_id,
                    'refund_id': event.refund_id
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
            failed_at=datetime.utcnow().isoformat(),
            retry_count=0
        )

        self.db.insert_dlq(dlq_entry.model_dump())

        return IngestionResult(
            success=False,
            message=f"Event sent to DLQ: {error_message}",
            details={'dlq_id': dlq_entry.dlq_id, 'error_type': error_type}
        )
