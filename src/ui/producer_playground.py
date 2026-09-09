"""
Producer Playground UI component
Allows users to emit sample events from different producers
"""
import streamlit as st
import json
from datetime import datetime, timezone
from src.ingestion.pipeline import IngestionPipeline
from src.ui.json_loader import load_json_files_from_directory, get_sample_events_directory, get_available_topics
from src.ui.json_editor import render_json_editor_with_hints, render_json_editor


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


def render_event_tab(
    pipeline,
    title: str,
    description: str,
    category_dir: str,
    cache_key: str,
    emit_button_key: str,
    default_template: dict = None
):
    """
    Generic renderer for event tabs with dynamic JSON loading.

    Args:
        pipeline: IngestionPipeline instance
        title: Tab title (e.g., "Pricing Updated Events")
        description: Tab description
        category_dir: Directory name under sample_events/ (e.g., "pricing_events")
        cache_key: Session state cache key for JSON content
        emit_button_key: Unique key for emit button
        default_template: Default JSON template if no files are loaded
    """
    st.markdown(f"### {title}")
    st.markdown(description)

    # Mode toggle: Form Mode vs JSON Mode
    edit_mode = st.radio(
        "Edit Mode",
        ["Form Mode (Quick)", "JSON Mode (Full Control)"],
        key=f"{cache_key}_edit_mode",
        horizontal=True
    )

    # Initialize session state keys
    if cache_key not in st.session_state:
        st.session_state[cache_key] = None

    last_scenario_key = f"{cache_key}_last_scenario"
    if last_scenario_key not in st.session_state:
        st.session_state[last_scenario_key] = None

    if edit_mode == "Form Mode (Quick)":
        # Get available topics for this category
        topics = get_available_topics(category_dir)

        # Topic dropdown
        topic = None
        if topics:
            topic = st.selectbox(
                "Select Topic",
                topics,
                key=f"{cache_key}_topic",
                help="Select a topic to filter scenarios"
            )

        # Load JSON files from directory (filtered by topic if selected)
        sample_dir = get_sample_events_directory(category_dir)
        json_files = load_json_files_from_directory(sample_dir, topic=topic)

        # Create dropdown options
        dropdown_options = ["Custom JSON"]  # Always have custom option
        if json_files:
            dropdown_options = [display_name for display_name, _, _ in json_files] + ["Custom JSON"]

        scenario = st.selectbox(
            "Select Scenario",
            dropdown_options,
            key=f"{cache_key}_scenario"
        )

        # Always update cache when scenario changes (fix: force update on every selection)
        scenario_changed = st.session_state[last_scenario_key] != scenario
        if scenario_changed:
            # Load selected JSON
            if scenario == "Custom JSON":
                event = default_template if default_template else {}
                if not event:
                    st.info("Enter your custom event JSON below")
            else:
                # Find the selected JSON file
                selected_json = next((content for display_name, _, content in json_files if display_name == scenario), None)
                if selected_json:
                    event = selected_json.copy()
                    # Update timestamp if it exists
                    if "emitted_at" in event:
                        event["emitted_at"] = datetime.now(timezone.utc).isoformat()
                else:
                    event = {}
                    st.warning(f"Could not load selected scenario: {scenario}")

            # Update cache with generated event
            json_str = json.dumps(event, indent=2)
            st.session_state[cache_key] = json_str
            # Delete old widget state to force recreation with new value
            widget_key = f"{cache_key}_json_display"
            if widget_key in st.session_state:
                del st.session_state[widget_key]
            st.session_state[last_scenario_key] = scenario

        # Display event JSON (read-only in Form Mode)
        st.markdown("#### Event JSON Preview")
        st.info("💡 **Tip**: To edit this event, switch to 'JSON Mode (Full Control)' using the toggle above")

        # Use dynamic key that includes scenario name to force re-render
        display_key = f"{cache_key}_json_display_{scenario.replace(' ', '_')}"

        event_json_display = render_json_editor(
            label="Generated event (read-only - use toggle above to switch to JSON Mode)",
            value=st.session_state[cache_key] if st.session_state[cache_key] else "{}",
            height=400,
            key=display_key,
            show_path=True,
            show_validation=True,
            read_only=True
        )

        # Use the cached JSON for emit button
        event_json = st.session_state[cache_key]

    else:  # JSON Mode
        st.info("💡 **JSON Mode**: Edit JSON directly. Switch back to Form Mode to use quick scenarios.")

        # Load from cache or provide template
        if st.session_state[cache_key]:
            initial_json = st.session_state[cache_key]
        else:
            # Use provided template or empty dict
            template_event = default_template if default_template else {}
            initial_json = json.dumps(template_event, indent=2)

        st.markdown("#### Event JSON")
        event_json = render_json_editor_with_hints(
            label="Edit event data (JSON Mode - no form interference)",
            value=initial_json,
            height=500,
            key=f"{cache_key}_json_mode",
            read_only=False
        )

        # Update cache with current value from editor
        st.session_state[cache_key] = event_json

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("📤 Emit Event", key=emit_button_key):
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


def render_pricing_events(pipeline):
    """Render pricing event scenarios"""

    default_template = {
        "event_type": "PricingUpdated",
        "schema_version": "pricing.commerce.v1",
        "order_id": "ORD-NEW",
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
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "emitter_service": "vertical-service"
    }

    render_event_tab(
        pipeline=pipeline,
        title="Pricing Updated Events",
        description="Events emitted by vertical services when pricing changes",
        category_dir="pricing_events",
        cache_key="pricing_json_cache",
        emit_button_key="emit_pricing",
        default_template=default_template
    )


def render_payment_events(pipeline):
    """Render payment event scenarios"""

    default_template = {
        "event_type": "payment.captured",
        "schema_version": "payment.timeline.v1",
        "order_id": "ORD-NEW",
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "payment": {
            "status": "Captured",
            "payment_id": "pi_new123",
            "pg_reference_id": "pg_new123",
            "payment_method": {
                "channel": "CC",
                "provider": "Stripe",
                "brand": "VISA"
            },
            "currency": "IDR",
            "authorized_amount": 1715000,
            "authorized_at": datetime.now(timezone.utc).isoformat(),
            "captured_amount": 1715000,
            "captured_amount_total": 1715000,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "instrument": None,
            "bnpl_plan": None
        },
        "idempotency_key": "pi_new123:captured"
    }

    render_event_tab(
        pipeline=pipeline,
        title="Payment Timeline Events",
        description="Events emitted by payment service during payment lifecycle",
        category_dir="payment_timeline",
        cache_key="payment_json_cache",
        emit_button_key="emit_payment",
        default_template=default_template
    )


def render_supplier_events(pipeline):
    """Render supplier event scenarios"""

    default_template = {
        "event_type": "IssuanceSupplierLifecycle",
        "schema_version": "supplier.timeline.v1",
        "order_id": "ORD-NEW",
        "order_detail_id": "OD-001",
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "supplier": {
            "status": "Confirmed",
            "supplier_id": "AGODA",
            "booking_code": "AG-NEW-001",
            "supplier_ref": "AG-REF-001",
            "amount_due": 180.00,
            "currency": "USD",
            "fx_context": {
                "timestamp_fx_rate": datetime.now(timezone.utc).isoformat(),
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
        "idempotency_key": "ORD-NEW:OD-001:AGODA:confirmed"
    }

    render_event_tab(
        pipeline=pipeline,
        title="Supplier Timeline Events",
        description="Events emitted by supplier service for bookings and payables",
        category_dir="supplier_and_payable_event",
        cache_key="supplier_json_cache",
        emit_button_key="emit_supplier",
        default_template=default_template
    )



def render_refund_events(pipeline):
    """Render refund event scenarios"""

    st.markdown("### Refund Events")
    st.markdown("Two types: Timeline events (refund.initiated/closed) and Component events (refund.issued)")

    # Sub-tabs for refund timeline vs refund components
    refund_tab1, refund_tab2 = st.tabs([
        "📅 Refund Timeline",
        "🧩 Refund Components"
    ])

    with refund_tab1:
        default_template = {
            "event_type": "refund.initiated",
            "schema_version": "refund.timeline.v1",
            "order_id": "ORD-NEW",
            "refund_id": "RFD-001",
            "status": "INITIATED",  # INITIATED, PROCESSING, ISSUED, CLOSED, FAILED
            "refund_amount": 500000,
            "currency": "IDR",
            "refund_reason": "Customer requested cancellation",
            "emitted_at": datetime.now(timezone.utc).isoformat(),
            "emitter_service": "refund-service"
        }

        render_event_tab(
            pipeline=pipeline,
            title="Refund Timeline Events",
            description="Events tracking refund lifecycle (initiated, closed)",
            category_dir="refund_timeline",
            cache_key="refund_timeline_json_cache",
            emit_button_key="emit_refund_timeline",
            default_template=default_template
        )

    with refund_tab2:
        default_template = {
            "event_type": "refund.issued",
            "schema_version": "refund.components.v1",
            "order_id": "ORD-NEW",
            "refund_id": "RFD-001",
            "components": [
                {
                    "is_refund": True,
                    "component_type": "RoomRate",
                    "amount": -100000,
                    "currency": "IDR",
                    "dimensions": {
                        "order_detail_id": "OD-001"
                    },
                    "description": "Partial refund - 1 night",
                    "refund_of_component_semantic_id": "cs-ORD-NEW-OD-001-RoomRate"
                }
            ],
            "emitted_at": datetime.now(timezone.utc).isoformat(),
            "emitter_service": "refund-service"
        }

        render_event_tab(
            pipeline=pipeline,
            title="Refund Component Events",
            description="Events creating refund components with lineage (refund.issued)",
            category_dir="refund_components",
            cache_key="refund_components_json_cache",
            emit_button_key="emit_refund_components",
            default_template=default_template
        )
