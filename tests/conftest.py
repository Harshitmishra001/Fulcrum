import os
import pytest
from src.db.database import init_db

@pytest.fixture(autouse=True)
def isolated_test_db(tmp_path, monkeypatch):
    """
    Guarantees that tests run against an isolated temporary SQLite database,
    completely preventing pollution or mutation of production fulcrum.db.
    """
    test_db_path = str(tmp_path / "test_fulcrum.db")
    monkeypatch.setenv("FULCRUM_DB_PATH", test_db_path)
    init_db(test_db_path)
    yield test_db_path
