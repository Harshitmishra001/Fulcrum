import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Prevent API key validation from blocking tests
os.environ["OPENROUTER_API_KEY"] = "test_key_not_used_in_tests"

from src.app_v2 import app
from src.db.database import init_db

client = TestClient(app)

@pytest.fixture
def mock_start_job():
    """Patch start_job to avoid spawning background threads that keep DB connections open.
    Also inserts into ingestion_jobs table to maintain deduplication logic.
    """
    from src.db.database import get_db_connection
    import sqlite3

    # Track jobs per document_id
    job_map = {}

    def mock_start(document_id, pdf_path, db_path, doc_hash):
        # Check if we already have a job for this document
        if document_id in job_map:
            return job_map[document_id]

        # Create a new mock job ID
        job_id = f"mock-job-{len(job_map)}"
        job_map[document_id] = job_id

        # Also insert into ingestion_jobs table so deduplication logic works
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ingestion_jobs (id, document_id, status, parser_version, model_version, prompt_hash)
                VALUES (?, ?, 'pending', 'pdfplumber-v2', 'gpt-4o-mini', 'v2_strict_evidence')
            """, (job_id, document_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

        return job_id

    with patch('src.worker.start_job', side_effect=mock_start):
        with patch('src.app_v2.start_job', side_effect=mock_start):
            yield

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch, mock_start_job):
    """
    Guarantees that tests run against an isolated temporary SQLite database,
    completely preventing pollution or mutation of production fulcrum.db.
    """
    test_db_path = str(tmp_path / "test_fulcrum.db")
    monkeypatch.setenv("FULCRUM_DB_PATH", test_db_path)
    init_db(test_db_path)
    yield test_db_path
    # Teardown: tmp_path is auto-managed by pytest

def test_api_idempotency():
    """Documents with identical content should be deduplicated via file_hash."""
    # Create a valid minimal PDF file
    file_content = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000052 00000 n\n"
        b"0000000101 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n149\n%%EOF\n"
    )

    # Upload once
    response1 = client.post("/api/upload", files={"file": ("dummy.pdf", file_content, "application/pdf")})
    assert response1.status_code == 200
    data1 = response1.json()
    assert "job_id" in data1
    assert data1["status"] == "pending"

    # Upload exact same content again
    response2 = client.post("/api/upload", files={"file": ("dummy.pdf", file_content, "application/pdf")})
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["job_id"] == data1["job_id"]
    assert "message" in data2

def test_oracle_cases_exist():
    """Verify required_cases.json contains the four expected verification cases."""
    case_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "required_cases.json")
    assert os.path.exists(case_path), f"required_cases.json not found at {case_path}"

    with open(case_path, encoding="utf-8") as f:
        cases = json.load(f)

    assert "case1_corroboration" in cases
    assert "case2_contradiction" in cases
    assert "case3_reconciliation" in cases
    assert "case4_failure" in cases

    assert cases["case2_contradiction"]["fact_a"]["value"] == 1.3
    assert cases["case2_contradiction"]["fact_b"]["value"] == 0.6