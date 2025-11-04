"""
Order Explorer UI component
Browse order pricing breakdowns, timelines, and component lineage
"""
import streamlit as st
import pandas as pd
import json
from datetime import datetime


def render_order_explorer(db):
    """Render the Order Explorer page"""

    st.markdown("## 🔍 Order Explorer")
    st.markdown("Browse pricing breakdowns, payment timelines, and component lineage")

    # Get all orders
    orders = db.get_all_orders()

    if not orders:
        st.info("📭 No orders found. Go to Producer Playground to emit some events!")
        return

    # Order selector
    selected_order = st.selectbox("Select Order", orders)

    if not selected_order:
        return

    # Tabs for different views
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "💰 Latest Breakdown",
        "📜 Version History",
        "🔗 Component Lineage",
        "💳 Payment Timeline",
        "🏪 Supplier Timeline",
        "💼 Supplier Payables"
    ])

    with tab1:
        refund_components = render_latest_breakdown(db, selected_order)
        # Render refunds separately if they exist
        if refund_components:
            st.markdown("---")  # Visual separator
            render_refunds(refund_components)

    with tab2:
        render_version_history(db, selected_order)

    with tab3:
        render_component_lineage(db, selected_order)

    with tab4:
        render_payment_timeline(db, selected_order)

    with tab5:
        render_supplier_timeline(db, selected_order)

    with tab6:
        render_supplier_payables(db, selected_order)


def render_latest_breakdown(db, order_id):
    """Show latest pricing breakdown (excluding refunds)"""

    st.markdown("### Current Pricing Breakdown")

    all_components = db.get_order_pricing_latest(order_id)

    if not all_components:
        st.warning("No pricing components found for this order")
        return

    # Separate refund components from regular components
    regular_components = [row for row in all_components if not row['is_refund']]
    refund_components = [row for row in all_components if row['is_refund']]

    if not regular_components:
        st.warning("No regular pricing components found for this order")
        return

    # Convert to DataFrame for display
    component_list = []
    total_amount = 0

    for row in regular_components:
        dimensions_dict = json.loads(row['dimensions'])

        component_list.append({
            'Component Type': row['component_type'],
            'Amount': format_currency(row['amount'], row['currency']),
            'Currency': row['currency'],
            'Dimensions': format_dimensions(dimensions_dict),
            'Description': row['description'] or '-',
            'Semantic ID': row['component_semantic_id'],
            'Version': row['version']
        })
        total_amount += row['amount']

    df = pd.DataFrame(component_list)

    # Display components
    st.dataframe(df, use_container_width=True)

    # Show total
    currency = regular_components[0]['currency']
    st.markdown(f"### Total: **{format_currency(total_amount, currency)}**")

    # Show metadata
    with st.expander("📋 Metadata"):
        latest_component = regular_components[0]
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Version", latest_component['version'])
        with col2:
            st.metric("Components", len(regular_components))
        with col3:
            st.metric("Emitter", latest_component['emitter_service'])

        st.text(f"Pricing Snapshot ID: {latest_component['pricing_snapshot_id']}")
        st.text(f"Emitted At: {latest_component['emitted_at']}")
        st.text(f"Ingested At: {latest_component['ingested_at']}")

    # Return refund components for rendering separately
    return refund_components


def render_refunds(refund_components):
    """Show refund components separately with lineage information"""

    if not refund_components:
        return  # No refunds to display

    st.markdown("### Refunds")
    st.info("💡 Refunds are shown separately from the current pricing breakdown. They reverse original components.")

    # Convert to DataFrame for display
    refund_list = []
    total_refund_amount = 0

    for row in refund_components:
        dimensions_dict = json.loads(row['dimensions'])

        # Show which component this refund reverses
        refund_of_display = row['refund_of_component_semantic_id'] or '-'

        refund_list.append({
            'Component Type': row['component_type'],
            'Amount': format_currency(row['amount'], row['currency']),
            'Currency': row['currency'],
            'Dimensions': format_dimensions(dimensions_dict),
            'Description': row['description'] or '-',
            'Semantic ID': row['component_semantic_id'],
            'Refund Of': refund_of_display,
            'Version': row['version']
        })
        total_refund_amount += row['amount']

    df = pd.DataFrame(refund_list)

    # Display refund components
    st.dataframe(df, use_container_width=True)

    # Show total refund amount
    currency = refund_components[0]['currency']
    st.markdown(f"### Total Refunded: **{format_currency(total_refund_amount, currency)}**")


def render_version_history(db, order_id):
    """Show all pricing versions for an order"""

    st.markdown("### Version History")

    history = db.get_order_pricing_history(order_id)

    if not history:
        st.warning("No version history found")
        return

    # Convert to DataFrame
    history_list = []
    for row in history:
        history_list.append({
            'Version': row['version'],
            'Snapshot ID': row['pricing_snapshot_id'][:16] + '...',
            'Components': row['component_count'],
            'Total Amount': format_currency(row['total_amount'], row['currency']),
            'Currency': row['currency'],
            'Emitted At': format_datetime(row['emitted_at'])
        })

    df = pd.DataFrame(history_list)
    st.dataframe(df, use_container_width=True)

    # Detail view for selected version
    selected_version = st.selectbox("Select version to view details", [h['Version'] for h in history_list])

    if selected_version:
        st.markdown(f"#### Version {selected_version} - Component Details")

        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT * FROM pricing_components_fact
            WHERE order_id = ? AND version = ?
            ORDER BY component_type, dimensions
        """, (order_id, selected_version))

        components = cursor.fetchall()

        component_details = []
        for row in components:
            dimensions_dict = json.loads(row['dimensions'])

            # Show full semantic ID for refund_of (precise reference)
            refund_of_display = row['refund_of_component_semantic_id'] or '-'

            component_details.append({
                'Type': row['component_type'],
                'Amount': format_currency(row['amount'], row['currency']),
                'Dimensions': format_dimensions(dimensions_dict),
                'Description': row['description'] or '-',
                'Semantic ID': row['component_semantic_id'],
                'Refund Of': refund_of_display
            })

        df_details = pd.DataFrame(component_details)
        st.dataframe(df_details, use_container_width=True)


def render_component_lineage(db, order_id):
    """Show component lineage including refunds"""

    st.markdown("### Component Lineage")
    st.markdown("Trace component history and refund relationships")

    # Get only non-refund semantic IDs for this order
    # Refunds have different semantic IDs but are shown via refund_of_component_semantic_id
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT DISTINCT component_semantic_id
        FROM pricing_components_fact
        WHERE order_id = ? AND is_refund = 0
        ORDER BY component_semantic_id
    """, (order_id,))

    semantic_ids = [row[0] for row in cursor.fetchall()]

    if not semantic_ids:
        st.warning("No components found")
        return

    selected_semantic_id = st.selectbox("Select Component", semantic_ids)

    if selected_semantic_id:
        lineage = db.get_component_lineage(selected_semantic_id)

        # Original component occurrences
        st.markdown("#### Original Component Occurrences")

        if lineage['original']:
            original_list = []
            for row in lineage['original']:
                dimensions_dict = json.loads(row['dimensions'])
                original_list.append({
                    'Version': row['version'],
                    'Amount': format_currency(row['amount'], row['currency']),
                    'Dimensions': format_dimensions(dimensions_dict),
                    'Description': row['description'] or '-',
                    'Instance ID': row['component_instance_id'],
                    'Emitted At': format_datetime(row['emitted_at'])
                })

            df_original = pd.DataFrame(original_list)
            st.dataframe(df_original, use_container_width=True)
        else:
            st.info("No original occurrences found")

        # Refund components
        st.markdown("#### Refund Components")

        if lineage['refunds']:
            refund_list = []
            for row in lineage['refunds']:
                dimensions_dict = json.loads(row['dimensions'])
                refund_list.append({
                    'Version': row['version'],
                    'Type': row['component_type'],
                    'Amount': format_currency(row['amount'], row['currency']),
                    'Dimensions': format_dimensions(dimensions_dict),
                    'Description': row['description'] or '-',
                    'Emitted At': format_datetime(row['emitted_at'])
                })

            df_refunds = pd.DataFrame(refund_list)
            st.dataframe(df_refunds, use_container_width=True)

            # Calculate net amount
            original_amount = sum(row['amount'] for row in lineage['original'])
            refund_amount = sum(row['amount'] for row in lineage['refunds'])
            net_amount = original_amount + refund_amount

            currency = lineage['original'][0]['currency'] if lineage['original'] else 'IDR'

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Original", format_currency(original_amount, currency))
            with col2:
                st.metric("Refunds", format_currency(refund_amount, currency))
            with col3:
                st.metric("Net", format_currency(net_amount, currency))
        else:
            st.info("No refunds for this component")


def render_payment_timeline(db, order_id):
    """Show payment timeline for order with enhanced payment lifecycle data"""

    st.markdown("### Payment Timeline")

    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT * FROM payment_timeline
        WHERE order_id = ?
        ORDER BY timeline_version ASC
    """, (order_id,))

    payments = cursor.fetchall()

    if not payments:
        st.info("No payment events found for this order")
        return

    payment_list = []
    for row in payments:
        # Parse instrument if present
        instrument_display = '-'
        if row['instrument_json']:
            try:
                instrument = json.loads(row['instrument_json'])
                instrument_display = instrument.get('display_hint', 'Internal')
            except:
                instrument_display = 'Error parsing'

        payment_list.append({
            'Version': row['timeline_version'],
            'Status': row['status'],
            'Event Type': row['event_type'],
            'Payment Method': row['payment_method'],
            'Authorized': format_currency(row['authorized_amount'] or 0, row['currency']),
            'Captured': format_currency(row['captured_amount_total'] or 0, row['currency']),
            'Instrument': instrument_display,
            'Intent ID': row['payment_intent_id'] or '-',
            'PG Reference': row['pg_reference_id'] or '-',
            'Emitted At': format_datetime(row['emitted_at'])
        })

    df = pd.DataFrame(payment_list)
    st.dataframe(df, use_container_width=True)

    # Latest status with enhanced info
    latest = payments[-1]
    status_emoji = {
        'Authorized': '🔐',
        'Captured': '✅',
        'Refunded': '↩️',
        'Failed': '❌'
    }.get(latest['status'], '💳')

    st.markdown(f"**Latest Status**: {status_emoji} `{latest['status']}` (v{latest['timeline_version']})")

    # Show payment flow summary
    if len(payments) > 1:
        with st.expander("📊 Payment Flow Summary"):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Total Events", len(payments))

            with col2:
                authorized_amt = latest['authorized_amount'] or 0
                st.metric("Authorized Amount", format_currency(authorized_amt, latest['currency']))

            with col3:
                captured_amt = latest['captured_amount_total'] or 0
                st.metric("Captured Total", format_currency(captured_amt, latest['currency']))

            # Payment intent consistency check
            intent_ids = set(p['payment_intent_id'] for p in payments if p['payment_intent_id'])
            if intent_ids:
                st.caption(f"Payment Intent ID: `{list(intent_ids)[0] if len(intent_ids) == 1 else 'Multiple'}`")
                if len(intent_ids) > 1:
                    st.warning(f"⚠️ Multiple payment intents detected: {', '.join(intent_ids)}")


def render_supplier_timeline(db, order_id):
    """Show supplier timeline for order"""

    st.markdown("### Supplier Timeline")

    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT * FROM supplier_timeline
        WHERE order_id = ?
        ORDER BY order_detail_id, supplier_timeline_version ASC
    """, (order_id,))

    suppliers = cursor.fetchall()

    if not suppliers:
        st.info("No supplier events found for this order")
        return

    # Group by order_detail_id
    order_details = {}
    for row in suppliers:
        od_id = row['order_detail_id']
        if od_id not in order_details:
            order_details[od_id] = []
        order_details[od_id].append(row)

    for od_id, events in order_details.items():
        st.markdown(f"#### {od_id}")

        supplier_list = []
        for row in events:
            supplier_list.append({
                'Version': row['supplier_timeline_version'],
                'Event Type': row['event_type'],
                'Supplier': row['supplier_id'],
                'Status': row['status'] or '-',
                'Booking Code': row['booking_code'] or '-',
                'Reference': row['supplier_reference_id'] or '-',
                'Amount': format_currency(row['amount'], row['currency']) if row['amount'] else '-',
                'Emitted At': format_datetime(row['emitted_at'])
            })

        df = pd.DataFrame(supplier_list)
        st.dataframe(df, use_container_width=True)

        # Latest status
        latest = events[-1]
        st.markdown(f"**Latest Status**: `{latest['event_type']}` (v{latest['supplier_timeline_version']})")


def render_supplier_payables(db, order_id):
    """Show supplier payable breakdown for order using status-driven obligation model"""

    st.markdown("### Supplier Payable Breakdown")
    st.caption("Status-driven obligation model: Collapses to latest status per supplier instance (supplier_id + supplier_ref)")

    # Get supplier payables with status-driven logic
    payables_data = db.get_supplier_payables_with_status(order_id)

    if not payables_data:
        st.info("No supplier payables recorded for this order")
        return

    # Display each supplier instance
    total_supplier = 0
    total_affiliate = 0
    total_tax = 0
    currency = 'IDR'

    for supplier_instance_data in payables_data:
        supplier_info = supplier_instance_data['supplier_instance']
        breakdown = supplier_instance_data['breakdown_lines']

        # Extract totals
        supplier_lines = [b for b in breakdown if b['obligation_type'] == 'SUPPLIER']
        affiliate_lines = [b for b in breakdown if b['obligation_type'] == 'AFFILIATE_COMMISSION']
        tax_lines = [b for b in breakdown if b['obligation_type'] == 'TAX_WITHHOLDING']

        # Status badge
        status_colors = {
            'Confirmed': '🟢', 'ISSUED': '🟢', 'Invoiced': '🟢', 'Settled': '🟢',
            'CancelledWithFee': '🟡', 'CancelledNoFee': '⚪', 'Voided': '⚪'
        }
        badge = status_colors.get(supplier_info['status'], '🔵')

        # Supplier header
        st.markdown(f"#### {supplier_info['supplier_id']} {badge} `{supplier_info['status']}`")
        st.caption(f"Ref: {supplier_info['supplier_reference_id']} | Detail: {supplier_info['order_detail_id']} | Version: {supplier_info['supplier_timeline_version']}")

        # Show effective payable vs original breakdown
        currency = supplier_info['currency'] or 'IDR'
        effective = supplier_info['effective_payable']

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Effective Payable", format_currency(effective, currency))
        with col2:
            if affiliate_lines:
                affiliate_amt = sum(b['amount'] for b in affiliate_lines)
                st.metric("Affiliate Commission", format_currency(affiliate_amt, currency))
                total_affiliate += affiliate_amt
        with col3:
            if tax_lines:
                tax_amt = sum(b['amount'] for b in tax_lines)
                st.metric("Tax Withholding", format_currency(tax_amt, currency))
                total_tax += tax_amt

        # Breakdown details in expander
        with st.expander("📋 View Detailed Breakdown"):
            if supplier_lines:
                st.markdown("**Supplier Cost:**")
                for line in supplier_lines:
                    st.write(f"• {line['party_name']}: {format_currency(line['amount'], line['currency'])}")

            if affiliate_lines:
                st.markdown("**Affiliate Commission:**")
                for line in affiliate_lines:
                    st.write(f"• {line['party_name']} (Partner ID: {line['party_id']})")
                    st.write(f"  Amount: {format_currency(line['amount'], line['currency'])}")
                    if line['calculation_description']:
                        st.caption(f"  💡 {line['calculation_description']}")

            if tax_lines:
                st.markdown("**Tax Withholding:**")
                for line in tax_lines:
                    st.write(f"• {line['party_name']}: {format_currency(line['amount'], line['currency'])}")
                    if line['calculation_description']:
                        st.caption(f"  💡 {line['calculation_description']}")

        total_supplier += effective
        st.markdown("---")

    # Grand total
    grand_total = total_supplier + total_affiliate + total_tax

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Total Breakdown:**")
        st.write(f"• Supplier Costs (Effective): {format_currency(total_supplier, currency)}")
        st.write(f"• Affiliate Commissions: {format_currency(total_affiliate, currency)}")
        st.write(f"• Tax Withholdings: {format_currency(total_tax, currency)}")
    with col2:
        st.markdown(f"### Grand Total: **{format_currency(grand_total, currency)}**")

    # Status legend
    with st.expander("📖 Status Legend & Business Rules"):
        st.markdown("""
        **Status-Driven Obligation Model:**

        | Status | Badge | Effective Payable |
        |--------|-------|-------------------|
        | Confirmed, ISSUED, Invoiced, Settled | 🟢 | Full `amount_due` |
        | CancelledWithFee | 🟡 | Only `cancellation_fee_amount` |
        | CancelledNoFee, Voided | ⚪ | Zero (struck through) |

        **How it works:**
        1. System gets latest event per supplier instance (supplier_id + supplier_ref)
        2. Maps status → effective obligation using CASE statement
        3. Supports rebooking: NATIVE cancelled → EXPEDIA confirmed shows both
        """)


# Utility functions

def format_currency(amount, currency):
    """Format currency amount with proper decimal handling per currency"""
    # Zero-decimal currencies (no subdivision in practice)
    # These currencies' smallest unit is the main unit itself
    ZERO_DECIMAL_CURRENCIES = ['IDR', 'JPY', 'KRW', 'VND', 'CLP', 'PYG', 'UGX', 'XAF', 'XOF']

    if currency in ZERO_DECIMAL_CURRENCIES:
        # Amount is already in main units (e.g., 246281 = IDR 246,281)
        return f"{currency} {amount:,.0f}"
    else:
        # Two-decimal currencies (has cents/pence/centimes)
        # Amount is in minor units (e.g., 150000 = USD 1,500.00)
        main_unit = amount / 100
        return f"{currency} {main_unit:,.2f}"


def format_dimensions(dimensions):
    """Format dimensions dict"""
    if not dimensions:
        return "ORDER"
    return ", ".join([f"{k}={v}" for k, v in dimensions.items()])


def format_datetime(dt_string):
    """Format datetime string"""
    try:
        dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return dt_string
