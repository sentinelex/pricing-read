"""
Normalized data models representing what Order Core stores after ingestion.
These are the upserted records with dual IDs and version keys assigned.
"""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel


class NormalizedPricingComponent(BaseModel):
    """
    Normalized pricing component with enrichment fields added by Order Core.
    This is what gets stored after ingesting PricingUpdatedEvent.
    Enrichment fields assigned during normalization:
    - pricing_snapshot_id (UUID minted by Order Core)
    - version (monotonic integer per order)
    - component_semantic_id (stable logical ID)
    - component_instance_id (unique per snapshot)
    """
    component_semantic_id: str  # Stable logical ID (assigned by Order Core)
    component_instance_id: str  # Unique per snapshot (assigned by Order Core)
    order_id: str
    pricing_snapshot_id: str  # Assigned by Order Core during normalization
    version: int  # Assigned by Order Core during normalization
    component_type: str
    amount: int
    currency: str
    dimensions: Dict[str, str]
    description: Optional[str] = None
    is_refund: bool = False  # Per-row flag indicating refund component
    refund_of_component_semantic_id: Optional[str] = None
    emitter_service: str
    ingested_at: datetime
    emitted_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class NormalizedPaymentTimeline(BaseModel):
    """
    Normalized payment timeline entry with enrichment fields added by Order Core.
    This is what gets stored after ingesting PaymentLifecycleEvent.
    """
    event_id: str
    order_id: str
    timeline_version: int  # Assigned by Order Core during normalization
    event_type: str
    status: str  # "Authorized", "Captured", "Refunded"
    payment_method: str
    payment_intent_id: Optional[str] = None  # For BNPL, retries tracking
    authorized_amount: Optional[int] = None
    captured_amount: Optional[int] = None  # Amount in this specific capture event
    captured_amount_total: Optional[int] = None  # Running total
    amount: Optional[int] = None  # Legacy field: captured_amount or authorized_amount for backward compatibility
    currency: str
    instrument_json: Optional[str] = None  # JSON string of masked instrument details
    pg_reference_id: Optional[str] = None
    emitter_service: str
    ingested_at: datetime
    emitted_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class NormalizedSupplierTimeline(BaseModel):
    """
    Normalized supplier timeline entry with enrichment fields added by Order Core.
    This is what gets stored after ingesting SupplierLifecycleEvent.
    """
    event_id: str
    order_id: str
    order_detail_id: str
    supplier_timeline_version: int  # Assigned by Order Core during normalization
    event_type: str
    supplier_id: str
    booking_code: Optional[str] = None
    supplier_reference_id: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    status: Optional[str] = None  # For status-driven obligation model
    cancellation_fee_amount: Optional[int] = None
    cancellation_fee_currency: Optional[str] = None
    emitter_service: str
    ingested_at: datetime
    emitted_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class NormalizedRefundTimeline(BaseModel):
    """Refund timeline entry"""
    event_id: str
    order_id: str
    refund_id: str
    refund_timeline_version: int
    event_type: str
    refund_amount: int
    currency: str
    refund_reason: Optional[str] = None
    emitter_service: str
    ingested_at: datetime
    emitted_at: datetime
    metadata: Optional[Dict[str, Any]] = None


class DLQEntry(BaseModel):
    """Dead Letter Queue entry for failed events"""
    dlq_id: str
    event_id: str
    event_type: str
    order_id: Optional[str] = None
    raw_event: str  # JSON string
    error_type: str
    error_message: str
    failed_at: datetime
    retry_count: int = 0
