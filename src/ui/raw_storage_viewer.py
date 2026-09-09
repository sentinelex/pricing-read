"""
Raw Data Storage Viewer
Shows raw table contents after event ingestion (not computed/aggregated views)
"""
import streamlit as st
import pandas as pd
import json
from typing import Optional


def render_raw_storage_viewer(db):
    """
    Render Raw Data Storage visualization section.
    Shows raw table contents to visualize what happens to each table after an event.
    """
    st.markdown("## 🗄️ Raw Data Storage Viewer")
    st.markdown("""
    This section shows **raw table contents** after event ingestion. Unlike Order Explorer which shows
    computed/aggregated views, this displays the actual rows stored in each table with all columns visible.

    **Use this to:**
    - Understand what gets written to storage after each event
    - Inspect enrichment fields (version keys, snapshot IDs)
    - Debug data flow issues
    - Validate append-only architecture (no updates, only inserts)
    """)

    # Order selector
    st.markdown("### 🔍 Filter by Order")
    col1, col2 = st.columns([3, 1])

    with col1:
        all_orders = db.get_all_orders()  # Returns list of order_id strings
        if not all_orders:
            st.warning("No orders in database. Go to Producer Playground to emit events.")
            return

        order_options = ["All Orders"] + all_orders  # all_orders is already a list of strings
        selected_order = st.selectbox("Select Order ID", order_options)

    with col2:
        if st.button("🔄 Refresh"):
            st.rerun()

    # Table selector tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "💰 Pricing Components",
        "💳 Payment Timeline",
        "🏢 Supplier Timeline",
        "📊 Supplier Payables",
        "💸 Refund Timeline",
        "❌ DLQ (Failed Events)"
    ])

    # Tab 1: Pricing Components Fact
    with tab1:
        render_pricing_components_table(db, selected_order)

    # Tab 2: Payment Timeline
    with tab2:
        render_payment_timeline_table(db, selected_order)

    # Tab 3: Supplier Timeline
    with tab3:
        render_supplier_timeline_table(db, selected_order)

    # Tab 4: Supplier Payable Lines
    with tab4:
        render_supplier_payables_table(db, selected_order)

    # Tab 5: Refund Timeline
    with tab5:
        render_refund_timeline_table(db, selected_order)

    # Tab 6: DLQ
    with tab6:
        render_dlq_table(db, selected_order)


def render_pricing_components_table(db, selected_order: str):
    """Render pricing_components_fact table with all columns."""
    st.markdown("#### 💰 Pricing Components Fact Table")
    st.markdown("""
    **Purpose**: Stores customer-facing pricing components with dual ID system.

    **Key Fields**:
    - `component_semantic_id`: Stable logical identity (query latest by this)
    - `component_instance_id`: Unique per snapshot occurrence
    - `pricing_snapshot_id` + `version`: Version family for repricing events
    - `is_refund`: Flag indicating if this is a refund component
    - `refund_of_component_semantic_id`: Lineage pointer (for refunds only)
    """)

    cursor = db.conn.cursor()

    if selected_order == "All Orders":
        cursor.execute("""
            SELECT * FROM pricing_components_fact
            ORDER BY order_id, version, component_type
        """)
    else:
        cursor.execute("""
            SELECT * FROM pricing_components_fact
            WHERE order_id = ?
            ORDER BY version, component_type
        """, (selected_order,))

    rows = cursor.fetchall()

    if not rows:
        st.info("No pricing components in storage.")
        return

    # Convert to DataFrame with proper column names
    columns = [desc[0] for desc in cursor.description]
    df = pd.DataFrame(rows, columns=columns)

    # Add row count
    st.caption(f"**Total Rows**: {len(df)}")

    # Expandable JSON columns
    st.markdown("##### 📋 Raw Data (Scroll horizontally to see all columns)")

    # Format JSON columns for better readability
    display_df = df.copy()
    if 'dimensions' in display_df.columns:
        display_df['dimensions'] = display_df['dimensions'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )
    if 'metadata' in display_df.columns:
        display_df['metadata'] = display_df['metadata'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )

    # Display with scroll
    st.dataframe(display_df, use_container_width=True, height=400)

    # Highlight version = -1 or is_refund
    refund_count = len(df[df['is_refund'] == 1]) if 'is_refund' in df.columns else 0
    if refund_count > 0:
        st.info(f"🔵 Found {refund_count} refund components (is_refund = 1)")

    # Download CSV
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"pricing_components_{selected_order}.csv",
        mime="text/csv"
    )


def render_payment_timeline_table(db, selected_order: str):
    """Render payment_timeline table."""
    st.markdown("#### 💳 Payment Timeline Table")
    st.markdown("""
    **Purpose**: Tracks payment lifecycle events (checkout, authorized, captured, refunded).

    **Key Fields**:
    - `timeline_version`: Monotonic version per order
    - `status`: Payment state (e.g., Authorized, Captured, Refunded)
    - `payment_id`: Payment intent ID
    - `pg_reference_id`: Payment gateway reference
    """)

    cursor = db.conn.cursor()

    if selected_order == "All Orders":
        cursor.execute("""
            SELECT * FROM payment_timeline
            ORDER BY order_id, timeline_version
        """)
    else:
        cursor.execute("""
            SELECT * FROM payment_timeline
            WHERE order_id = ?
            ORDER BY timeline_version
        """, (selected_order,))

    rows = cursor.fetchall()

    if not rows:
        st.info("No payment timeline events in storage.")
        return

    # Convert to DataFrame with proper column names
    columns = [desc[0] for desc in cursor.description]
    df = pd.DataFrame(rows, columns=columns)
    st.caption(f"**Total Rows**: {len(df)}")

    # Format JSON columns
    display_df = df.copy()
    if 'instrument' in display_df.columns:
        display_df['instrument'] = display_df['instrument'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )
    if 'bnpl_plan' in display_df.columns:
        display_df['bnpl_plan'] = display_df['bnpl_plan'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )
    if 'metadata' in display_df.columns:
        display_df['metadata'] = display_df['metadata'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )

    st.dataframe(display_df, use_container_width=True, height=400)

    # Download CSV
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"payment_timeline_{selected_order}.csv",
        mime="text/csv"
    )


def render_supplier_timeline_table(db, selected_order: str):
    """Render supplier_timeline table."""
    st.markdown("#### 🏢 Supplier Timeline Table")
    st.markdown("""
    **Purpose**: Tracks supplier lifecycle events (confirmed, issued, cancelled).

    **Key Fields**:
    - `supplier_timeline_version`: Monotonic version per order_detail
    - `status`: Supplier state (ISSUED, Confirmed, CancelledNoFee, CancelledWithFee)
    - `amount`: Amount due to supplier (baseline obligation)
    - ~~`cancellation_fee_amount`~~: **DEPRECATED** - Fees now in payable lines with `obligation_type='CANCELLATION_FEE'`
    """)

    cursor = db.conn.cursor()

    if selected_order == "All Orders":
        cursor.execute("""
            SELECT * FROM supplier_timeline
            ORDER BY order_id, order_detail_id, supplier_timeline_version
        """)
    else:
        cursor.execute("""
            SELECT * FROM supplier_timeline
            WHERE order_id = ?
            ORDER BY order_detail_id, supplier_timeline_version
        """, (selected_order,))

    rows = cursor.fetchall()

    if not rows:
        st.info("No supplier timeline events in storage.")
        return

    # Convert to DataFrame with proper column names
    columns = [desc[0] for desc in cursor.description]
    df = pd.DataFrame(rows, columns=columns)
    st.caption(f"**Total Rows**: {len(df)}")

    # Format JSON columns
    display_df = df.copy()
    if 'fx_context' in display_df.columns:
        display_df['fx_context'] = display_df['fx_context'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )
    if 'entity_context' in display_df.columns:
        display_df['entity_context'] = display_df['entity_context'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )
    if 'metadata' in display_df.columns:
        display_df['metadata'] = display_df['metadata'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )

    st.dataframe(display_df, use_container_width=True, height=400)

    # Highlight cancellation statuses
    cancelled_rows = df[df['status'].str.contains('Cancelled', na=False)] if 'status' in df.columns else pd.DataFrame()
    if not cancelled_rows.empty:
        st.warning(f"⚠️ Found {len(cancelled_rows)} cancelled supplier events")

    # Download CSV
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"supplier_timeline_{selected_order}.csv",
        mime="text/csv"
    )


def render_supplier_payables_table(db, selected_order: str):
    """Render supplier_payable_lines table with version = -1 highlighting."""
    st.markdown("#### 📊 Supplier Payable Lines Table")
    st.markdown("""
    **Purpose**: Multi-party payable breakdown (supplier, affiliate, tax, adjustments).

    **Key Fields**:
    - `obligation_type`: SUPPLIER, AFFILIATE_COMMISSION, TAX_WITHHOLDING, AFFILIATE_PENALTY, SUPPLIER_COMMISSION
    - `supplier_timeline_version`: Links to timeline event (or -1 for standalone adjustments)
    - `party_id`: Who we owe to (supplier_id, reseller_id, tax authority)
    - `amount`: Payable amount

    **Important**: Rows with `supplier_timeline_version = -1` are **standalone adjustments** (e.g., Salesforce penalties)
    that are ALWAYS included in total payables regardless of supplier status.
    """)

    cursor = db.conn.cursor()

    if selected_order == "All Orders":
        cursor.execute("""
            SELECT * FROM supplier_payable_lines
            ORDER BY order_id, order_detail_id, supplier_timeline_version, obligation_type
        """)
    else:
        cursor.execute("""
            SELECT * FROM supplier_payable_lines
            WHERE order_id = ?
            ORDER BY order_detail_id, supplier_timeline_version, obligation_type
        """, (selected_order,))

    rows = cursor.fetchall()

    if not rows:
        st.info("No supplier payable lines in storage.")
        return

    # Convert to DataFrame with proper column names
    columns = [desc[0] for desc in cursor.description]
    df = pd.DataFrame(rows, columns=columns)
    st.caption(f"**Total Rows**: {len(df)}")

    # Format JSON columns
    display_df = df.copy()
    if 'metadata' in display_df.columns:
        display_df['metadata'] = display_df['metadata'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )

    st.dataframe(display_df, use_container_width=True, height=400)

    # Highlight version = -1 (standalone adjustments)
    if 'supplier_timeline_version' in df.columns:
        standalone_count = len(df[df['supplier_timeline_version'] == -1])
        timeline_count = len(df[df['supplier_timeline_version'] >= 1])

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Timeline-Linked Payables", timeline_count, help="Linked to supplier_timeline events (version >= 1)")
        with col2:
            st.metric("Standalone Adjustments", standalone_count, help="Independent adjustments (version = -1, always counted)")

    # Download CSV
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"supplier_payables_{selected_order}.csv",
        mime="text/csv"
    )


def render_refund_timeline_table(db, selected_order: str):
    """Render refund_timeline table."""
    st.markdown("#### 💸 Refund Timeline Table")
    st.markdown("""
    **Purpose**: Tracks refund lifecycle events (initiated, closed).

    **Key Fields**:
    - `refund_timeline_version`: Monotonic version per refund_id
    - `refund_id`: Unique refund identifier
    - `refund_amount`: Total refund amount
    - `refund_reason`: Reason for refund
    """)

    cursor = db.conn.cursor()

    if selected_order == "All Orders":
        cursor.execute("""
            SELECT * FROM refund_timeline
            ORDER BY order_id, refund_id, refund_timeline_version
        """)
    else:
        cursor.execute("""
            SELECT * FROM refund_timeline
            WHERE order_id = ?
            ORDER BY refund_id, refund_timeline_version
        """, (selected_order,))

    rows = cursor.fetchall()

    if not rows:
        st.info("No refund timeline events in storage.")
        return

    # Convert to DataFrame with proper column names
    columns = [desc[0] for desc in cursor.description]
    df = pd.DataFrame(rows, columns=columns)
    st.caption(f"**Total Rows**: {len(df)}")

    # Format JSON columns
    display_df = df.copy()
    if 'metadata' in display_df.columns:
        display_df['metadata'] = display_df['metadata'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )

    st.dataframe(display_df, use_container_width=True, height=400)

    # Download CSV
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"refund_timeline_{selected_order}.csv",
        mime="text/csv"
    )


def render_dlq_table(db, selected_order: str):
    """Render DLQ (Dead Letter Queue) table for failed events."""
    st.markdown("#### ❌ DLQ (Failed Events) Table")
    st.markdown("""
    **Purpose**: Stores events that failed validation or ingestion.

    **Key Fields**:
    - `error_type`: Category of error (VALIDATION_ERROR, SCHEMA_ERROR, etc.)
    - `error_message`: Detailed error description
    - `raw_event`: Original event payload (for replay)
    """)

    cursor = db.conn.cursor()

    if selected_order == "All Orders":
        cursor.execute("""
            SELECT * FROM dlq
            ORDER BY failed_at DESC
            LIMIT 100
        """)
    else:
        cursor.execute("""
            SELECT * FROM dlq
            WHERE order_id = ?
            ORDER BY failed_at DESC
        """, (selected_order,))

    rows = cursor.fetchall()

    if not rows:
        st.success("✅ No failed events in DLQ")
        return

    # Convert to DataFrame with proper column names
    columns = [desc[0] for desc in cursor.description]
    df = pd.DataFrame(rows, columns=columns)
    st.caption(f"**Total Rows**: {len(df)}")

    # Show error summary
    if 'error_type' in df.columns:
        st.markdown("##### Error Type Breakdown")
        error_summary = df['error_type'].value_counts()
        st.bar_chart(error_summary)

    # Show raw data
    st.markdown("##### 📋 Failed Events")

    # Format raw_event column
    display_df = df.copy()
    if 'raw_event' in display_df.columns:
        display_df['raw_event'] = display_df['raw_event'].apply(
            lambda x: json.dumps(json.loads(x), indent=2) if isinstance(x, str) and x else None
        )

    st.dataframe(display_df, use_container_width=True, height=400)

    # Download CSV
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download as CSV",
        data=csv,
        file_name=f"dlq_{selected_order}.csv",
        mime="text/csv"
    )
