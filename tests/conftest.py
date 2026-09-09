"""
Shared pytest fixtures. Each test gets an isolated temporary database,
so tests never touch data/uprl.db or each other.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.storage.database import Database
from src.ingestion.pipeline import IngestionPipeline


@pytest.fixture
def db(tmp_path):
    """Isolated Database backed by a per-test temporary file."""
    database = Database(str(tmp_path / "test.db"))
    database.connect()
    database.initialize_schema()
    yield database
    database.close()


@pytest.fixture
def pipeline(db):
    """IngestionPipeline over the isolated database."""
    return IngestionPipeline(db)
