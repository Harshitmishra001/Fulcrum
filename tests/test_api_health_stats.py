import pytest
from fastapi.testclient import TestClient
from src.app_v2 import app

client = TestClient(app)

def test_api_health_endpoint():
    """Verifies that GET /api/health returns 200 with operational database status."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "active_facts" in data
    assert "total_relations" in data
    assert "total_failures" in data
    assert isinstance(data["active_facts"], int)
    assert isinstance(data["total_relations"], int)

def test_api_stats_endpoint():
    """Verifies that GET /api/stats returns breakdown by relation type and source doc."""
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_facts" in data
    assert "total_relations" in data
    assert "total_failures" in data
    assert "relations_by_type" in data
    assert "facts_by_document" in data
    assert isinstance(data["relations_by_type"], dict)
    assert isinstance(data["facts_by_document"], dict)

def test_api_facts_search():
    """Verifies that GET /api/facts/search supports entity and attribute filtering."""
    # Unfiltered search
    res_all = client.get("/api/facts/search?limit=10")
    assert res_all.status_code == 200
    assert "facts" in res_all.json()
    assert res_all.json()["total"] <= 10

    # Search with entity filter (case-insensitive substring)
    res_entity = client.get("/api/facts/search?entity=india")
    assert res_entity.status_code == 200
    for fact in res_entity.json()["facts"]:
        assert "india" in fact["entity"].lower()

    # Search with non-existent entity returns empty list cleanly
    res_empty = client.get("/api/facts/search?entity=nonexistent_xyz_entity_99")
    assert res_empty.status_code == 200
    assert res_empty.json()["total"] == 0
    assert len(res_empty.json()["facts"]) == 0

