"""
Event data models following Unified Pricing Read Layer specification.
These represent the standardized producer events.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from enum import Enum


class EventType(str, Enum):
    """Standard event types from producer services"""
    PRICING_UPDATED = "pricing.updated"
    PAYMENT_CHECKOUT = "payment.checkout"
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_REFUNDED = "payment.refunded"
    PAYMENT_SETTLED = "payment.settled"
    REFUND_INITIATED = "refund.initiated"
    REFUND_ISSUED = "refund.issued"
    REFUND_CLOSED = "refund.closed"
    SUPPLIER_ORDER_CONFIRMED = "supplier.order.confirmed"
    SUPPLIER_ORDER_ISSUED = "supplier.order.issued"
    SUPPLIER_INVOICE_RECEIVED = "supplier.invoice.received"


class ComponentType(str, Enum):
    """Commerce component types (not accounting GL codes)"""
    BASE_FARE = "BaseFare"
    ROOM_RATE = "RoomRate"  # Accommodation-specific base rate
    TAX = "Tax"
    SUBSIDY = "Subsidy"
    DISCOUNT = "Discount"
    FEE = "Fee"
    MARKUP = "Markup"
    CANCELLATION_FEE = "CancellationFee"
    AMENDMENT_FEE = "AmendmentFee"
    REFUND = "Refund"
    COMPENSATION = "Compensation"
    AFFILIATE_SHAREBACK = "AffiliateShareback"  # B2B affiliate commission
    VAT = "VAT"  # Value Added Tax


class PricingComponent(BaseModel):
    """Individual pricing component within an event"""
    component_type: Union[ComponentType, str]  # Accept both enum and string
    amount: Union[int, float]  # Support both int and float for decimal amounts
    currency: str
    dimensions: Dict[str, str]  # e.g., {"order_detail_id": "OD-001", "pax_id": "P1"}
    description: Optional[str] = None
    is_refund: Optional[bool] = None  # Per-component refund flag (producer can set explicitly)
    meta: Optional[Dict[str, Any]] = None  # Changed from 'metadata' for consistency with real schema
    metadata: Optional[Dict[str, Any]] = None  # Backward compatibility
    refund_of_component_semantic_id: Optional[str] = None  # For refund lineage


class CustomerContext(BaseModel):
    """Customer/Reseller context for B2B scenarios"""
    reseller_type_name: Optional[str] = None  # e.g., "B2B_AFFILIATE"
    reseller_id: Optional[str] = None
    reseller_name: Optional[str] = None


class EntityContext(BaseModel):
    """Legal entity context"""
    entity_code: Optional[str] = None  # e.g., "TNPL", "GTN"
    # Extended format for multi-entity scenarios
    merchant_of_record: Optional[str] = None
    supplier_entity: Optional[str] = None
    customer_entity: Optional[str] = None


class FXContext(BaseModel):
    """Foreign exchange context for multi-currency scenarios"""
    timestamp_fx_rate: Optional[str] = None
    as_of: Optional[str] = None  # Alternative field name
    payment_currency: str
    supply_currency: str
    record_currency: str
    gbv_currency: str
    payment_value: int
    supply_to_payment_fx_rate: float
    supply_to_record_fx_rate: float
    payment_to_gbv_fx_rate: float
    source: str  # e.g., "Treasury"


class DetailContext(BaseModel):
    """Order detail level context"""
    order_detail_id: str
    entity_context: Optional[EntityContext] = None
    fx_context: Optional[FXContext] = None


class Totals(BaseModel):
    """Total amount validation"""
    customer_total: int
    currency: str


class PricingUpdatedEvent(BaseModel):
    """
    Producer event emitted by verticals when pricing changes.
    NOTE: This is the RAW producer event. It does NOT contain:
    - pricing_snapshot_id (assigned by Order Core during normalization)
    - version (assigned by Order Core during normalization)
    These enrichment fields only appear in OrderUpserted events.

    OPTION A IMPLEMENTATION:
    Supports BOTH single detail_context (legacy) and detail_contexts array (new).
    When multiple order_detail_ids exist, use detail_contexts array with one context per order_detail.
    Each component's order_detail_id in dimensions should match one of the contexts.
    """
    event_id: Optional[str] = None  # Optional for backward compatibility
    event_type: str = "PricingUpdated"  # Support both formats
    schema_version: str = "pricing.commerce.v1"
    order_id: str
    vertical: Optional[str] = None  # e.g., "accommodation"
    components: List[PricingComponent]
    emitted_at: str  # Support both datetime and string
    emitter_service: Optional[str] = None  # Optional for backward compatibility
    customer_context: Optional[CustomerContext] = None  # For B2B scenarios
    detail_context: Optional[DetailContext] = None  # LEGACY: For single order_detail (backward compatibility)
    detail_contexts: Optional[List[DetailContext]] = None  # NEW: For multiple order_details (Option A)
    totals: Optional[Totals] = None  # Validation field
    meta: Optional[Dict[str, Any]] = None  # Trigger, reason, etc.
    metadata: Optional[Dict[str, Any]] = None  # Backward compatibility


class PaymentInstrument(BaseModel):
    """
    Masked payment instrument details.
    Only one of va/card/ewallet/bnpl should be populated based on type.
    """
    type: str  # "VA", "CARD", "EWALLET", "BNPL", "QR"
    va: Optional[Dict[str, Any]] = None  # e.g., {"bank": "BNI", "account_number_masked": "8060•••••••1234"}
    card: Optional[Dict[str, Any]] = None  # e.g., {"last4": "1234", "brand": "VISA", "exp_month": 12}
    ewallet: Optional[Dict[str, Any]] = None  # e.g., {"provider": "GOPAY", "phone_masked": "0812•••••••789"}
    bnpl: Optional[Dict[str, Any]] = None  # e.g., {"provider": "KREDIVO", "contract_id": "KRD-123"}
    display_hint: Optional[str] = None  # e.g., "BNI VA ••••1234"
    psp_ref: Optional[str] = None  # Payment Service Provider reference
    psp_trace_id: Optional[str] = None  # PSP trace/transaction ID


class PaymentMethod(BaseModel):
    """Payment method details"""
    channel: str  # e.g., "AFFILIATE_DEPOSIT", "CC", "VA"
    provider: str  # e.g., "AffiliateDeposit", "Stripe"
    brand: str  # e.g., "INTERNAL", "VISA"


class Payment(BaseModel):
    """
    Detailed payment information for payment lifecycle events.
    This is the producer event structure - contains full payment state.
    """
    status: str  # "Authorized", "Captured", "Refunded", etc.
    payment_id: Optional[str] = None  # Payment intent ID (shown as Intent ID in UI)
    pg_reference_id: Optional[str] = None  # Payment gateway reference (shown as PG Reference in UI)
    payment_method: PaymentMethod
    currency: str
    authorized_amount: Optional[int] = None
    authorized_at: Optional[str] = None
    captured_amount: Optional[int] = None  # Amount captured in this event
    captured_amount_total: Optional[int] = None  # Running total of all captures
    captured_at: Optional[str] = None
    instrument: Optional[PaymentInstrument] = None  # Masked instrument details
    bnpl_plan: Optional[Dict[str, Any]] = None  # For BNPL-specific data


class PaymentLifecycleEvent(BaseModel):
    """
    Producer event for payment timeline (checkout, authorized, captured, etc.).
    NOTE: This is the RAW producer event. It does NOT contain:
    - timeline_version (assigned by Order Core during normalization)
    This enrichment field only appears in PaymentTimelineUpserted events.
    """
    event_id: Optional[str] = None
    event_type: str  # "PaymentLifecycle"
    schema_version: str = "payment.timeline.v1"
    order_id: str
    emitted_at: str
    payment: Payment  # Required nested payment object with status, amounts, instrument
    idempotency_key: Optional[str] = None  # For exactly-once processing
    emitter_service: Optional[str] = "payment-core"
    meta: Optional[Dict[str, Any]] = None  # Additional metadata
    # Legacy fields (backward compatibility - deprecated)
    payment_method: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    pg_reference_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AffiliateShareback(BaseModel):
    """Affiliate commission/shareback details"""
    component_type: str = "AffiliateShareback"
    amount: float  # Can be decimal for precise calculation
    currency: str
    rate: float  # e.g., 0.1 for 10%
    basis: str  # e.g., "markup"


class AffiliateTax(BaseModel):
    """Tax on affiliate shareback"""
    type: str  # e.g., "VAT"
    amount: float
    currency: str
    rate: float  # e.g., 0.11 for 11%
    basis: str  # e.g., "shareback"


class Affiliate(BaseModel):
    """Affiliate-specific data for B2B resellers"""
    reseller_id: Optional[str] = None
    reseller_name: Optional[str] = None
    partnerShareback: AffiliateShareback
    taxes: List[AffiliateTax]
    meta: Optional[Dict[str, Any]] = None  # For carry-over metadata


class Cancellation(BaseModel):
    """Cancellation details for supplier orders"""
    fee_amount: Optional[int] = None
    fee_currency: Optional[str] = None


class Supplier(BaseModel):
    """Detailed supplier information"""
    status: str  # "ISSUED", "Confirmed", "CancelledNoFee", "CancelledWithFee", etc.
    supplier_id: str
    booking_code: Optional[str] = None
    supplier_ref: Optional[str] = None
    amount_due: Optional[int] = None
    currency: Optional[str] = None
    fx_context: Optional[FXContext] = None
    entity_context: Optional[EntityContext] = None
    affiliate: Optional[Affiliate] = None  # For B2B affiliate cases
    cancellation: Optional[Cancellation] = None  # For cancelled orders


class SupplierLifecycleEvent(BaseModel):
    """
    Producer event for supplier timeline (confirmed, issued, cancelled, etc.).
    NOTE: This is the RAW producer event. It does NOT contain:
    - supplier_timeline_version (assigned by Order Core during normalization)
    This enrichment field only appears in SupplierTimelineUpserted events.
    """
    event_id: Optional[str] = None
    event_type: str  # "IssuanceSupplierLifecycle"
    schema_version: str = "supplier.timeline.v1"
    order_id: str
    order_detail_id: str
    emitted_at: str
    supplier: Supplier  # Required nested supplier object with status, amounts
    idempotency_key: Optional[str] = None
    emitter_service: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None  # Additional metadata
    # Legacy fields (backward compatibility - deprecated)
    supplier_id: Optional[str] = None
    supplier_reference_id: Optional[str] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RefundLifecycleEvent(BaseModel):
    """Refund timeline events (initiated, closed)"""
    event_id: Optional[str] = None  # Optional - Order Core can generate if missing
    event_type: EventType
    schema_version: str = "refund.timeline.v1"
    order_id: str
    refund_id: str
    refund_timeline_version: int  # Monotonic per refund_id
    refund_amount: int
    currency: str
    refund_reason: Optional[str] = None
    emitted_at: datetime
    emitter_service: str = "refund-service"
    metadata: Optional[Dict[str, Any]] = None


class RefundIssuedEvent(BaseModel):
    """
    Producer event for refund issued with component breakdown.
    NOTE: This is the RAW producer event. It does NOT contain:
    - pricing_snapshot_id (assigned by Order Core during normalization)
    - version (assigned by Order Core during normalization)
    These enrichment fields only appear in RefundComponentsUpserted events.
    """
    event_id: Optional[str] = None  # Optional - Order Core can generate if missing
    event_type: str = EventType.REFUND_ISSUED
    schema_version: str = "refund.components.v1"
    order_id: str
    refund_id: str
    components: List[PricingComponent]  # Components with refund_of_component_semantic_id
    emitted_at: datetime
    emitter_service: str = "refund-service"
    meta: Optional[Dict[str, Any]] = None  # Additional metadata
    metadata: Optional[Dict[str, Any]] = None
