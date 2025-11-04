"""
Stress Tests UI component
Test edge cases like out-of-order events, duplicates, and idempotency
"""
import streamlit as st
import uuid
from datetime import datetime
import json
from src.ingestion.pipeline import IngestionPipeline


def render_stress_tests(db):
    """Render the Stress Tests page"""

    st.markdown("## 🧪 Stress Tests")
    st.markdown("Test edge cases and validate system behavior")

    pipeline = IngestionPipeline(db)

    # Test scenarios
    test_scenario = st.selectbox(
        "Select Test Scenario",
        [
            "Out-of-Order Events",
            "Duplicate Event (Idempotency)",
            "Invalid Event Schema",
            "Missing Required Fields",
            "Negative Amount Validation",
            "Version Gap Detection"
        ]
    )

    if test_scenario == "Out-of-Order Events":
        render_out_of_order_test(pipeline)

    elif test_scenario == "Duplicate Event (Idempotency)":
        render_duplicate_test(pipeline)

    elif test_scenario == "Invalid Event Schema":
        render_invalid_schema_test(pipeline)

    elif test_scenario == "Missing Required Fields":
        render_missing_fields_test(pipeline)

    elif test_scenario == "Negative Amount Validation":
        render_negative_amount_test(pipeline)

    elif test_scenario == "Version Gap Detection":
        render_version_gap_test(pipeline)


def render_out_of_order_test(pipeline):
    """Test out-of-order event processing"""

    st.markdown("### Out-of-Order Events Test")
    st.markdown("""
    This test validates that the system can handle events arriving out of chronological order.
    We'll emit version 3 before version 2, and verify both are stored correctly.
    """)

    order_id = st.text_input("Order ID", value=f"ORD-OOO-{uuid.uuid4().hex[:4]}")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Event 1: Version 3 (Later)")
        if st.button("Emit Version 3 First"):
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "pricing.updated",
                "schema_version": "pricing.commerce.v1",
                "order_id": order_id,
                "pricing_snapshot_id": str(uuid.uuid4()),
                "version": 3,
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 100000000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Version 3 - after repricing"
                    }
                ],
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "test-service"
            }

            result = pipeline.ingest_event(event)
            if result.success:
                st.success(f"✅ {result.message}")
            else:
                st.error(f"❌ {result.message}")

    with col2:
        st.markdown("#### Event 2: Version 2 (Earlier)")
        if st.button("Emit Version 2 Second"):
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "pricing.updated",
                "schema_version": "pricing.commerce.v1",
                "order_id": order_id,
                "pricing_snapshot_id": str(uuid.uuid4()),
                "version": 2,
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 90000000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Version 2 - first repricing"
                    }
                ],
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "test-service"
            }

            result = pipeline.ingest_event(event)
            if result.success:
                st.success(f"✅ {result.message}")
            else:
                st.error(f"❌ {result.message}")

    st.markdown("**Expected Behavior**: Both versions stored, latest view shows v3")


def render_duplicate_test(pipeline):
    """Test duplicate event handling"""

    st.markdown("### Duplicate Event (Idempotency) Test")
    st.markdown("""
    This test validates idempotency. If the same event_id is sent twice,
    the system should handle it gracefully (either skip or reject).
    """)

    event_id = st.text_input("Event ID (keep same for duplicate)", value=f"EVT-{uuid.uuid4().hex[:8]}")
    order_id = st.text_input("Order ID", value=f"ORD-DUP-{uuid.uuid4().hex[:4]}", key="dup_order")

    event = {
        "event_id": event_id,
        "event_type": "pricing.updated",
        "schema_version": "pricing.commerce.v1",
        "order_id": order_id,
        "pricing_snapshot_id": str(uuid.uuid4()),
        "version": 1,
        "components": [
            {
                "component_type": "BaseFare",
                "amount": 50000000,
                "currency": "IDR",
                "dimensions": {"order_detail_id": "OD-001"},
                "description": "Test component"
            }
        ],
        "emitted_at": datetime.utcnow().isoformat(),
        "emitter_service": "test-service"
    }

    if st.button("Emit Event (Click Multiple Times)"):
        result = pipeline.ingest_event(event)
        if result.success:
            st.success(f"✅ {result.message}")
            st.json(result.details)
        else:
            st.error(f"❌ {result.message}")
            st.json(result.details)

    st.info("**Note**: Currently, duplicate detection is not enforced. In production, use event_id uniqueness constraint or check before insert.")


def render_invalid_schema_test(pipeline):
    """Test invalid schema handling"""

    st.markdown("### Invalid Event Schema Test")
    st.markdown("Send event with invalid component_type or missing fields")

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "pricing.updated",
        "schema_version": "pricing.commerce.v1",
        "order_id": f"ORD-INV-{uuid.uuid4().hex[:4]}",
        "pricing_snapshot_id": str(uuid.uuid4()),
        "version": 1,
        "components": [
            {
                "component_type": "InvalidType",  # Invalid enum value
                "amount": 50000000,
                "currency": "IDR",
                "dimensions": {},
                "description": "Invalid component type"
            }
        ],
        "emitted_at": datetime.utcnow().isoformat(),
        "emitter_service": "test-service"
    }

    st.markdown("#### Event JSON (with invalid component_type)")
    st.json(event)

    if st.button("Emit Invalid Event"):
        result = pipeline.ingest_event(event)
        if result.success:
            st.success(f"✅ {result.message}")
        else:
            st.error(f"❌ {result.message} - Event sent to DLQ")
            st.json(result.details)

    st.markdown("**Expected Behavior**: Validation fails, event sent to DLQ")


def render_missing_fields_test(pipeline):
    """Test missing required fields"""

    st.markdown("### Missing Required Fields Test")

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "pricing.updated",
        # Missing schema_version
        "order_id": f"ORD-MIS-{uuid.uuid4().hex[:4]}",
        # Missing pricing_snapshot_id
        "version": 1,
        "components": [
            {
                "component_type": "BaseFare",
                "amount": 50000000,
                "currency": "IDR",
                "dimensions": {}
            }
        ],
        "emitted_at": datetime.utcnow().isoformat(),
        "emitter_service": "test-service"
    }

    st.markdown("#### Event JSON (missing schema_version and pricing_snapshot_id)")
    st.json(event)

    if st.button("Emit Incomplete Event"):
        result = pipeline.ingest_event(event)
        if result.success:
            st.success(f"✅ {result.message}")
        else:
            st.error(f"❌ {result.message} - Event sent to DLQ")
            st.json(result.details)

    st.markdown("**Expected Behavior**: Pydantic validation fails, event sent to DLQ")


def render_negative_amount_test(pipeline):
    """Test negative amount validation"""

    st.markdown("### Negative Amount Validation Test")
    st.markdown("""
    Negative amounts are valid for:
    - Subsidy, Discount (original components)
    - Refund (refund components)

    But should be validated in context.
    """)

    test_type = st.radio("Test Type", ["Valid Negative (Subsidy)", "Valid Negative (Refund)"])

    if test_type == "Valid Negative (Subsidy)":
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "pricing.updated",
            "schema_version": "pricing.commerce.v1",
            "order_id": f"ORD-NEG-{uuid.uuid4().hex[:4]}",
            "pricing_snapshot_id": str(uuid.uuid4()),
            "version": 1,
            "components": [
                {
                    "component_type": "BaseFare",
                    "amount": 100000000,
                    "currency": "IDR",
                    "dimensions": {"order_detail_id": "OD-001"},
                    "description": "Base fare"
                },
                {
                    "component_type": "Subsidy",
                    "amount": -20000000,  # Valid negative
                    "currency": "IDR",
                    "dimensions": {"order_detail_id": "OD-001"},
                    "description": "Promo discount"
                }
            ],
            "emitted_at": datetime.utcnow().isoformat(),
            "emitter_service": "test-service"
        }
    else:  # Refund
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "refund.issued",
            "schema_version": "refund.components.v1",
            "order_id": f"ORD-NEG-{uuid.uuid4().hex[:4]}",
            "refund_id": "RFD-001",
            "pricing_snapshot_id": str(uuid.uuid4()),
            "version": 2,
            "components": [
                {
                    "component_type": "Refund",
                    "amount": -50000000,  # Valid negative refund
                    "currency": "IDR",
                    "dimensions": {"order_detail_id": "OD-001"},
                    "description": "Refund amount",
                    "refund_of_component_semantic_id": "cs-ORD-9001-OD-OD-001-BaseFare"
                }
            ],
            "emitted_at": datetime.utcnow().isoformat(),
            "emitter_service": "refund-service"
        }

    st.json(event)

    if st.button("Emit Event with Negative Amount"):
        result = pipeline.ingest_event(event)
        if result.success:
            st.success(f"✅ {result.message}")
            st.json(result.details)
        else:
            st.error(f"❌ {result.message}")
            st.json(result.details)

    st.markdown("**Expected Behavior**: Valid negative amounts accepted")


def render_version_gap_test(pipeline):
    """Test version gap detection"""

    st.markdown("### Version Gap Detection Test")
    st.markdown("""
    Emit version 1, then version 3 (skipping version 2).
    System should accept both, but could flag the gap for monitoring.
    """)

    order_id = st.text_input("Order ID", value=f"ORD-GAP-{uuid.uuid4().hex[:4]}", key="gap_order")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Step 1: Version 1")
        if st.button("Emit Version 1"):
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "pricing.updated",
                "schema_version": "pricing.commerce.v1",
                "order_id": order_id,
                "pricing_snapshot_id": str(uuid.uuid4()),
                "version": 1,
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 80000000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Version 1"
                    }
                ],
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "test-service"
            }

            result = pipeline.ingest_event(event)
            if result.success:
                st.success(f"✅ {result.message}")
            else:
                st.error(f"❌ {result.message}")

    with col2:
        st.markdown("#### Step 2: Version 3 (Skip 2)")
        if st.button("Emit Version 3"):
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "pricing.updated",
                "schema_version": "pricing.commerce.v1",
                "order_id": order_id,
                "pricing_snapshot_id": str(uuid.uuid4()),
                "version": 3,  # Skipped version 2
                "components": [
                    {
                        "component_type": "BaseFare",
                        "amount": 100000000,
                        "currency": "IDR",
                        "dimensions": {"order_detail_id": "OD-001"},
                        "description": "Version 3"
                    }
                ],
                "emitted_at": datetime.utcnow().isoformat(),
                "emitter_service": "test-service"
            }

            result = pipeline.ingest_event(event)
            if result.success:
                st.success(f"✅ {result.message}")
            else:
                st.error(f"❌ {result.message}")

    st.markdown("**Expected Behavior**: Both accepted, but gap could be logged for investigation")
    st.info("**Enhancement Opportunity**: Add monitoring to detect and alert on version gaps")
