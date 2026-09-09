"""
SQLite database initialization and management.
Implements append-only fact tables and derived views.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
import json

from src.projection.payables import project_instance_payables, BOOKING_LEVEL


class Database:
    """SQLite database wrapper for prototype"""

    def __init__(self, db_path: str = "data/uprl.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None
        self._in_transaction = False

    @contextmanager
    def transaction(self):
        """
        Group writes into one atomic unit: commit on success, roll back on
        any exception. Insert methods defer their commits while active, so
        an event's writes land all-or-nothing. Re-entrant (inner joins outer).
        """
        self._ensure_connected()
        if self._in_transaction:
            yield
            return
        self._in_transaction = True
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self._in_transaction = False

    def _commit(self):
        """Commit immediately unless a transaction() block owns the commit."""
        if not self._in_transaction:
            self.conn.commit()

    def connect(self):
        """Establish database connection"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name
        return self.conn

    def _ensure_connected(self):
        """Ensure database connection is open, reconnect if needed"""
        if not self.conn:
            self.connect()
            return

        # Check if connection is still alive
        try:
            self.conn.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            # Connection is closed or broken, reconnect
            self.connect()

    # Ordered, numbered schema migrations. NEVER renumber or edit an entry
    # once shipped — append new entries. Each column-add migration declares
    # its target so it can be skipped (and recorded) when already satisfied.
    MIGRATIONS = [
        {
            'version': 1,
            'description': 'Add fulfillment_instance_id to supplier_timeline (2025-11-13)',
            'table': 'supplier_timeline',
            'column': 'fulfillment_instance_id',
            'sql': "ALTER TABLE supplier_timeline ADD COLUMN fulfillment_instance_id TEXT",
        },
        {
            'version': 2,
            'description': 'Add fulfillment_instance_id to supplier_payable_lines (2025-11-13)',
            'table': 'supplier_payable_lines',
            'column': 'fulfillment_instance_id',
            'sql': "ALTER TABLE supplier_payable_lines ADD COLUMN fulfillment_instance_id TEXT",
        },
        {
            'version': 3,
            'description': 'Add supplier_reference_id to supplier_payable_lines (2026-07-04)',
            'table': 'supplier_payable_lines',
            'column': 'supplier_reference_id',
            'sql': "ALTER TABLE supplier_payable_lines ADD COLUMN supplier_reference_id TEXT",
        },
    ]

    def _table_exists(self, cursor, table_name: str) -> bool:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return cursor.fetchone() is not None

    def _column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        cursor.execute(f"PRAGMA table_info({table_name})")
        return any(row[1] == column_name for row in cursor.fetchall())

    def _run_migrations(self, cursor):
        """
        Apply pending numbered migrations, tracked in schema_migrations.
        Runs before table creation: a migration whose target table does not
        exist yet (fresh database) is recorded as satisfied, because
        initialize_schema() creates tables at the current schema.
        """
        from datetime import datetime, timezone

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        cursor.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cursor.fetchall()}

        for migration in self.MIGRATIONS:
            version = migration['version']
            if version in applied:
                continue

            needs_apply = (
                self._table_exists(cursor, migration['table'])
                and not self._column_exists(cursor, migration['table'], migration['column'])
            )
            if needs_apply:
                print(f"🔄 Running migration {version}: {migration['description']}")
                cursor.execute(migration['sql'])
                print(f"✅ Migration {version} complete")

            cursor.execute(
                "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                (version, migration['description'],
                 datetime.now(timezone.utc).isoformat())
            )
        self._commit()

    def initialize_schema(self):
        """Create all tables and views with migration support"""
        if not self.conn:
            self.connect()

        cursor = self.conn.cursor()

        # Run migrations before creating tables
        self._run_migrations(cursor)

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
                fulfillment_instance_id TEXT,  -- NEW: For multi-instance payables (passes, multi-ride, etc.)
                amount INTEGER,
                amount_basis TEXT,  -- "gross", "net", or "redemption-triggered"
                currency TEXT,
                status TEXT,
                cancellation_fee_amount INTEGER,
                cancellation_fee_currency TEXT,
                fx_context TEXT,  -- JSON: FX rates and currencies
                entity_context TEXT,  -- JSON: Entity/legal context
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

        # New composite index for multi-instance payables
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_supplier_fulfillment_instance
            ON supplier_timeline(order_id, order_detail_id, supplier_reference_id, fulfillment_instance_id, supplier_timeline_version DESC)
        """)

        # Append-only fact table: Supplier Payable Lines (multi-party breakdown)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS supplier_payable_lines (
                line_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                order_detail_id TEXT NOT NULL,
                supplier_reference_id TEXT,  -- Booking code/reference for scoped projection
                fulfillment_instance_id TEXT,  -- NEW: For multi-instance payables (passes, multi-ride, etc.)
                supplier_timeline_version INTEGER NOT NULL,
                obligation_type TEXT NOT NULL,
                party_type TEXT,  -- "SUPPLIER", "AFFILIATE", "TAX_AUTHORITY", "INTERNAL"
                party_id TEXT NOT NULL,
                party_name TEXT,
                amount INTEGER NOT NULL,
                amount_effect TEXT NOT NULL DEFAULT 'INCREASES_PAYABLE',  -- "INCREASES_PAYABLE" or "DECREASES_PAYABLE"
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

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payable_lines_supplier_ref
            ON supplier_payable_lines(order_id, order_detail_id, supplier_reference_id, party_id, obligation_type)
        """)

        # New composite index for multi-instance payables
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_payable_lines_fulfillment
            ON supplier_payable_lines(order_id, order_detail_id, supplier_reference_id, fulfillment_instance_id, party_id, obligation_type)
        """)

        # Append-only fact table: Refund Timeline
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refund_timeline (
                event_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                refund_id TEXT NOT NULL,
                refund_timeline_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,  -- INITIATED, PROCESSING, ISSUED, CLOSED, FAILED
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

        # Processed events ledger: enforces idempotency at ingestion
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                idempotency_key TEXT,
                event_type TEXT NOT NULL,
                order_id TEXT,
                ingested_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_events_idempotency
            ON processed_events(idempotency_key)
            WHERE idempotency_key IS NOT NULL
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

        self._commit()

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
        self._commit()

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
        self._commit()

    def insert_supplier_timeline(self, entry: dict):
        """Insert supplier timeline entry (supports both v1 and v2 schema + multi-instance)"""
        self._ensure_connected()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO supplier_timeline VALUES (
                :event_id, :order_id, :order_detail_id, :supplier_timeline_version,
                :event_type, :supplier_id, :booking_code, :supplier_reference_id, :fulfillment_instance_id, :amount,
                :amount_basis, :currency, :status, :cancellation_fee_amount, :cancellation_fee_currency,
                :fx_context, :entity_context,
                :emitter_service, :ingested_at, :emitted_at, :metadata
            )
        """, {
            **entry,
            'booking_code': entry.get('booking_code'),
            'fulfillment_instance_id': entry.get('fulfillment_instance_id'),  # NEW: Multi-instance payables
            'amount_basis': entry.get('amount_basis'),  # "gross", "net", or "redemption-triggered"
            'status': entry.get('status'),
            'cancellation_fee_amount': entry.get('cancellation_fee_amount'),
            'cancellation_fee_currency': entry.get('cancellation_fee_currency'),
            'fx_context': entry.get('fx_context'),  # JSON string
            'entity_context': entry.get('entity_context'),  # JSON string
            'metadata': json.dumps(entry.get('metadata')) if entry.get('metadata') else None
        })
        self._commit()

    def insert_payable_line(self, entry: dict):
        """Insert supplier payable line (supports both v1 and v2 schema with amount_effect, party_type, and multi-instance)"""
        self._ensure_connected()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO supplier_payable_lines VALUES (
                :line_id, :event_id, :order_id, :order_detail_id, :supplier_reference_id, :fulfillment_instance_id, :supplier_timeline_version,
                :obligation_type, :party_type, :party_id, :party_name, :amount, :amount_effect, :currency,
                :calculation_basis, :calculation_rate, :calculation_description,
                :ingested_at, :metadata
            )
        """, {
            **entry,
            'supplier_reference_id': entry.get('supplier_reference_id'),  # Booking-scoped projection
            'fulfillment_instance_id': entry.get('fulfillment_instance_id'),  # NEW: Multi-instance payables
            'party_type': entry.get('party_type'),  # Party type field
            'amount_effect': entry.get('amount_effect', 'INCREASES_PAYABLE'),  # Default to INCREASES_PAYABLE for v1
            'metadata': json.dumps(entry.get('metadata')) if entry.get('metadata') else None
        })
        self._commit()

    def insert_refund_timeline(self, entry: dict):
        """Insert refund timeline entry"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO refund_timeline VALUES (
                :event_id, :order_id, :refund_id, :refund_timeline_version,
                :event_type, :status, :refund_amount, :currency, :refund_reason,
                :emitter_service, :ingested_at, :emitted_at, :metadata
            )
        """, {
            **entry,
            'metadata': json.dumps(entry.get('metadata'))
        })
        self._commit()

    def insert_dlq(self, dlq_entry: dict):
        """Insert DLQ entry"""
        self._ensure_connected()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO dlq VALUES (
                :dlq_id, :event_id, :event_type, :order_id, :raw_event,
                :error_type, :error_message, :failed_at, :retry_count
            )
        """, dlq_entry)
        self._commit()

    def find_processed_event(self, event_id: str, idempotency_key: str = None):
        """
        Check if an event was already successfully processed.
        Returns the matching ledger row (by event_id or idempotency_key), or None.
        """
        self._ensure_connected()
        cursor = self.conn.cursor()
        if idempotency_key:
            cursor.execute("""
                SELECT * FROM processed_events
                WHERE event_id = ? OR idempotency_key = ?
                LIMIT 1
            """, (event_id, idempotency_key))
        else:
            cursor.execute(
                "SELECT * FROM processed_events WHERE event_id = ? LIMIT 1",
                (event_id,)
            )
        return cursor.fetchone()

    def record_processed_event(self, event_id: str, event_type: str,
                               order_id: str = None, idempotency_key: str = None,
                               ingested_at: str = None):
        """Record a successfully processed event in the idempotency ledger"""
        self._ensure_connected()
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO processed_events
            (event_id, idempotency_key, event_type, order_id, ingested_at)
            VALUES (?, ?, ?, ?, ?)
        """, (event_id, idempotency_key, event_type, order_id, ingested_at))
        self._commit()

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
        """Get list of all orders in the system from ANY event type"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT order_id FROM (
                SELECT order_id FROM pricing_components_fact
                UNION
                SELECT order_id FROM payment_timeline
                UNION
                SELECT order_id FROM supplier_timeline
                UNION
                SELECT order_id FROM refund_timeline
            )
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
        self._ensure_connected()
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

    def get_refund_timeline(self, order_id: str):
        """Get refund timeline for an order (all refunds, all versions, ordered by refund_id and version)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                event_id, order_id, refund_id, refund_timeline_version,
                event_type, status, refund_amount, currency, refund_reason,
                emitter_service, ingested_at, emitted_at, metadata
            FROM refund_timeline
            WHERE order_id = ?
            ORDER BY refund_id ASC, refund_timeline_version ASC
        """, (order_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_supplier_payables_latest(self, order_id: str):
        """
        Get all supplier payable lines for an order (append-only, cumulative).
        Returns ALL lines across timeline versions - use get_payables_by_party for aggregation.
        """
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

    def get_payables_by_party(self, order_id: str):
        """
        Get total effective payables grouped by party_id and obligation_type.

        **STATUS-DRIVEN MODEL**:
        - Baseline supplier cost determined by latest supplier_timeline.status
        - Adjustments (penalties/credits) are ALWAYS additive
        - Commission/tax are conditionally included based on supplier status

        Use get_total_effective_payables() for status-aware calculation.
        This method returns RAW aggregation (all lines summed).
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                party_id,
                party_name,
                obligation_type,
                SUM(amount) as total_amount,
                currency,
                COUNT(*) as line_count,
                MIN(ingested_at) as first_recorded,
                MAX(ingested_at) as last_updated
            FROM supplier_payable_lines
            WHERE order_id = ?
            GROUP BY party_id, party_name, obligation_type, currency
            ORDER BY party_id, obligation_type
        """, (order_id,))

        columns = [
            'party_id', 'party_name', 'obligation_type', 'total_amount', 'currency',
            'line_count', 'first_recorded', 'last_updated'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_latest_supplier_statuses(self, order_id: str):
        """
        Latest supplier_timeline row per fulfillment instance:
        (order_detail_id, supplier_reference_id, fulfillment_instance_id).
        Multi-instance orders (e.g. passes) return one row per redemption.
        """
        self._ensure_connected()
        cursor = self.conn.cursor()
        cursor.execute("""
            WITH latest_status AS (
                SELECT
                    order_id,
                    order_detail_id,
                    supplier_id,
                    supplier_reference_id,
                    fulfillment_instance_id,
                    status,
                    amount,
                    amount_basis,
                    cancellation_fee_amount,
                    currency,
                    supplier_timeline_version,
                    ROW_NUMBER() OVER (
                        PARTITION BY order_id, order_detail_id, supplier_reference_id,
                                     COALESCE(fulfillment_instance_id, '__BOOKING_LEVEL__')
                        ORDER BY supplier_timeline_version DESC
                    ) as rn
                FROM supplier_timeline
                WHERE order_id = ?
            )
            SELECT * FROM latest_status WHERE rn = 1
        """, (order_id,))

        return [dict(zip(
            ['order_id', 'order_detail_id', 'supplier_id', 'supplier_reference_id',
             'fulfillment_instance_id', 'status', 'amount', 'amount_basis', 'cancellation_fee_amount', 'currency',
             'supplier_timeline_version', 'rn'],
            row
        )) for row in cursor.fetchall()]

    def get_payable_lines_for_instance(self, order_id: str, order_detail_id: str,
                                       supplier_reference_id: str, fulfillment_instance_id: str = None):
        """
        All payable lines (every version, including standalone -1) scoped to
        one fulfillment instance. Version selection is projection logic, not SQL.

        Standalone adjustments (version = -1) without a supplier_reference_id
        are detail-level obligations: they attach to the detail's booking-level
        instance (the invariant is that standalone adjustments are ALWAYS
        included; the instance COALESCE keeps them off per-redemption rows).
        """
        self._ensure_connected()
        instance_key = fulfillment_instance_id if fulfillment_instance_id else BOOKING_LEVEL
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT supplier_timeline_version, obligation_type, party_type,
                   party_id, party_name, amount, amount_effect, currency
            FROM supplier_payable_lines
            WHERE order_id = ? AND order_detail_id = ?
              AND (supplier_reference_id = ?
                   OR (supplier_timeline_version = -1 AND supplier_reference_id IS NULL))
              AND COALESCE(fulfillment_instance_id, ?) = ?
            ORDER BY rowid
        """, (order_id, order_detail_id, supplier_reference_id, BOOKING_LEVEL, instance_key))
        cols = ['supplier_timeline_version', 'obligation_type', 'party_type',
                'party_id', 'party_name', 'amount', 'amount_effect', 'currency']
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_total_effective_payables(self, order_id: str):
        """
        Effective payables per fulfillment instance using party-level
        projection with amount_effect. Business rules live in
        src/projection/payables.py; this method only fetches rows.
        """
        result = []
        for status_row in self.get_latest_supplier_statuses(order_id):
            lines = self.get_payable_lines_for_instance(
                order_id,
                status_row['order_detail_id'],
                status_row['supplier_reference_id'],
                status_row['fulfillment_instance_id'],
            )
            result.append(project_instance_payables(status_row, lines))
        return result

    def get_payables_timeline(self, order_id: str):
        """
        Get payables in chronological order showing evolution across timeline versions.

        Useful for audit trail: see when each obligation was created (commission, penalty, etc.)
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                supplier_timeline_version,
                obligation_type,
                party_id,
                party_name,
                amount,
                currency,
                calculation_description,
                ingested_at,
                event_id,
                line_id
            FROM supplier_payable_lines
            WHERE order_id = ?
            ORDER BY supplier_timeline_version ASC, obligation_type
        """, (order_id,))

        columns = [
            'supplier_timeline_version', 'obligation_type', 'party_id', 'party_name',
            'amount', 'currency', 'calculation_description', 'ingested_at', 'event_id', 'line_id'
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
