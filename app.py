"""
Unified Pricing Read Layer Prototype
Interactive Streamlit application demonstrating event ingestion and data flow
"""
import streamlit as st
from src.storage.database import Database

# Page configuration
st.set_page_config(
    page_title="UPRL Prototype",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database connection in session state
if 'db' not in st.session_state:
    db = Database()
    db.connect()
    db.initialize_schema()
    st.session_state.db = db

# Custom CSS for better styling
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #58a6ff;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #8b949e;
        margin-bottom: 2rem;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #238636;
        color: white;
        margin: 1rem 0;
    }
    .error-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #da3633;
        color: white;
        margin: 1rem 0;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #1f6feb;
        color: white;
        margin: 1rem 0;
    }
    .component-card {
        border: 1px solid #30363d;
        border-radius: 0.5rem;
        padding: 1rem;
        margin: 0.5rem 0;
        background-color: #0d1117;
    }
    .track-customer { border-left: 4px solid #58a6ff; }
    .track-payment { border-left: 4px solid #ffdd86; }
    .track-supplier { border-left: 4px solid #8bffb0; }
    .track-refund { border-left: 4px solid #ff9ead; }
    </style>
""", unsafe_allow_html=True)

# Main header
st.markdown('<div class="main-header">💰 Unified Pricing Read Layer</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Interactive Prototype - Event Flow Visualization</div>', unsafe_allow_html=True)

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Select Page",
    [
        "🏠 Home",
        "🎮 Producer Playground",
        "⚙️ Ingestion Console",
        "🔍 Order Explorer",
        "🧪 Stress Tests",
        "⚙️ Settings"
    ]
)

# Home page
if page == "🏠 Home":
    st.markdown("## Welcome to the UPRL Prototype")

    st.markdown("""
    This interactive prototype demonstrates the **Unified Pricing Read Layer** architecture,
    showing how producer events flow through Order Core ingestion into normalized storage.

    ### Key Features

    - **🎮 Producer Playground**: Emit sample events from verticals, payment, and refund services
    - **⚙️ Ingestion Console**: Watch real-time validation, ID generation, and normalization
    - **🔍 Order Explorer**: Browse order pricing breakdowns, timelines, and component lineage
    - **🧪 Stress Tests**: Test edge cases like out-of-order events, duplicates, and idempotency

    ### Architecture Overview

    ```
    Producers (Vertical/Payment/Refund)
           ↓ emit standardized events
    Order Core Ingestion Pipeline
           ├─ Schema validation (Pydantic)
           ├─ Dual ID generation (semantic + instance)
           ├─ Version key assignment
           └─ Normalization
              ↓
    Unified Pricing Read Layer
           ├─ Hot Store (latest projections)
           └─ Cold Store (append-only audit trail)
    ```

    ### Core Concepts

    **1. Dual ID Strategy**
    - **Semantic ID**: Stable logical identity (e.g., `cs-ORD-9001-OD-001-BaseFare`)
    - **Instance ID**: Unique per snapshot (e.g., `ci_f0a1d2c3b4a50001`)

    **2. Version Families** (Independent Evolution)
    - Pricing Snapshot Version (`pricing_snapshot_id` + `version`)
    - Payment Timeline Version (`timeline_version`)
    - Supplier Timeline Version (`supplier_timeline_version`)
    - Refund Timeline Version (`refund_timeline_version`)

    **3. Append-Only Architecture**
    - All changes create new versions
    - History is immutable
    - Refunds create new components with lineage pointers

    ### Get Started

    👉 Navigate to **Producer Playground** to emit your first event!
    """)

    # Quick stats
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        orders = st.session_state.db.get_all_orders()
        st.metric("Total Orders", len(orders))

    with col2:
        cursor = st.session_state.db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM pricing_components_fact")
        component_count = cursor.fetchone()[0]
        st.metric("Total Components", component_count)

    with col3:
        cursor.execute("SELECT COUNT(*) FROM payment_timeline")
        payment_count = cursor.fetchone()[0]
        st.metric("Payment Events", payment_count)

    with col4:
        cursor.execute("SELECT COUNT(*) FROM dlq")
        dlq_count = cursor.fetchone()[0]
        st.metric("DLQ Entries", dlq_count)

elif page == "🎮 Producer Playground":
    from src.ui.producer_playground import render_producer_playground
    render_producer_playground(st.session_state.db)

elif page == "⚙️ Ingestion Console":
    st.markdown("## ⚙️ Ingestion Console")
    st.markdown("View DLQ entries and ingestion statistics")

    # DLQ viewer
    cursor = st.session_state.db.conn.cursor()
    cursor.execute("SELECT * FROM dlq ORDER BY failed_at DESC LIMIT 50")
    dlq_entries = cursor.fetchall()

    if dlq_entries:
        st.warning(f"Found {len(dlq_entries)} failed events in DLQ")

        for entry in dlq_entries:
            with st.expander(f"❌ {entry['event_type']} - {entry['error_type']} ({entry['failed_at']})"):
                st.markdown(f"**DLQ ID**: `{entry['dlq_id']}`")
                st.markdown(f"**Event ID**: `{entry['event_id']}`")
                st.markdown(f"**Order ID**: `{entry['order_id'] or 'N/A'}`")
                st.markdown(f"**Error Type**: `{entry['error_type']}`")
                st.markdown(f"**Error Message**: {entry['error_message']}")
                st.markdown("**Raw Event**:")
                st.json(entry['raw_event'])

                if st.button(f"Retry Event", key=f"retry_{entry['dlq_id']}"):
                    st.info("Retry functionality would be implemented here")
    else:
        st.success("✅ No failed events in DLQ")

    # Ingestion statistics
    st.markdown("### Ingestion Statistics")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        cursor.execute("SELECT COUNT(DISTINCT order_id) FROM pricing_components_fact")
        order_count = cursor.fetchone()[0]
        st.metric("Orders Processed", order_count)

    with col2:
        cursor.execute("SELECT COUNT(*) FROM pricing_components_fact")
        component_count = cursor.fetchone()[0]
        st.metric("Components Ingested", component_count)

    with col3:
        cursor.execute("SELECT COUNT(*) FROM payment_timeline")
        payment_count = cursor.fetchone()[0]
        st.metric("Payment Events", payment_count)

    with col4:
        cursor.execute("SELECT COUNT(*) FROM dlq")
        dlq_count = cursor.fetchone()[0]
        st.metric("DLQ Entries", dlq_count)

elif page == "🔍 Order Explorer":
    from src.ui.order_explorer import render_order_explorer
    render_order_explorer(st.session_state.db)

elif page == "🧪 Stress Tests":
    from src.ui.stress_tests import render_stress_tests
    render_stress_tests(st.session_state.db)

elif page == "⚙️ Settings":
    st.markdown("## Settings")

    st.markdown("### Database")
    st.info(f"Database location: `{st.session_state.db.db_path}`")

    if st.button("🗑️ Clear All Data"):
        st.session_state.db.close()
        import os
        if os.path.exists(st.session_state.db.db_path):
            os.remove(st.session_state.db.db_path)

        # Reinitialize
        db = Database()
        db.connect()
        db.initialize_schema()
        st.session_state.db = db
        st.success("Database cleared and reinitialized!")
        st.rerun()

    st.markdown("### About")
    st.markdown("""
    **Unified Pricing Read Layer Prototype**
    Version: 1.0.0
    Purpose: Educational demonstration of event-driven pricing architecture

    Built with:
    - Streamlit (UI)
    - SQLite (Storage)
    - Pydantic (Validation)
    - Python 3.9+
    """)
