"""
Producer Playground UI component
Allows users to emit sample events from different producers
"""
import streamlit as st
import uuid
from datetime import datetime
import json
from src.ingestion.pipeline import IngestionPipeline


def render_producer_playground(db):
    """Render the Producer Playground page"""

    st.markdown("## 🎮 Producer Playground")
    st.markdown("Emit sample events from vertical services, payment, and refund systems.")

    # Create ingestion pipeline
    pipeline = IngestionPipeline(db)

    # Tabs for different event types
    tab1, tab2, tab3, tab4 = st.tabs([
        "💰 Pricing Events",
        "💳 Payment Events",
        "🏪 Supplier Events",
        "↩️ Refund Events"
    ])

    with tab1:
        render_pricing_events(pipeline)

    with tab2:
        render_payment_events(pipeline)

    with tab3:
        render_supplier_events(pipeline)

    with tab4:
        render_refund_events(pipeline)


def render_pricing_events(pipeline):
    """Render pricing event scenarios"""

    st.markdown("### Pricing Updated Events")
    st.markdown("Events emitted by vertical services when pricing changes")

    # Mode toggle: Form Mode vs JSON Mode
    edit_mode = st.radio(
        "Edit Mode",
        ["Form Mode (Quick)", "JSON Mode (Full Control)"],
        key="pricing_edit_mode",
        horizontal=True
    )

    # Initialize session state for JSON if not exists
    if "pricing_json_cache" not in st.session_state:
        st.session_state.pricing_json_cache = None

    if edit_mode == "Form Mode (Quick)":
        # Original scenario-based UI
        scenario = st.selectbox(
            "Select Scenario",
            [
                "Hotel 3-Night Booking (Simple)",
                "Hotel 3-Night with Subsidy",
                "Flight with Ancillaries",
                "Airport Transfer (Basic)",
                "B2B Affiliate Accommodation (Real Schema)",
                "Multi-Order-Detail with Contexts (Option A)",  # NEW: Multiple order details
                "Custom JSON"
            ]
        )

        if scenario == "Hotel 3-Night Booking (Simple)":
            event = {
                "event_type": "PricingUpdated",
                "schema_version": "pricing.commerce.v1",
                "order_id": "ORD-9001",
                "vertical": "accommodation",
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 1500000,  # IDR 1,500,000
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "3 nights @ IDR 500,000/night"
                    },
                    {
                        "component_type": "Tax",
                        "amount": 165000,  # 11% tax
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Hotel tax 11%"
                    },
                    {
                        "component_type": "Fee",
                        "amount": 50000,  # Platform fee
                        "currency": "IDR",
                        "dimensions": {},
                        "description": "Booking fee"
                    }
                ],
                "totals": {
                    "customer_total": 1715000,
                    "currency": "IDR"
                },
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "accommodation-service"
            }

        elif scenario == "Hotel 3-Night with Subsidy":
            event = {
                "event_type": "PricingUpdated",
                "schema_version": "pricing.commerce.v1",
                "order_id": "ORD-9002",
                "vertical": "accommodation",
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 1500000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "3 nights base rate"
                    },
                    {
                        "component_type": "Tax",
                        "amount": 165000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Hotel tax 11%"
                    },
                    {
                        "component_type": "Subsidy",
                        "amount": -200000,  # Negative = discount
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Promo HOTEL20",
                        "meta": {"promo_code": "HOTEL20", "subsidy_type": "joint"}
                    },
                    {
                        "component_type": "Fee",
                        "amount": 50000,
                        "currency": "IDR",
                        "dimensions": {},
                        "description": "Booking fee"
                    }
                ],
                "totals": {
                    "customer_total": 1515000,
                    "currency": "IDR"
                },
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "accommodation-service"
            }

        elif scenario == "Flight with Ancillaries":
            event = {
                "event_type": "PricingUpdated",
                "schema_version": "pricing.commerce.v1",
                "order_id": "ORD-9003",
                "vertical": "flight",
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 800000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-001",
                            "pax_id": "A1",
                            "leg_id": "CGK-SIN"
                        },
                        "description": "Adult base fare CGK-SIN"
                    },
                    {
                        "component_type": "Tax",
                        "amount": 150000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-001",
                            "pax_id": "A1",
                            "leg_id": "CGK-SIN"
                        },
                        "description": "Airport taxes + fuel surcharge"
                    },
                    {
                        "component_type": "Fee",
                        "amount": 30000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Baggage 20kg"
                    },
                    {
                        "component_type": "Fee",
                        "amount": 20000,
                        "currency": "IDR",
                        "dimensions": {},
                        "description": "Convenience fee"
                    }
                ],
                "totals": {
                    "customer_total": 1000000,
                    "currency": "IDR"
                },
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "flight-service"
            }

        elif scenario == "Airport Transfer (Basic)":
            event = {
                "event_type": "PricingUpdated",
                "schema_version": "pricing.commerce.v1",
                "order_id": "ORD-9004",
                "vertical": "airport_transfer",
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 250000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Airport transfer CGK to city"
                    },
                    {
                        "component_type": "Markup",
                        "amount": 50000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Platform markup"
                    }
                ],
                "totals": {
                    "customer_total": 300000,
                    "currency": "IDR"
                },
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "airport-transfer-service"
            }

        elif scenario == "B2B Affiliate Accommodation (Real Schema)":
            st.info("🏢 **B2B Affiliate Case**: Selling to reseller partner with shareback commission")
            event = {
                "event_type": "PricingUpdated",
                "schema_version": "pricing.commerce.v1",
                "order_id": "1200496236",
                "vertical": "accommodation",
                "emitted_at": datetime.utcnow().isoformat(),
                "customer_context": {
                    "reseller_type_name": "B2B_AFFILIATE",
                    "reseller_id": "100005361",
                    "reseller_name": "Partner CFD Non IDR - Accommodation - Invoicing"
                },
                "detail_context": {
                    "order_detail_id": "1200917821",
                    "entity_context": {
                        "entity_code": "TNPL"
                    },
                    "fx_context": {
                        "timestamp_fx_rate": "2025-07-31T13:25:21Z",
                        "payment_currency": "IDR",
                        "supply_currency": "IDR",
                        "record_currency": "IDR",
                        "gbv_currency": "IDR",
                        "payment_value": 293223,
                        "supply_to_payment_fx_rate": 1.0,
                        "supply_to_record_fx_rate": 1.0,
                        "payment_to_gbv_fx_rate": 1.0,
                        "source": "Treasury"
                    }
                },
                "components": [
                    {
                        "component_type": "RoomRate",
                        "amount": 246281,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "1200917821"
                        },
                        "meta": {
                            "basis": "supplier_net"
                        },
                        "description": "Supplier net rate for room"
                    },
                    {
                        "component_type": "Markup",
                        "amount": 46942,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "1200917821"
                        },
                        "meta": {
                            "basis": "net_markup",
                            "notes": "B2B reseller price uplift"
                        },
                        "description": "B2B partner markup"
                    }
                ],
                "totals": {
                    "customer_total": 293223,
                    "currency": "IDR"
                }
            }

            # Show financial breakdown in sidebar
            with st.expander("💰 Financial Breakdown", expanded=False):
                st.markdown("""
                **Customer Pays**: IDR 293,223 (by affiliate)
                **Supplier Cost**: IDR 246,281 (RoomRate)
                **Gross Margin**: IDR 46,942 (Markup)
                **Affiliate Commission**: IDR 4,694 (10% of markup)
                **VAT on Commission**: IDR 516 (11% of shareback)
                **Net Revenue**: IDR 41,732 (Markup - Commission - VAT)

                **Entities**:
                - TNPL: Pricing entity
                - GTN: Supplier payable entity (see supplier event)
                - Partner 100005361: B2B Affiliate reseller
                """)

        elif scenario == "Multi-Order-Detail with Contexts (Option A)":
            st.info("🏨 **Multi-Order-Detail Case**: 2 rooms with different entities and FX contexts")
            event = {
                "event_type": "PricingUpdated",
                "schema_version": "pricing.commerce.v1",
                "order_id": "ORD-MULTI-001",
                "vertical": "accommodation",
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "accommodation-pricing-service",
                "customer_context": {
                    "reseller_type_name": "B2C",
                    "reseller_id": None,
                    "reseller_name": None
                },
                "detail_contexts": [
                    {
                        "order_detail_id": "OD-001",
                        "entity_context": {
                            "entity_code": "TNPL"
                        },
                        "fx_context": {
                            "timestamp_fx_rate": datetime.utcnow().isoformat(),
                            "payment_currency": "IDR",
                            "supply_currency": "IDR",
                            "record_currency": "IDR",
                            "gbv_currency": "IDR",
                            "payment_value": 500000,
                            "supply_to_payment_fx_rate": 1.0,
                            "supply_to_record_fx_rate": 1.0,
                            "payment_to_gbv_fx_rate": 1.0,
                            "source": "Treasury"
                        }
                    },
                    {
                        "order_detail_id": "OD-002",
                        "entity_context": {
                            "entity_code": "GTN"
                        },
                        "fx_context": {
                            "timestamp_fx_rate": datetime.utcnow().isoformat(),
                            "payment_currency": "IDR",
                            "supply_currency": "USD",
                            "record_currency": "IDR",
                            "gbv_currency": "IDR",
                            "payment_value": 750000,
                            "supply_to_payment_fx_rate": 15000.0,
                            "supply_to_record_fx_rate": 15000.0,
                            "payment_to_gbv_fx_rate": 1.0,
                            "source": "Treasury"
                        }
                    }
                ],
                "components": [
                    {
                        "component_type": "RoomRate",
                        "amount": 400000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-001"
                        },
                        "description": "Standard Room - 2 nights",
                        "meta": {
                            "basis": "supplier_net",
                            "hotel_id": "HTL-123"
                        }
                    },
                    {
                        "component_type": "Tax",
                        "amount": 50000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-001"
                        },
                        "description": "Hotel Tax (TNPL entity)",
                        "meta": {
                            "tax_type": "hotel_tax",
                            "rate": 0.125
                        }
                    },
                    {
                        "component_type": "Markup",
                        "amount": 50000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-001"
                        },
                        "description": "Platform markup",
                        "meta": {
                            "basis": "net_markup",
                            "rate": 0.125
                        }
                    },
                    {
                        "component_type": "RoomRate",
                        "amount": 600000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-002"
                        },
                        "description": "Deluxe Suite - 3 nights",
                        "meta": {
                            "basis": "supplier_net",
                            "hotel_id": "HTL-456",
                            "original_currency": "USD",
                            "original_amount": 40
                        }
                    },
                    {
                        "component_type": "Tax",
                        "amount": 75000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-002"
                        },
                        "description": "Hotel Tax (GTN entity)",
                        "meta": {
                            "tax_type": "hotel_tax",
                            "rate": 0.125
                        }
                    },
                    {
                        "component_type": "Markup",
                        "amount": 75000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "OD-002"
                        },
                        "description": "Platform markup",
                        "meta": {
                            "basis": "net_markup",
                            "rate": 0.125
                        }
                    }
                ],
                "totals": {
                    "customer_total": 1250000,
                    "currency": "IDR"
                },
                "meta": {
                    "trigger": "order_created",
                    "note": "Multi-order-detail scenario: OD-001 uses TNPL entity with IDR, OD-002 uses GTN entity with USD->IDR conversion"
                }
            }

            # Show breakdown in expander
            with st.expander("💰 Financial Breakdown", expanded=False):
                st.markdown("""
                **Order Detail 1 (OD-001)** - TNPL entity, IDR:
                - RoomRate: IDR 400,000
                - Tax: IDR 50,000
                - Markup: IDR 50,000
                - **Subtotal**: IDR 500,000

                **Order Detail 2 (OD-002)** - GTN entity, USD→IDR:
                - RoomRate: IDR 600,000 (USD 40 @ 15,000)
                - Tax: IDR 75,000
                - Markup: IDR 75,000
                - **Subtotal**: IDR 750,000

                **Total**: IDR 1,250,000

                **Key Features**:
                - Two order_detail_ids with different entity contexts
                - OD-001: TNPL, no FX conversion (IDR→IDR)
                - OD-002: GTN, with FX conversion (USD→IDR at 15,000)
                - Each component matched to its context via order_detail_id
                """)

        else:  # Custom JSON
            event = {}
            st.info("Enter your custom event JSON below")

        # Update cache with generated event
        st.session_state.pricing_json_cache = json.dumps(event, indent=2)

        # Display event JSON (read-only in Form Mode)
        st.markdown("#### Event JSON Preview")
        st.info("💡 **Tip**: To edit this event, switch to 'JSON Mode (Full Control)' using the toggle above")

        event_json_display = st.text_area(
            "Generated event (read-only - use toggle above to switch to JSON Mode)",
            value=st.session_state.pricing_json_cache,
            height=400,
            key="pricing_event_json_display",
            disabled=True
        )

        # Use the cached JSON for emit button
        event_json = st.session_state.pricing_json_cache

    else:  # JSON Mode
        st.info("💡 **JSON Mode**: Edit JSON directly. Form fields are hidden. Switch back to Form Mode to use quick scenarios.")

        # Load from cache or provide template
        if st.session_state.pricing_json_cache:
            initial_json = st.session_state.pricing_json_cache
        else:
            # Default template (producer event - NO enrichment fields)
            template_event = {
                "event_type": "PricingUpdated",
                "schema_version": "pricing.commerce.v1",
                "order_id": "ORD-9001",
                "vertical": "accommodation",
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 1500000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Base fare"
                    }
                ],
                "totals": {
                    "customer_total": 1500000,
                    "currency": "IDR"
                },
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "vertical-service"
            }
            initial_json = json.dumps(template_event, indent=2)

        st.markdown("#### Event JSON")
        event_json = st.text_area(
            "Edit event data (JSON Mode - no form interference)",
            value=initial_json,
            height=500,
            key="pricing_event_json_mode"
        )

        # Update cache on every change
        st.session_state.pricing_json_cache = event_json

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("📤 Emit Event", key="emit_pricing"):
            try:
                event_data = json.loads(event_json)
                result = pipeline.ingest_event(event_data)

                if result.success:
                    st.success(f"✅ {result.message}")
                    st.json(result.details)
                else:
                    st.error(f"❌ {result.message}")
                    st.json(result.details)

            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {str(e)}")


def render_payment_events(pipeline):
    """Render payment event scenarios"""

    st.markdown("### Payment Timeline Events")

    # Mode toggle: Form Mode vs JSON Mode
    edit_mode = st.radio(
        "Edit Mode",
        ["Form Mode (Quick)", "JSON Mode (Full Control)"],
        key="payment_edit_mode",
        horizontal=True
    )

    # Initialize session state for JSON if not exists
    if "payment_json_cache" not in st.session_state:
        st.session_state.payment_json_cache = None

    if edit_mode == "Form Mode (Quick)":
        # Scenario-based payment lifecycle events
        scenario = st.selectbox(
            "Select Scenario",
            [
                "Payment Authorized (B2B Affiliate Deposit)",
                "Payment Captured (B2B Affiliate Deposit)",
                "Payment Authorized (Credit Card)",
                "Payment Captured (Credit Card)",
                "Custom JSON"
            ]
        )

        if scenario == "Payment Authorized (B2B Affiliate Deposit)":
            event = {
                "event_type": "payment.checkout",
                "schema_version": "payment.timeline.v1",
                "order_id": "1200496236",
                "emitted_at": datetime.utcnow().isoformat(),
                "payment": {
                    "status": "Authorized",
                    "payment_id": f"pi_{uuid.uuid4().hex[:8]}",
                    "pg_reference_id": f"pg_{uuid.uuid4().hex[:8]}",
                    "payment_method": {
                        "channel": "AFFILIATE_DEPOSIT",
                        "provider": "AffiliateDeposit",
                        "brand": "INTERNAL"
                    },
                    "currency": "IDR",
                    "authorized_amount": 296223,
                    "authorized_at": datetime.utcnow().isoformat(),
                    "captured_amount": None,
                    "captured_amount_total": 0,
                    "captured_at": None,
                    "instrument": None,
                    "bnpl_plan": None
                },
                "idempotency_key": f"pi_{uuid.uuid4().hex[:8]}:authorized"
            }

        elif scenario == "Payment Captured (B2B Affiliate Deposit)":
            event = {
                "event_type": "PaymentLifecycle",
                "schema_version": "payment.timeline.v1",
                "order_id": "1200496236",
                "emitted_at": datetime.utcnow().isoformat(),
                "payment": {
                    "status": "Captured",
                    "payment_id": f"pi_{uuid.uuid4().hex[:8]}",
                    "pg_reference_id": f"pg_{uuid.uuid4().hex[:8]}",
                    "payment_method": {
                        "channel": "AFFILIATE_DEPOSIT",
                        "provider": "AffiliateDeposit",
                        "brand": "INTERNAL"
                    },
                    "currency": "IDR",
                    "authorized_amount": 296223,
                    "authorized_at": datetime.utcnow().isoformat(),
                    "captured_amount": 296223,
                    "captured_amount_total": 296223,
                    "captured_at": datetime.utcnow().isoformat(),
                    "instrument": None,
                    "bnpl_plan": None
                },
                "idempotency_key": f"pi_{uuid.uuid4().hex[:8]}:captured"
            }

        elif scenario == "Payment Authorized (Credit Card)":
            event = {
                "event_type": "payment.authorized",
                "schema_version": "payment.timeline.v1",
                "order_id": "ORD-9001",
                "emitted_at": datetime.utcnow().isoformat(),
                "payment": {
                    "status": "Authorized",
                    "payment_id": f"pi_{uuid.uuid4().hex[:8]}",
                    "pg_reference_id": f"pg_{uuid.uuid4().hex[:8]}",
                    "payment_method": {
                        "channel": "CC",
                        "provider": "Stripe",
                        "brand": "VISA"
                    },
                    "currency": "IDR",
                    "authorized_amount": 1715000,
                    "authorized_at": datetime.utcnow().isoformat(),
                    "captured_amount": None,
                    "captured_amount_total": 0,
                    "captured_at": None,
                    "instrument": {
                        "type": "CARD",
                        "card": {
                            "last4": "1234",
                            "brand": "VISA",
                            "exp_month": 12,
                            "exp_year": 2026
                        },
                        "display_hint": "VISA ••••1234"
                    },
                    "bnpl_plan": None
                },
                "idempotency_key": f"pi_{uuid.uuid4().hex[:8]}:authorized"
            }

        elif scenario == "Payment Captured (Credit Card)":
            event = {
                "event_type": "payment.captured",
                "schema_version": "payment.timeline.v1",
                "order_id": "ORD-9001",
                "emitted_at": datetime.utcnow().isoformat(),
                "payment": {
                    "status": "Captured",
                    "payment_id": f"pi_{uuid.uuid4().hex[:8]}",
                    "pg_reference_id": f"pg_{uuid.uuid4().hex[:8]}",
                    "payment_method": {
                        "channel": "CC",
                        "provider": "Stripe",
                        "brand": "VISA"
                    },
                    "currency": "IDR",
                    "authorized_amount": 1715000,
                    "authorized_at": datetime.utcnow().isoformat(),
                    "captured_amount": 1715000,
                    "captured_amount_total": 1715000,
                    "captured_at": datetime.utcnow().isoformat(),
                    "instrument": {
                        "type": "CARD",
                        "card": {
                            "last4": "1234",
                            "brand": "VISA",
                            "exp_month": 12,
                            "exp_year": 2026
                        },
                        "display_hint": "VISA ••••1234"
                    },
                    "bnpl_plan": None
                },
                "idempotency_key": f"pi_{uuid.uuid4().hex[:8]}:captured"
            }

        else:  # Custom JSON
            event = {}
            st.info("Enter your custom payment event JSON below")

        # Update cache with generated event
        st.session_state.payment_json_cache = json.dumps(event, indent=2)

        # Display event JSON (read-only in Form Mode)
        st.markdown("#### Event JSON Preview")
        st.info("💡 **Tip**: To edit this event, switch to 'JSON Mode (Full Control)' using the toggle above")

        event_json_display = st.text_area(
            "Generated event (read-only - use toggle above to switch to JSON Mode)",
            value=st.session_state.payment_json_cache,
            height=300,
            key="payment_event_json_display",
            disabled=True
        )

        # Use the cached JSON for emit button
        event_json = st.session_state.payment_json_cache

    else:  # JSON Mode
        st.info("💡 **JSON Mode**: Edit JSON directly. Form fields are hidden. Switch back to Form Mode to use quick fields.")

        # Load from cache or provide template
        if st.session_state.payment_json_cache:
            initial_json = st.session_state.payment_json_cache
        else:
            # Default template (new schema with payment object)
            template_event = {
                "event_type": "payment.captured",
                "schema_version": "payment.timeline.v1",
                "order_id": "ORD-9001",
                "emitted_at": datetime.utcnow().isoformat(),
                "payment": {
                    "status": "Captured",
                    "payment_id": f"pi_{uuid.uuid4().hex[:8]}",
                    "pg_reference_id": f"pg_{uuid.uuid4().hex[:8]}",
                    "payment_method": {
                        "channel": "CC",
                        "provider": "Stripe",
                        "brand": "VISA"
                    },
                    "currency": "IDR",
                    "authorized_amount": 1715000,
                    "authorized_at": datetime.utcnow().isoformat(),
                    "captured_amount": 1715000,
                    "captured_amount_total": 1715000,
                    "captured_at": datetime.utcnow().isoformat(),
                    "instrument": {
                        "type": "CARD",
                        "card": {
                            "last4": "1234",
                            "brand": "VISA",
                            "exp_month": 12,
                            "exp_year": 2026
                        },
                        "display_hint": "VISA ••••1234"
                    },
                    "bnpl_plan": None
                },
                "idempotency_key": f"pi_{uuid.uuid4().hex[:8]}:captured"
            }
            initial_json = json.dumps(template_event, indent=2)

        st.markdown("#### Event JSON")
        event_json = st.text_area(
            "Edit event data (JSON Mode - no form interference)",
            value=initial_json,
            height=400,
            key="payment_event_json_mode"
        )

        # Update cache on every change
        st.session_state.payment_json_cache = event_json

    if st.button("📤 Emit Event", key="emit_payment"):
        try:
            event_data = json.loads(event_json)
            result = pipeline.ingest_event(event_data)

            if result.success:
                st.success(f"✅ {result.message}")
                st.json(result.details)
            else:
                st.error(f"❌ {result.message}")
                st.json(result.details)

        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {str(e)}")


def render_supplier_events(pipeline):
    """Render supplier event scenarios"""

    st.markdown("### Supplier Timeline Events")

    # Mode toggle: Form Mode vs JSON Mode
    edit_mode = st.radio(
        "Edit Mode",
        ["Form Mode (Quick)", "JSON Mode (Full Control)"],
        key="supplier_edit_mode",
        horizontal=True
    )

    # Initialize session state for JSON if not exists
    if "supplier_json_cache" not in st.session_state:
        st.session_state.supplier_json_cache = None

    if edit_mode == "Form Mode (Quick)":
        # Scenario-based supplier lifecycle events
        scenario = st.selectbox(
            "Select Scenario",
            [
                "Supplier Issued (B2B Affiliate with Shareback)",
                "Supplier Issued (Simple)",
                "Custom JSON"
            ]
        )

        if scenario == "Supplier Issued (B2B Affiliate with Shareback)":
            st.info("🏢 **B2B Affiliate**: Supplier issuance with affiliate commission and VAT")
            event = {
                "event_type": "IssuanceSupplierLifecycle",
                "schema_version": "supplier.commerce.v1",
                "order_id": "1200496236",
                "order_detail_id": "1200917821",
                "emitted_at": datetime.utcnow().isoformat(),
                "supplier": {
                    "status": "ISSUED",
                    "supplier_id": "NATIVE",
                    "booking_code": "1859696",
                    "supplier_ref": "1859696",
                    "amount_due": 246281,
                    "currency": "IDR",
                    "fx_context": {
                        "timestamp_fx_rate": datetime.utcnow().isoformat(),
                        "payment_currency": "IDR",
                        "supply_currency": "IDR",
                        "record_currency": "IDR",
                        "gbv_currency": "IDR",
                        "payment_value": 293223,
                        "supply_to_payment_fx_rate": 1,
                        "supply_to_record_fx_rate": 1,
                        "payment_to_gbv_fx_rate": 1,
                        "source": "Treasury"
                    },
                    "entity_context": {
                        "entity_code": "GTN"
                    },
                    "affiliate": {
                        "reseller_id": "100005361",
                        "reseller_name": "Partner CFD Non IDR - Accommodation - Invoicing",
                        "partnerShareback": {
                            "component_type": "AffiliateShareback",
                            "amount": 4694.2,
                            "currency": "IDR",
                            "rate": 0.1,
                            "basis": "markup"
                        },
                        "taxes": [
                            {
                                "type": "VAT",
                                "amount": 516.36,
                                "currency": "IDR",
                                "rate": 0.11,
                                "basis": "shareback"
                            }
                        ]
                    }
                },
                "idempotency_key": "1200496236:1200917821:NATIVE:issued"
            }

        elif scenario == "Supplier Issued (Simple)":
            event = {
                "event_type": "IssuanceSupplierLifecycle",
                "schema_version": "supplier.commerce.v1",
                "order_id": "ORD-9001",
                "order_detail_id": "OD-001",
                "emitted_at": datetime.utcnow().isoformat(),
                "supplier": {
                    "status": "Confirmed",
                    "supplier_id": "AGODA",
                    "booking_code": f"AG-BOOK-{uuid.uuid4().hex[:4].upper()}",
                    "supplier_ref": f"AG-REF-{uuid.uuid4().hex[:4].upper()}",
                    "amount_due": 180.00,
                    "currency": "USD",
                    "fx_context": {
                        "timestamp_fx_rate": datetime.utcnow().isoformat(),
                        "payment_currency": "IDR",
                        "supply_currency": "USD",
                        "record_currency": "IDR",
                        "gbv_currency": "IDR",
                        "payment_value": 2808000,
                        "supply_to_payment_fx_rate": 15600.00,
                        "supply_to_record_fx_rate": 15600.00,
                        "payment_to_gbv_fx_rate": 1.00,
                        "source": "Treasury"
                    },
                    "entity_context": {
                        "entity_code": "TNPL"
                    }
                },
                "idempotency_key": f"ORD-9001:OD-001:AGODA:confirmed"
            }

        else:  # Custom JSON
            event = {}
            st.info("Enter your custom supplier event JSON below")

        # Update cache with generated event
        st.session_state.supplier_json_cache = json.dumps(event, indent=2)

        # Display event JSON (read-only in Form Mode)
        st.markdown("#### Event JSON Preview")
        st.info("💡 **Tip**: To edit this event, switch to 'JSON Mode (Full Control)' using the toggle above")

        event_json_display = st.text_area(
            "Generated event (read-only - use toggle above to switch to JSON Mode)",
            value=st.session_state.supplier_json_cache,
            height=300,
            key="supplier_event_json_display",
            disabled=True
        )

        # Use the cached JSON for emit button
        event_json = st.session_state.supplier_json_cache

    else:  # JSON Mode
        st.info("💡 **JSON Mode**: Edit JSON directly. Form fields are hidden. Switch back to Form Mode to use quick fields.")

        # Load from cache or provide template
        if st.session_state.supplier_json_cache:
            initial_json = st.session_state.supplier_json_cache
        else:
            # Default template (new schema with supplier object and fx_context)
            template_event = {
                "event_type": "IssuanceSupplierLifecycle",
                "schema_version": "supplier.commerce.v1",
                "order_id": "ORD-9001",
                "order_detail_id": "OD-001",
                "emitted_at": datetime.utcnow().isoformat(),
                "supplier": {
                    "status": "Confirmed",
                    "supplier_id": "AGODA",
                    "booking_code": f"AG-BOOK-{uuid.uuid4().hex[:4].upper()}",
                    "supplier_ref": f"AG-REF-{uuid.uuid4().hex[:4].upper()}",
                    "amount_due": 180.00,
                    "currency": "USD",
                    "fx_context": {
                        "timestamp_fx_rate": datetime.utcnow().isoformat(),
                        "payment_currency": "IDR",
                        "supply_currency": "USD",
                        "record_currency": "IDR",
                        "gbv_currency": "IDR",
                        "payment_value": 2808000,
                        "supply_to_payment_fx_rate": 15600.00,
                        "supply_to_record_fx_rate": 15600.00,
                        "payment_to_gbv_fx_rate": 1.00,
                        "source": "Treasury"
                    },
                    "entity_context": {
                        "entity_code": "TNPL"
                    }
                },
                "idempotency_key": f"ORD-9001:OD-001:AGODA:confirmed"
            }
            initial_json = json.dumps(template_event, indent=2)

        st.markdown("#### Event JSON")
        event_json = st.text_area(
            "Edit event data (JSON Mode - no form interference)",
            value=initial_json,
            height=400,
            key="supplier_event_json_mode"
        )

        # Update cache on every change
        st.session_state.supplier_json_cache = event_json

    if st.button("📤 Emit Event", key="emit_supplier"):
        try:
            event_data = json.loads(event_json)
            result = pipeline.ingest_event(event_data)

            if result.success:
                st.success(f"✅ {result.message}")
                st.json(result.details)
            else:
                st.error(f"❌ {result.message}")
                st.json(result.details)

        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {str(e)}")


def render_refund_events(pipeline):
    """Render refund event scenarios"""

    st.markdown("### Refund Events")
    st.markdown("Two types: Timeline events (refund.initiated/closed) and Component events (refund.issued)")

    # Mode toggle: Form Mode vs JSON Mode
    edit_mode = st.radio(
        "Edit Mode",
        ["Form Mode (Quick)", "JSON Mode (Full Control)"],
        key="refund_edit_mode",
        horizontal=True
    )

    # Initialize session state for JSON if not exists
    if "refund_json_cache" not in st.session_state:
        st.session_state.refund_json_cache = None

    if edit_mode == "Form Mode (Quick)":
        # Original form-based UI
        event_category = st.radio(
            "Event Category",
            ["Timeline Events", "Component Events (Refund Issued)"],
            key="refund_category"
        )

        if event_category == "Timeline Events":
            event_type = st.selectbox(
                "Select Event Type",
                ["refund.initiated", "refund.closed"]
            )

            order_id = st.text_input("Order ID", value="ORD-9001", key="refund_order_id")
            refund_id = st.text_input("Refund ID", value="RFD-001")
            refund_timeline_version = st.number_input("Refund Timeline Version", min_value=1, value=1)

            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "schema_version": "refund.timeline.v1",
                "order_id": order_id,
                "refund_id": refund_id,
                "refund_timeline_version": refund_timeline_version,
                "refund_amount": 500000,
                "currency": "IDR",
                "refund_reason": "Customer requested cancellation",
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "refund-service"
            }

        else:  # Component Events
            st.markdown("**Refund Issued**: Creates refund components with `is_refund: true` and lineage to original")
            st.info("⚠️ **Important**: Refund components must have `is_refund: true` and `refund_of_component_semantic_id` pointing to the original component")

            order_id = st.text_input("Order ID", value="1200496236", key="refund_issued_order_id")
            refund_id = st.text_input("Refund ID", value="RFD-001", key="refund_issued_refund_id")

            event = {
                "event_type": "refund.issued",
                "schema_version": "refund.components.v1",
                "order_id": order_id,
                "refund_id": refund_id,
                "components": [
                    {
                        "is_refund": True,
                        "component_type": "RoomRate",
                        "amount": -100000,  # Negative amount (refund reverses the charge)
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "1200917821"
                        },
                        "description": "Partial refund - 1 night",
                        "refund_of_component_semantic_id": "cs-1200496236-1200917821-RoomRate"
                    }
                ],
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "refund-service"
            }

        # Update cache with generated event
        st.session_state.refund_json_cache = json.dumps(event, indent=2)

        # Display event JSON (read-only in Form Mode)
        st.markdown("#### Event JSON Preview")
        st.info("💡 **Tip**: To edit this event, switch to 'JSON Mode (Full Control)' using the toggle above")

        event_json_display = st.text_area(
            "Generated event (read-only - use toggle above to switch to JSON Mode)",
            value=st.session_state.refund_json_cache,
            height=400,
            key="refund_event_json_display",
            disabled=True
        )

        # Use the cached JSON for emit button
        event_json = st.session_state.refund_json_cache

    else:  # JSON Mode
        st.info("💡 **JSON Mode**: Edit JSON directly. Form fields are hidden. Switch back to Form Mode to use quick fields.")

        # Load from cache or provide template
        if st.session_state.refund_json_cache:
            initial_json = st.session_state.refund_json_cache
        else:
            # Default template (refund.issued with is_refund field)
            template_event = {
                "event_type": "refund.issued",
                "schema_version": "refund.components.v1",
                "order_id": "1200496236",
                "refund_id": "RFD-001",
                "components": [
                    {
                        "is_refund": True,
                        "component_type": "RoomRate",
                        "amount": -100000,
                        "currency": "IDR",
                        "dimensions": {
                            "order_detail_id": "1200917821"
                        },
                        "description": "Partial refund - 1 night",
                        "refund_of_component_semantic_id": "cs-1200496236-1200917821-RoomRate"
                    }
                ],
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "refund-service"
            }
            initial_json = json.dumps(template_event, indent=2)

        st.markdown("#### Event JSON")
        event_json = st.text_area(
            "Edit event data (JSON Mode - no form interference)",
            value=initial_json,
            height=500,
            key="refund_event_json_mode"
        )

        # Update cache on every change
        st.session_state.refund_json_cache = event_json

    if st.button("📤 Emit Event", key="emit_refund"):
        try:
            event_data = json.loads(event_json)
            result = pipeline.ingest_event(event_data)

            if result.success:
                st.success(f"✅ {result.message}")
                st.json(result.details)
            else:
                st.error(f"❌ {result.message}")
                st.json(result.details)

        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {str(e)}")
