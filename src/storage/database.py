"""
SQLite database initialization and management.
Implements append-only fact tables and derived views.
"""
import sqlite3
from pathlib import Path
from typing import Optional
import json


class Database:
    """SQLite database wrapper for prototype"""

    def __init__(self, db_path: str = "data/uprl.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Establish database connection"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        return self.conn

    def initialize_schema(self):
        """Create all tables and views"""
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

        # Append-only fact table: Pricing Components
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pricing_components_fact (
                component_semantic_id TEXT NOT NULL,
                component_instance_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                pricing_snapshot_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                component_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                dimensions TEXT NOT NULL,  -- JSON
                description TEXT,
                is_refund INTEGER NOT NULL DEFAULT 0,  -- 0=false, 1=true
                refund_of_component_semantic_id TEXT,
                emitter_service TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                emitted_at TEXT NOT NULL,
                metadata TEXT  -- JSON
            )
        """)

        # Index for querying by order and version
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pricing_order_version
            ON pricing_components_fact(order_id, version DESC)
        """)

        # Index for semantic ID lookups (lineage tracing)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pricing_semantic
            ON pricing_components_fact(component_semantic_id)
        """)

        # Append-only fact table: Payment Timeline
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_timeline (
                event_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                timeline_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,  -- "Authorized", "Captured", "Refunded"
                payment_method TEXT NOT NULL,
                payment_intent_id TEXT,  -- For BNPL, retries tracking
                authorized_amount INTEGER,
                captured_amount INTEGER,  -- Amount captured in this specific event
                captured_amount_total INTEGER,  -- Running total of all captures
                amount INTEGER NOT NULL,  -- Legacy field (backward compatibility)
                currency TEXT NOT NULL,
                instrument_json TEXT,  -- JSON string of masked instrument details
                pg_reference_id TEXT,
                emitter_service TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                emitted_at TEXT NOT NULL,
                metadata TEXT  -- JSON
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payment_order_version
            ON payment_timeline(order_id, timeline_version DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payment_order_status
            ON payment_timeline(order_id, status, timeline_version DESC)
        """)

        # Append-only fact table: Supplier Timeline
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS supplier_timeline (
                event_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                order_detail_id TEXT NOT NULL,
                supplier_timeline_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                supplier_id TEXT NOT NULL,
                booking_code TEXT,
                supplier_reference_id TEXT,
                amount INTEGER,
                currency TEXT,
                status TEXT,
                cancellation_fee_amount INTEGER,
                cancellation_fee_currency TEXT,
                emitter_service TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                emitted_at TEXT NOT NULL,
                metadata TEXT  -- JSON
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_supplier_order_detail_version
            ON supplier_timeline(order_id, order_detail_id, supplier_timeline_version DESC)
        """)

        # Append-only fact table: Supplier Payable Lines (multi-party breakdown)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS supplier_payable_lines (
                line_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                order_detail_id TEXT NOT NULL,
                supplier_timeline_version INTEGER NOT NULL,
                obligation_type TEXT NOT NULL,
                party_id TEXT NOT NULL,
                party_name TEXT,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                calculation_basis TEXT,
                calculation_rate REAL,
                calculation_description TEXT,
                ingested_at TEXT NOT NULL,
                metadata TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payable_lines_order
            ON supplier_payable_lines(order_id, order_detail_id, supplier_timeline_version DESC)
        """)

        # Append-only fact table: Refund Timeline
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refund_timeline (
                event_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                refund_id TEXT NOT NULL,
                refund_timeline_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                refund_amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                refund_reason TEXT,
                emitter_service TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                emitted_at TEXT NOT NULL,
                metadata TEXT  -- JSON
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_refund_order_refund_version
            ON refund_timeline(order_id, refund_id, refund_timeline_version DESC)
        """)

        # Dead Letter Queue
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dlq (
                dlq_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                order_id TEXT,
                raw_event TEXT NOT NULL,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                failed_at TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0
            )
        """)

        # Derived view: Latest Pricing Breakdown (per semantic component)
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS order_pricing_latest AS
            SELECT * FROM pricing_components_fact
            WHERE (order_id, component_semantic_id, version) IN (
                SELECT order_id, component_semantic_id, MAX(version)
                FROM pricing_components_fact
                GROUP BY order_id, component_semantic_id
            )
        """)

        # Derived view: Latest Payment Status
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS payment_timeline_latest AS
            SELECT * FROM payment_timeline
            WHERE (order_id, timeline_version) IN (
                SELECT order_id, MAX(timeline_version)
                FROM payment_timeline
                GROUP BY order_id
            )
        """)

        # Derived view: Latest Supplier Status per Order Detail
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS supplier_timeline_latest AS
            SELECT * FROM supplier_timeline
            WHERE (order_id, order_detail_id, supplier_timeline_version) IN (
                SELECT order_id, order_detail_id, MAX(supplier_timeline_version)
                FROM supplier_timeline
                GROUP BY order_id, order_detail_id
            )
        """)

        # Derived view: Latest Refund Status per Refund ID
        cursor.execute("""
            CREATE VIEW IF NOT EXISTS refund_timeline_latest AS
            SELECT * FROM refund_timeline
            WHERE (order_id, refund_id, refund_timeline_version) IN (
                SELECT order_id, refund_id, MAX(refund_timeline_version)
                FROM refund_timeline
                GROUP BY order_id, refund_id
            )
        """)

        self.conn.commit()

    def insert_pricing_component(self, component: dict):
        """Insert normalized pricing component"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO pricing_components_fact VALUES (
                :component_semantic_id, :component_instance_id, :order_id,
                :pricing_snapshot_id, :version, :component_type, :amount,
                :currency, :dimensions, :description, :is_refund, :refund_of_component_semantic_id,
                :emitter_service, :ingested_at, :emitted_at, :metadata
            )
        """, {
            **component,
            'dimensions': json.dumps(component['dimensions']),
            'is_refund': 1 if component.get('is_refund') else 0,  # Convert bool to SQLite INTEGER
            'metadata': json.dumps(component.get('metadata'))
        })
        self.conn.commit()

    def insert_payment_timeline(self, entry: dict):
        """Insert payment timeline entry"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO payment_timeline VALUES (
                :event_id, :order_id, :timeline_version, :event_type, :status,
                :payment_method, :payment_intent_id, :authorized_amount,
                :captured_amount, :captured_amount_total, :amount, :currency,
                :instrument_json, :pg_reference_id,
                :emitter_service, :ingested_at, :emitted_at, :metadata
            )
        """, {
            **entry,
            'instrument_json': entry.get('instrument_json'),  # JSON string or None
            'metadata': json.dumps(entry.get('metadata'))
        })
        self.conn.commit()

    def insert_supplier_timeline(self, entry: dict):
        """Insert supplier timeline entry"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO supplier_timeline VALUES (
                :event_id, :order_id, :order_detail_id, :supplier_timeline_version,
                :event_type, :supplier_id, :booking_code, :supplier_reference_id, :amount,
                :currency, :status, :cancellation_fee_amount, :cancellation_fee_currency,
                :emitter_service, :ingested_at, :emitted_at, :metadata
            )
        """, {
            **entry,
            'booking_code': entry.get('booking_code'),
            'status': entry.get('status'),
            'cancellation_fee_amount': entry.get('cancellation_fee_amount'),
            'cancellation_fee_currency': entry.get('cancellation_fee_currency'),
            'metadata': json.dumps(entry.get('metadata'))
        })
        self.conn.commit()

    def insert_payable_line(self, entry: dict):
        """Insert supplier payable line"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO supplier_payable_lines VALUES (
                :line_id, :event_id, :order_id, :order_detail_id, :supplier_timeline_version,
                :obligation_type, :party_id, :party_name, :amount, :currency,
                :calculation_basis, :calculation_rate, :calculation_description,
                :ingested_at, :metadata
            )
        """, {
            **entry,
            'metadata': json.dumps(entry.get('metadata')) if entry.get('metadata') else None
        })
        self.conn.commit()

    def insert_refund_timeline(self, entry: dict):
        """Insert refund timeline entry"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO refund_timeline VALUES (
                :event_id, :order_id, :refund_id, :refund_timeline_version,
                :event_type, :refund_amount, :currency, :refund_reason,
                :emitter_service, :ingested_at, :emitted_at, :metadata
            )
        """, {
            **entry,
            'metadata': json.dumps(entry.get('metadata'))
        })
        self.conn.commit()

    def insert_dlq(self, dlq_entry: dict):
        """Insert DLQ entry"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO dlq VALUES (
                :dlq_id, :event_id, :event_type, :order_id, :raw_event,
                :error_type, :error_message, :failed_at, :retry_count
            )
        """, dlq_entry)
        self.conn.commit()

    def get_order_pricing_latest(self, order_id: str):
        """Get latest pricing breakdown for an order"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM order_pricing_latest
            WHERE order_id = ?
            ORDER BY component_type, dimensions
        """, (order_id,))
        return cursor.fetchall()

    def get_order_pricing_history(self, order_id: str):
        """Get all pricing versions for an order"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT version, pricing_snapshot_id, COUNT(*) as component_count,
                   SUM(amount) as total_amount, currency, emitted_at
            FROM pricing_components_fact
            WHERE order_id = ?
            GROUP BY version, pricing_snapshot_id, currency, emitted_at
            ORDER BY version DESC
        """, (order_id,))
        return cursor.fetchall()

    def get_component_lineage(self, semantic_id: str):
        """
        Trace component lineage including refunds.

        Updated: Refunds now have DIFFERENT semantic_ids (include refund_id).
        We find refunds by matching refund_of_component_semantic_id to the original's semantic_id.
        """
        cursor = self.conn.cursor()
        # Get original component occurrences (is_refund=0)
        cursor.execute("""
            SELECT * FROM pricing_components_fact
            WHERE component_semantic_id = ? AND is_refund = 0
            ORDER BY version ASC
        """, (semantic_id,))
        original = cursor.fetchall()

        # Get refund components that reference this original component
        # Refunds have different semantic_ids but link back via refund_of_component_semantic_id
        cursor.execute("""
            SELECT * FROM pricing_components_fact
            WHERE refund_of_component_semantic_id = ? AND is_refund = 1
            ORDER BY version ASC
        """, (semantic_id,))
        refunds = cursor.fetchall()

        return {'original': original, 'refunds': refunds}

    def get_all_orders(self):
        """Get list of all orders in the system"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT order_id FROM pricing_components_fact
            ORDER BY order_id
        """)
        return [row[0] for row in cursor.fetchall()]

    # Version retrieval methods for normalization layer
    def get_latest_pricing_version(self, order_id: str) -> int:
        """
        Get the latest pricing version for an order.
        Used by normalization layer to assign monotonic version numbers.
        Returns None if no previous versions exist.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MAX(version) FROM pricing_components_fact
            WHERE order_id = ?
        """, (order_id,))
        result = cursor.fetchone()
        return result[0] if result and result[0] is not None else None

    def get_latest_payment_timeline_version(self, order_id: str) -> int:
        """
        Get the latest payment timeline version for an order.
        Used by normalization layer to assign monotonic timeline_version numbers.
        Returns None if no previous versions exist.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MAX(timeline_version) FROM payment_timeline
            WHERE order_id = ?
        """, (order_id,))
        result = cursor.fetchone()
        return result[0] if result and result[0] is not None else None

    def get_latest_supplier_timeline_version(self, order_id: str, order_detail_id: str) -> int:
        """
        Get the latest supplier timeline version for an order_detail.
        Used by normalization layer to assign monotonic supplier_timeline_version numbers.
        Returns None if no previous versions exist.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT MAX(supplier_timeline_version) FROM supplier_timeline
            WHERE order_id = ? AND order_detail_id = ?
        """, (order_id, order_detail_id))
        result = cursor.fetchone()
        return result[0] if result and result[0] is not None else None

    def get_payment_timeline(self, order_id: str):
        """Get payment timeline for an order (all versions, ordered by timeline_version)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                event_id, order_id, timeline_version, event_type, status,
                payment_method, payment_intent_id, authorized_amount,
                captured_amount, captured_amount_total, amount, currency,
                instrument_json, pg_reference_id,
                emitter_service, ingested_at, emitted_at, metadata
            FROM payment_timeline
            WHERE order_id = ?
            ORDER BY timeline_version ASC
        """, (order_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_supplier_timeline(self, order_id: str, order_detail_id: str):
        """Get supplier timeline for an order_detail (all versions, ordered by supplier_timeline_version)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                event_id, order_id, order_detail_id, supplier_timeline_version,
                event_type, supplier_id, supplier_reference_id, amount,
                currency, status, cancellation_fee_amount, cancellation_fee_currency,
                emitter_service, ingested_at, emitted_at, metadata
            FROM supplier_timeline
            WHERE order_id = ? AND order_detail_id = ?
            ORDER BY supplier_timeline_version ASC
        """, (order_id, order_detail_id))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_supplier_payables_latest(self, order_id: str):
        """Get latest supplier payable breakdown for an order"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                line_id,
                event_id,
                order_id,
                order_detail_id,
                supplier_timeline_version,
                obligation_type,
                party_id,
                party_name,
                amount,
                currency,
                calculation_basis,
                calculation_rate,
                calculation_description,
                ingested_at
            FROM supplier_payable_lines
            WHERE order_id = ?
            ORDER BY order_detail_id, obligation_type, party_id
        """, (order_id,))

        columns = [
            'line_id', 'event_id', 'order_id', 'order_detail_id', 'supplier_timeline_version',
            'obligation_type', 'party_id', 'party_name', 'amount', 'currency',
            'calculation_basis', 'calculation_rate', 'calculation_description', 'ingested_at'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_supplier_payables_by_detail(self, order_detail_id: str):
        """Get supplier payable breakdown for a specific order_detail"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                line_id,
                event_id,
                order_id,
                order_detail_id,
                supplier_timeline_version,
                obligation_type,
                party_id,
                party_name,
                amount,
                currency,
                calculation_basis,
                calculation_rate,
                calculation_description,
                ingested_at
            FROM supplier_payable_lines
            WHERE order_detail_id = ?
            ORDER BY obligation_type, party_id
        """, (order_detail_id,))

        columns = [
            'line_id', 'event_id', 'order_id', 'order_detail_id', 'supplier_timeline_version',
            'obligation_type', 'party_id', 'party_name', 'amount', 'currency',
            'calculation_basis', 'calculation_rate', 'calculation_description', 'ingested_at'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_supplier_effective_payables(self, order_id: str, order_detail_id: Optional[str] = None):
        """
        Get effective supplier payables using status-driven obligation model.
        
        Logic:
        1. Get latest event per supplier instance (supplier_id + supplier_ref)
        2. Map status to effective obligation:
           - Confirmed/Invoiced/Settled → amount_due
           - CancelledWithFee → cancellation_fee_amount
           - CancelledNoFee/Voided → 0
        """
        cursor = self.conn.cursor()
        
        # Build WHERE clause
        where_clause = "WHERE order_id = ?"
        params = [order_id]
        if order_detail_id:
            where_clause += " AND order_detail_id = ?"
            params.append(order_detail_id)
        
        query = f"""
        WITH ranked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (
              PARTITION BY order_id, order_detail_id, supplier_id, supplier_reference_id
              ORDER BY supplier_timeline_version DESC, emitted_at DESC
            ) AS rn
          FROM supplier_timeline
          {where_clause}
        ),
        latest_per_supplier AS (
          SELECT * FROM ranked WHERE rn = 1
        )
        SELECT
          supplier_id,
          supplier_reference_id,
          status,
          CASE
            WHEN status IN ('Confirmed', 'ISSUED', 'Invoiced', 'Settled') THEN COALESCE(amount, 0)
            WHEN status = 'CancelledWithFee' THEN COALESCE(cancellation_fee_amount, 0)
            WHEN status IN ('CancelledNoFee', 'Voided') THEN 0
            ELSE 0
          END AS effective_payable,
          currency,
          order_id,
          order_detail_id,
          supplier_timeline_version,
          event_id,
          emitted_at,
          metadata
        FROM latest_per_supplier
        ORDER BY order_detail_id, supplier_id
        """
        
        cursor.execute(query, params)
        columns = [
            'supplier_id', 'supplier_reference_id', 'status', 'effective_payable', 'currency',
            'order_id', 'order_detail_id', 'supplier_timeline_version', 'event_id', 'emitted_at', 'metadata'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_supplier_payables_with_status(self, order_id: str):
        """
        Get supplier payables with status-driven effective obligations.

        Returns breakdown per supplier instance with:
        - Latest status per supplier instance (supplier_id + supplier_ref)
        - Effective payable based on status
        - Breakdown lines (supplier cost, affiliate commission, tax)
        """
        cursor = self.conn.cursor()

        # Step 1: Get latest status per supplier instance
        query_status = """
        WITH ranked AS (
          SELECT
            order_id,
            order_detail_id,
            supplier_id,
            supplier_reference_id,
            status,
            amount,
            currency,
            cancellation_fee_amount,
            cancellation_fee_currency,
            supplier_timeline_version,
            event_id,
            emitted_at,
            metadata,
            ROW_NUMBER() OVER (
              PARTITION BY order_id, order_detail_id, supplier_id, supplier_reference_id
              ORDER BY supplier_timeline_version DESC, emitted_at DESC
            ) AS rn
          FROM supplier_timeline
          WHERE order_id = ?
        )
        SELECT * FROM ranked WHERE rn = 1
        """

        cursor.execute(query_status, (order_id,))
        status_columns = [
            'order_id', 'order_detail_id', 'supplier_id', 'supplier_reference_id', 'status',
            'amount', 'currency', 'cancellation_fee_amount', 'cancellation_fee_currency',
            'supplier_timeline_version', 'event_id', 'emitted_at', 'metadata', 'rn'
        ]
        latest_status_rows = [dict(zip(status_columns, row)) for row in cursor.fetchall()]

        # Step 2: Get payable lines for the latest version per supplier instance
        result = []
        for status_row in latest_status_rows:
            # Calculate effective payable based on status
            status = status_row['status']
            if status in ('Confirmed', 'ISSUED', 'Invoiced', 'Settled'):
                effective_payable = status_row['amount'] or 0
            elif status == 'CancelledWithFee':
                effective_payable = status_row['cancellation_fee_amount'] or 0
            elif status in ('CancelledNoFee', 'Voided'):
                effective_payable = 0
            else:
                effective_payable = 0

            # Get breakdown lines for this supplier instance's latest version
            cursor.execute("""
                SELECT
                    line_id,
                    event_id,
                    obligation_type,
                    party_id,
                    party_name,
                    amount,
                    currency,
                    calculation_basis,
                    calculation_rate,
                    calculation_description
                FROM supplier_payable_lines
                WHERE order_id = ?
                  AND order_detail_id = ?
                  AND supplier_timeline_version = ?
                ORDER BY obligation_type
            """, (
                status_row['order_id'],
                status_row['order_detail_id'],
                status_row['supplier_timeline_version']
            ))

            breakdown_columns = [
                'line_id', 'event_id', 'obligation_type', 'party_id', 'party_name',
                'amount', 'currency', 'calculation_basis', 'calculation_rate', 'calculation_description'
            ]
            breakdown_lines = [dict(zip(breakdown_columns, row)) for row in cursor.fetchall()]

            # Combine status info with breakdown
            result.append({
                'supplier_instance': {
                    'supplier_id': status_row['supplier_id'],
                    'supplier_reference_id': status_row['supplier_reference_id'],
                    'status': status,
                    'effective_payable': effective_payable,
                    'currency': status_row['currency'],
                    'order_detail_id': status_row['order_detail_id'],
                    'supplier_timeline_version': status_row['supplier_timeline_version'],
                    'emitted_at': status_row['emitted_at']
                },
                'breakdown_lines': breakdown_lines
            })

        return result

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
