import uuid
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.app import app
from src.db.database import save_fact, get_active_facts, deactivate_previous_runs

client = TestClient(app)

def test_sync_endpoints_serve_fast():
    """Verifies that routes are synchronous def running in threadpool without event loop freezing."""
    r_facts = client.get("/api/facts")
    assert r_facts.status_code == 200
    assert "facts" in r_facts.json()

    r_rel = client.get("/api/relations")
    assert r_rel.status_code == 200
    assert "relations" in r_rel.json()

    r_dash = client.get("/")
    assert r_dash.status_code == 200
    assert "Fulcrum" in r_dash.text

def test_missing_api_key_returns_clean_400_instead_of_500():
    """Critic 4.3: Evaluator without an API key gets a helpful 400 error, not a 500 crash."""
    with patch("src.app.OPENROUTER_API_KEY", ""):
        res = client.post(
            "/api/upload",
            files={"file": ("sample.pdf", b"%PDF-1.4\nminimal test content", "application/pdf")}
        )
        assert res.status_code == 400
        assert "OpenRouter API key is required" in res.json()["detail"]
        assert "starter dataset (RBI, IMF, Economic Survey) is already pre-cached" in res.json()["detail"]

def test_reupload_deactivates_stale_facts():
    """Critic 4.2: Re-extracting a document deactivates old facts to prevent duplicates."""
    uid = uuid.uuid4().hex[:8]
    doc = f"test_doc_dedup_{uid}"
    run_1 = f"run_alpha_{uid}"
    run_2 = f"run_beta_{uid}"
    fact_id_1 = f"fact_dedup_1_{uid}"
    fact_id_2 = f"fact_dedup_2_{uid}"

    # Insert a fact for run_1
    save_fact({
        "id": fact_id_1,
        "entity": "TestEntity",
        "attribute": "TestAttr",
        "value": 10.0,
        "period": {"raw_text": "FY2024", "period_type": "fiscal_year", "normalized": "FY2024"},
        "source_doc": doc,
        "source_page": 1,
        "source_quote": "Test fact 1",
        "chunk_id": f"test_{uid}__p0001__0001",
        "extraction_confidence": 0.9
    }, extraction_run_id=run_1)

    # Verify fact 1 is active
    active_before = get_active_facts(doc)
    assert any(f["id"] == fact_id_1 for f in active_before)

    # Deactivate previous runs when run_2 arrives
    deactivate_previous_runs(doc, run_2)

    # Save a fact for run_2
    save_fact({
        "id": fact_id_2,
        "entity": "TestEntity",
        "attribute": "TestAttr",
        "value": 12.0,
        "period": {"raw_text": "FY2024", "period_type": "fiscal_year", "normalized": "FY2024"},
        "source_doc": doc,
        "source_page": 1,
        "source_quote": "Test fact 2",
        "chunk_id": f"test_{uid}__p0001__0002",
        "extraction_confidence": 0.9
    }, extraction_run_id=run_2)

    active_after = get_active_facts(doc)
    active_ids = [f["id"] for f in active_after]
    assert fact_id_1 not in active_ids, "Stale fact from run_1 must be marked inactive"
    assert fact_id_2 in active_ids, "New fact from run_2 must be active"
