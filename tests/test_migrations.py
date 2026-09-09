"""
Tests for the numbered schema migration framework.

Run: python tests/test_migrations.py  (or pytest)
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.database import Database


def fresh_db(name):
    db_path = f"data/test_mig_{name}.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    return db_path


def applied_versions(db):
    return [r[0] for r in db.conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version")]


def test_fresh_database_records_all_migrations_without_applying():
    db_path = fresh_db("fresh")
    db = Database(db_path)
    db.connect()
    db.initialize_schema()

    assert applied_versions(db) == [m['version'] for m in Database.MIGRATIONS]
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(supplier_payable_lines)")]
    assert 'supplier_reference_id' in cols and 'fulfillment_instance_id' in cols
    db.close()
    os.remove(db_path)
    print("PASS: fresh database stamps all migrations as satisfied")


def test_legacy_database_gets_migrated():
    db_path = fresh_db("legacy")
    # Simulate the pre-ledger shipped schema: supplier_timeline always had
    # supplier_reference_id; the migrated columns are the ones missing
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE supplier_timeline (
            event_id TEXT PRIMARY KEY, order_id TEXT, order_detail_id TEXT,
            supplier_reference_id TEXT,
            supplier_timeline_version INTEGER, status TEXT, amount INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE supplier_payable_lines (
            line_id TEXT PRIMARY KEY, event_id TEXT, order_id TEXT,
            order_detail_id TEXT, supplier_timeline_version INTEGER,
            obligation_type TEXT, party_type TEXT, party_id TEXT,
            party_name TEXT, amount INTEGER, amount_effect TEXT,
            currency TEXT, calculation_basis TEXT, calculation_rate REAL,
            calculation_description TEXT, ingested_at TEXT, metadata TEXT
        )
    """)
    conn.commit()
    conn.close()

    db = Database(db_path)
    db.connect()
    db.initialize_schema()

    assert applied_versions(db) == [m['version'] for m in Database.MIGRATIONS]
    st_cols = [r[1] for r in db.conn.execute("PRAGMA table_info(supplier_timeline)")]
    pl_cols = [r[1] for r in db.conn.execute("PRAGMA table_info(supplier_payable_lines)")]
    assert 'fulfillment_instance_id' in st_cols
    assert 'fulfillment_instance_id' in pl_cols and 'supplier_reference_id' in pl_cols
    db.close()
    os.remove(db_path)
    print("PASS: legacy database receives pending ALTERs and ledger entries")


def test_initialize_schema_is_idempotent():
    db_path = fresh_db("idem")
    db = Database(db_path)
    db.connect()
    db.initialize_schema()
    first = applied_versions(db)
    db.initialize_schema()
    db.initialize_schema()
    assert applied_versions(db) == first, "re-running must not duplicate ledger rows"
    db.close()
    os.remove(db_path)
    print("PASS: initialize_schema is idempotent over the ledger")


def test_migration_versions_are_unique_and_ordered():
    versions = [m['version'] for m in Database.MIGRATIONS]
    assert versions == sorted(versions), "migrations must be declared in order"
    assert len(versions) == len(set(versions)), "duplicate migration version"
    assert all(set(m) >= {'version', 'description', 'table', 'column', 'sql'}
               for m in Database.MIGRATIONS)
    print("PASS: migration registry is ordered, unique, and well-formed")


if __name__ == "__main__":
    test_fresh_database_records_all_migrations_without_applying()
    test_legacy_database_gets_migrated()
    test_initialize_schema_is_idempotent()
    test_migration_versions_are_unique_and_ordered()
    print("\nAll migration tests passed ✅")
